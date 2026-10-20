import os
import sys
from pathlib import Path
from typing import Any, NoReturn

import pytest

from aiscript import paths, runner
from aiscript.errors import AiscriptError

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash scripts")

SCRIPT = """#!/usr/bin/env bash
echo "argc=$#"
for a in "$@"; do echo "[$a]"; done
"""


def make(tmp_path: Path, body: str = SCRIPT, mode: int = 0o755) -> Path:
    p = tmp_path / "s.sh"
    p.write_text(body)
    p.chmod(mode)
    return p


def test_exit_code_zero(tmp_path: Path) -> None:
    assert runner.run_script(make(tmp_path), []) == 0


@pytest.mark.parametrize("code", [1, 3, 42])
def test_exit_code_propagates(tmp_path: Path, code: int) -> None:
    p = make(tmp_path, f"#!/usr/bin/env bash\nexit {code}\n")
    assert runner.run_script(p, []) == code


def test_args_passthrough(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    rc = runner.run_script(make(tmp_path), ["--flag", "hello world", "-x", "", "--help"])
    out = capfd.readouterr().out
    assert rc == 0
    assert out.splitlines() == [
        "argc=5",
        "[--flag]",
        "[hello world]",
        "[-x]",
        "[]",
        "[--help]",
    ]


def test_non_executable_falls_back_to_bash(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    p = make(tmp_path, mode=0o644)
    assert not os.access(p, os.X_OK)
    assert runner.run_script(p, ["a"]) == 0
    assert "[a]" in capfd.readouterr().out


def test_signal_death_code(tmp_path: Path) -> None:
    p = make(tmp_path, "#!/usr/bin/env bash\nkill -TERM $$\n")
    assert runner.run_script(p, []) == 128 + 15


def test_keyboard_interrupt_returns_130(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner.subprocess, "run", boom)
    assert runner.run_script(make(tmp_path), []) == 130


def test_os_error_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> NoReturn:
        raise FileNotFoundError("nope")

    monkeypatch.setattr(runner.subprocess, "run", boom)
    with pytest.raises(AiscriptError):
        runner.run_script(make(tmp_path), [])


def test_windows_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.paths, "is_windows", lambda: True)
    monkeypatch.setattr(runner.shutil, "which", lambda n: None)
    cmd = runner._command(tmp_path / "x.ps1", ["a", "--b"])
    assert cmd[0] == "powershell"
    assert cmd[-3:] == [str(tmp_path / "x.ps1"), "a", "--b"]
    assert "-File" in cmd
    monkeypatch.setattr(runner.shutil, "which", lambda n: "/bin/pwsh")
    assert runner._command(tmp_path / "x.ps1", [])[0] == "/bin/pwsh"


def test_python_script_uses_system_python(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aiscript.env.python_command", lambda: ["py", "-3"])
    cmd = runner._command(tmp_path / "x.py", ["a"])
    assert cmd == ["py", "-3", str(tmp_path / "x.py"), "a"]


def test_project_main_uses_venv(tmp_path: Path) -> None:
    py = paths.venv_python(tmp_path)
    py.parent.mkdir(parents=True)
    py.write_text("")
    main = tmp_path / "main.py"
    assert runner._command(main, ["a", "--b"]) == [str(py), str(main), "a", "--b"]


def test_project_main_without_venv_errors(tmp_path: Path) -> None:
    proj = tmp_path / "foo"
    proj.mkdir()
    with pytest.raises(AiscriptError, match="aiscript --rebuild foo"):
        runner._command(proj / "main.py", [])


def test_run_python_script(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "x.py"
    p.write_text("import sys\nprint(sys.argv[1:])\nsys.exit(3)\n")
    assert runner.run_script(p, ["hi"]) == 3
    assert "['hi']" in capfd.readouterr().out


def test_command_named_main_is_plain_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aiscript.env.python_command", lambda: ["py3"])
    paths.ensure_dirs()
    script = paths.functions_dir() / "main.py"
    script.write_text("print('hi')\n")
    assert runner._command(script, ["a"]) == ["py3", str(script), "a"]
