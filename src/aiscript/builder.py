"""Staleness check and build pipeline."""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

from aiscript import llm, paths, pysetup, reviewer
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

    result = reviewer.review(script.code, script.language, settings.reviewer, script.dependencies)
    if not reviewer.confirm(script.code, result):
        raise AiscriptError("Script rejected; nothing saved.")

    paths.ensure_dirs()
    if script.dependencies:
        target = pysetup.install(name, script.code, script.dependencies)
    else:
        target = paths.function_target(name, script.language, has_deps=False)
        _write_file(name, target, script.code)
    _remove_other_artifacts(name, target)
    print(f"Saved {target}", file=sys.stderr)
    return target


def _write_file(name: str, target: Path, code: str) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=paths.functions_dir(), prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(code)
        if not paths.is_windows():
            os.chmod(tmp_name, 0o755)
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _remove_other_artifacts(name: str, target: Path) -> None:
    """Drop builds of ``name`` in another language or layout, so only ``target`` remains."""
    for path in paths.function_artifacts(name):
        if path == target or path in target.parents:
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            print(f"aiscript: warning: could not remove old build {path}: {exc}", file=sys.stderr)
