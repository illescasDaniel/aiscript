"""First-use and starter configuration scenarios S17 and S20–S23."""

import io
import sys

import pytest
import yaml

from aiscript import init_cmd, paths


class InteractiveInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_given_fresh_init_when_noninteractive_then_template_has_all_provider_examples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    # when
    assert init_cmd.run_init() == 0
    text = paths.config_path().read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    # then
    assert parsed["default_provider"] == "openai"
    for name in (
        "anthropic",
        "gemini",
        "codex-acp",
        "claude-acp",
        "gemini-acp",
        "opencode-go-acp",
        "glm-acp",
    ):
        assert name in text
    assert parsed.get("acp", {}).get("timeout_seconds", 100) == 100


def test_given_interactive_eof_when_first_use_init_then_no_config_is_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(sys, "stdin", InteractiveInput(""))
    monkeypatch.setattr(sys, "stderr", InteractiveInput())
    # when
    result = init_cmd.run_init()
    # then
    assert result != 0
    assert not paths.config_path().exists()


def test_given_existing_config_when_interactive_init_then_bytes_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    paths.aiscript_home().mkdir(parents=True)
    paths.config_path().write_text("default_provider: personal\n", encoding="utf-8")
    stdin = InteractiveInput("1\n")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stderr", InteractiveInput())
    # when
    assert init_cmd.run_init() == 0
    # then
    assert paths.config_path().read_text(encoding="utf-8") == "default_provider: personal\n"
    assert stdin.tell() == 0
