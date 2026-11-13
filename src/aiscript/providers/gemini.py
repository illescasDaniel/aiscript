"""Native Gemini generateContent API adapter."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

from aiscript.providers.anthropic import failure, post
from aiscript.providers.contracts import (
    CompletionRequest,
    CompletionResult,
    ProviderCapabilities,
    enforce_capabilities,
)


class GeminiProvider:
    """Use Gemini's native generateContent request and constrained JSON mode."""

    def __init__(self, base_url: str, model: str, api_key: str, timeout: float) -> None:
        self.base_url, self.model, self.api_key, self.timeout = base_url, model, api_key, timeout

    def complete(self, request: CompletionRequest) -> CompletionResult:
        enforce_capabilities(request, ProviderCapabilities(True, True, True, True))
        config: dict[str, Any] = {"maxOutputTokens": request.max_output_tokens or 4000}
        if request.schema is not None:
            config.update(responseMimeType="application/json", responseJsonSchema=request.schema)
        body = {
            "systemInstruction": {"parts": [{"text": request.instructions}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_data}]}],
            "generationConfig": config,
        }
        model = quote(self.model, safe="")
        response = post(
            self.base_url.rstrip("/") + "/models/" + model + ":generateContent",
            {"x-goog-api-key": self.api_key},
            body,
            self.timeout,
        )
        candidates = response.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = response.get("promptFeedback")
            if isinstance(feedback, dict) and feedback.get("blockReason"):
                return CompletionResult(
                    "refused", "", ProviderCapabilities(True, True, False, True)
                )
            raise failure("unexpected")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise failure("unexpected")
        content = candidate.get("content")
        parts = content.get("parts", []) if isinstance(content, dict) else []
        if not isinstance(parts, list):
            raise failure("unexpected")
        text = "".join(
            part["text"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
        reason = candidate.get("finishReason")
        status: Literal["completed", "refused", "incomplete"] = (
            "incomplete"
            if reason == "MAX_TOKENS"
            else "refused"
            if reason in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT")
            else "completed"
        )
        return CompletionResult(
            status, text, ProviderCapabilities(True, True, request.schema is not None, True)
        )
