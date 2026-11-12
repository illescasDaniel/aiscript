import os
import sys

import pytest
from helpers import need

from aiscript.config import (
    OFFICIAL_OPENAI_URL,
    OLLAYA_DEFAULT_MODEL,
    AiSettings,
    AskTarget,
    ProviderConfig,
    collect_known_secrets,
    describe_ask_target,
    identify_ask_target,
    load_ai_settings,
    load_raw_config,
    load_settings,
    resolve_ask_key,
)
from aiscript.errors import AskConfigError, ConfigError
from aiscript.paths import aiscript_home, config_path, legacy_secrets_path


def write_config(text: str, mode: int = 0o600) -> None:
    aiscript_home().mkdir(parents=True, exist_ok=True)
    p = config_path()
    p.write_text(text, encoding="utf-8")
    os.chmod(p, mode)


def test_no_yaml_with_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    s = load_settings()
    assert s.generator.name == "openai"
    assert s.generator.api_key == "sk-env"
    assert s.generator.model == "gpt-6-luna"
    assert s.generator.base_url is None
    assert s.reviewer is None


def test_no_yaml_no_key_error_text() -> None:
    with pytest.raises(ConfigError) as ei:
        load_settings()
    msg = str(ei.value)
    assert "openai" in msg
    assert "OPENAI_API_KEY" in msg
    assert str(config_path()) in msg
    assert "aiscript --init" in msg


def test_missing_file_raw_is_empty() -> None:
    assert load_raw_config() == {}


def test_invalid_yaml() -> None:
    write_config("a: [unclosed\n")
    with pytest.raises(ConfigError):
        load_raw_config()


def test_non_mapping_yaml() -> None:
    write_config("- a\n- b\n")
    with pytest.raises(ConfigError):
        load_raw_config()


def test_yaml_key_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    write_config('providers:\n  openai: {api_key: "sk-yaml", model: "m1"}\n')
    s = load_settings()
    assert s.generator.api_key == "sk-yaml"
    assert s.generator.model == "m1"


@pytest.mark.parametrize("placeholder", ["", "sk-proj-...", "sk-...", "xyz..."])
def test_placeholder_ignored(monkeypatch: pytest.MonkeyPatch, placeholder: str) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    write_config(f'providers:\n  openai: {{api_key: "{placeholder}"}}\n')
    assert load_settings().generator.api_key == "sk-env"


def test_provider_specific_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-env")
    write_config(
        "default_provider: groq\nproviders:\n  groq: {endpoint: 'https://x/v1', model: j}\n"
    )
    s = load_settings()
    assert s.generator.api_key == "groq-env"
    assert s.generator.base_url == "https://x/v1"
    assert s.generator.model == "j"


def test_aiscript_provider_env_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISCRIPT_PROVIDER", "b")
    write_config("default_provider: a\nproviders:\n  a: {api_key: ka}\n  b: {api_key: kb}\n")
    assert load_settings().generator.name == "b"
    assert load_settings().generator.api_key == "kb"


def test_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISCRIPT_PROVIDER", "nope")
    write_config("providers:\n  a: {api_key: ka}\n")
    with pytest.raises(ConfigError, match="nope"):
        load_settings()


def test_localhost_key_bypass() -> None:
    write_config(
        "default_provider: local_ollama\nproviders:\n"
        "  local_ollama: {base_url: 'http://localhost:11434/v1', model: llama3}\n"
    )
    s = load_settings()
    assert s.generator.api_key == "not-needed"
    assert s.generator.model == "llama3"


def test_127_bypass_via_env_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1234/v1")
    s = load_settings()
    assert s.generator.api_key == "not-needed"
    assert s.generator.base_url == "http://127.0.0.1:1234/v1"


def test_remote_base_url_still_needs_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    with pytest.raises(ConfigError):
        load_settings()


def test_base_url_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env/v1")
    write_config(
        "providers:\n  openai: {api_key: k, base_url: 'https://bu/v1', endpoint: 'https://ep/v1'}\n"
    )
    assert load_settings().generator.base_url == "https://bu/v1"


def test_env_base_url_used_for_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert load_settings().generator.base_url == "https://env/v1"


def test_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("AISCRIPT_MODEL", "gpt-x")
    assert load_settings().generator.model == "gpt-x"


def test_yaml_model_beats_env_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISCRIPT_MODEL", "gpt-x")
    write_config("providers:\n  openai: {api_key: k, model: from-yaml}\n")
    assert load_settings().generator.model == "from-yaml"


def test_reviewer_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_API_KEY", "jk")
    write_config(
        "default_provider: openai\nreviewer_provider: jev\nproviders:\n"
        "  openai: {api_key: ko, model: gm}\n"
        "  jev: {endpoint: 'https://jev/v1'}\n"
    )
    s = load_settings()
    assert s.reviewer is not None
    assert need(s.reviewer).name == "jev"
    assert need(s.reviewer).api_key == "jk"
    assert need(s.reviewer).base_url == "https://jev/v1"
    assert need(s.reviewer).kind == "jev"
    assert need(s.reviewer).model == "jev-latest"  # Jev default, not the generator's model


