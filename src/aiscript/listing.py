"""Header parsing and ``--list`` output."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from aiscript import paths
from aiscript.errors import AiscriptError

_HEADER_LINES = 40
_DESC_RE = re.compile(r"^\s*#\s*Description:\s*(.*?)\s*$", re.IGNORECASE)
_USAGE_RE = re.compile(r"^\s*#\s*Usage:\s*(.*?)\s*$", re.IGNORECASE)
_NOT_BUILT = "(not built)"


def parse_header(path: Path) -> dict[str, str]:
    """Extract ``Description`` and ``Usage`` from a script's leading comment lines."""
    result = {"description": "", "usage": ""}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _, line in zip(range(_HEADER_LINES), fh, strict=False):
                if not result["description"]:
                    m = _DESC_RE.match(line)
                    if m:
                        result["description"] = m.group(1)
                        continue
                if not result["usage"]:
                    m = _USAGE_RE.match(line)
                    if m:
                        result["usage"] = m.group(1)
    except OSError:
        pass
    return result


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def _command_names() -> list[str]:
    names: set[str] = set()
    pdir, fdir = paths.prompts_dir(), paths.functions_dir()
    if pdir.is_dir():
        names.update(p.stem for p in pdir.glob("*.txt"))
    if fdir.is_dir():
        names.update(p.stem for p in fdir.glob(f"*.{paths.script_ext()}"))
    valid = []
    for n in names:
        try:
            paths.validate_command_name(n)
        except AiscriptError:
            continue
        valid.append(n)
    return sorted(valid, key=str.lower)


def list_commands() -> int:
    """Print a table of commands to stdout; return 0."""
    rows: list[tuple[str, str, str]] = []
    any_stale = False
    for name in _command_names():
        ppath = paths.prompt_path(name)
        fpath = paths.function_path(name)
        label = name
        if fpath.exists():
            header = parse_header(fpath)
            desc, usage = header["description"], header["usage"]
            if ppath.exists() and ppath.stat().st_mtime_ns > fpath.stat().st_mtime_ns:
                label += " *"
                any_stale = True
        else:
            desc, usage = _NOT_BUILT, ""
        rows.append((label, desc, usage))

    if not rows:
        print("No commands yet. Try: aiscript <name>", file=sys.stderr)
        return 0

    cols = shutil.get_terminal_size(fallback=(100, 24)).columns
    name_w = max(len("NAME"), *(len(r[0]) for r in rows))
    usage_w = min(max(len("USAGE"), *(len(r[2]) for r in rows)), 40)
    desc_w = max(20, cols - name_w - usage_w - 4)
    desc_w = min(desc_w, max(len("DESCRIPTION"), *(len(r[1]) for r in rows)))

    def fmt(a: str, b: str, c: str) -> str:
        return f"{a:<{name_w}}  {b:<{desc_w}}  {c}".rstrip()

    lines = [fmt("NAME", "DESCRIPTION", "USAGE")]
    for label, desc, usage in rows:
        lines.append(fmt(label, _truncate(desc, desc_w), _truncate(usage, usage_w)))
    print("\n".join(lines))
    if any_stale:
        print(
            "\n* prompt changed since last build; will rebuild on next run",
            file=sys.stdout,
        )
    return 0
