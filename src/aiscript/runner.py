"""Execute a cached script."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from aiscript import env, paths
from aiscript.ask_counter import COUNTER_ENV, run_counter
from aiscript.errors import AiscriptError

# Read-only directory with the Python `aiscript` shim (package data, versioned with the install).
SHIM_DIR = Path(__file__).resolve().parent / "_shim"


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


_SHIM_IMPORT = re.compile(
    r"^\s*(?:import\s+(?:[\w.]+(?:\s+as\s+\w+)?\s*,\s*)*aiscript\b|from\s+aiscript\b)", re.MULTILINE
)


def uses_shim(path: Path) -> bool:
    """True for a Python script whose source imports ``aiscript`` (D1)."""
    if path.suffix != ".py":
        return False
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _SHIM_IMPORT.search(source) is not None


def script_env(path: Path, base: Mapping[str, str], counter_dir: Path | None) -> dict[str, str]:
    """Environment for a script run: `base` plus the counter and, for shim users, PYTHONPATH."""
    result = dict(base)
    if counter_dir is not None:
        result[COUNTER_ENV] = str(counter_dir)
    if uses_shim(path):
        existing = base.get("PYTHONPATH")
        parts = [str(SHIM_DIR), existing] if existing else [str(SHIM_DIR)]
        result["PYTHONPATH"] = os.pathsep.join(parts)
    return result


def run_script(path: Path, args: list[str]) -> int:
    """Run ``path`` with ``args``, inheriting stdio; return its exit code."""
    cmd = _command(path, args)
    try:
        with run_counter() as counter_dir:
            proc = subprocess.run(cmd, env=script_env(path, os.environ, counter_dir))
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        raise AiscriptError(f"Could not execute {path}: {exc}") from exc
    rc = proc.returncode
    if rc < 0:  # killed by a signal (POSIX)
        return 128 - rc
    return rc
