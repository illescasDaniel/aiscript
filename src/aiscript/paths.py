"""Config-root paths, name validation, and OS/shell detection."""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from typing import Literal

from aiscript.errors import AiscriptError

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Language of a generated script. "bash"/"powershell" are the native shells.
Language = Literal["bash", "powershell", "python"]


def aiscript_home() -> Path:
    """Return the config root: $AISCRIPT_HOME, $XDG_CONFIG_HOME/aiscript, or ~/.config/aiscript."""
    override = os.environ.get("AISCRIPT_HOME")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "aiscript"
    return Path.home() / ".config" / "aiscript"


def prompts_dir() -> Path:
    return aiscript_home() / "prompts"


def functions_dir() -> Path:
    return aiscript_home() / "functions"


def config_path() -> Path:
    return aiscript_home() / "config.yaml"


def legacy_secrets_path() -> Path:
    """Old name of config.yaml; still read (with a warning) when config.yaml is missing."""
    return aiscript_home() / "secrets.yaml"


def ensure_dirs() -> None:
    """Create prompts/ and functions/ (and the home) if missing."""
    prompts_dir().mkdir(parents=True, exist_ok=True)
    functions_dir().mkdir(parents=True, exist_ok=True)


def validate_command_name(name: str) -> str:
    """Return ``name`` if it is a safe command name, else raise AiscriptError."""
    if not _NAME_RE.fullmatch(name):
        raise AiscriptError(
            f"Invalid command name {name!r}: use letters, digits, '_' or '-', "
            "starting with a letter or digit."
        )
    return name


def is_windows() -> bool:
    return platform.system() == "Windows"


def shell_kind() -> Literal["bash", "powershell"]:
    return "powershell" if is_windows() else "bash"


def script_ext() -> Literal["sh", "ps1"]:
    return "ps1" if is_windows() else "sh"


def prompt_path(name: str) -> Path:
    return prompts_dir() / f"{validate_command_name(name)}.txt"


def project_dir(name: str) -> Path:
    """Directory of a Python script with dependencies (main.py, .venv, lock files)."""
    return functions_dir() / validate_command_name(name)


def function_path(name: str) -> Path:
    """Existing artifact for ``name`` (project main.py, .py, native shell), else the shell path."""
    validate_command_name(name)
    for candidate in (
        project_dir(name) / "main.py",
        functions_dir() / f"{name}.py",
        functions_dir() / f"{name}.{script_ext()}",
    ):
        if candidate.is_file():
            return candidate
    return functions_dir() / f"{name}.{script_ext()}"


def function_target(name: str, language: Language, *, has_deps: bool) -> Path:
    """Where a new build of ``name`` is written."""
    if language == "python" and has_deps:
        return project_dir(name) / "main.py"
    ext = {"python": "py", "powershell": "ps1", "bash": "sh"}[language]
    return functions_dir() / f"{validate_command_name(name)}.{ext}"


def function_artifacts(name: str) -> list[Path]:
    """Every existing artifact of ``name``: script files and the project dir."""
    validate_command_name(name)
    found = [p for ext in ("sh", "ps1", "py") if (p := functions_dir() / f"{name}.{ext}").is_file()]
    project = project_dir(name)
    if (project / "main.py").is_file():
        found.append(project)
    return found


def language_of(path: Path) -> Language:
    if path.suffix == ".py":
        return "python"
    if path.suffix == ".ps1":
        return "powershell"
    return "bash"


def is_project_main(path: Path) -> bool:
    """True for ``functions/<name>/main.py``, not a plain script of a command named ``main``."""
    return path.name == "main.py" and path.parent.resolve() != functions_dir().resolve()


def venv_python(project: Path) -> Path:
    if is_windows():
        return project / ".venv" / "Scripts" / "python.exe"
    return project / ".venv" / "bin" / "python"
