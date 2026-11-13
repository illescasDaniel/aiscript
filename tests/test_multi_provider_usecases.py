"""Use-case level multi-provider scenarios: S1-S5, S19, S21, S22, S24, S25, S27 and S9."""

import io
import os
import stat
import sys
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
import yaml

from aiscript import ask_cli, config, init_cmd, llm, onboarding, paths
from aiscript.ask import AskPrompt
from aiscript.config import AcpSettings
from aiscript.errors import AiscriptError, ConfigError
from aiscript.provider_factory import ACP_COMMANDS, AskBridge, make_provider
from aiscript.providers.contracts import (
    CompletionError,
    CompletionRequest,
    CompletionResult,
    ProviderCapabilities,
)

ACP_FIXTURE = Path(__file__).parent / "fixtures" / "fake_multi_provider_acp.py"
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}
SCHEMA = (
    '{"type":"object","properties":{"count":{"type":"integer"}},'
    '"required":["count"],"additionalProperties":false}'
)
OFFICIAL_URLS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/m1:generateContent",
}


class Interactive(io.StringIO):
    def isatty(self) -> bool:
        return True


def write_config(text: str) -> None:
    paths.aiscript_home().mkdir(parents=True, exist_ok=True)
    paths.config_path().write_text(text, encoding="utf-8")
    paths.config_path().chmod(0o600)


def capture_post(monkeypatch: pytest.MonkeyPatch, vendor: str) -> list[str]:
    urls: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        urls.append(url)
        if vendor == "anthropic":
            body: dict[str, Any] = {
                "content": [{"type": "text", "text": "native answer"}],
                "stop_reason": "end_turn",
            }
        else:
            body = {
                "candidates": [
                    {"content": {"parts": [{"text": "native answer"}]}, "finishReason": "STOP"}
                ]
            }
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx, "post", fake_post)
    return urls


def use_fixture_agent(monkeypatch: pytest.MonkeyPatch, name: str = "codex-acp") -> None:
    monkeypatch.setitem(ACP_COMMANDS, name, (sys.executable, str(ACP_FIXTURE)))


def run_ask(
    config_text: str, schema: str | None = None, data: bytes = b"input"
) -> tuple[int, bytes]:
    write_config(config_text)
    stdout = io.BytesIO()
    code = ask_cli.run(
        "summarise", "a document", schema, stdin=io.BytesIO(data), stdout=stdout, environ={}
    )
    return code, stdout.getvalue()


# --- G1 / S1 / S2: native default endpoints carry the API version path ---


