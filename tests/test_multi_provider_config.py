"""Approved multi-provider configuration scenarios S5, S15, S16 and S26."""

import pytest

from aiscript import config
from aiscript.errors import AskConfigError, ConfigError


@pytest.mark.parametrize(
    "name", ["codex-acp", "claude-acp", "gemini-acp", "opencode-go-acp", "glm-acp"]
)
def test_given_builtin_and_unrelated_provider_when_ask_resolves_then_builtin_is_selected(
    name: str,
) -> None:
    # given
    raw = {"default_provider": name, "providers": {"other": {"model": "unused"}}}
    # when
    target = config.identify_ask_target(raw)
    # then
    assert target.provider == name


def test_given_explicit_name_collision_when_ask_resolves_then_definition_wins() -> None:
    # given
    raw = {
        "default_provider": "codex-acp",
        "providers": {"codex-acp": {"model": "my-model", "base_url": "http://localhost/v1"}},
    }
    # when
    target = config.identify_ask_target(raw)
    # then
    assert target.model == "my-model"
    assert target.base_url == "http://localhost/v1"


def test_given_omitted_acp_limits_when_loaded_then_defaults_apply() -> None:
    # given
    raw: dict[str, object] = {}
    # when
    limits = config.load_acp_settings(raw)
    # then
    assert (limits.timeout_seconds, limits.max_frame_kib, limits.max_response_kib) == (
        100,
        1024,
        1024,
    )


def test_given_custom_acp_limits_when_loaded_then_values_are_preserved() -> None:
    # given
    raw = {"acp": {"timeout_seconds": 120, "max_frame_kib": 256, "max_response_kib": 512}}
    # when
    limits = config.load_acp_settings(raw)
    # then
    assert (limits.timeout_seconds, limits.max_frame_kib, limits.max_response_kib) == (
        120,
        256,
        512,
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("timeout_seconds", True),
        ("timeout_seconds", 0),
        ("timeout_seconds", 601),
        ("max_frame_kib", False),
        ("max_frame_kib", 0),
        ("max_frame_kib", 16385),
        ("max_response_kib", "1024"),
        ("max_response_kib", 16385),
    ],
)
def test_given_invalid_acp_limit_when_loaded_then_configuration_fails(
    key: str, value: object
) -> None:
    # given
    raw = {"acp": {key: value}}
    # when / then
    with pytest.raises(ConfigError):
        config.load_acp_settings(raw)


@pytest.mark.parametrize("key", ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"])
def test_given_implicit_native_key_when_collecting_secrets_then_key_is_included(key: str) -> None:
    # given
    secret = "known-secret-value-123456"
    # when
    secrets = config.collect_known_secrets({}, {key: secret})
    # then
    assert secret in secrets


@pytest.mark.parametrize("entry", [None, {}])
def test_given_empty_builtin_acp_entry_when_ask_resolves_then_acp_is_selected(
    entry: dict[str, str] | None,
) -> None:
    # given
    raw = {"default_provider": "codex-acp", "providers": {"codex-acp": entry}}
    # when
    target = config.identify_ask_target(raw)
    # then
    assert target.kind == "acp"


def test_given_unknown_provider_without_providers_when_resolved_then_no_empty_known_list() -> None:
    # given
    raw = {"default_provider": "nowhere"}
    # when / then
    with pytest.raises(AskConfigError) as caught:
        config.identify_ask_target(raw)
    assert "known providers" not in str(caught.value)
