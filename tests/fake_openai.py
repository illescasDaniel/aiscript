"""Local fake OpenAI-compatible HTTP server for adapter and CLI tests.

Serves ``/v1/chat/completions`` and ``/v1/responses`` on 127.0.0.1 with a scripted response
queue and request recording. 429 and 5xx answers carry ``retry-after-ms: 1`` so retry tests stay
fast.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any

PATHS = ("/v1/chat/completions", "/v1/responses")


@dataclass
class FakeReply:
    """One scripted answer."""

    status: int = 200
    body: Any = None  # JSON-serialised unless it is str/bytes (sent verbatim)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RecordedRequest:
    path: str
    headers: dict[str, str]  # lower-cased names
    body: Any  # decoded JSON, or the raw text when it is not JSON


def chat_reply(text: str, *, finish_reason: str = "stop", refusal: str | None = None) -> FakeReply:
    message: dict[str, Any] = {"role": "assistant", "content": text, "refusal": refusal}
    return FakeReply(
        body={
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 0,
            "model": "fake",
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        }
    )


def responses_reply(
    text: str, *, status: str = "completed", refusal: str | None = None
) -> FakeReply:
    part: dict[str, Any] = (
        {"type": "refusal", "refusal": refusal}
        if refusal is not None
        else {"type": "output_text", "text": text, "annotations": []}
    )
    body: dict[str, Any] = {
        "id": "resp_fake",
        "object": "response",
        "created_at": 0,
        "model": "fake",
        "status": status,
        "output": [
            {
                "id": "msg_fake",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [part],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "none",
        "tools": [],
    }
    if status == "incomplete":
        body["incomplete_details"] = {"reason": "max_output_tokens"}
    return FakeReply(body=body)


def responses_no_message_reply(*, status: str = "incomplete", reasoning: bool = True) -> FakeReply:
    """A Responses reply without any message part (reasoning only, or an empty output)."""
    reply = responses_reply("", status=status)
    reply.body["output"] = (
        [{"id": "rs_fake", "type": "reasoning", "summary": []}] if reasoning else []
    )
    return reply


def error_reply(status: int, message: str = "fake error", code: str | None = None) -> FakeReply:
    return FakeReply(
        status=status,
        body={"error": {"message": message, "type": "fake_error", "code": code}},
    )


class FakeOpenAI:
    """Threaded HTTP server; use as a context manager or call ``start``/``stop``."""

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self._queue: deque[FakeReply] = deque()
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace")
                try:
                    body: Any = json.loads(raw)
                except ValueError:
                    body = raw
                headers = {k.lower(): v for k, v in self.headers.items()}
                fake._respond(self, RecordedRequest(self.path, headers, body))

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def enqueue(self, *replies: FakeReply) -> None:
        """Script the next answers, consumed in order (one per request)."""
        with self._lock:
            self._queue.extend(replies)

    def _respond(self, handler: BaseHTTPRequestHandler, request: RecordedRequest) -> None:
        with self._lock:
            self.requests.append(request)
            reply = self._queue.popleft() if self._queue else None
        if request.path not in PATHS:
            reply = error_reply(404, "unknown path")
        elif reply is None:
            reply = error_reply(418, "fake server: response queue is empty")
        body = reply.body
        payload = (
            body
            if isinstance(body, bytes)
            else body.encode("utf-8")
            if isinstance(body, str)
            else json.dumps(body).encode("utf-8")
        )
        headers = dict(reply.headers)
        if reply.status == 429 or reply.status >= 500:
            headers.setdefault("retry-after-ms", "1")
        handler.send_response(reply.status)
        handler.send_header("content-type", "application/json")
        handler.send_header("content-length", str(len(payload)))
        for name, value in headers.items():
            handler.send_header(name, value)
        handler.end_headers()
        handler.wfile.write(payload)

    def start(self) -> FakeOpenAI:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> FakeOpenAI:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
