"""``aiscript --check-secrets``: scan the cached scripts and prompts."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from aiscript import paths
from aiscript.config import collect_known_secrets, load_raw_config
from aiscript.secret_scan import KnownSecrets, SecretFinding, scan

_SKIPPED_DIRS = frozenset({".venv", "__pycache__", "node_modules"})
_SKIPPED_SUFFIXES = (".tmp", ".bak", "~")


def _is_source(path: Path) -> bool:
    name = path.name
    return not name.startswith(".") and not name.endswith(_SKIPPED_SUFFIXES)


def _files_under(directory: Path) -> Iterator[Path]:
    """Source files below ``directory``, not entering virtual environments or caches."""
    if not directory.is_dir():
        return
    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d not in _SKIPPED_DIRS and not d.startswith("."))
        for name in sorted(files):
            path = Path(root) / name
            if _is_source(path) and path.is_file():
                yield path


def cached_sources(home: Path) -> list[Path]:
    """Every cached prompt and script under ``home``."""
    found: list[Path] = []
    prompts = home / "prompts"
    if prompts.is_dir():
        found.extend(p for p in sorted(prompts.glob("*.txt")) if _is_source(p) and p.is_file())
    found.extend(_files_under(home / "functions"))
    cache = home / "file-cache"
    if cache.is_dir():
        for version in sorted(cache.glob("*/version-*")):
            found.extend(_files_under(version))
    return found


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def sweep(sources: Sequence[Path], secrets: KnownSecrets) -> list[tuple[Path, list[SecretFinding]]]:
    """Scan each source; return only those with findings."""
    result: list[tuple[Path, list[SecretFinding]]] = []
    for path in sources:
        text = _read(path)
        if text is None:
            continue
        language = None if path.suffix == ".txt" else paths.language_of(path)
        findings = scan(text, secrets, language=language)
        if findings:
            result.append((path, findings))
    return result


def _label(path: Path, home: Path) -> str:
    try:
        return path.relative_to(home).as_posix()
    except ValueError:
        return path.as_posix()


def check_secrets() -> int:
    """Run the sweep over the real home and print a report; return the exit code."""
    home = paths.aiscript_home()
    secrets = KnownSecrets.from_values(collect_known_secrets(load_raw_config(), os.environ))
    hits = sweep(cached_sources(home), secrets)
    if not hits:
        print("aiscript: no keys found in cached scripts or prompts.", file=sys.stderr)
        return 0
    for path, findings in hits:
        for line in sorted({f.line for f in findings}):
            print(f"{_label(path, home)}:{line}: looks like an API key", file=sys.stderr)
    print(
        "aiscript: rotate the key, then rebuild or remove the listed commands.",
        file=sys.stderr,
    )
    return 1
