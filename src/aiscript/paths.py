"""Config-root paths, name validation, and OS/shell detection."""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from typing import Literal

from aiscript.errors import AiscriptError

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


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


def function_path(name: str) -> Path:
    return functions_dir() / f"{validate_command_name(name)}.{script_ext()}"
