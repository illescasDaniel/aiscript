"""Native Anthropic Messages API adapter."""

from __future__ import annotations

from typing import Any, Literal

import httpx2 as httpx

from aiscript.providers.contracts import (
    CompletionError,
    CompletionRequest,
    CompletionResult,
    ProviderCapabilities,
    ProviderFailure,
    enforce_capabilities,
)


def failure(kind: ProviderFailure, code: int | None = None) -> CompletionError:
    """Create bounded metadata without retaining provider payloads."""
    error = CompletionError("provider request failed")
    error.kind, error.status_code = kind, code
    return error


def post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Send a bounded API request without leaking response bodies in errors."""
    for attempt in range(3):
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=timeout)
        except httpx.TimeoutException:
            if attempt < 2:
                continue
            raise failure("timeout") from None
        except httpx.RequestError:
            if attempt < 2:
                continue
            raise failure("connection") from None
        code = response.status_code
        if code >= 400:
            if (code == 429 or code >= 500) and attempt < 2:
                continue
            kind: ProviderFailure = (
                "auth"
                if code == 401
                else "forbidden"
                if code == 403
                else "not_found"
                if code == 404
                else "bad_request"
                if code == 400
                else "rate_limit"
                if code == 429
                else "server"
                if code >= 500
                else "unexpected"
            )
            raise failure(kind, code)
        try:
            value = response.json()
        except ValueError:
            raise failure("unexpected") from None
        if not isinstance(value, dict):
            raise failure("unexpected")
        return value
    raise failure("unexpected")


class AnthropicProvider:
    """Use the native Messages API, never the OpenAI compatibility layer."""

    def __init__(self, base_url: str, model: str, api_key: str, timeout: float) -> None:
        self.base_url, self.model, self.api_key, self.timeout = base_url, model, api_key, timeout

    def complete(self, request: CompletionRequest) -> CompletionResult:
        enforce_capabilities(request, ProviderCapabilities(True, True, True, True))
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens or 4000,
            "system": request.instructions,
            "messages": [{"role": "user", "content": request.user_data}],
        }
        if request.schema is not None:
            body["output_config"] = {"format": {"type": "json_schema", "schema": request.schema}}
        response = post(
            self.base_url.rstrip("/") + "/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            body,
            self.timeout,
        )
        content = response.get("content")
        if not isinstance(content, list):
            raise failure("unexpected")
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
        reason = response.get("stop_reason")
        status: Literal["completed", "refused", "incomplete"] = (
            "incomplete"
            if reason == "max_tokens"
            else "refused"
            if reason == "refusal"
            else "completed"
        )
        return CompletionResult(
            status, text, ProviderCapabilities(True, True, request.schema is not None, True)
        )
