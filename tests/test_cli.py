import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, NoReturn

import pytest
from helpers import TTY, FakeLLM

from aiscript import cli, llm, paths
from aiscript.config import ProviderConfig, Settings

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash scripts")

ECHO = (
    "#!/usr/bin/env bash\n"
    "# aiscript: echo\n"
    "# Description: echoes args\n"
    "# Usage: echo <args>\n"
    'for a in "$@"; do echo "arg:$a"; done\n'
    "exit ${EXIT_WITH:-0}\n"
)
RISKY = "#!/usr/bin/env bash\nsudo ls\n"


@pytest.fixture
def gen(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM(ECHO)
    monkeypatch.setattr(llm, "generate_script", fake)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(ProviderConfig("fake", "k", None, "m"), None),
    )
    return fake


def say(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    monkeypatch.setattr("builtins.input", lambda _="": answer)


def make_cached(name: str = "echo", script: str = ECHO, prompt: str = "echo things") -> Path:
    paths.ensure_dirs()
    paths.prompt_path(name).write_text(prompt)
    f = paths.function_path(name)
    f.write_text(script)
    f.chmod(0o755)
    future = time.time_ns() + 5_000_000_000
    os.utime(f, ns=(future, future))
    return f


def test_no_args(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2
    out = capsys.readouterr()
    assert "usage" in out.err and out.out == ""


def test_help_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    assert "usage" in capsys.readouterr().err
    assert cli.main(["-h"]) == 0
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("aiscript ")


def test_unknown_and_conflicting_flags() -> None:
    assert cli.main(["--bogus"]) == 2
    assert cli.main(["--list", "--init"]) == 2


@pytest.mark.parametrize("bad", ["../x", "a/b", ".hidden", "a b"])
def test_invalid_names(bad: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([bad]) == 1
    assert "aiscript: error: Invalid command name" in capsys.readouterr().err


def test_new_command_flow(
    gen: FakeLLM, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    say(monkeypatch, "echo my args")
    assert cli.main(["echo", "a", "--flag", "two words"]) == 0
    cap = capfd.readouterr()
    assert cap.out.splitlines() == ["arg:a", "arg:--flag", "arg:two words"]
    assert "Command not found. What should 'echo' do?" in cap.err
    assert paths.prompt_path("echo").read_text().strip() == "echo my args"
    assert gen.calls == [("echo", "echo my args")]
    f = paths.function_path("echo")
    assert stat.S_IMODE(f.stat().st_mode) == 0o755


def test_empty_answer_aborts(
    gen: FakeLLM, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    say(monkeypatch, "   ")
    assert cli.main(["echo"]) == 1
    assert "nothing saved" in capsys.readouterr().err
    assert list(paths.prompts_dir().iterdir()) == []
    assert list(paths.functions_dir().iterdir()) == []


def test_eof_aborts(gen: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    def eof(_: str = "") -> NoReturn:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert cli.main(["echo"]) == 1
    assert list(paths.prompts_dir().iterdir()) == []


def test_cached_run_skips_llm_and_settings(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    make_cached()

    def no(*a: Any, **k: Any) -> NoReturn:
        raise AssertionError("should not be called")

    monkeypatch.setattr(llm, "generate_script", no)
    monkeypatch.setattr(cli, "load_settings", no)
    assert cli.main(["echo", "--help", "x y"]) == 0
    assert capfd.readouterr().out.splitlines() == ["arg:--help", "arg:x y"]


def test_exit_code_propagation(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    make_cached()
    monkeypatch.setenv("EXIT_WITH", "7")
    assert cli.main(["echo"]) == 7


def test_stale_prompt_triggers_rebuild(gen: FakeLLM, capfd: pytest.CaptureFixture[str]) -> None:
    f = make_cached()
    gen.script = ECHO.replace("arg:", "new:")
    future = time.time_ns() + 50_000_000_000
    os.utime(paths.prompt_path("echo"), ns=(future, future))
    assert cli.main(["echo", "z"]) == 0
    assert capfd.readouterr().out == "new:z\n"
    assert len(gen.calls) == 1
    assert "new:" in f.read_text()


def test_build_error_returns_1(
    gen: FakeLLM, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths.ensure_dirs()
    paths.prompt_path("echo").write_text("x")

    def boom(*a: Any, **k: Any) -> NoReturn:
        raise cli.AiscriptError("kaput")

    monkeypatch.setattr(cli, "load_settings", boom)
    assert cli.main(["echo"]) == 1
    assert "aiscript: error: kaput" in capsys.readouterr().err


def test_risky_rejected_writes_nothing(
    gen: FakeLLM, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gen.script = RISKY
    say(monkeypatch, "list as root")
    assert cli.main(["root"]) == 1
    assert "Script rejected; nothing saved." in capsys.readouterr().err
    assert list(paths.functions_dir().iterdir()) == []


def test_risky_approved_writes_and_runs(
    gen: FakeLLM, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    gen.script = "#!/usr/bin/env bash\nsudo -n true 2>/dev/null; echo ran\n"
    monkeypatch.setattr(sys, "stdin", TTY("go", "y"))
    assert cli.main(["root"]) == 0
    assert "ran" in capfd.readouterr().out
    assert paths.function_path("root").exists()


def test_rebuild(gen: FakeLLM, capfd: pytest.CaptureFixture[str]) -> None:
    f = make_cached()
    gen.script = ECHO.replace("arg:", "rebuilt:")
    assert cli.main(["--rebuild", "echo"]) == 0
    cap = capfd.readouterr()
    assert cap.out.strip() == str(f)  # path printed, script not executed
    assert "rebuilt:" in f.read_text()
    assert len(gen.calls) == 1


def test_rebuild_rejected_keeps_old(gen: FakeLLM, capsys: pytest.CaptureFixture[str]) -> None:
    f = make_cached()
    old = f.read_text()
    gen.script = RISKY
    assert cli.main(["--rebuild", "echo"]) == 1
    assert "rejected" in capsys.readouterr().err
    assert f.read_text() == old


def test_rebuild_missing_prompt(gen: FakeLLM, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--rebuild", "nope"]) == 1
    assert "No prompt for 'nope'" in capsys.readouterr().err


def test_edit_missing_prompt(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--edit", "nope"]) == 1
    assert "No prompt for 'nope'" in capsys.readouterr().err


def make_editor(tmp_path: Path, body: str) -> Path:
    ed = tmp_path / "fake-editor"
    ed.write_text(f"#!/usr/bin/env bash\n{body}\n")
    ed.chmod(0o755)
    return ed


def test_edit_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    f = make_cached()
    old = time.time_ns() - 5_000_000_000
    os.utime(f, ns=(old, old))
    ed = make_editor(tmp_path, 'sleep 0.05; echo more >> "$1"')
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", str(ed))
    assert cli.main(["--edit", "echo"]) == 0
    assert "changed" in capsys.readouterr().err
    assert paths.prompt_path("echo").read_text().endswith("more\n")
    assert builder_needs("echo")


def builder_needs(name: str) -> bool:
    from aiscript import builder

    return builder.needs_build(name)


def test_edit_unchanged_and_visual_with_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_cached()
    ed = make_editor(tmp_path, "exit 0")
    monkeypatch.setenv("VISUAL", f"{ed} --wait")
    monkeypatch.setenv("EDITOR", "does-not-exist")
    assert cli.main(["--edit", "echo"]) == 0
    assert "unchanged" in capsys.readouterr().err


def test_list(capsys: pytest.CaptureFixture[str]) -> None:
    make_cached()
    paths.prompt_path("other").write_text("x")
    assert cli.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "echoes args" in out and "other" in out and "(not built)" in out


def test_init(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--init"]) == 0
    assert paths.config_path().exists()
    assert stat.S_IMODE(paths.config_path().stat().st_mode) == 0o600
    assert paths.prompts_dir().is_dir() and paths.functions_dir().is_dir()


def test_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    def kb(*a: Any, **k: Any) -> NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", kb)
    assert cli.main(["newcmd"]) == 130


def test_python_m_aiscript_importable() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "aiscript", "--version"], capture_output=True, text=True
    )
    assert r.returncode == 0 and r.stdout.startswith("aiscript ")


def test_remove_deletes_prompt_and_script(capsys: pytest.CaptureFixture[str]) -> None:
    f = make_cached()
    prompt = paths.prompt_path("echo")
    assert cli.main(["--remove", "echo"]) == 0
    assert not f.exists() and not prompt.exists()
    err = capsys.readouterr().err
    assert str(f) in err and str(prompt) in err


def test_remove_prompt_only(capsys: pytest.CaptureFixture[str]) -> None:
    paths.ensure_dirs()
    paths.prompt_path("todo").write_text("do things\n")
    assert cli.main(["--remove", "todo"]) == 0
    assert not paths.prompt_path("todo").exists()


def test_remove_missing(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--remove", "nope"]) == 1
    assert "No command named 'nope'" in capsys.readouterr().err


def test_remove_invalid_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--remove", "../x"]) == 1


def test_remove_then_list_is_empty(capsys: pytest.CaptureFixture[str]) -> None:
    make_cached()
    cli.main(["--remove", "echo"])
    capsys.readouterr()
    assert cli.main(["--list"]) == 0
    assert "echo" not in capsys.readouterr().out


def test_remove_project_dir_and_other_artifacts(capsys: pytest.CaptureFixture[str]) -> None:
    paths.ensure_dirs()
    paths.prompt_path("proj").write_text("x\n")
    project = paths.project_dir("proj")
    (project / ".venv" / "bin").mkdir(parents=True)
    (project / "main.py").write_text("print()\n")
    py = paths.functions_dir() / "proj.py"
    py.write_text("print()\n")
    assert cli.main(["--remove", "proj"]) == 0
    assert not project.exists() and not py.exists()
    assert not paths.prompt_path("proj").exists()
    assert str(project) in capsys.readouterr().err
