"""config.yaml + environment loader."""

from __future__ import annotations

import os
import re
import stat
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from aiscript.errors import ConfigError
from aiscript.paths import config_path, is_windows, legacy_secrets_path


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str | None
    base_url: str | None
    model: str
    kind: str = "openai"  # "openai" (OpenAI-compatible) or "jev" (TypeSafe System One; Ollaya too)
    api: str = "chat"  # for kind "openai": "responses" or "chat" (completions)
    reasoning_effort: str | None = None  # sent only when set
    temperature: float | None = None  # sent only when set (GPT-6 rejects it unless effort=none)


@dataclass(frozen=True)
class Settings:
    generator: ProviderConfig
    reviewer: ProviderConfig | None


DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-6-luna"
JEV_DEFAULT_MODEL = "jev-latest"
OLLAYA_DEFAULT_MODEL = "jevk5:4b"
OLLAYA_DEFAULT_URL = "http://localhost:11435"
_KINDS = {"openai", "jev", "ollaya"}
_APIS = {"responses", "chat"}
_OPENAI_HOSTS = {"api.openai.com"}
_JEV_NAMES = {"jev", "typesafe"}
_OLLAYA_NAMES = {"ollaya"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def load_raw_config() -> dict[str, Any]:
    """Return parsed config.yaml ({} if missing); ConfigError on invalid YAML.

    Falls back to the legacy secrets.yaml (with a one-time stderr warning) when config.yaml
    does not exist. The old file is never moved automatically.
    """
    path = config_path()
    if not path.is_file():
        legacy = legacy_secrets_path()
        if not legacy.is_file():
            return {}
        print(
            f"aiscript: warning: secrets.yaml is deprecated; rename it: mv {legacy} {path}",
            file=sys.stderr,
        )
        path = legacy
    if not is_windows():
        try:
            mode = path.stat().st_mode
        except OSError:
            mode = 0
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            print(
                f"aiscript: warning: {path} is accessible by other users; run: chmod 600 {path}",
                file=sys.stderr,
            )
    import yaml  # deferred: cached runs never read the config

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level.")
    return data


def _clean(value: object) -> str | None:
    """Return a stripped non-empty string, or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def is_local(base_url: str | None) -> bool:
    if not base_url:
        return False
    try:
        host = urlparse(base_url).hostname
    except ValueError:
        return False
    return (host or "").lower() in _LOCAL_HOSTS


def _is_official_openai(base_url: str | None) -> bool:
    if not base_url:
        return True
    try:
        return (urlparse(base_url).hostname or "").lower() in _OPENAI_HOSTS
    except ValueError:
        return False


def _env_key_name(provider: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", provider).upper() + "_API_KEY"


def _ollaya_base_url() -> str:
    """$OLLAYA_HOST (``host:port`` or a URL) or the local default."""
    host = _clean(os.environ.get("OLLAYA_HOST"))
    if host is None:
        return OLLAYA_DEFAULT_URL
    return host if "://" in host else f"http://{host}"


def _resolve_provider(
    name: str, raw: dict[str, Any], *, generator: bool, fallback_model: str | None = None
) -> ProviderConfig:
    path = config_path()
    providers = raw.get("providers")
    if providers is None:
        providers = {}
    if not isinstance(providers, dict):
        raise ConfigError(f"'providers' in {path} must be a mapping.")
    if providers and name not in providers:
        known = ", ".join(sorted(str(k) for k in providers))
        raise ConfigError(
            f"Provider '{name}' is not defined in {path} (known providers: {known}). "
            "Edit the file or run `aiscript --init`."
        )
    entry = providers.get(name) or {}
    if not isinstance(entry, dict):
        raise ConfigError(f"Provider '{name}' in {path} must be a mapping.")

    default_kind = (
        "jev"
        if name.lower() in _JEV_NAMES
        else "ollaya"
        if name.lower() in _OLLAYA_NAMES
        else "openai"
    )
    kind = (_clean(entry.get("kind")) or default_kind).lower()
    if kind not in _KINDS:
        raise ConfigError(
            f"Provider '{name}' in {path} has unknown kind '{kind}' "
            "(expected: openai, jev, ollaya)."
        )
    # Ollaya speaks the Jev wire protocol: only its defaults differ, so it becomes kind "jev".
    ollaya = kind == "ollaya"
    if ollaya:
        kind = "jev"

    base_url = _clean(entry.get("base_url")) or _clean(entry.get("endpoint"))
    if base_url is None and ollaya:
        base_url = _ollaya_base_url()
    if base_url is None and generator:
        base_url = _clean(os.environ.get("OPENAI_BASE_URL"))

    api_key = _clean(entry.get("api_key"))
    if api_key is not None and api_key.endswith("..."):
        api_key = None  # placeholder from the template
    if api_key is None:
        api_key = _clean(os.environ.get(_env_key_name(name)))
    if api_key is None and ollaya:
        api_key = _clean(os.environ.get("OLLAYA_API_KEY")) or "not-needed"  # auth is optional
    if api_key is None and kind == "jev":
        api_key = _clean(os.environ.get("TYPESAFE_API_KEY"))
    # A local server never gets the global OpenAI key: it would be sent to it in the clear.
    if api_key is None and generator and kind == "openai" and not is_local(base_url):
        api_key = _clean(os.environ.get("OPENAI_API_KEY"))
    if api_key is None and is_local(base_url):
        api_key = "not-needed"
    if api_key is None:
        if not generator:
            hint = f" (or comment out `reviewer_provider: {name}` to use only the static review)"
        else:
            hint = ""
        env_names = _env_key_name(name)
        if kind == "jev":
            env_names += " or TYPESAFE_API_KEY"
        elif generator:
            env_names += " or OPENAI_API_KEY"
        raise ConfigError(
            f"No API key for provider '{name}'. Set `api_key` for it in {path} "
            "(run `aiscript --init` to create the file, or edit "
            f"~/.config/aiscript/config.yaml), or export {env_names}{hint}."
        )

    if base_url and base_url.lower().startswith("http://") and not is_local(base_url):
        print(
            f"aiscript: warning: provider '{name}' uses plain http:// ({base_url}); "
            "its API key and your scripts travel unencrypted.",
            file=sys.stderr,
        )

    model = _clean(entry.get("model"))
    if model is None and generator:
        model = _clean(os.environ.get("AISCRIPT_MODEL"))
    if model is None and ollaya:
        model = OLLAYA_DEFAULT_MODEL
    if model is None and kind == "jev":
        model = JEV_DEFAULT_MODEL
    if model is None:
        model = fallback_model or DEFAULT_MODEL

    # OpenAI's own endpoint gets the Responses API; other OpenAI-compatible servers
    # (Ollama, vLLM, ...) often only implement Chat Completions.
    api = (_clean(entry.get("api")) or "").lower() or (
        "responses" if _is_official_openai(base_url) else "chat"
    )
    if api not in _APIS:
        raise ConfigError(
            f"Provider '{name}' in {path} has unknown api '{api}' (expected: responses, chat)."
        )
    reasoning_effort = _clean(entry.get("reasoning_effort"))
    temperature = entry.get("temperature")
    if temperature is not None:
        try:
            temperature = float(temperature)
        except (TypeError, ValueError):
            raise ConfigError(
                f"Provider '{name}' in {path}: temperature must be a number."
            ) from None
    return ProviderConfig(
        name=name,
        api_key=api_key,
        base_url=base_url,
        model=model,
        kind=kind,
        api=api,
        reasoning_effort=reasoning_effort,
        temperature=temperature,
    )


def load_settings() -> Settings:
    """Resolve generator/reviewer providers; raise ConfigError with actionable text."""
    raw = load_raw_config()
    gen_name = (
        _clean(os.environ.get("AISCRIPT_PROVIDER"))
        or _clean(raw.get("default_provider"))
        or DEFAULT_PROVIDER
    )
    generator = _resolve_provider(gen_name, raw, generator=True)
    if generator.kind == "jev":
        raise ConfigError(
            f"Provider '{gen_name}' is a Jev-style (TypeSafe/Ollaya) classifier and cannot "
            "generate scripts. "
            "Use it as `reviewer_provider` and pick a chat model for `default_provider`."
        )

    reviewer = None
    rev_name = _clean(raw.get("reviewer_provider"))
    if rev_name:
        reviewer = _resolve_provider(rev_name, raw, generator=False, fallback_model=generator.model)
    return Settings(generator=generator, reviewer=reviewer)