def test_openai_reviewer_falls_back_to_generator_model(monkeypatch: pytest.MonkeyPatch) -> None:
    write_config(
        "reviewer_provider: rev\nproviders:\n"
        "  openai: {api_key: ko, model: gm}\n  rev: {api_key: kr}\n"
    )
    s = load_settings()
    assert need(s.reviewer).kind == "openai"
    assert need(s.reviewer).model == "gm"


def test_jev_reviewer_uses_typesafe_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")
    write_config("reviewer_provider: jev\nproviders:\n  openai: {api_key: ko}\n  jev: {}\n")
    s = load_settings()
    assert need(s.reviewer).api_key == "ts"
    assert need(s.reviewer).base_url is None


def test_kind_can_be_set_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    write_config(
        "reviewer_provider: guard\nproviders:\n"
        "  openai: {api_key: ko}\n  guard: {kind: jev, api_key: kg, model: jev-1.14.0}\n"
    )
    s = load_settings()
    assert (need(s.reviewer).kind, need(s.reviewer).model) == ("jev", "jev-1.14.0")


def test_unknown_kind_rejected() -> None:
    write_config("providers:\n  openai: {api_key: ko, kind: bogus}\n")
    with pytest.raises(ConfigError, match="unknown kind"):
        load_settings()


def test_jev_cannot_be_generator() -> None:
    write_config("default_provider: jev\nproviders:\n  jev: {api_key: k}\n")
    with pytest.raises(ConfigError, match="cannot generate scripts"):
        load_settings()


def test_reviewer_does_not_use_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "ko")
    write_config(
        "reviewer_provider: jev\nproviders:\n  openai: {}\n  jev: {endpoint: 'https://jev/v1'}\n"
    )
    with pytest.raises(ConfigError) as ei:
        load_settings()
    assert "jev" in str(ei.value)
    assert "JEV_API_KEY" in str(ei.value)


def test_reviewer_ignores_openai_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "ko")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env/v1")
    write_config("reviewer_provider: r\nproviders:\n  openai: {}\n  r: {api_key: kr}\n")
    s = load_settings()
    assert s.generator.base_url == "https://env/v1"
    assert need(s.reviewer).base_url is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_permission_warning(capsys: pytest.CaptureFixture[str]) -> None:
    write_config("providers:\n  openai: {api_key: k}\n", mode=0o644)
    load_settings()
    assert "chmod 600" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_no_warning_when_private(capsys: pytest.CaptureFixture[str]) -> None:
    write_config("providers:\n  openai: {api_key: k}\n", mode=0o600)
    load_settings()
    assert capsys.readouterr().err == ""


def test_api_defaults_to_responses_for_openai() -> None:
    write_config("providers:\n  openai: {api_key: k}\n")
    g = load_settings().generator
    assert g.api == "responses"
    assert g.temperature is None and g.reasoning_effort is None


def test_api_defaults_to_chat_for_other_endpoints() -> None:
    write_config(
        "default_provider: ollama\nproviders:\n"
        "  ollama: {base_url: 'http://localhost:11434/v1', model: llama3}\n"
    )
    assert load_settings().generator.api == "chat"


def test_api_effort_temperature_from_yaml() -> None:
    write_config(
        "providers:\n  openai: {api_key: k, api: chat, reasoning_effort: low, temperature: 0}\n"
    )
    g = load_settings().generator
    assert (g.api, g.reasoning_effort, g.temperature) == ("chat", "low", 0.0)


@pytest.mark.parametrize(
    ("entry", "match"),
    [("api: soap", "unknown api"), ("temperature: hot", "temperature must be a number")],
)
def test_api_and_temperature_validation(entry: str, match: str) -> None:
    write_config(f"providers:\n  openai: {{api_key: k, {entry}}}\n")
    with pytest.raises(ConfigError, match=match):
        load_settings()


def test_legacy_secrets_fallback_warns(capsys: pytest.CaptureFixture[str]) -> None:
    aiscript_home().mkdir(parents=True, exist_ok=True)
    legacy = legacy_secrets_path()
    legacy.write_text("providers:\n  openai: {api_key: k-old}\n", encoding="utf-8")
    os.chmod(legacy, 0o600)
    assert load_settings().generator.api_key == "k-old"
    err = capsys.readouterr().err
    assert "secrets.yaml is deprecated" in err
    assert f"mv {legacy} {config_path()}" in err
    assert legacy.exists()  # never moved automatically


