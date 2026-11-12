"""Acceptance tests for explicit prompt-file invocation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, NoReturn

import pytest
from helpers import FakeLLM

from aiscript import cli, llm, paths
from aiscript.config import ProviderConfig, Settings

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="generated shell is Bash")

ECHO = (
    "#!/usr/bin/env bash\n"
    "# Description: echo arguments\n"
    "# Usage: echo [args...]\n"
    'for a in "$@"; do printf "arg:<%s>\\n" "$a"; done\n'
)


@pytest.fixture
def generator(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM(ECHO)
    monkeypatch.setattr(llm, "generate_script", fake)
    monkeypatch.setattr(
        cli, "load_settings", lambda: Settings(ProviderConfig("fake", "k", None, "m"), None)
    )
    return fake


def test_given_prompt_file_when_invoked_then_prompt_and_arguments_are_preserved(
    tmp_path: Path, generator: FakeLLM, capfd: pytest.CaptureFixture[str]
) -> None:
    # given
    source = tmp_path / "-prompt with spaces"
    source.write_text("#!/usr/bin/env aiscript\nList folders\n", encoding="utf-8")
    # when
    status = cli.main([str(source), "two words", "", "--flag", "$(echo unsafe)"])
    # then
    assert status == 0
    assert capfd.readouterr().out.splitlines() == [
        "arg:<two words>",
        "arg:<>",
        "arg:<--flag>",
        "arg:<$(echo unsafe)>",
    ]
    assert len(generator.calls) == 1
    assert generator.calls[0][1] == "List folders\n"


def test_given_file_without_shebang_when_invoked_then_whole_file_is_prompt(
    tmp_path: Path, generator: FakeLLM
) -> None:
    # given
    source = tmp_path / "prompt"
    source.write_text("List folders\n", encoding="utf-8")
    # when
    status = cli.main([str(source)])
    # then
    assert status == 0
    assert generator.calls[0][1] == "List folders\n"


def test_given_cached_prompt_when_repeated_then_no_generation_or_settings_load(
    tmp_path: Path, generator: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    source = tmp_path / "prompt"
    source.write_text("List folders\n", encoding="utf-8")
    assert cli.main([str(source)]) == 0

    def unexpected(*args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("cache hit must not load settings or generate")

    monkeypatch.setattr(llm, "generate_script", unexpected)
    monkeypatch.setattr(cli, "load_settings", unexpected)
    # when / then
    assert cli.main([str(source)]) == 0
    assert len(generator.calls) == 1


def test_given_prompt_changed_with_same_timestamp_when_invoked_then_rebuilds(
    tmp_path: Path, generator: FakeLLM
) -> None:
    # given
    source = tmp_path / "prompt"
    source.write_text("First prompt\n", encoding="utf-8")
    assert cli.main([str(source)]) == 0
    timestamps = source.stat()
    source.write_text("Other prompt\n", encoding="utf-8")
    os.utime(source, ns=(timestamps.st_atime_ns, timestamps.st_mtime_ns))
    # when
    status = cli.main([str(source)])
    # then
    assert status == 0
    assert [call[1] for call in generator.calls] == ["First prompt\n", "Other prompt\n"]


def test_given_only_shebang_changed_when_invoked_then_reuses_build(
    tmp_path: Path, generator: FakeLLM
) -> None:
    # given
    source = tmp_path / "prompt"
    source.write_text("#!/usr/bin/env aiscript\nSame prompt\n", encoding="utf-8")
    assert cli.main([str(source)]) == 0
    source.write_text("#!/some/other/interpreter\nSame prompt\n", encoding="utf-8")
    # when
    status = cli.main([str(source)])
    # then
    assert status == 0
    assert len(generator.calls) == 1


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid", "empty"])
def test_given_invalid_source_when_invoked_then_fails_without_generation(
    tmp_path: Path, generator: FakeLLM, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    # given
    source = tmp_path / "prompt"
    if kind == "directory":
        source.mkdir()
    elif kind == "invalid":
        source.write_bytes(b"\xff")
    elif kind == "empty":
        source.write_text("#!/usr/bin/env aiscript\n   \n", encoding="utf-8")
    # when
    status = cli.main([str(source)])
    # then
    assert status != 0
    error = capsys.readouterr().err
    assert error
    assert "Invalid command name" not in error
    assert generator.calls == []


def test_given_build_failure_after_edit_when_invoked_then_never_runs_old_build(
    tmp_path: Path,
    generator: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # given
    source = tmp_path / "prompt"
    source.write_text("First prompt\n", encoding="utf-8")
    assert cli.main([str(source), "old"]) == 0
    capfd.readouterr()
    source.write_text("Changed prompt\n", encoding="utf-8")

    def fail(*args: Any, **kwargs: Any) -> NoReturn:
        raise cli.AiscriptError("generation failed")

    monkeypatch.setattr(llm, "generate_script", fail)
    # when
    status = cli.main([str(source), "should-not-run"])
    # then
    output = capfd.readouterr()
    assert status != 0
    assert output.out == ""
    assert "generation failed" in output.err
    # A failed rebuild preserves the earlier approved version.
    source.write_text("First prompt\n", encoding="utf-8")
    assert cli.main([str(source), "old"]) == 0
    assert capfd.readouterr().out == "arg:<old>\n"


def test_given_risky_build_and_noninteractive_input_when_invoked_then_refuses(
    tmp_path: Path, generator: FakeLLM, capfd: pytest.CaptureFixture[str]
) -> None:
    # given
    source = tmp_path / "prompt"
    source.write_text("List as root\n", encoding="utf-8")
    generator.script = "#!/usr/bin/env bash\nsudo ls\n"
    # when
    status = cli.main([str(source)])
    # then
    assert status != 0
    assert capfd.readouterr().out == ""
    assert len(generator.calls) == 1


def test_given_bare_name_and_matching_file_when_invoked_then_named_command_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    # given
    monkeypatch.chdir(tmp_path)
    (tmp_path / "same").write_text("file prompt\n", encoding="utf-8")
    paths.ensure_dirs()
    paths.prompt_path("same").write_text("named prompt\n", encoding="utf-8")
    target = paths.function_path("same")
    target.write_text(ECHO, encoding="utf-8")
    target.chmod(0o755)
    future = paths.prompt_path("same").stat().st_mtime_ns + 1_000_000
    os.utime(target, ns=(future, future))
    # when
    status = cli.main(["same", "named"])
    # then
    assert status == 0
    assert capfd.readouterr().out == "arg:<named>\n"


def test_given_symlink_alias_and_moved_file_when_invoked_then_identity_is_canonical(
    tmp_path: Path, generator: FakeLLM
) -> None:
    # given
    source = tmp_path / "source"
    alias = tmp_path / "alias"
    moved = tmp_path / "moved"
    source.write_text("List folders\n", encoding="utf-8")
    alias.symlink_to(source)
    # when
    assert cli.main([str(source)]) == 0
    assert cli.main([str(alias)]) == 0
    source.rename(moved)
    assert cli.main([str(moved)]) == 0
    # then
    assert len(generator.calls) == 2


def test_given_generated_program_when_it_exits_nonzero_then_status_is_forwarded(
    tmp_path: Path, generator: FakeLLM, capfd: pytest.CaptureFixture[str]
) -> None:
    # given
    source = tmp_path / "prompt"
    source.write_text("Print and fail\n", encoding="utf-8")
    generator.script = "#!/usr/bin/env bash\necho result\necho problem >&2\nexit 7\n"
    # when
    status = cli.main([str(source)])
    # then
    captured = capfd.readouterr()
    assert status == 7
    assert captured.out == "result\n"
    assert "problem" in captured.err


def test_given_parallel_invocations_when_cache_is_empty_then_one_build_is_published(
    tmp_path: Path, generator: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    source = tmp_path / "prompt"
    source.write_text("Concurrent prompt\n", encoding="utf-8")
    entered = Event()
    proceed = Event()

    def delayed(
        p: ProviderConfig, name: str, intent: str, *, max_calls_per_run: int = 1
    ) -> llm.GeneratedScript:
        entered.set()
        assert proceed.wait(5)
        return generator(p, name, intent)

    monkeypatch.setattr(llm, "generate_script", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cli.main, [str(source)])
        assert entered.wait(5)
        second = pool.submit(cli.main, [str(source)])
        proceed.set()
        assert first.result(timeout=10) == 0
        assert second.result(timeout=10) == 0
    assert len(generator.calls) == 1


def test_given_cached_executable_prompt_when_os_launches_shebang_then_arguments_arrive(
    tmp_path: Path, generator: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    source = tmp_path / "prompt"
    source.write_text("#!/usr/bin/env aiscript\nPrint arguments\n", encoding="utf-8")
    source.chmod(0o755)
    assert cli.main([str(source)]) == 0
    bindir = tmp_path / "bin"
    bindir.mkdir()
    interpreter = bindir / "aiscript"
    interpreter.write_text(
        f"#!{sys.executable}\nfrom aiscript.cli import main\nraise SystemExit(main())\n",
        encoding="utf-8",
    )
    interpreter.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    result = subprocess.run([str(source), "two words"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert result.stdout == "arg:<two words>\n"
    assert len(generator.calls) == 1


def test_given_another_process_holds_lease_when_acquired_then_waits_for_release(
    tmp_path: Path,
) -> None:
    import select
    import subprocess

    lock_path = tmp_path / "lock"
    program = (
        "from aiscript.prompt_file import _lock\n"
        "from pathlib import Path\n"
        "import sys\n"
        "print('ready', flush=True)\n"
        "with _lock(Path(sys.argv[1])):\n"
        " print('locked', flush=True)\n"
        " sys.stdin.readline()\n"
    )
    first = subprocess.Popen(
        [sys.executable, "-c", program, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    second = None
    try:
        assert first.stdout is not None
        assert first.stdout.readline().strip() == "ready"
        assert first.stdout.readline().strip() == "locked"
        second = subprocess.Popen(
            [sys.executable, "-c", program, str(lock_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert second.stdout is not None
        assert second.stdout.readline().strip() == "ready"
        assert select.select([second.stdout], [], [], 0.2)[0] == []
        assert first.stdin is not None
        first.stdin.write("\n")
        first.stdin.flush()
        assert first.wait(timeout=5) == 0
        assert second.stdout.readline().strip() == "locked"
        assert second.stdin is not None
        second.stdin.write("\n")
        second.stdin.flush()
        assert second.wait(timeout=5) == 0
    finally:
        if first.poll() is None:
            first.kill()
            first.wait()
        if second is not None and second.poll() is None:
            second.kill()
            second.wait()


def test_given_cache_publication_fails_when_prompt_changes_then_old_build_is_not_run(
    tmp_path: Path,
    generator: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    from aiscript import prompt_file

    source = tmp_path / "prompt"
    source.write_text("First prompt\n", encoding="utf-8")
    assert cli.main([str(source), "first"]) == 0
    capfd.readouterr()
    source.write_text("Second prompt\n", encoding="utf-8")

    def fail(*args: Any, **kwargs: Any) -> NoReturn:
        raise OSError("publication failed")

    with monkeypatch.context() as patch:
        patch.setattr(prompt_file, "_publish", fail)
        assert cli.main([str(source), "must-not-run"]) != 0
    output = capfd.readouterr()
    assert output.out == ""
    assert "publication failed" in output.err
    source.write_text("First prompt\n", encoding="utf-8")
    assert cli.main([str(source), "first"]) == 0
    assert capfd.readouterr().out == "arg:<first>\n"
    assert len(generator.calls) == 2


def test_given_uncached_shebang_when_os_launches_then_builds_and_forwards_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    source = tmp_path / "first-build"
    source.write_text("#!/usr/bin/env aiscript\nCopy stdin\n", encoding="utf-8")
    source.chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "generated.txt"
    executable = bindir / "aiscript"
    code = "#!/usr/bin/env python3\nimport sys\nsys.stdout.write(sys.stdin.read())\n"
    wrapper = (
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        "from aiscript import cli, llm\n"
        "from aiscript.config import Settings, ProviderConfig\n"
        "cli.load_settings = lambda: Settings(ProviderConfig('fake', 'k', None, 'm'), None)\n"
        "def generate(provider, name, intent, **kw):\n"
        f" Path({str(calls)!r}).write_text(intent)\n"
        f" return llm.GeneratedScript({code!r}, 'python', [])\n"
        "llm.generate_script = generate\n"
        "raise SystemExit(cli.main())\n"
    )
    executable.write_text(wrapper, encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    result = subprocess.run(
        [str(source)], input="input data\n", capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "input data\n"
    assert calls.read_text(encoding="utf-8") == "Copy stdin\n"


def test_given_local_dependency_with_console_script_when_built_then_script_path_works(
    tmp_path: Path,
    generator: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    import zipfile

    from aiscript import env, reviewer

    wheel = tmp_path / "localdemo-1.0-py3-none-any.whl"
    records = {
        "localdemo.py": "def main():\n print('installed-script-ok')\n",
        "localdemo-1.0.dist-info/METADATA": (
            "Metadata-Version: 2.1\nName: localdemo\nVersion: 1.0\n"
        ),
        "localdemo-1.0.dist-info/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        "localdemo-1.0.dist-info/entry_points.txt": (
            "[console_scripts]\nlocaldemo = localdemo:main\n"
        ),
    }
    record_name = "localdemo-1.0.dist-info/RECORD"
    records[record_name] = "".join(f"{name},,\n" for name in [*records, record_name])
    with zipfile.ZipFile(wheel, "w") as package:
        for name, content in records.items():
            package.writestr(name, content)
    source = tmp_path / "prompt"
    source.write_text("run installed dependency command", encoding="utf-8")
    generator.script = (
        "#!/usr/bin/env python3\n"
        "import pathlib, subprocess, sys\n"
        "command = pathlib.Path(sys.executable).parent / 'localdemo'\n"
        "raise SystemExit(subprocess.call([str(command)]))\n"
    )
    generator.dependencies = [str(wheel)]
    monkeypatch.setattr(env, "uv_path", lambda: None)
    monkeypatch.setattr(reviewer, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    assert cli.main([str(source)]) == 0
    assert "installed-script-ok" in capfd.readouterr().out
