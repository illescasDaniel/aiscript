"""Bounded Agent Client Protocol transport over a local child process."""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from aiscript.providers.contracts import (
    CompletionError,
    CompletionRequest,
    CompletionResult,
    ProviderCapabilities,
    ProviderFailure,
    enforce_capabilities,
)

_OFFERED = ProviderCapabilities(
    system_role=False, no_agent_tools=False, strict_schema=False, output_token_limit=False
)
_FRAME_LIMIT = (
    "limit exceeded: an ACP message was larger than acp.max_frame_kib; "
    "raise it or shorten the input"
)
_RESPONSE_LIMIT = (
    "limit exceeded: the agent's answer was larger than acp.max_response_kib; raise it"
)
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}")
_SIGN_IN = "authentication failed; sign in to the agent and try again"


class AcpLimits(Protocol):
    """Limits supplied by the caller without importing application configuration."""

    @property
    def timeout_seconds(self) -> int: ...

    @property
    def max_frame_kib(self) -> int: ...

    @property
    def max_response_kib(self) -> int: ...


def _failure(kind: ProviderFailure, detail: str | None = None) -> CompletionError:
    error = CompletionError("ACP provider request failed")
    error.kind = kind
    error.status_code = None
    error.detail = detail
    return error


def _stop_group(proc: subprocess.Popen[bytes], sig: int) -> None:
    """Signal the agent's whole process group; an already-dead group is not an error."""
    if sys.platform == "win32":
        with contextlib.suppress(OSError):
            proc.terminate()
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, sig)


def _terminate(signum: int, frame: object) -> None:
    """Unwind through the cleanup that reaps the owned agent; keep the 128+signal status."""
    raise SystemExit(128 + signum)