def test_config_yaml_wins_over_legacy(capsys: pytest.CaptureFixture[str]) -> None:
    write_config("providers:\n  openai: {api_key: k-new}\n")
    legacy_secrets_path().write_text("providers:\n  openai: {api_key: k-old}\n")
    assert load_settings().generator.api_key == "k-new"
    assert "deprecated" not in capsys.readouterr().err


def _ollaya(extra: str = "") -> ProviderConfig:
    write_config(
        f"reviewer_provider: ollaya\nproviders:\n  openai: {{api_key: ko}}\n  ollaya: {{{extra}}}\n"
    )
    return need(load_settings().reviewer)


def test_ollaya_defaults_need_no_key() -> None:
    r = _ollaya()
    assert (r.kind, r.base_url, r.model) == ("jev", "http://localhost:11435", OLLAYA_DEFAULT_MODEL)
    assert OLLAYA_DEFAULT_MODEL == "jevk5:4b"
    assert r.api_key == "not-needed"


def test_ollaya_without_yaml_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "ko")
    write_config("reviewer_provider: ollaya\n")
    r = need(load_settings().reviewer)
    assert (r.kind, r.base_url, r.api_key) == ("jev", "http://localhost:11435", "not-needed")


def test_ollaya_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAYA_HOST", "127.0.0.1:9999")
    assert _ollaya().base_url == "http://127.0.0.1:9999"
    monkeypatch.setenv("OLLAYA_HOST", "https://box.lan:1")
    assert _ollaya().base_url == "https://box.lan:1"


def test_ollaya_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAYA_API_KEY", "oll")
    assert _ollaya().api_key == "oll"
    monkeypatch.setenv("OLLAYA_API_KEY", "other")
    assert _ollaya("api_key: from-yaml").api_key == "from-yaml"


def test_ollaya_yaml_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAYA_HOST", "envhost:1")
    r = _ollaya('base_url: "http://x:2", model: "m9"')
    assert (r.base_url, r.model) == ("http://x:2", "m9")


def test_ollaya_kind_explicit_on_other_name() -> None:
    write_config(
        "reviewer_provider: loc\nproviders:\n  openai: {api_key: ko}\n  loc: {kind: ollaya}\n"
    )
    r = need(load_settings().reviewer)
    assert (r.kind, r.model) == ("jev", OLLAYA_DEFAULT_MODEL)


def test_ollaya_cannot_be_generator() -> None:
    write_config("default_provider: ollaya\nproviders:\n  ollaya: {}\n")
    with pytest.raises(ConfigError, match="cannot generate scripts"):
        load_settings()


LOCAL_OLLAMA = 'providers:\n  ollama: {{base_url: "http://localhost:11434/v1"{extra}}}\n'


def test_local_generator_ignores_openai_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    write_config(LOCAL_OLLAMA.format(extra="") + "default_provider: ollama\n")
    assert load_settings().generator.api_key == "not-needed"


def test_local_generator_named_env_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-env")
    write_config(LOCAL_OLLAMA.format(extra="") + "default_provider: ollama\n")
    assert load_settings().generator.api_key == "ollama-env"


def test_local_generator_yaml_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-env")
    write_config(LOCAL_OLLAMA.format(extra=', api_key: "yaml-key"') + "default_provider: ollama\n")
    assert load_settings().generator.api_key == "yaml-key"


def test_remote_generator_uses_openai_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    write_config(
        'default_provider: remote\nproviders:\n  remote: {base_url: "https://api.example.com/v1"}\n'
    )
    assert load_settings().generator.api_key == "sk-env"


def _write_decisions_config(
    fields: str = "api_key: reviewer-yaml", *, name: str = "openai_decisions"
) -> None:
    write_config(
        f"reviewer_provider: {name}\nproviders:\n"
        "  openai: {api_key: generator-key, model: generator-model}\n"
        f"  {name}: {{kind: openai, api: decisions, {fields}}}\n"
    )


@pytest.mark.parametrize("model", [None, "future-decisions-model-2099"])
@pytest.mark.parametrize("generator_model", [None, "generator-env-model"])
def test_given_decisions_model_when_settings_resolve_then_model_is_independent(
    monkeypatch: pytest.MonkeyPatch, model: str | None, generator_model: str | None
) -> None:
    # given
    generator_fields = "api_key: generator-key"
    if generator_model is not None:
        monkeypatch.setenv("AISCRIPT_MODEL", generator_model)
    else:
        generator_fields += ", model: generator-model"
    reviewer_fields = "kind: openai, api: decisions, api_key: reviewer-yaml"
    if model is not None:
        reviewer_fields += f", model: {model}"
    write_config(
        "reviewer_provider: openai_decisions\nproviders:\n"
        f"  openai: {{{generator_fields}}}\n"
        f"  openai_decisions: {{{reviewer_fields}}}\n"
    )

    # when
    settings = load_settings()

    # then
    reviewer = need(settings.reviewer)
    assert reviewer.model == (model or "gpt-6-luna")
    assert (reviewer.name, reviewer.kind, reviewer.api) == (
        "openai_decisions",
        "openai",
        "decisions",
    )
    assert settings.generator == ProviderConfig(
        name="openai",
        api_key="generator-key",
        base_url=None,
        model=generator_model or "generator-model",
        api="responses",
    )


