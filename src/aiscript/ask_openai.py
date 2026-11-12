"""OpenAI adapters for ``--ask``; the only module importing ``openai`` for it."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any, Literal, Protocol, TypeVar

import openai
from openai import OpenAI
from openai.types.responses import Response

from aiscript.ask import AskPrompt, AskProvider, ProviderCallError, ProviderReply
from aiscript.config import ASK_RETRIES, AiSettings, AskTarget

SCHEMA_NAME = "aiscript_answer"
T = TypeVar("T")
Status = Literal["completed", "incomplete", "refused"]


def _status_error(exc: openai.APIStatusError) -> ProviderCallError:
    """Map an HTTP failure to a bounded kind; the response body is never read."""
    status = exc.status_code
    if status == 429:
        code = getattr(exc, "code", None)
        return ProviderCallError("quota" if code == "insufficient_quota" else "rate_limit", status)
    kinds = {400: "bad_request", 401: "auth", 403: "forbidden", 404: "not_found"}
    if status in kinds:
        return ProviderCallError(kinds[status], status)  # type: ignore[arg-type]
    if status >= 500:
        return ProviderCallError("server", status)
    return ProviderCallError("unexpected", status)


def _call(request: Callable[..., T], **kwargs: Any) -> T:
    """Run an SDK call and translate every failure into ``ProviderCallError``."""
    try:
        return request(**kwargs)
    except ProviderCallError:
        raise
    except openai.APITimeoutError:
        raise ProviderCallError("timeout") from None
    except openai.APIConnectionError:
        raise ProviderCallError("connection") from None
    except openai.APIStatusError as exc:
        raise _status_error(exc) from None
    except Exception:  # noqa: BLE001 - malformed replies must not leak payloads
        raise ProviderCallError("unexpected") from None


class _HttpResponse(Protocol):
    """The slice of the SDK's HTTP response the retry hook touches (httpx is a moving name)."""

    status_code: int
    headers: MutableMapping[str, str]
    content: bytes

    def read(self) -> bytes: ...


def _stop_retry_on_quota(response: _HttpResponse) -> None:
    """Mark ``insufficient_quota`` 429s as final: retrying them cannot succeed."""
    if response.status_code != 429:
        return
    response.read()
    if b"insufficient_quota" in response.content:
        response.headers["x-should-retry"] = "false"


def _client(target: AskTarget, api_key: str, timeout: float, max_retries: int) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=target.base_url,
        timeout=timeout,
        max_retries=max_retries,
        http_client=openai.DefaultHttpxClient(event_hooks={"response": [_stop_retry_on_quota]}),
    )


class ResponsesAskProvider:
    """``responses.create(..., store=False)`` with no tools."""

    def __init__(
        self, target: AskTarget, api_key: str, *, timeout: float, max_retries: int = ASK_RETRIES
    ) -> None:
        self._target = target
        self._client = _client(target, api_key, timeout, max_retries)

    def complete(self, prompt: AskPrompt) -> ProviderReply:
        kwargs: dict[str, Any] = {
            "model": self._target.model,
            "instructions": prompt.system,
            "input": prompt.user,
            "store": False,
            "max_output_tokens": prompt.max_output_tokens,
        }
        if self._target.reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": self._target.reasoning_effort}
        if self._target.temperature is not None:
            kwargs["temperature"] = self._target.temperature
        if prompt.schema is not None:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": SCHEMA_NAME,
                    "schema": prompt.schema,
                    "strict": True,
                }
            }
        response = _call(self._client.responses.create, **kwargs)
        try:
            return self._normalise(response)
        except Exception:  # noqa: BLE001
            raise ProviderCallError("unexpected") from None

    @staticmethod
    def _normalise(response: Response) -> ProviderReply:
        parts = [
            part for item in response.output if item.type == "message" for part in item.content
        ]
        if any(part.type == "refusal" for part in parts):
            return ProviderReply("refused", "")
        text = "".join(part.text for part in parts if part.type == "output_text")
        status: Status = "incomplete" if response.status == "incomplete" else "completed"
        return ProviderReply(status, text)


class ChatAskProvider:
    """``chat.completions.create``; ``max_completion_tokens`` if official else ``max_tokens``."""

    def __init__(
        self, target: AskTarget, api_key: str, *, timeout: float, max_retries: int = ASK_RETRIES
    ) -> None:
        self._target = target
        self._client = _client(target, api_key, timeout, max_retries)

    def complete(self, prompt: AskPrompt) -> ProviderReply:
        limit_key = "max_completion_tokens" if self._target.official else "max_tokens"
        kwargs: dict[str, Any] = {
            "model": self._target.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            limit_key: prompt.max_output_tokens,
        }
        if self._target.official:
            kwargs["store"] = False  # other servers may reject the field
        if self._target.reasoning_effort is not None:
            kwargs["reasoning_effort"] = self._target.reasoning_effort
        if self._target.temperature is not None:
            kwargs["temperature"] = self._target.temperature
        if prompt.schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": SCHEMA_NAME, "schema": prompt.schema, "strict": True},
            }
        response = _call(self._client.chat.completions.create, **kwargs)
        try:
            choice = response.choices[0]
            message = choice.message
            if message.refusal or choice.finish_reason == "content_filter":
                return ProviderReply("refused", "")
            status: Status = "incomplete" if choice.finish_reason == "length" else "completed"
            return ProviderReply(status, message.content or "")
        except Exception:  # noqa: BLE001
            raise ProviderCallError("unexpected") from None


def make_openai_provider(target: AskTarget, api_key: str, limits: AiSettings) -> AskProvider:
    """Pick the adapter for ``target.api``."""
    if target.api == "chat":
        return ChatAskProvider(target, api_key, timeout=limits.timeout_seconds)
    return ResponsesAskProvider(target, api_key, timeout=limits.timeout_seconds)
