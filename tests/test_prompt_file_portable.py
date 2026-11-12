"""Portable prompt file behavior and failure coverage."""

from __future__ import annotations

import io
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any, NoReturn

import pytest
from helpers import FakeLLM

from aiscript import cli, env, llm, prompt_file, pysetup, reviewer
from aiscript.config import ProviderConfig, Settings

PROGRAM = "#!/usr/bin/env python3\nprint('safe')\n"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM(PROGRAM)
    monkeypatch.setattr(llm, "generate_script", fake)
    monkeypatch.setattr(
        cli, "load_settings", lambda: Settings(ProviderConfig("fake", "key", None, "m"), None)
    )
    return fake


def test_given_risky_prompt_and_noninteractive_stdin_when_refused_then_stdin_is_untouched(
    tmp_path: Path, fake: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "prompt"
    source.write_text("dangerous task", encoding="utf-8")
    fake.script = "#!/usr/bin/env python3\nimport os\nos.system('sudo ls')\n"
    stream = io.StringIO("data for program\n")
    monkeypatch.setattr(sys, "stdin", stream)
    assert cli.main([str(source)]) != 0
    assert stream.read() == "data for program\n"


def test_given_declined_review_when_building_file_then_nothing_is_published(
    tmp_path: Path, fake: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "prompt"
    source.write_text("task", encoding="utf-8")
    monkeypatch.setattr(reviewer, "confirm", lambda *args, **kwargs: False)
    assert cli.main([str(source)]) != 0
    assert not list((tmp_path / "aiscript" / "file-cache").rglob("manifest.json"))


def test_given_dependency_setup_failure_when_rebuilding_then_prior_cache_survives(
    tmp_path: Path, fake: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "prompt"
    source.write_text("first", encoding="utf-8")
    monkeypatch.setattr(prompt_file, "run_script", lambda path, args: 0)
    assert cli.main([str(source)]) == 0
    source.write_text("second", encoding="utf-8")
    fake.dependencies = ["example-package"]
    monkeypatch.setattr(reviewer, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(env, "uv_path", lambda: None)
    monkeypatch.setattr(
        env, "find_python", lambda: env.PythonInfo([sys.executable], "3.13.0", False)
    )

    def fail(*args: Any, **kwargs: Any) -> NoReturn:
        raise cli.AiscriptError("dependency installation failed")

    monkeypatch.setattr(pysetup, "_install_pip", fail)
    assert cli.main([str(source)]) != 0
    source.write_text("first", encoding="utf-8")
    assert cli.main([str(source)]) == 0
    assert len(fake.calls) == 2


def test_given_unreadable_prompt_when_invoked_then_reports_failure(
    tmp_path: Path,
    fake: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "prompt"
    source.write_text("task", encoding="utf-8")
    original = Path.open

    def inaccessible(self: Path, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if self == source:
            raise PermissionError("access denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", inaccessible)
    assert cli.main([str(source)]) != 0
    assert "access denied" in capsys.readouterr().err
    assert not fake.calls


def test_given_corrupt_cache_when_invoked_then_does_not_build_or_run(
    tmp_path: Path,
    fake: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "prompt"
    source.write_text("task", encoding="utf-8")
    monkeypatch.setattr(prompt_file, "run_script", lambda path, args: 0)
    assert cli.main([str(source)]) == 0
    manifest = next((tmp_path / "aiscript" / "file-cache").rglob("manifest.json"))
    manifest.write_text("{", encoding="utf-8")
    assert cli.main([str(source)]) != 0
    assert "cache" in capsys.readouterr().err.lower()
    assert len(fake.calls) == 1


def test_given_program_cannot_launch_when_invoked_then_reports_failure(
    tmp_path: Path,
    fake: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "prompt"
    source.write_text("task", encoding="utf-8")
    monkeypatch.setattr(env, "python_command", lambda: ["missing-interpreter-for-test"])
    assert cli.main([str(source)]) != 0
    assert "Could not execute" in capsys.readouterr().err


def test_given_concurrent_source_edit_when_building_then_each_run_matches_its_snapshot(
    tmp_path: Path,
    fake: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "prompt"
    source.write_text("first", encoding="utf-8")
    entered = Event()
    proceed = Event()
    executed: list[str] = []

    def generate(
        provider: ProviderConfig, name: str, intent: str, *, max_calls_per_run: int = 1
    ) -> llm.GeneratedScript:
        if intent == "first":
            entered.set()
            assert proceed.wait(5)
        return llm.GeneratedScript(f"#!/usr/bin/env python3\n# {intent}\n", "python", [])

    def run(path: Path, args: list[str]) -> int:
        executed.append(path.read_text(encoding="utf-8"))
        return 0

    monkeypatch.setattr(llm, "generate_script", generate)
    monkeypatch.setattr(prompt_file, "run_script", run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cli.main, [str(source)])
        assert entered.wait(5)
        source.write_text("second", encoding="utf-8")
        second = pool.submit(cli.main, [str(source)])
        proceed.set()
        assert first.result(timeout=10) == 0
        assert second.result(timeout=10) == 0
    assert len(executed) == 2
    assert any("# first\n" in code for code in executed)
    assert any("# second\n" in code for code in executed)