@pytest.mark.parametrize(
    ("role", "kind", "name", "message"),
    [
        ("generator", "openai", "openai_decisions", "reviewer"),
        ("reviewer", "jev", "openai_decisions", "openai"),
        ("reviewer", "ollaya", "openai_decisions", "openai"),
        ("reviewer", None, "jev", "openai"),
        ("reviewer", None, "ollaya", "openai"),
    ],
)
def test_given_decisions_invalid_role_or_kind_when_settings_resolve_then_config_error(
    role: str, kind: str | None, name: str, message: str
) -> None:
    # given
    kind_field = f"kind: {kind}, " if kind else ""
    selection = f"default_provider: {name}" if role == "generator" else f"reviewer_provider: {name}"
    write_config(
        f"{selection}\nproviders:\n  openai: {{api_key: generator-key}}\n"
        f"  {name}: {{{kind_field}api: decisions, api_key: reviewer-yaml}}\n"
    )

    # when / then
    with pytest.raises(ConfigError) as error:
        load_settings()
    assert message in str(error.value).lower()
    assert name in str(error.value)
    assert "unknown api" not in str(error.value).lower()


@pytest.mark.parametrize("setting", ["temperature: 0", "temperature: 0.7", "reasoning_effort: low"])
def test_given_decisions_generation_setting_when_settings_resolve_then_config_error(
    setting: str,
) -> None:
    # given
    _write_decisions_config(f"api_key: reviewer-yaml, {setting}")

    # when / then
    with pytest.raises(ConfigError) as error:
        load_settings()
    assert setting.split(":")[0] in str(error.value)
    assert "openai_decisions" in str(error.value)


@pytest.mark.parametrize(
    "endpoints",
    [
        "",
        "base_url: 'https://api.openai.com/v1'",
        "base_url: 'https://api.openai.com/v1/'",
        "endpoint: 'https://api.openai.com/v1'",
        "endpoint: 'https://api.openai.com/v1/'",
        "base_url: 'https://api.openai.com/v1', endpoint: 'https://api.openai.com/v1/'",
    ],
)
def test_given_decisions_official_endpoint_when_settings_resolve_then_canonical_url_is_pinned(
    monkeypatch: pytest.MonkeyPatch, endpoints: str
) -> None:
    # given
    monkeypatch.setenv("OPENAI_BASE_URL", "https://environment.invalid/v1")
    _write_decisions_config(f"api_key: reviewer-yaml, {endpoints}")

    # when
    settings = load_settings()

    # then
    assert need(settings.reviewer).base_url == "https://api.openai.com/v1"
    assert settings.generator.base_url == "https://environment.invalid/v1"


@pytest.mark.parametrize("alias", ["base_url", "endpoint"])
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "https://custom.invalid/v1",
        "http://api.openai.com/v1",
        "not-a-url",
        "https://api.openai.com/v2",
        "https://api.openai.com/v1?redirect=elsewhere",
        "https://api.openai.com/v1#fragment",
        "https://user:password@api.openai.com/v1",
        "https://api.openai.com.evil.invalid/v1",
    ],
)
def test_given_decisions_disallowed_endpoint_when_settings_resolve_then_config_error(
    alias: str, url: str
) -> None:
    # given
    _write_decisions_config(f"api_key: reviewer-yaml, {alias}: '{url}'")

    # when / then
    with pytest.raises(ConfigError) as error:
        load_settings()
    assert "https://api.openai.com/v1" in str(error.value)
    assert "openai_decisions" in str(error.value)


@pytest.mark.parametrize("canonical_alias", ["base_url", "endpoint"])
@pytest.mark.parametrize(
    "hidden_url",
    ["http://localhost:11434/v1", "https://custom.invalid/v1", "not-a-url"],
)
def test_given_decisions_conflicting_aliases_when_settings_resolve_then_neither_bypasses_validation(
    canonical_alias: str, hidden_url: str
) -> None:
    # given
    other_alias = "endpoint" if canonical_alias == "base_url" else "base_url"
    _write_decisions_config(
        f"api_key: reviewer-yaml, {canonical_alias}: 'https://api.openai.com/v1', "
        f"{other_alias}: '{hidden_url}'"
    )

    # when / then
    with pytest.raises(ConfigError) as error:
        load_settings()
    assert "https://api.openai.com/v1" in str(error.value)
    assert "openai_decisions" in str(error.value)


