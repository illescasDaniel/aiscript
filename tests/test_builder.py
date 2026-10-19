import os
import stat
import sys
import time
from pathlib import Path
from typing import NoReturn

import pytest
from helpers import TTY, FakeLLM

from aiscript import builder, llm, paths, reviewer
from aiscript.config import ProviderConfig, Settings
from aiscript.errors import AiscriptError

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="bash scripts")

SAFE = "#!/usr/bin/env bash\n# aiscript: hi\n# Description: says hi\n# Usage: hi\necho hi\n"
RISKY = "#!/usr/bin/env bash\nsudo ls\n"


@pytest.fixture
def settings() -> Settings:
    return Settings(generator=ProviderConfig("fake", "k", None, "m"), reviewer=None)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    gen = FakeLLM(SAFE)
    monkeypatch.setattr(llm, "generate_script", gen)
    return gen


def write_prompt(name: str, text: str = "say hi") -> None:
    paths.ensure_dirs()
    paths.prompt_path(name).write_text(text)


def test_needs_build_missing_function() -> None:
    write_prompt("hi")
    assert builder.needs_build("hi")


def test_needs_build_mtime(settings: Settings, fake_llm: FakeLLM) -> None:
    write_prompt("hi")
    fpath = builder.build("hi", settings)
    assert not builder.needs_build("hi")
    future = time.time_ns() + 10_000_000_000
    os.utime(paths.prompt_path("hi"), ns=(future, future))
    assert builder.needs_build("hi")
    os.utime(fpath, ns=(future + 1, future + 1))
    assert not builder.needs_build("hi")


def test_build_writes_script(
    settings: Settings, fake_llm: FakeLLM, capsys: pytest.CaptureFixture[str]
) -> None:
    write_prompt("hi", "  say hi \n")
    path = builder.build("hi", settings)
    assert path == paths.function_path("hi")
    assert path.read_text() == SAFE
    assert fake_llm.calls == [("hi", "say hi")]
    assert "fake/m" in capsys.readouterr().err
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o755
    assert [p.name for p in paths.functions_dir().iterdir()] == [path.name]


def test_build_empty_prompt(settings: Settings, fake_llm: FakeLLM) -> None:
    write_prompt("hi", "  \n")
    with pytest.raises(AiscriptError, match="empty"):
        builder.build("hi", settings)
    assert fake_llm.calls == []


def test_build_missing_prompt(settings: Settings, fake_llm: FakeLLM) -> None:
    paths.ensure_dirs()
    with pytest.raises(AiscriptError, match="No prompt"):
        builder.build("nope", settings)


@posix_only
def test_risky_rejected_leaves_nothing(settings: Settings, fake_llm: FakeLLM) -> None:
    fake_llm.script = RISKY
    write_prompt("hi")
    # non-interactive stdin in pytest -> refused
    with pytest.raises(AiscriptError, match="Script rejected; nothing saved."):
        builder.build("hi", settings)
    assert list(paths.functions_dir().iterdir()) == []


@posix_only
def test_risky_declined_interactively(
    settings: Settings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm.script = RISKY
    write_prompt("hi")
    monkeypatch.setattr(sys, "stdin", TTY("n"))
    with pytest.raises(AiscriptError, match="rejected"):
        builder.build("hi", settings)
    assert list(paths.functions_dir().iterdir()) == []


@posix_only
def test_risky_approved_writes(
    settings: Settings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm.script = RISKY
    write_prompt("hi")
    monkeypatch.setattr(reviewer, "confirm", lambda s, r, **kw: r.risky)
    path = builder.build("hi", settings)
    assert path.read_text() == RISKY


def test_write_failure_cleans_temp(
    settings: Settings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_prompt("hi")

    def boom(src: str | Path, dst: str | Path) -> NoReturn:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        builder.build("hi", settings)
    assert list(paths.functions_dir().iterdir()) == []