class AcpProvider:
    """Run one isolated ACP session per completion.

    This is a protocol boundary, not an operating-system sandbox. The selected
    executable retains its own operating-system permissions and configuration.
    """

    def __init__(
        self,
        command: Sequence[str],
        limits: AcpLimits,
        cwd: Path,
        required_model_prefix: str | None = None,
    ) -> None:
        self._command = tuple(command)
        self._limits = limits
        self._cwd = cwd
        self._required_model_prefix = required_model_prefix

    def complete(self, request: CompletionRequest) -> CompletionResult:
        previous = None
        installed = False
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm is not None and threading.current_thread() is threading.main_thread():
            try:
                previous = signal.signal(sigterm, _terminate)
                installed = True
            except (OSError, ValueError):
                pass
        try:
            return self._complete(request)
        finally:
            if installed and sigterm is not None:
                signal.signal(sigterm, previous if previous is not None else signal.SIG_DFL)

    def _check_model(self, session: Mapping[str, Any]) -> None:
        """Fail closed unless the session's model belongs to the required plan."""
        prefix = self._required_model_prefix
        assert prefix is not None
        options = session.get("configOptions")
        current: object = None
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict) and (
                    option.get("id") == "model" or option.get("category") == "model"
                ):
                    current = option.get("currentValue")
                    break
        if isinstance(current, str) and current.startswith(prefix):
            return
        shown = (
            f"the current model is {current}"
            if isinstance(current, str) and _MODEL_ID.fullmatch(current)
            else "the agent did not report its current model"
        )
        plan = prefix.rstrip("/")
        raise _failure(
            "unsupported",
            f"{plan} needs a model from its plan; set "
            f'"model": "{prefix}<model>" in the agent\'s own configuration '
            f"(for OpenCode, see `opencode models {plan}`); {shown}",
        )

    def _complete(self, request: CompletionRequest) -> CompletionResult:
        enforce_capabilities(request, _OFFERED)
        deadline = time.monotonic() + self._limits.timeout_seconds
        group: dict[str, Any]
        if sys.platform == "win32":
            group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            group = {"start_new_session": True}
        try:
            proc = subprocess.Popen(
                self._command,
                cwd=self._cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                **group,
            )
        except FileNotFoundError:
            raise _failure(
                "connection",
                f"the agent executable '{self._command[0]}' was not found; "
                "install it and make sure it is on PATH",
            ) from None
        except (OSError, ValueError):
            raise _failure(
                "connection",
                f"could not start the agent executable '{self._command[0]}'; "
                "check that it is on PATH and runnable",
            ) from None

        incoming: queue.Queue[bytes | None] = queue.Queue(maxsize=8)
        outgoing: queue.Queue[bytes | None] = queue.Queue(maxsize=8)
        stopped = threading.Event()
        frame_limit = self._limits.max_frame_kib * 1024
        response_limit = self._limits.max_response_kib * 1024

        def receive() -> None:
            assert proc.stdout is not None
            try:
                while not stopped.is_set():
                    frame = proc.stdout.readline(frame_limit + 1)
                    while not stopped.is_set():
                        try:
                            incoming.put(frame or None, timeout=0.1)
                            break
                        except queue.Full:
                            continue
                    if not frame or len(frame) > frame_limit:
                        break
            except (OSError, ValueError):
                try:
                    incoming.put_nowait(None)
                except queue.Full:
                    pass

        def send() -> None:
            assert proc.stdin is not None
            try:
                while not stopped.is_set():
                    try:
                        frame = outgoing.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if frame is None:
                        break
                    proc.stdin.write(frame)
                    proc.stdin.flush()
            except (OSError, ValueError):
                pass

        def drain_stderr() -> None:
            assert proc.stderr is not None
            try:
                while proc.stderr.read(8192):
                    pass
            except (OSError, ValueError):
                pass

        workers = [
            threading.Thread(target=receive, daemon=True),
            threading.Thread(target=send, daemon=True),
            threading.Thread(target=drain_stderr, daemon=True),
        ]
        for worker in workers:
            worker.start()

        session_id: str | None = None
        completed = False

        def enqueue(message: Mapping[str, Any]) -> None:
            payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(payload) + 1 > frame_limit:
                raise _failure("protocol", _FRAME_LIMIT)
            try:
                outgoing.put(payload + b"\n", timeout=max(0.0, deadline - time.monotonic()))
            except queue.Full:
                raise _failure("timeout") from None

        def reply_to_reverse(message: dict[str, Any]) -> None:
            method = message.get("method")
            request_id = message.get("id")
            if method == "session/request_permission":
                params = message.get("params")
                options = params.get("options") if isinstance(params, dict) else None
                if not isinstance(options, list):
                    options = []
                reject = next(
                    (
                        item.get("optionId")
                        for item in options or []
                        if isinstance(item, dict)
                        and item.get("kind") in ("reject_once", "reject_always")
                        and isinstance(item.get("optionId"), str)
                    ),
                    None,
                )
                outcome: dict[str, str] = (
                    {"outcome": "selected", "optionId": reject}
                    if reject is not None
                    else {"outcome": "cancelled"}
                )
                enqueue({"jsonrpc": "2.0", "id": request_id, "result": {"outcome": outcome}})
            else:
                enqueue(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": "Method not available"},
                    }
                )

        pieces: list[str] = []
        response_bytes = 0

        def wait_response(expected_id: int) -> dict[str, Any]:
            nonlocal response_bytes
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _failure("timeout")
                try:
                    line = incoming.get(timeout=remaining)
                except queue.Empty:
                    raise _failure("timeout") from None
                if line is not None and len(line) > frame_limit:
                    raise _failure("protocol", _FRAME_LIMIT)
                if line is None or not line.endswith(b"\n"):
                    raise _failure("protocol")
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    raise _failure("protocol") from None
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise _failure("protocol")
                method = message.get("method")
                if isinstance(method, str):
                    if "id" in message:
                        reply_to_reverse(message)
                    elif method == "session/update":
                        params = message.get("params")
                        update = params.get("update") if isinstance(params, dict) else None
                        if (
                            isinstance(update, dict)
                            and update.get("sessionUpdate") == "agent_message_chunk"
                        ):
                            content = update.get("content")
                            if isinstance(content, dict) and content.get("type") == "text":
                                part = content.get("text")
                                if not isinstance(part, str):
                                    raise _failure("protocol")
                                response_bytes += len(part.encode("utf-8"))
                                if response_bytes > response_limit:
                                    raise _failure("protocol", _RESPONSE_LIMIT)
                                pieces.append(part)
                    continue
                if message.get("id") != expected_id:
                    raise _failure("protocol")
                if "error" in message:
                    error = message.get("error")
                    code = error.get("code") if isinstance(error, dict) else None
                    text = str(error.get("message", "")).lower() if isinstance(error, dict) else ""
                    if code == 429 or "rate limit" in text or "quota" in text:
                        raise _failure("rate_limit")
                    if code == -32000:
                        raise _failure("auth", _SIGN_IN)
                    raise _failure("protocol")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise _failure("protocol")
                return result

        try:
            enqueue(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientCapabilities": {
                            "fs": {"readTextFile": False, "writeTextFile": False}
                        },
                        "clientInfo": {"name": "aiscript", "version": "1"},
                    },
                }
            )
            initialized = wait_response(1)
            if initialized.get("protocolVersion") != 1:
                raise _failure("unsupported")
            enqueue(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/new",
                    "params": {"cwd": str(self._cwd.resolve()), "mcpServers": []},
                }
            )
            session = wait_response(2)
            value = session.get("sessionId")
            if not isinstance(value, str) or not value:
                raise _failure("protocol")
            session_id = value
            if self._required_model_prefix is not None:
                self._check_model(session)
            prompt = request.instructions + "\n\n" + request.user_data
            if request.schema is not None:
                prompt += "\n\nReturn only JSON matching this schema: " + json.dumps(
                    request.schema, ensure_ascii=False, separators=(",", ":")
                )
            enqueue(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "session/prompt",
                    "params": {
                        "sessionId": session_id,
                        "prompt": [{"type": "text", "text": prompt}],
                    },
                }
            )
            result = wait_response(3)
            reason = result.get("stopReason")
            if reason not in (
                "end_turn",
                "max_tokens",
                "max_turn_requests",
                "refusal",
                "cancelled",
            ):
                raise _failure("protocol")
            status: Literal["completed", "refused", "incomplete"] = "completed"
            if reason in ("max_tokens", "max_turn_requests"):
                status = "incomplete"
            elif reason == "refusal":
                status = "refused"
            if reason == "cancelled":
                raise _failure("cancelled")
            completed = True
            return CompletionResult(
                status=status,
                text="".join(pieces),
                capabilities=_OFFERED,
            )
        finally:
            if not completed and session_id is not None and proc.poll() is None:
                try:
                    outgoing.put_nowait(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "method": "session/cancel",
                                "params": {"sessionId": session_id},
                            },
                            separators=(",", ":"),
                        ).encode("utf-8")
                        + b"\n"
                    )
                except queue.Full:
                    pass
                # Give the writer a brief opportunity to send cancellation before termination.
                stopped.wait(0.05)
            stopped.set()
            # Stop the agent and anything it spawned: they share its process group.
            _stop_group(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            _stop_group(proc, getattr(signal, "SIGKILL", signal.SIGTERM))
            proc.wait()
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
            for worker in workers:
                worker.join(timeout=0.2)