@pytest.mark.parametrize(
    ("yaml_key", "expected"),
    [
        ("reviewer-yaml", "reviewer-yaml"),
        ("", "reviewer-env"),
        ("   ", "reviewer-env"),
        ("sk-proj-...", "reviewer-env"),
        ("sk-...", "reviewer-env"),
        ("xyz...", "reviewer-env"),
    ],
)
@pytest.mark.parametrize("name", ["openai_decisions", "custom-review"])
def test_given_decisions_keys_when_settings_resolve_then_dedicated_precedence_is_used(
    monkeypatch: pytest.MonkeyPatch, yaml_key: str, expected: str, name: str
) -> None:
    # given
    monkeypatch.setenv("OPENAI_API_KEY", "global-key")
    env_name = "CUSTOM_REVIEW_API_KEY" if name == "custom-review" else "OPENAI_DECISIONS_API_KEY"
    monkeypatch.setenv(env_name, "reviewer-env")
    _write_decisions_config(f"api_key: '{yaml_key}'", name=name)

    # when
    reviewer = need(load_settings().reviewer)

    # then
    assert reviewer.api_key == expected
    assert reviewer.name == name


@pytest.mark.parametrize("source", ["yaml", "environment"])
@pytest.mark.parametrize("key", [None, "", "   ", "sk-proj-...", "sk-...", "xyz..."])
def test_given_decisions_no_usable_dedicated_key_when_settings_resolve_then_credential_error(
    monkeypatch: pytest.MonkeyPatch, source: str, key: str | None
) -> None:
    # given
    monkeypatch.setenv("OPENAI_API_KEY", "global-key")
    monkeypatch.delenv("OPENAI_DECISIONS_API_KEY", raising=False)
    fields = ""
    if key is not None:
        if source == "yaml":
            fields = f"api_key: '{key}'"
        else:
            monkeypatch.setenv("OPENAI_DECISIONS_API_KEY", key)
    _write_decisions_config(fields)

    # when / then
    with pytest.raises(ConfigError) as error:
        load_settings()
    message = str(error.value)
    assert "No API key" in message
    assert "api_key" in message
    assert "OPENAI_DECISIONS_API_KEY" in message
    assert "openai_decisions" in message


# --- AI inside scripts (1.4.0): C4 provider and key resolution, C5 ai: block ---

_AI_KEY_BOUNDS = [
    ("max_input_kb", 1, 1024),
    ("max_calls_per_run", 1, 100),
    ("timeout_seconds", 1, 600),
    ("max_output_tokens", 1, 32000),
]
_AI_DEFAULTS = {
    "max_input_kb": 128,
    "max_calls_per_run": 1,
    "timeout_seconds": 60,
    "max_output_tokens": 4000,
}
_REMOTE = "https://x.example/v1"
_KEY_VALUE = "sk-secret-value-123456"


@pytest.mark.parametrize("raw", [{}, {"ai": None}])
def test_given_absent_or_null_ai_block_when_load_ai_settings_then_defaults(
    raw: dict[str, object],
) -> None:
    # when
    ai = load_ai_settings(raw)

    # then
    assert (ai.max_input_kb, ai.max_calls_per_run, ai.timeout_seconds, ai.max_output_tokens) == (
        128,
        1,
        60,
        4000,
    )
    assert ai == AiSettings()


@pytest.mark.parametrize(("key", "low", "high"), _AI_KEY_BOUNDS)
def test_given_ai_value_at_bounds_when_load_ai_settings_then_accepted(
    key: str, low: int, high: int
) -> None:
    # when
    at_low = load_ai_settings({"ai": {key: low}})
    at_high = load_ai_settings({"ai": {key: high}})

    # then
    assert getattr(at_low, key) == low
    assert getattr(at_high, key) == high
    for other, default in _AI_DEFAULTS.items():
        if other != key:
            assert getattr(at_low, other) == default


@pytest.mark.parametrize(("key", "low", "high"), _AI_KEY_BOUNDS)
def test_given_ai_value_outside_bounds_when_load_ai_settings_then_config_error_names_key(
    key: str, low: int, high: int
) -> None:
    for bad in (0, -1, low - 1, high + 1):
        # when / then
        with pytest.raises(ConfigError, match=key):
            load_ai_settings({"ai": {key: bad}})


@pytest.mark.parametrize("bad", [1.5, True, False, "128", None, [1]])
@pytest.mark.parametrize("key", [k for k, _, _ in _AI_KEY_BOUNDS])
def test_given_non_integer_ai_value_when_load_ai_settings_then_config_error_names_key(
    key: str, bad: object
) -> None:
    # when / then
    with pytest.raises(ConfigError, match=key):
        load_ai_settings({"ai": {key: bad}})


def test_given_unknown_ai_key_when_load_ai_settings_then_config_error_names_it() -> None:
    # when / then
    with pytest.raises(ConfigError, match="max_retries"):
        load_ai_settings({"ai": {"max_retries": 3}})


