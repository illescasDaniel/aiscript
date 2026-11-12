"""Adapter tests for ``--ask`` (S1, S2, S13-S16, S19, S20) against the local fake server."""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import openai
import pytest
from fake_openai import (
    FakeOpenAI,
    FakeReply,
    chat_reply,
    error_reply,
    responses_no_message_reply,
    responses_reply,
)

from aiscript import ask_openai
from aiscript.ask import AskPrompt, ProviderCallError, ProviderReply
from aiscript.ask_openai import ChatAskProvider, ResponsesAskProvider, make_openai_provider
from aiscript.config import AiSettings, AskTarget

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"n": {"type": "integer"}},
    "required": ["n"],
    "additionalProperties": False,
}
SECRET_PAYLOAD = "PAYLOAD-MUST-NOT-LEAK-12345"

Provider = ResponsesAskProvider | ChatAskProvider
Factory = Callable[..., Provider]
BOTH = pytest.mark.parametrize(
    ("cls", "path", "reply"),
    [
        (ResponsesAskProvider, "/v1/responses", responses_reply),
        (ChatAskProvider, "/v1/chat/completions", chat_reply),
    ],
    ids=["responses", "chat"],
)


def target(
    fake: FakeOpenAI,
    api: str = "responses",
    *,
    official: bool = False,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> AskTarget:
    return AskTarget(
        provider="openai",
        model="model-x",
        base_url=fake.base_url,
        api=api,  # type: ignore[arg-type]
        official=official,
        local=True,
        reasoning_effort=reasoning_effort,
        temperature=temperature,
    )


def prompt(schema: dict[str, Any] | None = None) -> AskPrompt:
    return AskPrompt(
        system="SYSTEM TEXT",
        user='{"task": "t", "data_description": "d", "data": "x"}',
        schema=schema,
        max_output_tokens=321,
    )


def build(cls: type, fake: FakeOpenAI, **kw: Any) -> Provider:
    api = "responses" if cls is ResponsesAskProvider else "chat"
    tkw = {k: kw.pop(k) for k in ("official", "reasoning_effort", "temperature") if k in kw}
    kw.setdefault("timeout", 5.0)
    provider: Provider = cls(target(fake, api, **tkw), "sk-given", **kw)
    return provider


# S1, S2: request content -------------------------------------------------------------------


def test_given_responses_when_complete_then_request_has_instructions_input_model_store_false(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(responses_reply("hello"))
    provider = build(ResponsesAskProvider, fake_openai)
    # when
    result = provider.complete(prompt())
    # then
    (req,) = fake_openai.requests
    assert req.path == "/v1/responses"
    assert req.body["instructions"] == "SYSTEM TEXT"
    assert req.body["input"] == prompt().user
    assert req.body["model"] == "model-x"
    assert req.body["store"] is False
    assert req.body["max_output_tokens"] == 321
    assert "tools" not in req.body
    assert "text" not in req.body or "format" not in req.body["text"]
    assert result == ProviderReply("completed", "hello")


def test_given_chat_when_complete_then_request_has_system_and_user_messages_and_no_tools(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply("hello"))
    provider = build(ChatAskProvider, fake_openai)
    # when
    result = provider.complete(prompt())
    # then
    (req,) = fake_openai.requests
    assert req.path == "/v1/chat/completions"
    assert req.body["model"] == "model-x"
    assert req.body["messages"] == [
        {"role": "system", "content": "SYSTEM TEXT"},
        {"role": "user", "content": prompt().user},
    ]
    assert "tools" not in req.body
    assert "response_format" not in req.body
    assert result == ProviderReply("completed", "hello")


def test_given_schema_when_responses_complete_then_strict_json_schema_in_text_format(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(responses_reply('{"n": 1}'))
    provider = build(ResponsesAskProvider, fake_openai)
    # when
    provider.complete(prompt(SCHEMA))
    # then
    fmt = fake_openai.requests[0].body["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["schema"] == SCHEMA
    assert isinstance(fmt["name"], str)
    assert fmt["name"]


def test_given_schema_when_chat_complete_then_strict_json_schema_in_response_format(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply('{"n": 1}'))
    provider = build(ChatAskProvider, fake_openai)
    # when
    provider.complete(prompt(SCHEMA))
    # then
    rf = fake_openai.requests[0].body["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == SCHEMA
    assert rf["json_schema"]["name"]


# token limit parameter -------------------------------------------------------------------


def test_given_official_chat_when_complete_then_max_completion_tokens_is_sent(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply("x"))
    provider = build(ChatAskProvider, fake_openai, official=True)
    # when
    provider.complete(prompt())
    # then
    body = fake_openai.requests[0].body
    assert body["max_completion_tokens"] == 321
    assert "max_tokens" not in body


def test_given_non_official_chat_when_complete_then_max_tokens_is_sent(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply("x"))
    provider = build(ChatAskProvider, fake_openai, official=False)
    # when
    provider.complete(prompt())
    # then
    body = fake_openai.requests[0].body
    assert body["max_tokens"] == 321
    assert "max_completion_tokens" not in body


# reasoning_effort / temperature ------------------------------------------------------------


def test_given_reasoning_and_temperature_when_responses_then_forwarded(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(responses_reply("x"))
    provider = build(ResponsesAskProvider, fake_openai, reasoning_effort="low", temperature=0.2)
    # when
    provider.complete(prompt())
    # then
    body = fake_openai.requests[0].body
    assert body["reasoning"] == {"effort": "low"}
    assert body["temperature"] == 0.2


def test_given_reasoning_and_temperature_when_chat_then_forwarded(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply("x"))
    provider = build(ChatAskProvider, fake_openai, reasoning_effort="low", temperature=0.2)
    # when
    provider.complete(prompt())
    # then
    body = fake_openai.requests[0].body
    assert body["reasoning_effort"] == "low"
    assert body["temperature"] == 0.2


@BOTH
def test_given_unset_reasoning_and_temperature_when_complete_then_not_sent(
    fake_openai: FakeOpenAI, cls: type, path: str, reply: Callable[..., FakeReply]
) -> None:
    # given
    fake_openai.enqueue(reply("x"))
    provider = build(cls, fake_openai)
    # when
    provider.complete(prompt())
    # then
    body = fake_openai.requests[0].body
    assert "reasoning" not in body
    assert "reasoning_effort" not in body
    assert "temperature" not in body


# reply normalisation ----------------------------------------------------------------------


def test_given_responses_incomplete_when_complete_then_status_incomplete(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(responses_reply("par", status="incomplete"))
    # when
    result = build(ResponsesAskProvider, fake_openai).complete(prompt())
    # then
    assert result.status == "incomplete"


@pytest.mark.parametrize(
    ("status", "reasoning", "expected"),
    [
        ("incomplete", True, "incomplete"),
        ("incomplete", False, "incomplete"),
        ("completed", True, "completed"),
        ("completed", False, "completed"),
    ],
)
def test_given_responses_without_message_part_when_complete_then_empty_reply(
    fake_openai: FakeOpenAI, status: str, reasoning: bool, expected: str
) -> None:
    # given
    fake_openai.enqueue(responses_no_message_reply(status=status, reasoning=reasoning))
    # when
    result = build(ResponsesAskProvider, fake_openai).complete(prompt())
    # then
    assert (result.status, result.text) == (expected, "")


def test_given_responses_refusal_part_when_complete_then_status_refused(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(responses_reply("", refusal="I cannot"))
    # when
    result = build(ResponsesAskProvider, fake_openai).complete(prompt())
    # then
    assert result.status == "refused"


def test_given_chat_finish_reason_length_when_complete_then_status_incomplete(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply("par", finish_reason="length"))
    # when
    result = build(ChatAskProvider, fake_openai).complete(prompt())
    # then
    assert result.status == "incomplete"


def test_given_chat_message_refusal_when_complete_then_status_refused(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply("", refusal="I cannot"))
    # when
    result = build(ChatAskProvider, fake_openai).complete(prompt())
    # then
    assert result.status == "refused"


def test_given_chat_content_filter_when_complete_then_status_refused(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply("", finish_reason="content_filter"))
    # when
    result = build(ChatAskProvider, fake_openai).complete(prompt())
    # then
    assert result.status == "refused"


# error mapping ---------------------------------------------------------------------------


def complete_error(provider: Provider) -> ProviderCallError:
    with pytest.raises(ProviderCallError) as info:
        provider.complete(prompt())
    return info.value


@BOTH
@pytest.mark.parametrize(
    ("status", "code", "kind"),
    [
        (400, None, "bad_request"),
        (401, None, "auth"),
        (403, None, "forbidden"),
        (404, None, "not_found"),
        (429, "insufficient_quota", "quota"),
    ],
)
def test_given_http_error_when_complete_then_bounded_kind_without_payload(
    fake_openai: FakeOpenAI,
    cls: type,
    path: str,
    reply: Callable[..., FakeReply],
    status: int,
    code: str | None,
    kind: str,
) -> None:
    # given
    fake_openai.enqueue(error_reply(status, SECRET_PAYLOAD, code))
    # when
    err = complete_error(build(cls, fake_openai))
    # then
    assert err.kind == kind
    assert err.status_code == status
    assert SECRET_PAYLOAD not in str(err)
    assert SECRET_PAYLOAD not in repr(err)
    assert len(fake_openai.requests) == 1


@BOTH
def test_given_rate_limit_when_complete_then_three_requests_and_rate_limit_kind(
    fake_openai: FakeOpenAI, cls: type, path: str, reply: Callable[..., FakeReply]
) -> None:
    # given
    fake_openai.enqueue(*[error_reply(429, SECRET_PAYLOAD, "rate_limit_exceeded")] * 3)
    # when
    err = complete_error(build(cls, fake_openai))
    # then
    assert err.kind == "rate_limit"
    assert len(fake_openai.requests) == 3
    assert SECRET_PAYLOAD not in str(err)


@BOTH
def test_given_server_error_when_complete_then_three_requests_and_server_kind(
    fake_openai: FakeOpenAI, cls: type, path: str, reply: Callable[..., FakeReply]
) -> None:
    # given
    fake_openai.enqueue(*[error_reply(500, SECRET_PAYLOAD)] * 3)
    # when
    err = complete_error(build(cls, fake_openai))
    # then
    assert err.kind == "server"
    assert len(fake_openai.requests) == 3
    assert SECRET_PAYLOAD not in str(err)


@BOTH
def test_given_malformed_body_when_complete_then_unexpected(
    fake_openai: FakeOpenAI, cls: type, path: str, reply: Callable[..., FakeReply]
) -> None:
    # given
    fake_openai.enqueue(FakeReply(body=f"<html>{SECRET_PAYLOAD}</html>"))
    # when
    err = complete_error(build(cls, fake_openai))
    # then
    assert err.kind == "unexpected"
    assert SECRET_PAYLOAD not in str(err)


@BOTH
def test_given_empty_choices_or_output_when_complete_then_unexpected(
    fake_openai: FakeOpenAI, cls: type, path: str, reply: Callable[..., FakeReply]
) -> None:
    # given
    fake_openai.enqueue(FakeReply(body={"unexpected": SECRET_PAYLOAD}))
    # when
    err = complete_error(build(cls, fake_openai))
    # then
    assert err.kind == "unexpected"
    assert SECRET_PAYLOAD not in str(err)


@BOTH
def test_given_closed_port_when_complete_then_connection(
    fake_openai: FakeOpenAI, cls: type, path: str, reply: Callable[..., FakeReply]
) -> None:
    # given
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    tgt = target(fake_openai, "responses" if cls is ResponsesAskProvider else "chat")
    tgt = AskTarget(**{**tgt.__dict__, "base_url": f"http://127.0.0.1:{port}/v1"})
    provider = cls(tgt, "sk-given", timeout=5.0, max_retries=0)
    # when
    err = complete_error(provider)
    # then
    assert err.kind == "connection"
    assert err.status_code is None


@contextmanager
def silent_server() -> Iterator[str]:
    """Accepts connections and never answers."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        srv.settimeout(0.1)
        while not stop.is_set():
            try:
                held.append(srv.accept()[0])
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.getsockname()[1]}/v1"
    finally:
        stop.set()
        thread.join(timeout=2)
        for conn in held:
            conn.close()
        srv.close()


@BOTH
def test_given_unresponsive_server_when_complete_then_timeout(
    fake_openai: FakeOpenAI, cls: type, path: str, reply: Callable[..., FakeReply]
) -> None:
    # given
    api = "responses" if cls is ResponsesAskProvider else "chat"
    with silent_server() as url:
        tgt = AskTarget(**{**target(fake_openai, api).__dict__, "base_url": url})
        provider = cls(tgt, "sk-given", timeout=0.3, max_retries=0)
        # when
        err = complete_error(provider)
    # then
    assert err.kind == "timeout"


# client construction (S19, S20) -------------------------------------------------------------


def capture_clients(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    real = openai.OpenAI

    def spy(*args: Any, **kwargs: Any) -> openai.OpenAI:
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(openai, "OpenAI", spy)
    monkeypatch.setattr(ask_openai, "OpenAI", spy, raising=False)
    return seen


@BOTH
def test_given_adapter_when_built_then_client_has_explicit_timeout_retries_base_url_key(
    fake_openai: FakeOpenAI,
    monkeypatch: pytest.MonkeyPatch,
    cls: type,
    path: str,
    reply: Callable[..., FakeReply],
) -> None:
    # given
    seen = capture_clients(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1/never")
    # when
    build(cls, fake_openai, timeout=7.0)
    # then
    assert len(seen) == 1
    assert seen[0]["timeout"] == 7.0
    assert seen[0]["max_retries"] == 2
    assert seen[0]["base_url"] == fake_openai.base_url
    assert seen[0]["api_key"] == "sk-given"


@BOTH
def test_given_openai_env_when_complete_then_only_given_key_and_explicit_url_used(
    fake_openai: FakeOpenAI,
    monkeypatch: pytest.MonkeyPatch,
    cls: type,
    path: str,
    reply: Callable[..., FakeReply],
) -> None:
    # given
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1/never")
    fake_openai.enqueue(reply("ok"))
    # when
    result = build(cls, fake_openai).complete(prompt())
    # then
    (req,) = fake_openai.requests
    assert req.path == path
    assert req.headers["authorization"] == "Bearer sk-given"
    assert "sk-from-env" not in str(req.headers)
    assert result.text == "ok"


# factory ---------------------------------------------------------------------------------


def test_given_target_api_when_make_provider_then_matching_adapter(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    limits = AiSettings()
    # when
    responses = make_openai_provider(target(fake_openai, "responses"), "k", limits)
    chat = make_openai_provider(target(fake_openai, "chat"), "k", limits)
    # then
    assert isinstance(responses, ResponsesAskProvider)
    assert isinstance(chat, ChatAskProvider)


def test_given_limits_when_make_provider_then_client_uses_configured_timeout(
    fake_openai: FakeOpenAI, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    seen = capture_clients(monkeypatch)
    # when
    make_openai_provider(target(fake_openai), "k", AiSettings(timeout_seconds=17))
    # then
    assert seen[0]["timeout"] == 17
    assert seen[0]["max_retries"] == 2


def test_given_official_chat_when_complete_then_store_false_is_sent(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply("x"))
    provider = build(ChatAskProvider, fake_openai, official=True)
    # when
    provider.complete(prompt())
    # then
    assert fake_openai.requests[0].body["store"] is False


def test_given_non_official_chat_when_complete_then_store_is_not_sent(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    fake_openai.enqueue(chat_reply("x"))
    provider = build(ChatAskProvider, fake_openai, official=False)
    # when
    provider.complete(prompt())
    # then
    assert "store" not in fake_openai.requests[0].body
