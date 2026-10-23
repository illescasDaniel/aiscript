import os
import stat
import sys
import time
from pathlib import Path
from typing import NoReturn

import pytest
from helpers import TTY, FakeLLM

from aiscript import builder, llm, paths, pysetup, reviewer
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


PY = "#!/usr/bin/env python3\n# aiscript: hi\n# Description: says hi\n# Usage: hi\nprint('hi')\n"


def test_build_python_writes_py(settings: Settings, fake_llm: FakeLLM) -> None:
    fake_llm.script = PY
    write_prompt("hi")
    path = builder.build("hi", settings)
    assert path == paths.functions_dir() / "hi.py"
    assert path == paths.function_path("hi")
    assert path.read_text() == PY


def test_language_switch_removes_old_build(settings: Settings, fake_llm: FakeLLM) -> None:
    write_prompt("hi")
    old = builder.build("hi", settings)
    fake_llm.script = PY
    new = builder.build("hi", settings)
    assert not old.exists()
    assert [p.name for p in paths.functions_dir().iterdir()] == [new.name]


def test_dependencies_need_approval(settings: Settings, fake_llm: FakeLLM) -> None:
    fake_llm.script, fake_llm.dependencies = PY, ["requests"]
    write_prompt("hi")
    # non-interactive stdin in pytest -> refused even though the code itself is benign
    with pytest.raises(AiscriptError, match="rejected"):
        builder.build("hi", settings)
    assert list(paths.functions_dir().iterdir()) == []


def test_dependencies_build_project(
    settings: Settings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm.script, fake_llm.dependencies = PY, ["requests"]
    write_prompt("hi")
    paths.functions_dir().joinpath("hi.py").write_text(PY)  # previous stdlib-only build
    monkeypatch.setattr(reviewer, "confirm", lambda s, r, **kw: True)
    calls: list[tuple[str, str, list[str]]] = []

    def fake_install(name: str, code: str, deps: list[str]) -> Path:
        calls.append((name, code, deps))
        main = paths.project_dir(name) / "main.py"
        main.parent.mkdir()
        main.write_text(code)
        return main

    monkeypatch.setattr(pysetup, "install", fake_install)
    path = builder.build("hi", settings)
    assert calls == [("hi", PY, ["requests"])]
    assert path == paths.project_dir("hi") / "main.py" == paths.function_path("hi")
    assert [p.name for p in paths.functions_dir().iterdir()] == ["hi"]


def test_failed_project_install_keeps_old_build(
    settings: Settings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_prompt("hi")
    old = builder.build("hi", settings)
    fake_llm.script, fake_llm.dependencies = PY, ["requests"]
    monkeypatch.setattr(reviewer, "confirm", lambda s, r, **kw: True)

    def boom(name: str, code: str, deps: list[str]) -> NoReturn:
        raise AiscriptError("pip failed")

    monkeypatch.setattr(pysetup, "install", boom)
    with pytest.raises(AiscriptError, match="pip failed"):
        builder.build("hi", settings)
    assert old.read_text() == SAFE


@pytest.mark.parametrize("answer", ["noninteractive", "n", "", "maybe", "eof", "interrupt"])
def test_given_risky_rebuild_when_cancelled_then_previous_script_and_installs_are_untouched(
    settings: Settings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    # given
    write_prompt("hi")
    old = paths.functions_dir() / "hi.py"
    old.write_text(PY)
    fake_llm.script, fake_llm.dependencies = PY, ["requests"]
    installs: list[object] = []
    monkeypatch.setattr(pysetup, "install", lambda *args: installs.append(args))
    monkeypatch.setattr(
        reviewer,
        "llm_review",
        lambda *args: reviewer.ReviewResult(True, ["OpenAI Decisions review unavailable"]),
    )
    settings = Settings(
        generator=settings.generator,
        reviewer=ProviderConfig(
            "openai_decisions", "key", None, "gpt-6-luna", kind="openai", api="decisions"
        ),
    )

    class ConfirmationInput:
        def isatty(self) -> bool:
            return answer != "noninteractive"

        def readline(self) -> str:
            if answer == "eof":
                return ""
            if answer == "interrupt":
                raise KeyboardInterrupt
            return answer + "\n"

    monkeypatch.setattr(sys, "stdin", ConfirmationInput())

    # when
    with pytest.raises(AiscriptError, match="Script rejected; nothing saved."):
        builder.build("hi", settings)

    # then
    assert installs == []
    assert old.read_text() == PY
    assert list(paths.functions_dir().iterdir()) == [old]


@pytest.mark.parametrize("answer", ["y", "yes"])
def test_given_unavailable_review_when_user_explicitly_approves_then_build_is_saved(
    settings: Settings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    # given
    write_prompt("hi")
    monkeypatch.setattr(
        reviewer,
        "llm_review",
        lambda *args: reviewer.ReviewResult(True, ["OpenAI Decisions review unavailable"]),
    )
    settings = Settings(
        generator=settings.generator,
        reviewer=ProviderConfig(
            "openai_decisions", "key", None, "gpt-6-luna", kind="openai", api="decisions"
        ),
    )
    monkeypatch.setattr(sys, "stdin", TTY(answer))

    # when
    result = builder.build("hi", settings)

    # then
    assert result.read_text() == SAFE


def test_given_safe_review_when_stdin_is_noninteractive_then_build_does_not_prompt(
    settings: Settings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    write_prompt("hi")
    monkeypatch.setattr(reviewer, "llm_review", lambda *args: reviewer.ReviewResult(False, []))
    settings = Settings(
        generator=settings.generator,
        reviewer=ProviderConfig(
            "openai_decisions", "key", None, "gpt-6-luna", kind="openai", api="decisions"
        ),
    )

    def unexpected_prompt(*args: object) -> NoReturn:
        pytest.fail("Safe noninteractive builds must not ask for confirmation")

    monkeypatch.setattr("builtins.input", unexpected_prompt)

    # when
    result = builder.build("hi", settings)

    # then
    assert result.read_text() == SAFE
