"""Execute a cached script."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from aiscript import paths
from aiscript.errors import AiscriptError


def _command(path: Path, args: list[str]) -> list[str]:
    if paths.is_windows():
        shell = shutil.which("pwsh") or "powershell"
        return [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(path),
            *args,
        ]
    if os.access(path, os.X_OK):
        return [str(path), *args]
    return ["bash", str(path), *args]


def run_script(path: Path, args: list[str]) -> int:
    """Run ``path`` with ``args``, inheriting stdio; return its exit code."""
    cmd = _command(path, args)
    try:
        proc = subprocess.run(cmd)
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        raise AiscriptError(f"Could not execute {path}: {exc}") from exc
    rc = proc.returncode
    if rc < 0:  # killed by a signal (POSIX)
        return 128 - rc
    return rc
