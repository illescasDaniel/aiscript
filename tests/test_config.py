import os
import sys

import pytest
from helpers import need

from aiscript.config import OLLAYA_DEFAULT_MODEL, ProviderConfig, load_raw_config, load_settings
from aiscript.errors import ConfigError
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
