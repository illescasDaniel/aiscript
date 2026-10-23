"""`aiscript --init`: create config dirs, config.yaml, and .gitignore protection."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from aiscript.paths import (
    aiscript_home,
    config_path,
    ensure_dirs,
    functions_dir,
    is_windows,
    legacy_secrets_path,
    prompts_dir,
)

CONFIG_TEMPLATE = """\
# aiscript config. Contains API keys: keep it private (chmod 600) and out of git.
# Keys can also come from the environment: OPENAI_API_KEY, OPENAI_DECISIONS_API_KEY,
# TYPESAFE_API_KEY, <PROVIDER>_API_KEY.

# Provider that writes the scripts (override with $AISCRIPT_PROVIDER).
default_provider: openai

# Decision model that reviews scripts on top of the built-in static scan.
# Use `ollaya` for a local, keyless review; comment out to use only the static scan.
reviewer_provider: jev

providers:
  # OpenAI (or any OpenAI-compatible API). API key: https://platform.openai.com/api-keys
  openai:
    api_key: "..."
    model: "gpt-6-luna"
    # reasoning_effort: low    # none | low | medium | high | xhigh | max (model-dependent)

  # OpenAI Decisions API reviewer provider.
  # openai_decisions:
  #   kind: openai
  #   api: decisions
  #   api_key: "..."
  #   model: "gpt-6-luna"

  # Jev (TypeSafe AI) safety reviewer. API key: https://console.typesafe.ai/keys
  jev:
    api_key: "..."

  # Uses Ollaya for a local decision model (https://ollaya.dev), model example: jevk5:4b
  # ollaya:
  #   model: "jevk5:4b"

  # Uses Ollama for a local LLM to create the scripts (set `default_provider: ollama`)
  # ollama:
  #   base_url: "http://localhost:11434/v1"
  #   model: "qwen3"
"""

# secrets.yaml stays listed so files from before the rename remain ignored.
_IGNORE_LINES = ("config.yaml", "secrets.yaml", "functions/")


def ensure_gitignore(home: Path) -> bool:
    """Append config.yaml, secrets.yaml, functions/ to home/.gitignore if home is a git repo."""
    if not (home / ".git").exists():
        return False
    gi = home / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    present = {line.strip() for line in existing.splitlines()}
    missing = [line for line in _IGNORE_LINES if line not in present]
    if not missing:
        return False
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    gi.write_text(existing + prefix + "\n".join(missing) + "\n", encoding="utf-8")
    return True


def run_init() -> int:
    def say(msg: str) -> None:
        print(msg, file=sys.stderr)

    home = aiscript_home()
    ensure_dirs()
    say(f"Config directory: {home}")
    say(f"  prompts:   {prompts_dir()}")
    say(f"  functions: {functions_dir()}")

    path = config_path()
    legacy = legacy_secrets_path()
    if not path.exists() and legacy.is_file():
        # Old layout: don't create a second file that would shadow the user's keys.
        say(f"Found legacy {legacy}; rename it: mv {legacy} {path}")
        path = legacy
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            say(f"Config file already exists (left untouched): {path}")
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(CONFIG_TEMPLATE)
            say(f"Created config file: {path}")
    if not is_windows():
        os.chmod(path, 0o600)

    if ensure_gitignore(home):
        say(f"Updated {home / '.gitignore'} (config.yaml, secrets.yaml, functions/)")

    say("")
    say("Next steps:")
    say(f"  1. Put your OpenAI and Jev API keys in {path}")
    say("     (or export OPENAI_API_KEY and TYPESAFE_API_KEY).")
    say("     For a local, keyless review, use the `ollaya` provider (https://ollaya.dev).")
    say("  2. Create your first command:  aiscript <name>")
    return 0
