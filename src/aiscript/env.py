"""Host environment detection for the generator prompt and the runner."""

from __future__ import annotations

import functools
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_MIN_PYTHON = (3, 8)
_VERSION_TIMEOUT_SECONDS = 5.0
_VERSION_RE = re.compile(r"Python (\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class PythonInfo:
    command: list[str]  # argv prefix that runs it, e.g. ["/usr/bin/python3"] or ["py", "-3"]
    version: str  # e.g. "3.13.1"
    is_system: bool  # False when falling back to aiscript's own interpreter (sys.executable)


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _candidates() -> list[list[str]]:
    """Argv prefixes to try, best first (only those whose executable is on PATH)."""
    names = [["py", "-3"], ["python"]] if _is_windows() else [["python3"], ["python"]]
    found: list[list[str]] = []
    for argv in names:
        exe = shutil.which(argv[0])
        if exe:
            found.append([exe, *argv[1:]])
    return found


def python_command() -> list[str]:
    """Fast (PATH lookup only, no subprocess): argv prefix for running a stdlib-only script."""
    candidates = _candidates()
    return candidates[0] if candidates else [sys.executable]


def _probe(command: list[str]) -> str | None:
    """Return the ``X.Y.Z`` version of ``command`` if it is a working Python >= 3.8."""
    try:
        result = subprocess.run(
            [*command, "--version"],
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:  # e.g. the Windows Store stub
        return None
    match = _VERSION_RE.search(f"{result.stdout}\n{result.stderr}")
    if not match:
        return None
    major, minor, patch = (int(g) for g in match.groups())
    if (major, minor) < _MIN_PYTHON:
        return None
    return f"{major}.{minor}.{patch}"


@functools.cache
def find_python() -> PythonInfo:
    """System Python with its version (runs ``--version``); falls back to sys.executable."""
    for command in _candidates():
        version = _probe(command)
        if version:
            return PythonInfo(command, version, True)
    return PythonInfo([sys.executable], platform.python_version(), False)


def uv_path() -> str | None:
    """Path to the ``uv`` executable, or None."""
    return shutil.which("uv")


def _os_description() -> str:
    system = platform.system() or "Unknown"
    desc = f"{system} {platform.release()}".strip()
    if system == "Linux":
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    pretty = line.split("=", 1)[1].strip().strip("\"'")
                    desc += f" ({pretty})"
                    break
        except OSError:
            pass
    elif system == "Darwin":
        mac_version = platform.mac_ver()[0]
        if mac_version:
            desc += f" (macOS {mac_version})"
    return desc


def describe() -> str:
    """Multi-line TARGET ENVIRONMENT block for the generator's system prompt."""
    py = find_python()
    if py.is_system:
        shown = " ".join([Path(py.command[0]).name.removesuffix(".exe"), *py.command[1:]])
        python_line = f"{py.version} ({shown})"
    else:
        python_line = f"{py.version} (aiscript's own interpreter; no suitable system Python found)"
    shell = "PowerShell" if _is_windows() else "Bash"
    lines = [
        f"- Host OS: {_os_description()}",
        f"- Architecture: {platform.machine() or 'unknown'}",
        f"- Native shell: {shell}",
        f"- Python: {python_line}",
        f"- uv: {'available' if uv_path() else 'not installed'}",
    ]
    return "\n".join(lines)
