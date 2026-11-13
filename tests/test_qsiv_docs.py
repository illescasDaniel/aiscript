"""Starter config and docs mention QSIV (S22)."""

from __future__ import annotations

from pathlib import Path

import yaml

from aiscript.init_cmd import CONFIG_TEMPLATE

ROOT = Path(__file__).resolve().parent.parent


def _doc(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_given_the_starter_config_when_read_then_it_has_a_commented_qsiv_example() -> None:
    # given / when / then (S22)
    assert "\n# reviewer_provider: qsiv\n" in CONFIG_TEMPLATE
    assert "# qsiv:" in CONFIG_TEMPLATE
    assert "qsiv-runtime setup" in CONFIG_TEMPLATE
    assert "Linux" in CONFIG_TEMPLATE and "NVIDIA" in CONFIG_TEMPLATE


def test_given_the_starter_config_when_parsed_then_qsiv_is_not_active() -> None:
    # given / when
    data = yaml.safe_load(CONFIG_TEMPLATE)
    # then: off by default; existing behaviour unchanged
    assert data["reviewer_provider"] == "jev"
    assert "qsiv" not in data["providers"]


def test_given_the_docs_when_read_then_qsiv_is_described() -> None:
    # given
    configuration = _doc("docs/configuration.md")
    safety = _doc("docs/safety.md")
    readme = _doc("README.md")
    # when / then (S22)
    for text in (configuration, safety):
        assert "qsiv" in text.lower()
    assert "qsiv-runtime setup" in configuration and "qsiv-runtime doctor" in configuration
    assert "uvx qsiv-runtime setup" in configuration and "aiscript[qsiv]" in configuration
    assert "Linux" in configuration and "8.9" in configuration
    assert "Reviewer unavailable" in safety
    assert "stays on" in safety or "never leaves" in safety
    assert "QSIV" in readme
