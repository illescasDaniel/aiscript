"""Staleness check and build pipeline."""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path

from aiscript import llm, paths, reviewer
from aiscript.config import Settings
from aiscript.errors import AiscriptError


def needs_build(name: str) -> bool:
    """True if the function is missing or older than its prompt."""
    fpath = paths.function_path(name)
    if not fpath.exists():
        return True
    ppath = paths.prompt_path(name)
    if not ppath.exists():
        return False
    return ppath.stat().st_mtime_ns > fpath.stat().st_mtime_ns


def _read_intent(name: str) -> str:
    ppath = paths.prompt_path(name)
    try:
        intent = ppath.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise AiscriptError(
            f"No prompt for {name!r}. Run `aiscript {name}` to create it."
        ) from None
    if not intent:
        raise AiscriptError(f"Prompt for {name!r} is empty: {ppath}")
    return intent


def build(name: str, settings: Settings) -> Path:
    """Generate, review and atomically write the script for ``name``."""
    intent = _read_intent(name)
    gen = settings.generator
    print(f"Generating {name!r} with {gen.name}/{gen.model}...", file=sys.stderr)
    script = llm.generate_script(gen, name, intent)

    shell = paths.shell_kind()
    result = reviewer.review(script, shell, settings.reviewer)
    if not reviewer.confirm(script, result):
        raise AiscriptError("Script rejected; nothing saved.")

    paths.ensure_dirs()
    target = paths.function_path(name)
    fd, tmp_name = tempfile.mkstemp(dir=paths.functions_dir(), prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(script)
        if not paths.is_windows():
            os.chmod(tmp_name, 0o755)
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    print(f"Saved {target}", file=sys.stderr)
    return target