@pytest.mark.parametrize("vendor", ["anthropic", "gemini"])
def test_given_native_provider_without_base_url_when_generating_then_versioned_url_is_posted(
    vendor: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv(KEYS[vendor], "native-secret-key-123456")
    write_config(f"default_provider: {vendor}\nproviders:\n  {vendor}:\n    model: m1\n")
    urls = capture_post(monkeypatch, vendor)
    settings = config.load_settings()
    # when
    answer = llm.chat(settings.generator, "system", "user")
    # then
    assert answer == "native answer"
    assert urls == [OFFICIAL_URLS[vendor]]


@pytest.mark.parametrize("vendor", ["anthropic", "gemini"])
def test_given_native_provider_without_base_url_when_asking_then_versioned_url_is_posted(
    vendor: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    urls = capture_post(monkeypatch, vendor)
    monkeypatch.setenv(KEYS[vendor], "native-secret-key-123456")
    write_config(f"default_provider: {vendor}\nproviders:\n  {vendor}:\n    model: m1\n")
    raw = config.load_raw_config()
    target = config.identify_ask_target(raw)
    key = config.resolve_ask_key(target, raw, os.environ)
    provider = make_provider(
        target.kind, target.provider, target.model, target.base_url, key, 5, AcpSettings()
    )
    # when
    reply = AskBridge(provider, is_acp=False, timeout=5).complete(AskPrompt("s", "u", None, 50))
    # then
    assert reply.text == "native answer"
    assert urls == [OFFICIAL_URLS[vendor]]


@pytest.mark.parametrize("vendor", ["anthropic", "gemini"])
def test_given_default_native_url_when_checked_then_only_official_origin_receives_env_key(
    vendor: str,
) -> None:
    # given
    official = config._NATIVE_URLS[vendor]
    # when / then
    assert config._native_official(vendor, None)
    assert config._native_official(vendor, official)
    assert not config._native_official(vendor, "https://evil.example/v1")
    assert not config._native_official(vendor, official.replace("https://", "http://"))
    assert not config._native_official(vendor, "https://x@" + official.removeprefix("https://"))


# --- G5 / S3: ACP generation through llm.chat ---


def test_given_acp_generator_when_chat_runs_then_agent_text_is_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    use_fixture_agent(monkeypatch)
    write_config("default_provider: codex-acp\n")
    settings = config.load_settings()
    # when
    answer = llm.chat(settings.generator, "system", "user")
    # then
    assert settings.generator.kind == "acp"
    assert answer == "fixture answer"


def test_given_missing_agent_executable_when_chat_runs_then_error_names_it_and_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setitem(ACP_COMMANDS, "codex-acp", ("no-such-agent-executable",))
    write_config("default_provider: codex-acp\n")
    settings = config.load_settings()
    # when / then
    with pytest.raises(AiscriptError) as caught:
        llm.chat(settings.generator, "system", "private user text")
    assert "no-such-agent-executable" in str(caught.value)
    assert "PATH" in str(caught.value)
    assert "private user text" not in str(caught.value)


# --- G5 / S4 and S27: ACP ask ---


def test_given_acp_ask_with_schema_when_answer_matches_then_json_is_printed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # given
    use_fixture_agent(monkeypatch)
    monkeypatch.setenv("FAKE_ACP_TEXT", '{"count": 3}')
    schema = SCHEMA
    # when
    code, out = run_ask("default_provider: codex-acp\n", schema)
    # then
    assert code == 0
    assert out == b'{"count":3}\n'
    assert "fixture" not in capsys.readouterr().err


def test_given_acp_ask_with_schema_when_answer_mismatches_then_exit_8_and_no_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # given
    use_fixture_agent(monkeypatch)
    monkeypatch.setenv("FAKE_ACP_TEXT", '{"count": "three"}')
    schema = SCHEMA
    # when
    code, out = run_ask("default_provider: codex-acp\n", schema)
    # then
    assert code == 8
    assert out == b""
    assert "three" not in capsys.readouterr().err


def test_given_acp_ask_with_configured_timeout_when_it_runs_then_one_notice_names_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # given
    use_fixture_agent(monkeypatch)
    # when
    code, out = run_ask("default_provider: codex-acp\nacp:\n  timeout_seconds: 120\n")
    # then
    stderr = capsys.readouterr().err
    assert code == 0
    assert out == b"fixture answer\n"
    notices = [line for line in stderr.splitlines() if line.startswith("aiscript:")]
    assert notices == ["aiscript: This request can take up to 120 seconds."]
    assert stderr.count("120") == 1


def test_given_missing_acp_executable_when_asking_then_message_names_it_without_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # given
    monkeypatch.setitem(ACP_COMMANDS, "codex-acp", ("no-such-agent-executable",))
    # when
    code, out = run_ask("default_provider: codex-acp\n", data=b"private document")
    # then
    stderr = capsys.readouterr().err
    assert code == 5
    assert out == b""
    assert "no-such-agent-executable" in stderr
    assert "PATH" in stderr
    assert "private document" not in stderr


# --- G4 / S9: the strict-schema requirement is forwarded and honoured ---


class RecordingProvider:
    def __init__(self, error: CompletionError | None = None) -> None:
        self.requests: list[CompletionRequest] = []
        self.error = error

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        caps = ProviderCapabilities(True, True, True, True)
        return CompletionResult("completed", "{}", caps)


@pytest.mark.parametrize(("is_acp", "expected"), [(False, True), (True, False)])
def test_given_schema_ask_when_bridged_then_strict_schema_is_required_only_for_apis(
    is_acp: bool, expected: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    # given
    provider = RecordingProvider()
    bridge = AskBridge(provider, is_acp=is_acp, timeout=5)
    # when
    bridge.complete(AskPrompt("s", "u", {"type": "object"}, 50))
    # then
    assert provider.requests[0].require_strict_schema is expected
    assert provider.requests[0].max_output_tokens == 50


def test_given_unsupported_capability_when_asking_then_actionable_text_reaches_the_user(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # given
    error = CompletionError("unsupported")
    error.kind, error.status_code = "unsupported", None
    error.detail = "this provider cannot guarantee strict JSON schema output; remove the schema"
    monkeypatch.setattr(
        "aiscript.ask_cli.make_provider", lambda *args, **kwargs: RecordingProvider(error)
    )
    schema = SCHEMA
    # when
    code, out = run_ask("default_provider: codex-acp\n", schema)
    # then
    assert code == 5
    assert out == b""
    assert "strict JSON schema" in capsys.readouterr().err


# --- G5 / S5: generator-path resolution ---


def test_given_builtin_acp_and_unrelated_entries_when_generator_resolves_then_builtin_wins() -> (
    None
):
    # given
    write_config("default_provider: codex-acp\nproviders:\n  other:\n    model: unused\n")
    # when
    generator = config.load_settings().generator
    # then
    assert (generator.name, generator.kind) == ("codex-acp", "acp")


def test_given_explicit_same_name_entry_when_generator_resolves_then_definition_wins() -> None:
    # given
    write_config(
        "default_provider: codex-acp\nproviders:\n  codex-acp:\n"
        "    base_url: http://localhost:1/v1\n    model: mine\n"
    )
    # when
    generator = config.load_settings().generator
    # then
    assert generator.kind == "openai"
    assert (generator.base_url, generator.model) == ("http://localhost:1/v1", "mine")


def test_given_unknown_provider_when_generator_resolves_then_config_error_is_raised() -> None:
    # given
    write_config("default_provider: nowhere\nproviders:\n  other:\n    model: unused\n")
    # when / then
    with pytest.raises(ConfigError, match="nowhere"):
        config.load_settings()


# --- G5 / S19, S21, S22, S24: first-use onboarding ---


def scripted(monkeypatch: pytest.MonkeyPatch, answers: str) -> Interactive:
    err = Interactive()
    monkeypatch.setattr(sys, "stdin", Interactive(answers))
    monkeypatch.setattr(sys, "stderr", err)
    return err


def test_given_first_use_when_provider_is_chosen_then_private_complete_config_is_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    err = scripted(monkeypatch, "2\n")
    # when
    proceed = onboarding.setup_if_needed(init_cmd.CONFIG_TEMPLATE)
    # then
    path = paths.config_path()
    text = path.read_text(encoding="utf-8")
    assert proceed
    assert yaml.safe_load(text)["default_provider"] == "anthropic"
    assert text == init_cmd.CONFIG_TEMPLATE.replace(
        "default_provider: openai", "default_provider: anthropic", 1
    )
    assert "Created config file" in err.getvalue()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_given_invalid_menu_input_when_prompted_then_menu_reprompts_until_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    err = scripted(monkeypatch, "99\nbogus\n\n3\n")
    # when
    proceed = onboarding.setup_if_needed(init_cmd.CONFIG_TEMPLATE)
    # then
    assert proceed
    assert err.getvalue().count("Choose a listed provider.") == 3
    default = yaml.safe_load(paths.config_path().read_text(encoding="utf-8"))["default_provider"]
    assert default == "gemini"


@pytest.mark.parametrize("failing", ["fsync", "link"])
def test_given_publication_failure_when_publishing_then_error_and_no_partial_file(
    failing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    def boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk trouble")

    monkeypatch.setattr(os, failing, boom)
    target = tmp_path / "config.yaml"
    # when / then
    with pytest.raises(AiscriptError, match="Cannot create config file"):
        onboarding.publish_config(target, "default_provider: gemini\n")
    assert list(tmp_path.iterdir()) == []


def test_given_env_override_when_onboarding_then_generation_uses_it_and_ask_uses_saved_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-key-123456")
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe-test-key-123456")
    monkeypatch.setenv("AISCRIPT_PROVIDER", "openai")
    err = scripted(monkeypatch, "2\n")
    # when
    onboarding.setup_if_needed(init_cmd.CONFIG_TEMPLATE)
    # then
    assert "AISCRIPT_PROVIDER selects openai" in err.getvalue()
    assert config.load_settings().generator.name == "openai"
    assert config.identify_ask_target(config.load_raw_config()).provider == "anthropic"
    monkeypatch.delenv("AISCRIPT_PROVIDER")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key-123456")
    assert config.load_settings().generator.name == "anthropic"


# --- G5 / S25: starter example activation ---


def starter_with(default: str, uncomment: str) -> str:
    text = init_cmd.CONFIG_TEMPLATE.replace(
        "default_provider: openai", f"default_provider: {default}", 1
    )
    assert f"  # {uncomment}" in text
    return text.replace(f"  # {uncomment}", f"  {uncomment}", 1)


@pytest.mark.parametrize(
    "name", ["codex-acp", "claude-acp", "gemini-acp", "opencode-go-acp", "glm-acp"]
)
def test_given_starter_acp_entry_uncommented_when_resolved_then_builtin_acp_is_selected(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe-test-key-123456")
    text = starter_with(name, f"{name}:\n")
    write_config(text)
    assert yaml.safe_load(text)["providers"][name] is None
    # when
    target = config.identify_ask_target(config.load_raw_config())
    generator = config.load_settings().generator
    # then
    assert (target.provider, target.kind) == (name, "acp")
    assert (generator.name, generator.kind) == (name, "acp")


@pytest.mark.parametrize("vendor", ["anthropic", "gemini"])
def test_given_starter_native_entry_when_selected_then_native_is_used_with_env_key(
    vendor: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe-test-key-123456")
    text = init_cmd.CONFIG_TEMPLATE.replace(
        "default_provider: openai", f"default_provider: {vendor}", 1
    )
    write_config(text)
    monkeypatch.setenv(KEYS[vendor], "native-secret-key-123456")
    # when
    generator = config.load_settings().generator
    # then
    assert generator.kind == vendor
    assert generator.model == ("claude-sonnet-5-5" if vendor == "anthropic" else "gemini-3-pro")
