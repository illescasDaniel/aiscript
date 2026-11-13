"""config.yaml + environment loader."""

from __future__ import annotations

import os
import re
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlparse

from aiscript.errors import AskConfigError, ConfigError
from aiscript.paths import config_path, is_windows, legacy_secrets_path


@dataclass(frozen=True)
class QSIVSettings:
    """Optional ``providers.qsiv`` keys; None means the qsiv-runtime default."""

    model_directory: str | None = None
    python: str | None = None
    runtime: Literal["fp8", "reference"] | None = None


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str | None = field(repr=False)
    base_url: str | None
    model: str
    kind: str = "openai"  # "openai" (OpenAI-compatible) or "jev" (TypeSafe System One; Ollaya too)
    api: str = "chat"  # for kind "openai": "responses", "chat", or reviewer-only "decisions"
    reasoning_effort: str | None = None  # sent only when set
    temperature: float | None = None  # sent only when set (GPT-6 rejects it unless effort=none)
    qsiv: QSIVSettings | None = None  # set only for the reviewer-only kind "qsiv" (api "qsiv")


OFFICIAL_OPENAI_URL: Final = "https://api.openai.com/v1"
ASK_RETRIES: Final = 2

ACP_PROVIDERS: Final = frozenset(
    {"codex-acp", "claude-acp", "gemini-acp", "opencode-go-acp", "glm-acp"}
)
NATIVE_PROVIDERS: Final = frozenset({"anthropic", "gemini"})
QSIV_PROVIDER: Final = "qsiv"
_QSIV_KEYS: Final = frozenset({"kind", "model_directory", "python", "runtime"})
_BUILTIN_PROVIDERS: Final = ACP_PROVIDERS | NATIVE_PROVIDERS | {"openai", QSIV_PROVIDER}
_NATIVE_URLS: Final = {
    # The adapters append only the resource path, so the API version belongs here; the
    # official-origin check compares the host only.
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}
_NATIVE_MODELS: Final = {"anthropic": "claude-sonnet-4-5", "gemini": "gemini-2.5-pro"}
_NATIVE_KEYS: Final = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


@dataclass(frozen=True)
class AiSettings:
    """The optional ``ai:`` section of config.yaml (run-time limits of ``--ask``)."""

    max_input_kb: int = 128
    max_calls_per_run: int = 1
    timeout_seconds: int = 60
    max_output_tokens: int = 4000


@dataclass(frozen=True)
class AcpSettings:
    """Limits for a single ACP process and exchange."""

    timeout_seconds: int = 100
    max_frame_kib: int = 1024
    max_response_kib: int = 1024


@dataclass(frozen=True)
class AskTarget:
    """Run-time endpoint of ``--ask``: the YAML ``default_provider`` only, never the environment."""

    provider: str
    model: str
    base_url: str  # never None: the official URL is pinned
    api: Literal["responses", "chat"]
    official: bool
    local: bool
    kind: str = "openai"
    reasoning_effort: str | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class Settings:
    generator: ProviderConfig
    reviewer: ProviderConfig | None
    ai: AiSettings = AiSettings()
    ai_target: str = "the default provider"
    known_secrets: tuple[str, ...] = field(default=(), repr=False)


DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-6-luna"
DECISIONS_DEFAULT_MODEL = "gpt-6-luna"
JEV_DEFAULT_MODEL = "jev-latest"
OLLAYA_DEFAULT_MODEL = "jevk5:4b"
OLLAYA_DEFAULT_URL = "http://localhost:11435"
# "qsiv" is not listed: like acp and the native kinds it returns from its own branch.
_KINDS = {"openai", "jev", "ollaya"}
_APIS = {"responses", "chat", "decisions"}
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
        # No PyYAML snippet: the offending line may hold an api_key.
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise ConfigError(f"Invalid YAML in {path}{where}") from None
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


