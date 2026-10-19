import os
from pathlib import Path

import pytest

from aiscript import listing, paths

T = 1_000_000_000_000_000_000
SEC = 1_000_000_000  # Windows timestamps have 100 ns resolution: offsets must be coarser

HEADER = """#!/usr/bin/env bash
set -euo pipefail
# aiscript: foo
# Description: Does foo things
# Usage: foo <a> [b]
# more comment
echo hi
"""


def write(path: Path, text: str, mtime_ns: int | None = None) -> None:
    paths.ensure_dirs()
    path.write_text(text)
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))


def test_parse_header(tmp_path: Path) -> None:
    p = tmp_path / "f.sh"
    p.write_text(HEADER)
    assert listing.parse_header(p) == {
        "description": "Does foo things",
        "usage": "foo <a> [b]",
    }


def test_parse_header_case_insensitive_and_missing(tmp_path: Path) -> None:
    p = tmp_path / "f.sh"
    p.write_text("#!/bin/bash\n#description:   lower\n")
    assert listing.parse_header(p) == {"description": "lower", "usage": ""}
    p.write_text("echo hi\n")
    assert listing.parse_header(p) == {"description": "", "usage": ""}


def test_parse_header_only_first_40_lines(tmp_path: Path) -> None:
    p = tmp_path / "f.sh"
    p.write_text("\n" * 45 + "# Description: late\n")
    assert listing.parse_header(p)["description"] == ""


def test_parse_header_missing_file(tmp_path: Path) -> None:
    assert listing.parse_header(tmp_path / "nope") == {"description": "", "usage": ""}


def test_list_empty(capsys: pytest.CaptureFixture[str]) -> None:
    assert listing.list_commands() == 0
    cap = capsys.readouterr()
    assert "No commands yet. Try: aiscript <name>" in cap.err
    assert cap.out == ""


def test_list_table(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "120")
    write(paths.prompt_path("foo"), "do foo", T)
    write(paths.function_path("foo"), HEADER, T + 10 * SEC)
    write(paths.prompt_path("bar"), "do bar", T)
    assert listing.list_commands() == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["NAME", "DESCRIPTION", "USAGE"]
    foo = next(line for line in out if line.startswith("foo"))
    bar = next(line for line in out if line.startswith("bar"))
    assert "Does foo things" in foo and "foo <a> [b]" in foo
    assert "(not built)" in bar
    assert "*" not in foo
    assert out.index(bar) < out.index(foo)  # sorted
    assert not any("rebuild" in line for line in out)


def test_list_stale_marked(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "120")
    write(paths.function_path("foo"), HEADER, T)
    write(paths.prompt_path("foo"), "changed", T + SEC)
    write(paths.function_path("ok"), HEADER, T + 5 * SEC)
    write(paths.prompt_path("ok"), "same", T)
    listing.list_commands()
    out = capsys.readouterr().out
    foo = next(line for line in out.splitlines() if line.startswith("foo"))
    ok = next(line for line in out.splitlines() if line.startswith("ok"))
    assert "foo *" in foo
    assert "*" not in ok
    assert "will rebuild" in out


def test_list_equal_mtime_not_stale(capsys: pytest.CaptureFixture[str]) -> None:
    write(paths.function_path("foo"), HEADER, T)
    write(paths.prompt_path("foo"), "x", T)
    listing.list_commands()
    assert "*" not in capsys.readouterr().out


def test_list_function_without_prompt(capsys: pytest.CaptureFixture[str]) -> None:
    write(paths.function_path("orphan"), HEADER)
    listing.list_commands()
    assert "orphan" in capsys.readouterr().out


def test_list_ignores_invalid_names(capsys: pytest.CaptureFixture[str]) -> None:
    write(paths.prompts_dir() / "bad name.txt", "x")
    write(paths.prompt_path("good"), "x")
    listing.list_commands()
    out = capsys.readouterr().out
    assert "good" in out and "bad name" not in out


def test_list_truncates_description(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "60")
    long = "# Description: " + "word " * 40 + "\n# Usage: foo\n"
    write(paths.function_path("foo"), "#!/bin/bash\n" + long)
    listing.list_commands()
    lines = capsys.readouterr().out.splitlines()
    assert any("…" in line for line in lines)
    assert all(len(line) <= 60 for line in lines)
