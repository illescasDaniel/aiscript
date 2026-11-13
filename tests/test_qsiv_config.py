"""providers.qsiv configuration (S19, S21 aiscript half)."""

from __future__ import annotations

import os

import pytest
from helpers import need

from aiscript.config import QSIVSettings, load_settings
from aiscript.errors import ConfigError
from aiscript.paths import aiscript_home, config_path


def write_config(text: str) -> None:
    aiscript_home().mkdir(parents=True, exist_ok=True)
    config_path().write_text(text, encoding="utf-8")
    os.chmod(config_path(), 0o600)


BASE = "default_provider: openai\nreviewer_provider: qsiv\n"
OPENAI = "  openai: {api_key: sk-test}\n"


def test_given_reviewer_qsiv_without_a_section_when_loaded_then_defaults_and_no_key() -> None:
    # given
    write_config(BASE + "providers:\n" + OPENAI)
    # when
    reviewer = need(load_settings().reviewer)
    # then (S19)
    assert (reviewer.kind, reviewer.api, reviewer.name) == ("qsiv", "qsiv", "qsiv")
    assert reviewer.api_key is None and reviewer.base_url is None
    assert reviewer.qsiv in (None, QSIVSettings())


def test_given_reviewer_qsiv_with_no_providers_at_all_when_loaded_then_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    write_config("reviewer_provider: qsiv\n")
    # when / then (S19)
    assert need(load_settings().reviewer).kind == "qsiv"


def test_given_an_empty_section_when_loaded_then_defaults() -> None:
    # given
    write_config(BASE + "providers:\n" + OPENAI + "  qsiv:\n")
    # when / then
    assert need(load_settings().reviewer).kind == "qsiv"


def test_given_all_keys_when_loaded_then_settings_are_carried() -> None:
    # given
    write_config(
        BASE
        + "providers:\n"
        + OPENAI
        + "  qsiv:\n    model_directory: /m\n    python: /venv/bin/python\n    runtime: reference\n"
    )
    # when
    reviewer = need(load_settings().reviewer)
    # then (S21: explicit config is passed on; the package resolves the rest)
    assert reviewer.qsiv == QSIVSettings("/m", "/venv/bin/python", "reference")


def test_given_the_explicit_kind_when_loaded_then_a_custom_name_works() -> None:
    # given
    write_config(
        "default_provider: openai\nreviewer_provider: gpu\nproviders:\n"
        + OPENAI
        + "  gpu: {kind: qsiv, runtime: fp8}\n"
    )
    # when / then
    reviewer = need(load_settings().reviewer)
    assert reviewer.kind == "qsiv" and reviewer.name == "gpu"


@pytest.mark.parametrize(
    ("section", "needle"),
    [
        ("runtime: int8", "runtime"),
        ("model_directory: 5", "model_directory"),
        ("python: [a]", "python"),
        ("foo: 1", "foo"),
        ("api_key: sk-x", "api_key"),
        ("kind: qsiv, base_url: http://x", "base_url"),
    ],
)
def test_given_an_invalid_section_when_loaded_then_config_error_names_provider_and_key(
    section: str, needle: str
) -> None:
    # given
    write_config(BASE + "providers:\n" + OPENAI + f"  qsiv: {{{section}}}\n")
    # when
    with pytest.raises(ConfigError) as raised:
        load_settings()
    # then (S19)
    assert "qsiv" in str(raised.value) and needle in str(raised.value)


def test_given_default_provider_qsiv_when_loaded_then_config_error_says_it_cannot_generate() -> (
    None
):
    # given
    write_config("default_provider: qsiv\nreviewer_provider: qsiv\n")
    # when
    with pytest.raises(ConfigError) as raised:
        load_settings()
    # then (S19)
    assert "QSIV cannot generate" in str(raised.value)


def test_given_the_env_override_of_the_generator_is_qsiv_when_loaded_then_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("AISCRIPT_PROVIDER", "qsiv")
    write_config("default_provider: openai\n")
    # when / then
    with pytest.raises(ConfigError, match="QSIV cannot generate"):
        load_settings()


def test_given_an_unknown_kind_when_loaded_then_expected_list_names_qsiv() -> None:
    # given
    write_config(
        "default_provider: openai\nreviewer_provider: weird\nproviders:\n"
        + OPENAI
        + "  weird: {kind: nope}\n"
    )
    # when
    with pytest.raises(ConfigError) as raised:
        load_settings()
    # then
    assert "(expected: openai, jev, ollaya, qsiv)." in str(raised.value)


def test_given_a_config_without_qsiv_when_loaded_then_unchanged() -> None:
    # given
    write_config(
        "default_provider: openai\nreviewer_provider: jev\nproviders:\n"
        + OPENAI
        + "  jev: {api_key: k}\n"
    )
    # when
    settings = load_settings()
    # then (S19: existing configs load unchanged)
    assert need(settings.reviewer).kind == "jev"
    assert settings.generator.kind == "openai"


def test_given_a_qsiv_named_provider_with_a_base_url_when_loaded_then_it_is_not_taken_over() -> (
    None
):
    # given: an existing config that happens to use the name "qsiv" for an HTTP endpoint
    write_config(
        "default_provider: openai\nreviewer_provider: qsiv\nproviders:\n"
        + OPENAI
        + "  qsiv: {base_url: 'https://example.com/v1', api_key: sk-x}\n"
    )
    # when
    reviewer = need(load_settings().reviewer)
    # then
    assert reviewer.kind != "qsiv" and reviewer.base_url == "https://example.com/v1"
    assert reviewer.api_key == "sk-x"
