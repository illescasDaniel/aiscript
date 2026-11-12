"""Composition root for ``aiscript --ask``."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import IO

from aiscript import ask_counter, ask_openai
from aiscript.ask import AskRequest, JsonSchema, decode_input, run_ask, validate_call
from aiscript.config import (
    identify_ask_target,
    load_ai_settings,
    load_raw_config,
    resolve_ask_key,
)
from aiscript.errors import AskConfigError, AskError, AskUsageError, ConfigError

_MAX_MESSAGE = 600


def _parse_schema(schema_json: str | None) -> JsonSchema | None:
    if schema_json is None:
        return None
    try:
        schema = json.loads(schema_json)
    except ValueError:
        raise AskUsageError("The schema is not valid JSON.") from None
    if not isinstance(schema, dict):
        raise AskUsageError("The schema must be a JSON object.")
    return schema


def _ask(
    task: str,
    data_description: str,
    schema_json: str | None,
    stdin: IO[bytes],
    stdout: IO[bytes],
    environ: Mapping[str, str],
) -> None:
    schema = _parse_schema(schema_json)
    validate_call(task, data_description, schema)  # F6
    try:
        raw = load_raw_config()
        limits = load_ai_settings(raw)
    except ConfigError as exc:
        raise AskConfigError(str(exc)) from None
    target = identify_ask_target(raw)  # F7
    key = resolve_ask_key(target, raw, environ)
    max_bytes = limits.max_input_kb * 1024
    data = decode_input(stdin.read(max_bytes), max_bytes)  # F8
    provider = ask_openai.make_openai_provider(target, key, limits)
    result = run_ask(  # F13, then send (F9-F12)
        AskRequest(task, data, data_description, schema),
        limits=limits,
        provider=provider,
        counter=ask_counter.counter_from_env(environ),
        where=f"provider '{target.provider}'",
    )
    stdout.write((result.render() + "\n").encode("utf-8"))
    stdout.flush()


def run(
    task: str,
    data_description: str,
    schema_json: str | None,
    *,
    stdin: IO[bytes],
    stdout: IO[bytes],
    environ: Mapping[str, str],
) -> int:
    """Wire the core to the OpenAI adapter and the call counter; return the exit code."""
    try:
        _ask(task, data_description, schema_json, stdin, stdout, environ)
    except AskError as exc:
        message = str(exc)
        if len(message) > _MAX_MESSAGE:
            message = message[:_MAX_MESSAGE] + "..."
        print(f"aiscript: error: {message}", file=sys.stderr)
        return exc.exit_code
    return 0