@pytest.mark.parametrize("bad", [[1, 2], "fast", 5])
def test_given_non_mapping_ai_block_when_load_ai_settings_then_config_error(bad: object) -> None:
    # when / then
    with pytest.raises(ConfigError, match="ai"):
        load_ai_settings({"ai": bad})


def test_given_no_default_provider_when_identify_ask_target_then_openai_defaults() -> None:
    # when
    target = identify_ask_target({})

    # then
    assert target == AskTarget(
        provider="openai",
        model="gpt-6-luna",
        base_url=OFFICIAL_OPENAI_URL,
        api="responses",
        official=True,
        local=False,
    )


def test_given_openai_entry_without_base_url_when_identify_then_official_url_is_pinned() -> None:
    # given
    raw = {"providers": {"openai": {"model": "m1", "reasoning_effort": "low", "temperature": 0.5}}}

    # when
    target = identify_ask_target(raw)

    # then
    assert target.base_url == OFFICIAL_OPENAI_URL
    assert target.official is True
    assert target.local is False
    assert target.model == "m1"
    assert target.api == "responses"
    assert target.reasoning_effort == "low"
    assert target.temperature == 0.5


def test_given_non_official_chat_endpoint_when_identify_then_chat_and_not_official() -> None:
    # given
    raw = {"default_provider": "groq", "providers": {"groq": {"base_url": _REMOTE, "model": "j"}}}

    # when
    target = identify_ask_target(raw)

    # then
    assert (target.provider, target.model, target.base_url) == ("groq", "j", _REMOTE)
    assert target.api == "chat"
    assert target.official is False
    assert target.local is False


def test_given_explicit_api_when_identify_then_it_is_used() -> None:
    # given
    raw: dict[str, object] = {
        "default_provider": "x",
        "providers": {"x": {"base_url": _REMOTE, "api": "responses"}},
    }

    # when / then
    assert identify_ask_target(raw).api == "responses"


def test_given_loopback_endpoint_when_identify_then_local_flag_set() -> None:
    # given
    raw = {
        "default_provider": "ollama",
        "providers": {"ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen3"}},
    }

    # when
    target = identify_ask_target(raw)

    # then
    assert target.local is True
    assert target.official is False
    assert target.base_url == "http://localhost:11434/v1"
    assert target.api == "chat"


def test_given_routing_env_vars_when_identify_then_they_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    raw = {
        "default_provider": "openai",
        "providers": {"openai": {"model": "yaml-model"}, "other": {"base_url": _REMOTE}},
    }
    monkeypatch.setenv("AISCRIPT_PROVIDER", "other")
    monkeypatch.setenv("AISCRIPT_MODEL", "env-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://evil.example/v1")

    # when
    target = identify_ask_target(raw)

    # then
    assert (target.provider, target.model, target.base_url) == (
        "openai",
        "yaml-model",
        OFFICIAL_OPENAI_URL,
    )


def test_given_routing_env_vars_when_generator_loads_then_they_are_still_honoured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    write_config(
        'default_provider: openai\nproviders:\n  openai: {api_key: "sk-y", model: "yaml-model"}\n'
        '  other: {api_key: "sk-o", base_url: "https://x.example/v1"}\n'
    )
    monkeypatch.setenv("AISCRIPT_PROVIDER", "other")
    monkeypatch.setenv("AISCRIPT_MODEL", "env-model")

    # when
    s = load_settings()

    # then
    assert s.generator.name == "other"
    assert s.generator.model == "env-model"


def test_given_routing_env_vars_when_settings_load_then_ask_target_stays_yaml_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    write_config(
        'default_provider: openai\nproviders:\n  openai: {api_key: "sk-y", model: "yaml-model"}\n'
        '  other: {api_key: "sk-o", base_url: "https://x.example/v1"}\n'
    )
    monkeypatch.setenv("AISCRIPT_PROVIDER", "other")
    monkeypatch.setenv("AISCRIPT_MODEL", "env-model")

    # when
    target = identify_ask_target(load_raw_config())

    # then
    assert (target.provider, target.model) == ("openai", "yaml-model")


@pytest.mark.parametrize(
    "providers",
    [
        {"jev": {"api_key": "ts-key-12345"}},
        {"ollaya": {}},
        {"x": {"kind": "jev"}},
        {"x": {"kind": "ollaya"}},
        {"x": {"api": "decisions"}},
        {"x": {"kind": "openai", "api": "decisions", "api_key": "sk-decisions-1"}},
    ],
)
def test_given_non_openai_compatible_default_when_identify_then_ask_config_error(
    providers: dict[str, object],
) -> None:
    # given
    name = next(iter(providers))
    raw = {"default_provider": name, "providers": providers}

    # when / then
    with pytest.raises(AskConfigError):
        identify_ask_target(raw)


