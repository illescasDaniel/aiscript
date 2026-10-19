import stat
import sys
from pathlib import Path

import pytest
import yaml
from helpers import need

from aiscript.config import load_settings
from aiscript.init_cmd import CONFIG_TEMPLATE, ensure_gitignore, run_init
from aiscript.paths import (
    aiscript_home,
    config_path,
    functions_dir,
    legacy_secrets_path,
    prompts_dir,
)


def test_init_creates_everything(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_init() == 0
    assert prompts_dir().is_dir()
    assert functions_dir().is_dir()
    assert config_path().read_text() == CONFIG_TEMPLATE
    err = capsys.readouterr().err
    assert "Created config file" in err
    assert "Next steps" in err


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_init_mode_0600() -> None:
    run_init()
    assert stat.S_IMODE(config_path().stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_init_fixes_existing_mode_without_overwriting(capsys: pytest.CaptureFixture[str]) -> None:
    aiscript_home().mkdir(parents=True)
    config_path().write_text("mine: 1\n")
    config_path().chmod(0o644)
    run_init()
    assert config_path().read_text() == "mine: 1\n"
    assert stat.S_IMODE(config_path().stat().st_mode) == 0o600
    assert "already exists" in capsys.readouterr().err


def test_init_idempotent() -> None:
    run_init()
    first = config_path().read_text()
    assert run_init() == 0
    assert config_path().read_text() == first


def test_template_is_valid_yaml_and_commented() -> None:
    data = yaml.safe_load(CONFIG_TEMPLATE)
    assert data["default_provider"] == "openai"
    assert data["reviewer_provider"] == "jev"
    assert set(data["providers"]) == {"openai", "jev"}
    assert "chmod 600" in CONFIG_TEMPLATE
    assert "# ollama:" in CONFIG_TEMPLATE


def test_fresh_template_works_with_env_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    run_init()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-env")
    s = load_settings()
    assert s.generator.api_key == "sk-env"
    assert s.generator.model == "gpt-6-luna"
    assert (need(s.reviewer).name, need(s.reviewer).kind, need(s.reviewer).api_key) == (
        "jev",
        "jev",
        "ts-env",
    )


def test_fresh_template_without_jev_key_explains_how_to_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiscript.errors import ConfigError

    run_init()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    with pytest.raises(ConfigError, match="comment out `reviewer_provider: jev`"):
        load_settings()


def test_fresh_template_without_key_errors() -> None:
    from aiscript.errors import ConfigError

    run_init()
    with pytest.raises(ConfigError):
        load_settings()


def test_no_gitignore_without_git_dir(tmp_path: Path) -> None:
    run_init()
    assert not (aiscript_home() / ".gitignore").exists()
    assert ensure_gitignore(aiscript_home()) is False


def test_gitignore_created_when_git_exists() -> None:
    run_init()
    (aiscript_home() / ".git").mkdir()
    assert ensure_gitignore(aiscript_home()) is True
    lines = (aiscript_home() / ".gitignore").read_text().splitlines()
    assert lines == ["config.yaml", "secrets.yaml", "functions/"]
    assert ensure_gitignore(aiscript_home()) is False


def test_gitignore_preserves_content_and_no_duplicates() -> None:
    home = aiscript_home()
    home.mkdir(parents=True)
    (home / ".git").mkdir()
    gi = home / ".gitignore"
    gi.write_text("*.log\nsecrets.yaml\n")
    assert ensure_gitignore(home) is True
    assert gi.read_text() == "*.log\nsecrets.yaml\nconfig.yaml\nfunctions/\n"


def test_gitignore_adds_newline_when_missing() -> None:
    home = aiscript_home()
    home.mkdir(parents=True)
    (home / ".git").mkdir()
    gi = home / ".gitignore"
    gi.write_text("*.log")
    ensure_gitignore(home)
    assert gi.read_text() == "*.log\nconfig.yaml\nsecrets.yaml\nfunctions/\n"


def test_run_init_updates_gitignore() -> None:
    home = aiscript_home()
    home.mkdir(parents=True)
    (home / ".git").mkdir()
    run_init()
    run_init()
    assert (home / ".gitignore").read_text() == "config.yaml\nsecrets.yaml\nfunctions/\n"


def _uncommented_template() -> str:
    lines = []
    for line in CONFIG_TEMPLATE.splitlines():
        if line.startswith(("  # ollaya:", "  # ollama:", "  #   model:", "  #   base_url:")):
            line = "  " + line[4:]
        lines.append(line)
    return "\n".join(lines) + "\n"


def test_template_local_blocks_resolve_when_uncommented(monkeypatch: pytest.MonkeyPatch) -> None:
    text = _uncommented_template()
    assert set(yaml.safe_load(text)["providers"]) == {"openai", "jev", "ollaya", "ollama"}
    aiscript_home().mkdir(parents=True)

    config_path().write_text(text.replace("default_provider: openai", "default_provider: ollama"))
    config_path().chmod(0o600)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-env")
    g = load_settings().generator
    assert (g.name, g.kind, g.api, g.api_key) == ("ollama", "openai", "chat", "not-needed")
    assert (g.base_url, g.model) == ("http://localhost:11434/v1", "qwen3")

    config_path().write_text(text.replace("reviewer_provider: jev", "reviewer_provider: ollaya"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    r = need(load_settings().reviewer)
    assert (r.name, r.kind, r.api_key) == ("ollaya", "jev", "not-needed")
    assert (r.base_url, r.model) == ("http://localhost:11435", "jevk5:4b")


def test_init_with_legacy_secrets_creates_nothing_new(capsys: pytest.CaptureFixture[str]) -> None:
    aiscript_home().mkdir(parents=True)
    legacy = legacy_secrets_path()
    legacy.write_text("mine: 1\n")
    assert run_init() == 0
    assert not config_path().exists()
    assert legacy.read_text() == "mine: 1\n"
    err = capsys.readouterr().err
    assert "mv" in err
    assert str(config_path()) in err
