from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiscript import env, paths, pysetup
from aiscript.errors import AiscriptError

CODE = "#!/usr/bin/env python3\nprint('hi')\n"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AISCRIPT_HOME", str(tmp_path))
    monkeypatch.setattr(paths, "is_windows", lambda: False)
    monkeypatch.setattr(
        env, "find_python", lambda: env.PythonInfo(["/usr/bin/python3"], "3.12.1", True)
    )
    return tmp_path / "functions"


class Runner:
    """Fake for pysetup._run that records calls and creates the files a real run would."""

    def __init__(self, fail_on: str | None = None, message: str = "boom") -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on
        self.message = message

    def __call__(self, cmd: list[str], cwd: Path, env_vars: dict[str, str] | None = None) -> None:
        self.calls.append(cmd)
        if self.fail_on and self.fail_on in cmd:
            raise AiscriptError(self.message)
        if "sync" in cmd:
            (cwd / ".venv" / "bin").mkdir(parents=True)
            (cwd / ".venv" / "bin" / "python").write_text("")
            (cwd / "uv.lock").write_text("lock")
        elif "venv" in cmd:
            (cwd / ".venv" / "bin").mkdir(parents=True)
            (cwd / ".venv" / "bin" / "python").write_text("")


def _use_uv(monkeypatch: pytest.MonkeyPatch, available: bool) -> None:
    monkeypatch.setattr(env, "uv_path", lambda: "/usr/bin/uv" if available else None)


def test_uv_install(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_uv(monkeypatch, True)
    runner = Runner()
    monkeypatch.setattr(pysetup, "_run", runner)
    main = pysetup.install("tool", CODE, ["requests>=2", "rich"])
    assert main == home / "tool" / "main.py"
    assert main.read_text() == CODE
    pyproject = (home / "tool" / "pyproject.toml").read_text()
    assert 'name = "aiscript-tool"' in pyproject
    assert 'requires-python = ">=3.12"' in pyproject
    assert 'dependencies = ["requests>=2", "rich"]' in pyproject
    assert runner.calls == [["/usr/bin/uv", "sync", "--python", "3.12"]]
    assert (home / "tool" / "uv.lock").exists()
    marker = json.loads((home / "tool" / ".aiscript-deps.json").read_text())
    assert marker["installer"] == "uv"
    assert [p.name for p in home.iterdir()] == ["tool"]


def test_pip_install(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_uv(monkeypatch, False)
    runner = Runner()
    monkeypatch.setattr(pysetup, "_run", runner)
    main = pysetup.install("tool", CODE, ["rich", "requests"])
    assert (home / "tool" / "requirements.txt").read_text() == "requests\nrich\n"
    assert runner.calls[0][:3] == ["/usr/bin/python3", "-m", "venv"]
    assert runner.calls[1][1:5] == ["-m", "pip", "install", "--disable-pip-version-check"]
    assert runner.calls[1][-2:] == ["-r", "requirements.txt"]
    assert main.exists()


def test_failure_keeps_previous_and_cleans_staging(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_uv(monkeypatch, True)
    monkeypatch.setattr(pysetup, "_run", Runner())
    pysetup.install("tool", CODE, ["rich"])

    monkeypatch.setattr(pysetup, "_run", Runner(fail_on="sync"))
    with pytest.raises(AiscriptError, match="boom"):
        pysetup.install("tool", "print('new')\n", ["other"])
    assert (home / "tool" / "main.py").read_text() == CODE
    assert [p.name for p in home.iterdir()] == ["tool"]


def test_failure_on_new_project_leaves_nothing(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_uv(monkeypatch, True)
    monkeypatch.setattr(pysetup, "_run", Runner(fail_on="sync"))
    with pytest.raises(AiscriptError):
        pysetup.install("tool", CODE, ["rich"])
    assert list(home.iterdir()) == []


def test_reuse_when_dependencies_unchanged(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_uv(monkeypatch, True)
    monkeypatch.setattr(pysetup, "_run", Runner())
    pysetup.install("tool", CODE, ["rich", "requests"])
    sentinel = home / "tool" / ".venv" / "sentinel"
    sentinel.write_text("x")

    second = Runner()
    monkeypatch.setattr(pysetup, "_run", second)
    main = pysetup.install("tool", "print('v2')\n", ["requests", "rich"])
    assert second.calls == []
    assert main.read_text() == "print('v2')\n"
    assert (home / "tool" / ".venv" / "sentinel").exists()
    assert (home / "tool" / "uv.lock").exists()


def test_no_reuse_when_installer_changes(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_uv(monkeypatch, True)
    monkeypatch.setattr(pysetup, "_run", Runner())
    pysetup.install("tool", CODE, ["rich"])

    _use_uv(monkeypatch, False)
    runner = Runner()
    monkeypatch.setattr(pysetup, "_run", runner)
    pysetup.install("tool", CODE, ["rich"])
    assert len(runner.calls) == 2
    assert not (home / "tool" / "uv.lock").exists()
    assert (home / "tool" / "requirements.txt").exists()


def test_replace_with_new_dependencies(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_uv(monkeypatch, True)
    monkeypatch.setattr(pysetup, "_run", Runner())
    pysetup.install("tool", CODE, ["rich"])
    runner = Runner()
    monkeypatch.setattr(pysetup, "_run", runner)
    pysetup.install("tool", "print('v2')\n", ["rich", "httpx"])
    assert len(runner.calls) == 1
    assert (home / "tool" / "main.py").read_text() == "print('v2')\n"
    assert '"httpx"' in (home / "tool" / "pyproject.toml").read_text()
    assert [p.name for p in home.iterdir()] == ["tool"]


def test_ensurepip_error_suggests_python3_venv(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_uv(monkeypatch, False)
    monkeypatch.setattr(
        pysetup, "_run", Runner(fail_on="venv", message="ensurepip is not available")
    )
    with pytest.raises(AiscriptError, match="python3-venv") as exc:
        pysetup.install("tool", CODE, ["rich"])
    assert "uv" in str(exc.value)
    assert list(home.iterdir()) == []