def test_given_undefined_default_provider_when_identify_then_ask_config_error() -> None:
    # given
    raw = {"default_provider": "missing", "providers": {"openai": {}}}

    # when / then
    with pytest.raises(AskConfigError, match="missing"):
        identify_ask_target(raw)


def test_given_broken_reviewer_key_when_identify_then_target_unaffected() -> None:
    # given: reviewer jev has no key anywhere; load_settings would fail on it
    raw = {
        "default_provider": "openai",
        "reviewer_provider": "jev",
        "providers": {"openai": {"api_key": "sk-ok-12345678"}, "jev": {"api_key": "..."}},
    }

    # when
    target = identify_ask_target(raw)
    key = resolve_ask_key(target, raw, {})

    # then
    assert target.provider == "openai"
    assert key == "sk-ok-12345678"


def _official() -> AskTarget:
    return AskTarget("openai", "m", OFFICIAL_OPENAI_URL, "responses", official=True, local=False)


def _remote() -> AskTarget:
    return AskTarget("groq", "m", _REMOTE, "chat", official=False, local=False)


def _local() -> AskTarget:
    return AskTarget("ollama", "m", "http://127.0.0.1:11434/v1", "chat", official=False, local=True)


def test_given_all_key_sources_when_resolve_official_then_yaml_wins() -> None:
    # given
    raw = {"providers": {"openai": {"api_key": "sk-yaml-12345678"}}}
    environ = {"OPENAI_API_KEY": "sk-env-12345678"}

    # when / then
    assert resolve_ask_key(_official(), raw, environ) == "sk-yaml-12345678"


def test_given_named_and_global_env_when_resolve_official_then_named_wins() -> None:
    # given
    target = AskTarget("groq", "m", OFFICIAL_OPENAI_URL, "chat", official=True, local=False)
    environ = {"GROQ_API_KEY": "gsk-named-1234", "OPENAI_API_KEY": "sk-global-1234"}

    # when / then
    assert resolve_ask_key(target, {"providers": {"groq": {}}}, environ) == "gsk-named-1234"


def test_given_hyphenated_provider_when_resolve_official_then_named_env_is_normalised() -> None:
    # given
    target = AskTarget("my-oai", "m", OFFICIAL_OPENAI_URL, "chat", official=True, local=False)
    environ = {"MY_OAI_API_KEY": "sk-named-1234", "OPENAI_API_KEY": "sk-global-1234"}

    # when / then
    assert resolve_ask_key(target, {"providers": {"my-oai": {}}}, environ) == "sk-named-1234"


def test_given_placeholder_yaml_key_when_resolve_official_then_env_key_used() -> None:
    # given
    raw = {"providers": {"openai": {"api_key": "sk-proj-..."}}}

    # when / then
    assert resolve_ask_key(_official(), raw, {"OPENAI_API_KEY": "sk-env-12345678"}) == (
        "sk-env-12345678"
    )


def test_given_only_openai_env_key_when_resolve_official_then_used() -> None:
    # when / then
    assert resolve_ask_key(_official(), {}, {"OPENAI_API_KEY": "sk-env-12345678"}) == (
        "sk-env-12345678"
    )


def test_given_no_key_when_resolve_official_then_error_names_sources_without_values() -> None:
    # given
    raw = {"providers": {"openai": {"api_key": "..."}}}

    # when
    with pytest.raises(AskConfigError) as ei:
        resolve_ask_key(_official(), raw, {})

    # then
    msg = str(ei.value)
    assert "api_key" in msg
    assert "OPENAI_API_KEY" in msg
    assert str(config_path()) in msg


def test_given_env_only_key_when_resolve_non_official_then_error_and_value_not_leaked() -> None:
    # given
    environ = {"GROQ_API_KEY": _KEY_VALUE, "OPENAI_API_KEY": _KEY_VALUE + "-2"}

    # when
    with pytest.raises(AskConfigError) as ei:
        resolve_ask_key(_remote(), {"providers": {"groq": {}}}, environ)

    # then
    msg = str(ei.value)
    assert "api_key" in msg
    assert _KEY_VALUE not in msg


def test_given_yaml_key_when_resolve_non_official_then_it_is_used() -> None:
    # given
    raw = {"providers": {"groq": {"api_key": "gsk-yaml-12345"}}}

    # when / then
    assert resolve_ask_key(_remote(), raw, {"OPENAI_API_KEY": "sk-env-12345678"}) == (
        "gsk-yaml-12345"
    )


def test_given_loopback_without_key_when_resolve_then_not_needed() -> None:
    # when / then
    assert resolve_ask_key(_local(), {"providers": {"ollama": {}}}, {}) == "not-needed"


def test_given_loopback_and_openai_env_key_when_resolve_then_env_key_not_used() -> None:
    # when
    key = resolve_ask_key(_local(), {"providers": {"ollama": {}}}, {"OPENAI_API_KEY": _KEY_VALUE})

    # then
    assert key == "not-needed"


