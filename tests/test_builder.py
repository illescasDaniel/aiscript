import base64
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import NoReturn

import pytest
from helpers import TTY, FakeLLM

from aiscript import builder, llm, paths, pysetup, reviewer
from aiscript.config import AiSettings, ProviderConfig, Settings
from aiscript.errors import AiscriptError, SecretFoundError

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


# ---- AI in scripts: key scans and wiring (S4, S5, S6, C7)

KEY = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
OTHER_KEY = "sk-proj-ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210"  # not configured: pattern match only
FRAGMENT = KEY[12:24]
HEADER = "#!/usr/bin/env bash\n# aiscript: hi\n# Description: d\n# Usage: hi\n"
PY_HEADER = "#!/usr/bin/env python3\n# aiscript: hi\n# Description: d\n# Usage: hi\n"
OLD = "#!/usr/bin/env bash\n# old build\necho old\n"


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


@pytest.fixture
def key_settings() -> Settings:
    return Settings(
        generator=ProviderConfig("fake", "k", None, "m"), reviewer=None, known_secrets=(KEY,)
    )


def _previous_build() -> Path:
    paths.ensure_dirs()
    target = paths.function_path("hi")
    target.write_text(OLD)
    return target


@pytest.mark.parametrize(
    "leak",
    [
        KEY,
        FRAGMENT,
        _b64(KEY),
        OTHER_KEY,
    ],
    ids=["exact", "fragment", "base64", "pattern"],
)
def test_given_key_in_prompt_when_build_then_refused_before_generator(
    leak: str,
    key_settings: Settings,
    fake_llm: FakeLLM,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given
    previous = _previous_build()
    write_prompt("hi", f"list files\nand also\nuse {leak} to log in\n")
    # when
    with pytest.raises(SecretFoundError) as exc:
        builder.build("hi", key_settings)
    # then
    assert fake_llm.calls == []
    message = str(exc.value)
    assert re.search(r"\bon line 3\b", message), message
    assert "remove" in message.lower()
    out = capsys.readouterr()
    for text in (message, out.out, out.err):
        assert leak not in text and KEY not in text and FRAGMENT not in text
    assert previous.read_text() == OLD
    assert [p.name for p in paths.functions_dir().iterdir()] == [previous.name]


def test_given_key_in_prompt_when_generate_reviewed_then_no_generator_call(
    key_settings: Settings, fake_llm: FakeLLM
) -> None:
    with pytest.raises(SecretFoundError):
        builder.generate_reviewed("hi", f"token is {KEY}", key_settings)
    assert fake_llm.calls == []


def test_given_clean_prompt_when_build_then_generator_called(
    key_settings: Settings, fake_llm: FakeLLM
) -> None:
    write_prompt("hi", "say hi")
    builder.build("hi", key_settings)
    assert fake_llm.calls == [("hi", "say hi")]


# every piece under 12 characters: only joined/folded views can see the key
_PIECES = [KEY[:11], KEY[11:22], KEY[22:33], KEY[33:]]
_QUOTED = [f'"{piece}"' for piece in _PIECES]

_KEY_CODE = {
    "short-plus": PY_HEADER + "k = " + " + ".join(_QUOTED) + '\nprint("hi")\n',
    "short-join": PY_HEADER + 'k = "".join([' + ", ".join(_QUOTED) + '])\nprint("hi")\n',
    "short-implicit": PY_HEADER + "k = (" + " ".join(_QUOTED) + ')\nprint("hi")\n',
    "short-names": PY_HEADER
    + "".join(f"p{i} = {q}\n" for i, q in enumerate(_QUOTED))
    + 'k = p0 + p1 + p2 + p3\nprint("hi")\n',
    "short-bash-quotes": HEADER + "KEY=" + "".join(_QUOTED) + "\necho hi\n",
    "exact": HEADER + f'KEY="{KEY}"\necho hi\n',
    "split": PY_HEADER + f'k = "{KEY[:20]}" + "{KEY[20:]}"\nprint("hi")\n',
    "reversed": PY_HEADER + f'k = "{KEY[::-1]}"[::-1]\nprint("hi")\n',
    "base64": HEADER + f"echo {_b64(KEY)} | base64 -d\n",
    "hex": PY_HEADER + f'k = bytes.fromhex("{KEY.encode().hex()}").decode()\nprint("hi")\n',
    "chr": PY_HEADER + "k = " + " + ".join(f"chr({ord(c)})" for c in KEY) + "\nprint('hi')\n",
    "printf": HEADER + "printf '" + "".join(f"\\x{ord(c):02x}" for c in KEY) + "'\n",
}


@pytest.mark.parametrize("variant", sorted(_KEY_CODE))
def test_given_key_in_generated_code_when_build_then_refused_before_reviewer(
    variant: str,
    key_settings: Settings,
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given
    fake_llm.script = _KEY_CODE[variant]
    previous = _previous_build()
    write_prompt("hi", "say hi")
    reviewed: list[str] = []

    def spy(script: str, *a: object, **kw: object) -> reviewer.ReviewResult:
        reviewed.append(script)
        return reviewer.ReviewResult(False, [])

    monkeypatch.setattr(reviewer, "review", spy)
    monkeypatch.setattr(reviewer, "confirm", lambda s, r, **kw: True)
    monkeypatch.setattr(sys, "stdin", TTY("y", "y"))
    # when
    with pytest.raises(SecretFoundError) as exc:
        builder.build("hi", key_settings)
    # then: no reviewer call, no prompt, no override, nothing printed or saved
    assert reviewed == []
    out = capsys.readouterr()
    assert out.out == ""
    for text in (str(exc.value), out.err):
        assert KEY not in text and FRAGMENT not in text
        assert "echo hi" not in text and "Run this script" not in text
    assert previous.read_text() == OLD
    assert [p.name for p in paths.functions_dir().iterdir()] == [previous.name]


def test_given_non_ai_build_when_generate_reviewed_then_wiring_passes_settings(
    monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLLM
) -> None:
    # given
    settings = Settings(
        generator=ProviderConfig("fake", "k", None, "m"),
        reviewer=None,
        ai=AiSettings(max_calls_per_run=3),
        ai_target="openai/gpt-x",
        known_secrets=(KEY,),
    )
    seen: dict[str, object] = {}

    def spy(script: str, language: str, rev: object, deps: object = (), **kw: object) -> object:
        seen.update(kw)
        return reviewer.ReviewResult(False, [])

    monkeypatch.setattr(reviewer, "review", spy)
    # when
    out = builder.generate_reviewed("hi", "say hi", settings)
    # then
    assert out.code == SAFE
    assert fake_llm.max_calls_per_run == 3
    assert seen == {"ai_target": "openai/gpt-x"}


AI_SCRIPT = HEADER + 'aiscript --ask "summarise" --data-description "lines" < f\n'


def test_given_ai_script_when_build_non_interactive_then_refused(
    key_settings: Settings, fake_llm: FakeLLM
) -> None:
    fake_llm.script = AI_SCRIPT
    write_prompt("hi")
    with pytest.raises(AiscriptError, match="Script rejected; nothing saved."):
        builder.build("hi", key_settings)
    assert list(paths.functions_dir().iterdir()) == []


def test_given_ai_script_when_user_confirms_then_saved(
    key_settings: Settings, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm.script = AI_SCRIPT
    write_prompt("hi")
    monkeypatch.setattr(sys, "stdin", TTY("y"))
    assert builder.build("hi", key_settings).read_text() == AI_SCRIPT
