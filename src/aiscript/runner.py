"""Execute a cached script."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from aiscript import env, paths
from aiscript.errors import AiscriptError


def _command(path: Path, args: list[str]) -> list[str]:
    if path.suffix == ".py":
        if paths.is_project_main(path):  # project with dependencies: run in its venv
            python = paths.venv_python(path.parent)
            if not python.exists():
                name = path.parent.name
                raise AiscriptError(
                    f"The environment of {name!r} is missing; run `aiscript --rebuild {name}`."
                )
            return [str(python), str(path), *args]
        return [*env.python_command(), str(path), *args]
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
