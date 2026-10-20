import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from aiscript import env


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    env.find_python.cache_clear()


def which_map(monkeypatch: pytest.MonkeyPatch, found: dict[str, str]) -> None:
    monkeypatch.setattr(env.shutil, "which", lambda name: found.get(name))


def fake_run(
    monkeypatch: pytest.MonkeyPatch, outputs: dict[str, Any], calls: list[list[str]] | None = None
) -> None:
    """outputs maps argv[0] to (returncode, stdout, stderr) or an exception to raise."""

    def run(argv: list[str], **kw: Any) -> SimpleNamespace:
        if calls is not None:
            calls.append(argv)
        out = outputs[argv[0]]
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(returncode=out[0], stdout=out[1], stderr=out[2])

    monkeypatch.setattr(env.subprocess, "run", run)


def test_python_command_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env.platform, "system", lambda: "Linux")
    which_map(monkeypatch, {"python": "/bin/python", "python3": "/bin/python3"})
    assert env.python_command() == ["/bin/python3"]
    which_map(monkeypatch, {"python": "/bin/python"})
    assert env.python_command() == ["/bin/python"]


def test_python_command_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env.platform, "system", lambda: "Windows")
    which_map(monkeypatch, {"py": "C:\\py.exe", "python": "C:\\python.exe"})
    assert env.python_command() == ["C:\\py.exe", "-3"]


def test_python_command_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    which_map(monkeypatch, {})
    assert env.python_command() == [sys.executable]


def test_find_python_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env.platform, "system", lambda: "Linux")
    which_map(monkeypatch, {"python3": "/bin/python3"})
    calls: list[list[str]] = []
    fake_run(monkeypatch, {"/bin/python3": (0, "Python 3.12.4\n", "")}, calls)
    info = env.find_python()
    assert info == env.PythonInfo(["/bin/python3"], "3.12.4", True)
    assert env.find_python() is info and len(calls) == 1  # cached
    assert calls[0] == ["/bin/python3", "--version"]


def test_find_python_skips_broken_and_old(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env.platform, "system", lambda: "Linux")
    which_map(monkeypatch, {"python3": "/bin/python3", "python": "/bin/python"})
    fake_run(monkeypatch, {"/bin/python3": (9009, "", ""), "/bin/python": (0, "", "Python 2.7.18")})
    info = env.find_python()
    assert info == env.PythonInfo([sys.executable], info.version, False)


@pytest.mark.parametrize(
    "result",
    [OSError("nope"), subprocess.TimeoutExpired("x", 5), (0, "", ""), (1, "Python 3.12.1", "")],
)
def test_find_python_unavailable(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    monkeypatch.setattr(env.platform, "system", lambda: "Windows")
    which_map(monkeypatch, {"py": "C:\\py.exe"})
    fake_run(monkeypatch, {"C:\\py.exe": result})
    assert env.find_python().is_system is False


def test_find_python_windows_py_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env.platform, "system", lambda: "Windows")
    which_map(monkeypatch, {"py": "C:\\py.exe"})
    calls: list[list[str]] = []
    fake_run(monkeypatch, {"C:\\py.exe": (0, "Python 3.11.9", "")}, calls)
    assert env.find_python().command == ["C:\\py.exe", "-3"]
    assert calls[0] == ["C:\\py.exe", "-3", "--version"]


def test_uv_path(monkeypatch: pytest.MonkeyPatch) -> None:
    which_map(monkeypatch, {"uv": "/bin/uv"})
    assert env.uv_path() == "/bin/uv"
    which_map(monkeypatch, {})
    assert env.uv_path() is None


def test_describe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env.platform, "system", lambda: "Linux")
    monkeypatch.setattr(env.platform, "release", lambda: "6.1")
    monkeypatch.setattr(env.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        env, "find_python", lambda: env.PythonInfo(["/bin/python3"], "3.12.4", True)
    )
    which_map(monkeypatch, {"uv": "/bin/uv"})
    text = env.describe()
    assert text.startswith("- Host OS: Linux 6.1")
    for line in (
        "- Architecture: x86_64",
        "- Native shell: Bash",
        "- Python: 3.12.4 (python3)",
        "- uv: available",
    ):
        assert line in text.splitlines()


def test_describe_fallback_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env.platform, "system", lambda: "Windows")
    monkeypatch.setattr(env.platform, "release", lambda: "11")
    monkeypatch.setattr(env, "find_python", lambda: env.PythonInfo(["x"], "3.13.0", False))
    which_map(monkeypatch, {})
    text = env.describe()
    assert "- Native shell: PowerShell" in text
    assert "aiscript's own interpreter" in text and "- uv: not installed" in text


def test_os_description_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(env.platform, "release", lambda: "24.1.0")
    monkeypatch.setattr(env.platform, "mac_ver", lambda: ("15.1", ("", "", ""), "arm64"))
    assert env._os_description() == "Darwin 24.1.0 (macOS 15.1)"
