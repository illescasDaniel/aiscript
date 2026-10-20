"""Project folders with a private virtual environment for Python scripts with dependencies."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from aiscript import env, paths
from aiscript.errors import AiscriptError

_MARKER = ".aiscript-deps.json"
_TIMEOUT = 600
# Files that describe an installed venv and travel with it when it is reused.
_REUSABLE = (".venv", "pyproject.toml", "uv.lock", "requirements.txt", _MARKER)


def _normalise(dependencies: list[str]) -> list[str]:
    return sorted({d.strip() for d in dependencies if d.strip()})


def _venv_python(project: Path) -> Path:
    sub = ("Scripts", "python.exe") if paths.is_windows() else ("bin", "python")
    return project.joinpath(".venv", *sub)


def _run(cmd: list[str], cwd: Path, env_vars: dict[str, str] | None = None) -> None:
    """Run ``cmd``; raise AiscriptError with the tail of its output on failure."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env_vars,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise AiscriptError(f"Timed out after {_TIMEOUT}s running: {' '.join(cmd)}") from None
    except OSError as exc:
        raise AiscriptError(f"Could not run {cmd[0]!r}: {exc}") from None
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").strip().splitlines()[-20:])
        raise AiscriptError(f"`{' '.join(cmd)}` failed (exit {proc.returncode}):\n{tail}")


def _project_name(name: str) -> str:
    return "aiscript-" + re.sub(r"[^A-Za-z0-9._-]+", "-", name)


def _install_uv(uv: str, name: str, staging: Path, deps: list[str], py: env.PythonInfo) -> None:
    major_minor = ".".join(py.version.split(".")[:2])
    deps_toml = ", ".join(json.dumps(d) for d in deps)
    (staging / "pyproject.toml").write_text(
        "[project]\n"
        f"name = {json.dumps(_project_name(name))}\n"
        'version = "0"\n'
        f'requires-python = ">={major_minor}"\n'
        f"dependencies = [{deps_toml}]\n"
        "\n[tool.uv]\n"
        "package = false\n",
        encoding="utf-8",
        newline="\n",
    )
    clean = {
        k: v for k, v in os.environ.items() if k not in ("UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV")
    }
    _run([uv, "sync", "--python", major_minor], staging, clean)


def _install_pip(staging: Path, deps: list[str], py: env.PythonInfo) -> None:
    (staging / "requirements.txt").write_text(
        "".join(f"{d}\n" for d in deps), encoding="utf-8", newline="\n"
    )
    venv_dir = staging / ".venv"
    try:
        _run([*py.command, "-m", "venv", str(venv_dir)], staging)
    except AiscriptError as exc:
        text = str(exc)
        if "ensurepip" in text or "python3-venv" in text or "No module named venv" in text:
            raise AiscriptError(
                f"Could not create a virtual environment: {exc}\n"
                "Install the venv module (e.g. `apt install python3-venv` on Debian/Ubuntu) "
                "or install uv (https://docs.astral.sh/uv/)."
            ) from None
        raise
    cmd = [str(_venv_python(staging)), "-m", "pip", "install", "--disable-pip-version-check"]
    _run([*cmd, "-r", "requirements.txt"], staging)


def _reuse(
    current: Path, staging: Path, deps: list[str], installer: str, version: str
) -> list[str]:
    """Move the reusable venv files of ``current`` into ``staging`` if they match; return names."""
    try:
        meta = json.loads((current / _MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if (
        not isinstance(meta, dict)
        or meta.get("dependencies") != deps
        or meta.get("installer") != installer
        or meta.get("python") != version
        or not _venv_python(current).exists()
    ):
        return []
    moved: list[str] = []
    try:
        for item in _REUSABLE:
            if (current / item).exists():
                os.replace(current / item, staging / item)
                moved.append(item)
    except OSError:
        _restore(current, staging, moved)
        return []
    return moved


def _restore(current: Path, staging: Path, moved: list[str]) -> None:
    for item in moved:
        with contextlib.suppress(OSError):
            os.replace(staging / item, current / item)


def _swap(staging: Path, final: Path, name: str) -> None:
    """Replace ``final`` with ``staging``, restoring the old project if the swap fails."""
    backup: Path | None = None
    if final.exists():
        backup = final.with_name(f".{name}.old.{os.getpid()}")
        shutil.rmtree(backup, ignore_errors=True)
        os.replace(final, backup)
    try:
        os.replace(staging, final)
    except BaseException:
        if backup is not None:
            with contextlib.suppress(OSError):
                os.replace(backup, final)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def install(name: str, code: str, dependencies: list[str]) -> Path:
    """Create/replace ``functions/<name>/`` (main.py + venv) atomically; return main.py's path."""
    paths.validate_command_name(name)
    paths.ensure_dirs()
    functions = paths.functions_dir()
    final = functions / name
    deps = _normalise(dependencies)
    py = env.find_python()
    uv = env.uv_path()
    installer = "uv" if uv else "pip"

    staging = Path(tempfile.mkdtemp(dir=functions, prefix=f".{name}.", suffix=".tmp"))
    moved: list[str] = []
    try:
        main = staging / "main.py"
        main.write_text(code, encoding="utf-8", newline="\n")
        if not paths.is_windows():
            os.chmod(main, 0o755)

        moved = _reuse(final, staging, deps, installer, py.version) if final.is_dir() else []
        if not moved:
            print(
                f"Installing dependencies for {name!r} with {installer}: {', '.join(deps)}...",
                file=sys.stderr,
            )
            if uv:
                _install_uv(uv, name, staging, deps, py)
            else:
                _install_pip(staging, deps, py)
            (staging / _MARKER).write_text(
                json.dumps({"dependencies": deps, "installer": installer, "python": py.version}),
                encoding="utf-8",
            )
        _swap(staging, final, name)
    except BaseException:
        if moved and final.is_dir():
            _restore(final, staging, moved)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final / "main.py"
