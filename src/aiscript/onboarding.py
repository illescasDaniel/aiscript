"""Interactive first-use provider selection and safe config publication."""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

from aiscript.errors import AiscriptError
from aiscript.paths import config_path, legacy_secrets_path
from aiscript.provider_factory import ACP_COMMANDS

# Hints indicate local presence only; they are not authentication checks.
_PROVIDERS: tuple[tuple[str, str | None, str | None], ...] = (
    ("openai", None, "OPENAI_API_KEY"),
    ("anthropic", None, "ANTHROPIC_API_KEY"),
    ("gemini", None, "GEMINI_API_KEY"),
    ("codex-acp", ACP_COMMANDS["codex-acp"][0], None),
    ("claude-acp", ACP_COMMANDS["claude-acp"][0], None),
    ("gemini-acp", ACP_COMMANDS["gemini-acp"][0], None),
    ("opencode-go-acp", ACP_COMMANDS["opencode-go-acp"][0], None),
    ("glm-acp", ACP_COMMANDS["glm-acp"][0], None),
)


def _indicator(command: str | None, key: str | None) -> str:
    try:
        if command is not None:
            return "executable found" if shutil.which(command) else "not detected"
        if key is not None:
            present = key in os.environ or (
                key == "GEMINI_API_KEY" and "GOOGLE_API_KEY" in os.environ
            )
            return "API key present" if present else "not detected"
    except (OSError, ValueError):
        return "unknown"
    return "unknown"


def select_provider() -> str | None:
    """Ask once for a provider, without launching agents or reading key values."""
    print("Choose your default provider (local hints do not verify login):", file=sys.stderr)
    for index, (name, command, key) in enumerate(_PROVIDERS, start=1):
        print(f"  {index}. {name} — {_indicator(command, key)}", file=sys.stderr)
    names = tuple(name for name, _, _ in _PROVIDERS)
    while True:
        print("Provider number or name (Ctrl-D to cancel): ", end="", file=sys.stderr, flush=True)
        try:
            answer = input().strip()
        except (EOFError, KeyboardInterrupt):
            print("\nProvider setup cancelled.", file=sys.stderr)
            return None
        if answer.isdecimal() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        if answer in names:
            return answer
        print("Choose a listed provider.", file=sys.stderr)


def publish_config(path: Path, content: str) -> bool:
    """Publish a complete private file without replacing a concurrent winner."""
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    except OSError as exc:
        raise AiscriptError(f"Cannot create config file {path}: {exc}") from exc
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


def setup_if_needed(template: str) -> bool:
    """Interactively choose a provider when no config exists; False means cancelled."""
    path = config_path()
    if path.exists() or legacy_secrets_path().is_file():
        return True
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return True
    selected = select_provider()
    if selected is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    content = template.replace("default_provider: openai", f"default_provider: {selected}", 1)
    created = publish_config(path, content)
    if created:
        print(f"Created config file: {path}", file=sys.stderr)
        print(
            f"Set up {selected} credentials or sign in with its agent as needed.", file=sys.stderr
        )
    else:
        print(f"Config created concurrently; using existing file: {path}", file=sys.stderr)
    override = os.environ.get("AISCRIPT_PROVIDER", "").strip()
    if override:
        print(
            f"AISCRIPT_PROVIDER selects {override} for this generation; "
            "the saved default is used by --ask.",
            file=sys.stderr,
        )
    return True