def test_given_loopback_with_yaml_key_when_resolve_then_yaml_key() -> None:
    # given
    raw = {"providers": {"ollama": {"api_key": "local-key-1234"}}}

    # when / then
    assert resolve_ask_key(_local(), raw, {}) == "local-key-1234"


def test_given_default_provider_when_describe_then_label_names_provider_and_model() -> None:
    # given
    raw = {"default_provider": "groq", "providers": {"groq": {"base_url": _REMOTE, "model": "j"}}}

    # when
    label = describe_ask_target(raw)

    # then
    assert "groq" in label
    assert "j" in label


@pytest.mark.parametrize(
    "raw",
    [
        {"default_provider": "jev", "providers": {"jev": {"api_key": "ts-key-12345"}}},
        {"default_provider": "missing", "providers": {"openai": {}}},
        {"default_provider": "x", "providers": "nonsense"},
        {"ai": [1], "providers": {"x": 1}, "default_provider": 7},
    ],
)
def test_given_unusable_default_when_describe_then_never_raises_and_says_not_usable(
    raw: dict[str, object],
) -> None:
    # when
    label = describe_ask_target(raw)

    # then
    assert "not usable" in label.lower()


def test_given_configured_keys_when_collect_known_secrets_then_all_real_ones_deduped() -> None:
    # given
    raw = {
        "providers": {
            "openai": {"api_key": "sk-yaml-openai-1"},
            "groq": {"api_key": "gsk-yaml-groq-1"},
            "jev": {"api_key": "ts-dup-value-123"},
            "ph": {"api_key": "sk-proj-..."},
            "short": {"api_key": "abc1234"},
            "loc": {"api_key": "not-needed"},
            "bare": {},
        }
    }
    environ = {
        "OPENAI_API_KEY": "sk-env-openai-1",
        "OPENAI_DECISIONS_API_KEY": "sk-env-decisions",
        "TYPESAFE_API_KEY": "ts-dup-value-123",
        "OLLAYA_API_KEY": "short",
        "BARE_API_KEY": "bare-env-key-123",
        "GROQ_API_KEY": "gsk-env-groq-1",
        "UNRELATED_API_KEY": "unrelated-value-1",
        "PATH": "/usr/bin:/bin",
    }

    # when
    secrets = collect_known_secrets(raw, environ)

    # then
    assert sorted(secrets) == sorted(
        {
            "sk-yaml-openai-1",
            "gsk-yaml-groq-1",
            "ts-dup-value-123",
            "sk-env-openai-1",
            "sk-env-decisions",
            "bare-env-key-123",
            "gsk-env-groq-1",
        }
    )
    assert len(secrets) == len(set(secrets))


def test_given_only_placeholders_and_short_values_when_collect_then_empty() -> None:
    # given
    raw = {"providers": {"a": {"api_key": "..."}, "b": {"api_key": "1234567"}}}
    environ = {"OLLAYA_API_KEY": "not-needed", "OPENAI_API_KEY": "short", "A_API_KEY": "x..."}

    # when / then
    assert collect_known_secrets(raw, environ) == ()


def test_given_valid_config_when_load_settings_then_ai_fields_are_filled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    write_config(
        "ai: {max_input_kb: 256, max_calls_per_run: 3, timeout_seconds: 30,"
        " max_output_tokens: 1000}\n"
        'providers:\n  openai: {api_key: "sk-yaml-12345678", model: m1}\n'
    )
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-env-12345678")

    # when
    s = load_settings()

    # then
    assert s.ai == AiSettings(256, 3, 30, 1000)
    assert "openai" in s.ai_target
    assert "m1" in s.ai_target
    assert "sk-yaml-12345678" in s.known_secrets
    assert "ts-env-12345678" in s.known_secrets
    assert "sk-yaml-12345678" not in repr(s)


def test_given_130_style_config_when_load_settings_then_defaults_and_unchanged_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    write_config(
        "default_provider: openai\nreviewer_provider: jev\n"
        'providers:\n  openai: {api_key: "sk-y1234567"}\n  jev: {api_key: "ts-y1234567"}\n'
    )

    # when
    s = load_settings()

    # then
    assert s.ai == AiSettings()
    assert s.generator.name == "openai"
    assert s.generator.api_key == "sk-y1234567"
    assert need(s.reviewer).name == "jev"
    assert "openai" in s.ai_target
    assert "sk-y1234567" in s.known_secrets


@pytest.mark.parametrize("block", ["ai: {max_input_kb: 0}", "ai: {bogus: 1}", "ai: [1]"])
def test_given_invalid_ai_block_when_load_settings_then_config_error(
    monkeypatch: pytest.MonkeyPatch, block: str
) -> None:
    # given
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-12345678")
    write_config(block + "\n")

    # when / then
    with pytest.raises(ConfigError):
        load_settings()