def _native_official(kind: str, url: str | None) -> bool:
    """Only official HTTPS origins may receive native provider environment keys."""
    try:
        parsed = urlparse(url or _NATIVE_URLS[kind])
        expected = urlparse(_NATIVE_URLS[kind])
        return (
            parsed.scheme.lower() == "https"
            and parsed.hostname == expected.hostname
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _selected_kind(name: str, providers: Mapping[str, Any], entry: Mapping[str, Any]) -> str:
    explicit = _clean(entry.get("kind"))
    if explicit:
        return explicit.lower()
    # An empty entry (e.g. an uncommented `codex-acp:`) does not define an endpoint.
    if name not in providers or not (entry.get("base_url") or entry.get("endpoint")):
        if name in ACP_PROVIDERS:
            return "acp"
        if name in NATIVE_PROVIDERS:
            return name
        if name == QSIV_PROVIDER:
            return QSIV_PROVIDER
    if name.lower() in _JEV_NAMES:
        return "jev"
    if name.lower() in _OLLAYA_NAMES:
        return "ollaya"
    return "openai"


def _qsiv_settings(name: str, entry: Mapping[str, Any], path: Path) -> QSIVSettings:
    """Unknown keys, non-string paths and a runtime other than fp8/reference are errors."""
    for key in entry:
        if key not in _QSIV_KEYS:
            raise ConfigError(
                f"Provider '{name}' in {path}: unknown QSIV key '{key}' "
                f"(expected: {', '.join(sorted(_QSIV_KEYS - {'kind'}))})."
            )
    paths: dict[str, str | None] = {}
    for key in ("model_directory", "python"):
        value = entry.get(key)
        if value is not None and not (isinstance(value, str) and value.strip()):
            raise ConfigError(f"Provider '{name}' in {path}: {key} must be a path string.")
        paths[key] = value.strip() if isinstance(value, str) else None
    runtime = entry.get("runtime")
    if runtime is None:
        return QSIVSettings(paths["model_directory"], paths["python"])
    if runtime == "fp8" or runtime == "reference":
        return QSIVSettings(paths["model_directory"], paths["python"], runtime)
    raise ConfigError(f"Provider '{name}' in {path}: runtime must be fp8 or reference.")


def _resolve_provider(
    name: str, raw: dict[str, Any], *, generator: bool, fallback_model: str | None = None
) -> ProviderConfig:
    path = config_path()
    providers = raw.get("providers")
    if providers is None:
        providers = {}
    if not isinstance(providers, dict):
        raise ConfigError(f"'providers' in {path} must be a mapping.")
    if (
        name not in providers
        and name not in _BUILTIN_PROVIDERS
        and not (not providers and name.lower() in _JEV_NAMES | _OLLAYA_NAMES)
    ):
        known = ", ".join(sorted(str(k) for k in providers))
        listed = f" (known providers: {known})" if known else ""
        raise ConfigError(
            f"Provider '{name}' is not defined in {path}{listed}. "
            "Edit the file or run `aiscript --init`."
        )
    entry = providers.get(name) or {}
    if not isinstance(entry, dict):
        raise ConfigError(f"Provider '{name}' in {path} must be a mapping.")

    kind = _selected_kind(name, providers, entry)
    if kind == "acp":
        if not generator or name not in ACP_PROVIDERS:
            raise ConfigError(f"Provider '{name}' cannot be used as an ACP reviewer or alias.")
        if entry:
            raise ConfigError(f"Provider '{name}': ACP settings belong to the agent configuration.")
        return ProviderConfig(
            name=name, api_key=None, base_url=None, model="", kind="acp", api="acp"
        )
    if kind == QSIV_PROVIDER:
        if generator:
            raise ConfigError(
                f"Provider '{name}' in {path}: QSIV cannot generate scripts. "
                "Select it with `reviewer_provider` and use another generator."
            )
        return ProviderConfig(
            name=name,
            api_key=None,
            base_url=None,
            model="",
            kind=QSIV_PROVIDER,
            api=QSIV_PROVIDER,
            qsiv=_qsiv_settings(name, entry, path),
        )
    if kind in NATIVE_PROVIDERS:
        if not generator:
            raise ConfigError(f"Provider '{name}': native API reviewer is not supported.")
        base_url = _clean(entry.get("base_url")) or _clean(entry.get("endpoint"))
        key = _clean(entry.get("api_key"))
        if key and key.endswith("..."):
            key = None
        if key is None and _native_official(kind, base_url):
            key = next(
                (
                    _clean(os.environ.get(k))
                    for k in _NATIVE_KEYS[kind]
                    if _clean(os.environ.get(k))
                ),
                None,
            )
        if key is None:
            if not _native_official(kind, base_url):
                raise ConfigError(
                    f"Provider '{name}': set api_key explicitly for a non-official endpoint."
                )
            raise ConfigError(
                f"No API key for provider '{name}'. Set api_key or export {_NATIVE_KEYS[kind][0]}."
            )
        native_model = (
            _clean(entry.get("model"))
            or _clean(os.environ.get("AISCRIPT_MODEL"))
            or _NATIVE_MODELS[kind]
        )
        return ProviderConfig(
            name=name,
            api_key=key,
            base_url=base_url or _NATIVE_URLS[kind],
            model=native_model,
            kind=kind,
            api=kind,
        )
    if kind not in _KINDS:
        raise ConfigError(
            f"Provider '{name}' in {path} has unknown kind '{kind}' "
            "(expected: openai, jev, ollaya, qsiv)."
        )
    if (_clean(entry.get("api")) or "").lower() == "decisions":
        if generator:
            raise ConfigError(
                f"Provider '{name}' in {path}: Decisions is only supported as a reviewer. "
                "Select it with `reviewer_provider` and use another generator."
            )
        if kind != "openai":
            raise ConfigError(f"Provider '{name}' in {path}: Decisions requires kind 'openai'.")
        for setting in ("temperature", "reasoning_effort"):
            if setting in entry:
                raise ConfigError(
                    f"Provider '{name}' in {path}: {setting} is not supported by Decisions. "
                    "Remove that setting."
                )

        official_url = "https://api.openai.com/v1"
        for alias in ("base_url", "endpoint"):
            if alias in entry and _clean(entry[alias]) not in (official_url, official_url + "/"):
                raise ConfigError(
                    f"Provider '{name}' in {path}: Decisions {alias} must be "
                    f"{official_url} (an optional trailing slash is accepted)."
                )

        api_key = None
        env_name = _env_key_name(name)
        for candidate in (entry.get("api_key"), os.environ.get(env_name)):
            cleaned_key = _clean(candidate)
            if cleaned_key is not None and not cleaned_key.endswith("..."):
                api_key = cleaned_key
                break
        if api_key is None:
            raise ConfigError(
                f"No API key for provider '{name}'. Set `api_key` for it in {path} "
                f"or export {env_name}; Decisions requires a dedicated reviewer credential."
            )
        return ProviderConfig(
            name=name,
            api_key=api_key,
            base_url=official_url,
            model=_clean(entry.get("model")) or DECISIONS_DEFAULT_MODEL,
            kind="openai",
            api="decisions",
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
        elif generator and env_names != "OPENAI_API_KEY":
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
            f"Provider '{name}' in {path} has unknown api '{api}' "
            "(expected: responses, chat, decisions)."
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
    ai = load_ai_settings(raw)
    load_acp_settings(raw)  # reject invalid ACP limits before any provider is invoked
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
    return Settings(
        generator=generator,
        reviewer=reviewer,
        ai=ai,
        ai_target=describe_ask_target(raw),
        known_secrets=collect_known_secrets(raw, os.environ),
    )


_AI_BOUNDS: Final = {
    "max_input_kb": (1, 1024),
    "max_calls_per_run": (1, 100),
    "timeout_seconds": (1, 600),
    "max_output_tokens": (1, 32000),
}
_MIN_SECRET_LENGTH: Final = 8
_KNOWN_KEY_ENV_NAMES: Final = (
    "OPENAI_API_KEY",
    "OPENAI_DECISIONS_API_KEY",
    "TYPESAFE_API_KEY",
    "OLLAYA_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)


def load_acp_settings(raw: Mapping[str, Any]) -> AcpSettings:
    """Parse ACP deadline and size limits before launching an agent."""
    path = config_path()
    block = raw.get("acp")
    if block is None:
        return AcpSettings()
    if not isinstance(block, dict):
        raise ConfigError(f"'acp' in {path} must be a mapping.")
    bounds = {
        "timeout_seconds": (1, 600),
        "max_frame_kib": (1, 16384),
        "max_response_kib": (1, 16384),
    }
    for key in block:
        if key not in bounds:
            raise ConfigError(f"Unknown key '{key}' in the 'acp' section of {path}.")
    values: dict[str, int] = {}
    for key, (low, high) in bounds.items():
        if key not in block:
            continue
        value = block[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigError(f"'acp.{key}' in {path} must be an integer from {low} to {high}.")
        values[key] = value
    return AcpSettings(**values)


def load_ai_settings(raw: Mapping[str, Any]) -> AiSettings:
    """Read and bound-check the ``ai:`` section; ConfigError on a bad value (F1)."""
    path = config_path()
    block = raw.get("ai")
    if block is None:
        return AiSettings()
    if not isinstance(block, dict):
        raise ConfigError(f"'ai' in {path} must be a mapping.")
    for key in block:
        if key not in _AI_BOUNDS:
            raise ConfigError(
                f"Unknown key '{key}' in the 'ai' section of {path} "
                f"(expected: {', '.join(_AI_BOUNDS)})."
            )
    values: dict[str, int] = {}
    for key, (low, high) in _AI_BOUNDS.items():
        if key not in block:
            continue
        value = block[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigError(f"'ai.{key}' in {path} must be an integer from {low} to {high}.")
        values[key] = value
    return AiSettings(**values)


def identify_ask_target(raw: Mapping[str, Any]) -> AskTarget:
    """Name the run-time endpoint from config.yaml alone: no environment, no key (F7)."""
    path = config_path()
    name = _clean(raw.get("default_provider")) or DEFAULT_PROVIDER
    providers = raw.get("providers")
    if providers is None:
        providers = {}
    if not isinstance(providers, dict):
        raise AskConfigError(f"'providers' in {path} must be a mapping.")
    if (
        name not in providers
        and name not in _BUILTIN_PROVIDERS
        and not (not providers and name.lower() in _JEV_NAMES | _OLLAYA_NAMES)
    ):
        known = ", ".join(sorted(str(k) for k in providers))
        listed = f" (known providers: {known})" if known else ""
        raise AskConfigError(f"Provider '{name}' is not defined in {path}{listed}.")
    entry = providers.get(name) or {}
    if not isinstance(entry, dict):
        raise AskConfigError(f"Provider '{name}' in {path} must be a mapping.")
    kind = _selected_kind(name, providers, entry)
    if kind == "acp":
        if name not in ACP_PROVIDERS or entry:
            raise AskConfigError(
                f"Provider '{name}': ACP settings belong to the agent configuration."
            )
        return AskTarget(
            provider=name,
            model="",
            base_url="",
            api="chat",
            official=False,
            local=False,
            kind="acp",
        )
    if kind in NATIVE_PROVIDERS:
        url = _clean(entry.get("base_url")) or _clean(entry.get("endpoint"))
        return AskTarget(
            provider=name,
            model=_clean(entry.get("model")) or _NATIVE_MODELS[kind],
            base_url=url or _NATIVE_URLS[kind],
            api="chat",
            official=_native_official(kind, url),
            local=is_local(url),
            kind=kind,
        )
    api_name = (_clean(entry.get("api")) or "").lower()
    if kind != "openai":
        raise AskConfigError(
            f"Provider '{name}' in {path} is not OpenAI-compatible (kind '{kind}'); "
            "`--ask` needs an OpenAI-compatible default_provider."
        )
    if api_name not in ("", "responses", "chat"):
        raise AskConfigError(
            f"Provider '{name}' in {path} uses api '{api_name}'; "
            "`--ask` supports responses or chat."
        )
    configured_url = _clean(entry.get("base_url")) or _clean(entry.get("endpoint"))
    official = _is_official_openai(configured_url)
    api: Literal["responses", "chat"] = (
        "chat" if api_name == "chat" else "responses" if api_name or official else "chat"
    )
    temperature = entry.get("temperature")
    if temperature is not None:
        try:
            temperature = float(temperature)
        except (TypeError, ValueError):
            raise AskConfigError(
                f"Provider '{name}' in {path}: temperature must be a number."
            ) from None
    return AskTarget(
        provider=name,
        model=_clean(entry.get("model")) or DEFAULT_MODEL,
        base_url=configured_url or OFFICIAL_OPENAI_URL,
        api=api,
        official=official,
        local=is_local(configured_url),
        reasoning_effort=_clean(entry.get("reasoning_effort")),
        temperature=temperature,
    )


def _yaml_key(raw: Mapping[str, Any], provider: str) -> str | None:
    """The ``api_key`` of a providers entry, None when absent or a template placeholder."""
    providers = raw.get("providers")
    if not isinstance(providers, dict):
        return None
    entry = providers.get(provider)
    if not isinstance(entry, dict):
        return None
    key = _clean(entry.get("api_key"))
    return None if key is None or key.endswith("...") else key


def resolve_ask_key(target: AskTarget, raw: Mapping[str, Any], environ: Mapping[str, str]) -> str:
    """Pick the API key for ``target`` in the C4 order (F7, S19)."""
    if target.kind == "acp":
        return ""
    key = _yaml_key(raw, target.provider)
    if key is not None:
        return key
    if target.kind in NATIVE_PROVIDERS:
        if target.official:
            for env_name in _NATIVE_KEYS[target.kind]:
                key = _clean(environ.get(env_name))
                if key is not None:
                    return key
        if not target.official:
            raise AskConfigError(
                f"Provider '{target.provider}' uses a non-official endpoint; "
                f"set api_key in {config_path()}."
            )
        raise AskConfigError(
            f"No API key for provider '{target.provider}'. "
            f"Set api_key or export {_NATIVE_KEYS[target.kind][0]}."
        )
    if target.official:
        env_name = _env_key_name(target.provider)
        for name in (env_name, "OPENAI_API_KEY"):
            key = _clean(environ.get(name))
            if key is not None:
                return key
        names = env_name if env_name == "OPENAI_API_KEY" else f"{env_name} or OPENAI_API_KEY"
        raise AskConfigError(
            f"No API key for provider '{target.provider}'. Set `api_key` for it in "
            f"{config_path()} or export {names}."
        )
    if target.local:
        return "not-needed"
    raise AskConfigError(
        f"Provider '{target.provider}' uses a non-official endpoint, so its key must be set as "
        f"`api_key` in {config_path()}; {_env_key_name(target.provider)} and OPENAI_API_KEY "
        "are only used for api.openai.com."
    )


def describe_ask_target(raw: Mapping[str, Any]) -> str:
    """Human-readable provider name for the build-time "AI use" finding; never raises."""
    try:
        target = identify_ask_target(raw)
    except AskConfigError as exc:
        return f"the default provider (not usable for --ask: {exc})"
    if target.kind == "acp":
        return f"provider '{target.provider}' (agent-configured model)"
    return f"provider '{target.provider}' (model {target.model})"


def collect_known_secrets(raw: Mapping[str, Any], environ: Mapping[str, str]) -> tuple[str, ...]:
    """Every configured or exported API key, for the secret scanner (C8)."""
    providers = raw.get("providers")
    names = [str(k) for k in providers] if isinstance(providers, dict) else []
    candidates: list[str | None] = [_yaml_key(raw, n) for n in names]
    env_names = [*_KNOWN_KEY_ENV_NAMES, *(_env_key_name(n) for n in names)]
    candidates.extend(_clean(environ.get(n)) for n in env_names)
    found: dict[str, None] = {}
    for value in candidates:
        if (
            value is not None
            and len(value) >= _MIN_SECRET_LENGTH
            and value != "not-needed"
            and not value.endswith("...")
        ):
            found[value] = None
    return tuple(found)
