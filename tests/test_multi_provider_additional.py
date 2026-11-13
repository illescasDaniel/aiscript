"""Additional ACP subprocess boundary scenarios (S7, S8, S11, S13)."""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2 as httpx
import pytest

from aiscript.onboarding import _indicator, publish_config
from aiscript.providers.acp import AcpProvider
from aiscript.providers.anthropic import AnthropicProvider
from aiscript.providers.contracts import CompletionError, CompletionRequest
from aiscript.providers.gemini import GeminiProvider

FIXTURE = Path(__file__).parent / "fixtures" / "fake_multi_provider_extra.py"


def provider(tmp_path: Path) -> AcpProvider:
    limits = SimpleNamespace(timeout_seconds=1, max_frame_kib=4, max_response_kib=1)
    return AcpProvider([sys.executable, str(FIXTURE)], limits, tmp_path)


@pytest.mark.parametrize("mode", ["eof", "aggregate"])
def test_given_unusable_acp_stream_when_request_runs_then_no_partial_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    # given
    monkeypatch.setenv("FAKE_EXTRA_MODE", mode)
    # when / then
    with pytest.raises(CompletionError) as caught:
        provider(tmp_path).complete(CompletionRequest("instructions", "input"))
    assert caught.value.kind == "protocol"


def test_given_acp_file_read_request_when_denied_then_agent_can_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_EXTRA_MODE", "callback")
    # when
    result = provider(tmp_path).complete(CompletionRequest("instructions", "input"))
    # then
    assert result.text == "ok"
    assert result.status == "completed"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process existence check")
def test_given_stalled_acp_agent_when_deadline_passes_then_owned_process_is_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    pid_path = tmp_path / "agent.pid"
    monkeypatch.setenv("FAKE_EXTRA_MODE", "hang")
    monkeypatch.setenv("FAKE_EXTRA_PID_PATH", str(pid_path))
    # when
    started = time.monotonic()
    with pytest.raises(CompletionError) as caught:
        provider(tmp_path).complete(CompletionRequest("instructions", "input"))
    # then
    assert caught.value.kind == "timeout"
    assert time.monotonic() - started < 4
    pid = int(pid_path.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_given_two_initializers_when_publishing_then_winner_is_not_overwritten(
    tmp_path: Path,
) -> None:
    # given
    target = tmp_path / "config.yaml"
    candidates = ("default_provider: anthropic\n", "default_provider: gemini\n")
    # when
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda value: publish_config(target, value), candidates))
    # then
    assert sorted(results) == [False, True]
    assert target.read_text(encoding="utf-8") == candidates[results.index(True)]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["config.yaml"]


def test_given_unavailable_local_detection_when_menu_checks_then_status_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    def unavailable(command: str) -> None:
        raise OSError("lookup unavailable")

    monkeypatch.setattr("aiscript.onboarding.shutil.which", unavailable)
    # when / then
    assert _indicator("codex-acp", None) == "unknown"


@pytest.mark.parametrize("vendor", ["anthropic", "gemini"])
def test_given_native_schema_request_when_completed_then_schema_and_limit_are_sent(
    vendor: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    requests: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        requests.append({"url": url, **kwargs})
        payload: dict[str, Any]
        if vendor == "anthropic":
            payload = {
                "content": [{"type": "text", "text": '{"ok":true}'}],
                "stop_reason": "end_turn",
            }
        else:
            payload = {
                "candidates": [
                    {"content": {"parts": [{"text": '{"ok":true}'}]}, "finishReason": "STOP"}
                ]
            }
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx, "post", fake_post)
    schema: dict[str, Any] = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    request = CompletionRequest("instructions", "data", schema, 37, True)
    selected = (
        AnthropicProvider("https://example.test/v1", "model", "secret", 5)
        if vendor == "anthropic"
        else GeminiProvider("https://example.test/v1", "model", "secret", 5)
    )
    # when
    answer = selected.complete(request)
    # then
    assert answer.text == '{"ok":true}'
    assert answer.capabilities.strict_schema
    body = requests[0]["json"]
    if vendor == "anthropic":
        assert body["max_tokens"] == 37
        assert body["output_config"]["format"]["schema"] == schema
    else:
        assert body["generationConfig"]["maxOutputTokens"] == 37
        assert body["generationConfig"]["responseJsonSchema"] == schema


def test_given_native_api_rejection_when_request_fails_then_secret_is_not_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(401, text="private-token and private-prompt")

    monkeypatch.setattr(httpx, "post", fake_post)
    client = AnthropicProvider("https://example.test/v1", "model", "private-token", 5)
    # when / then
    with pytest.raises(CompletionError) as caught:
        client.complete(CompletionRequest("private-prompt", "private-data"))
    assert caught.value.kind == "auth"
    assert "private" not in str(caught.value)


def test_given_acp_rate_limit_error_when_request_runs_then_category_is_rate_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_EXTRA_MODE", "ratelimit")
    # when / then
    with pytest.raises(CompletionError) as caught:
        provider(tmp_path).complete(CompletionRequest("instructions", "input"))
    assert caught.value.kind == "rate_limit"


def test_given_menu_when_listed_then_detection_matches_runtime_executables() -> None:
    # given
    from aiscript.onboarding import _PROVIDERS
    from aiscript.provider_factory import ACP_COMMANDS

    # when
    detected = {name: command for name, command, _ in _PROVIDERS if name in ACP_COMMANDS}
    # then
    assert detected == {name: command[0] for name, command in ACP_COMMANDS.items()}


def test_given_opencode_go_when_menu_checks_then_it_detects_the_opencode_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from aiscript.onboarding import _PROVIDERS

    command = {name: command for name, command, _ in _PROVIDERS}["opencode-go-acp"]
    monkeypatch.setattr(
        "shutil.which", lambda name: "/bin/opencode" if name == "opencode" else None
    )
    # when / then
    assert command == "opencode"
    assert _indicator(command, None) == "executable found"


def _gone(pid: int) -> bool:
    """True once the process no longer exists (a zombie awaiting reaping counts as alive)."""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        status = Path(f"/proc/{pid}/status")
        if status.exists() and "\nState:\tZ" in status.read_text(encoding="utf-8"):
            return True
        time.sleep(0.05)
    return False


_SIGTERM_CHILD = """
import sys
from pathlib import Path
from types import SimpleNamespace
from aiscript.providers.acp import AcpProvider
from aiscript.providers.contracts import CompletionRequest

limits = SimpleNamespace(timeout_seconds=20, max_frame_kib=4, max_response_kib=1)
provider = AcpProvider([sys.executable, sys.argv[1]], limits, Path.cwd())
provider.complete(CompletionRequest("instructions", "input"))
"""


@pytest.mark.skipif(os.name == "nt", reason="POSIX signals")
def test_given_sigterm_during_acp_call_when_handled_then_agent_is_reaped(
    tmp_path: Path,
) -> None:
    # given
    import signal
    import subprocess

    pid_path = tmp_path / "agent.pid"
    env = {**os.environ, "FAKE_EXTRA_MODE": "hang", "FAKE_EXTRA_PID_PATH": str(pid_path)}
    child = subprocess.Popen(
        [sys.executable, "-c", _SIGTERM_CHILD, str(FIXTURE)], env=env, cwd=tmp_path
    )
    try:
        deadline = time.monotonic() + 10
        while not (pid_path.exists() and pid_path.read_text(encoding="utf-8")):
            assert time.monotonic() < deadline and child.poll() is None
            time.sleep(0.05)
        time.sleep(0.5)  # let the call reach the blocking prompt
        # when
        child.send_signal(signal.SIGTERM)
        code = child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    # then
    assert code == 143
    assert _gone(int(pid_path.read_text(encoding="utf-8")))


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_given_agent_spawned_grandchild_when_request_ends_then_no_descendant_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    child_path = tmp_path / "grandchild.pid"
    monkeypatch.setenv("FAKE_EXTRA_MODE", "grandchild")
    monkeypatch.setenv("FAKE_EXTRA_CHILD_PID_PATH", str(child_path))
    # when
    result = provider(tmp_path).complete(CompletionRequest("instructions", "input"))
    # then
    assert result.text == "ok"
    assert _gone(int(child_path.read_text(encoding="utf-8")))


def test_given_acp_auth_error_when_request_runs_then_user_is_told_to_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_EXTRA_MODE", "auth")
    # when / then
    with pytest.raises(CompletionError) as caught:
        provider(tmp_path).complete(CompletionRequest("instructions", "input"))
    assert caught.value.kind == "auth"
    assert caught.value.detail is not None
    assert "sign in to the agent" in caught.value.detail
    assert "API key" not in caught.value.detail


def test_given_response_cap_exceeded_when_request_runs_then_message_names_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_EXTRA_MODE", "aggregate")
    # when / then
    with pytest.raises(CompletionError) as caught:
        provider(tmp_path).complete(CompletionRequest("instructions", "input"))
    assert caught.value.detail is not None
    assert "limit exceeded" in caught.value.detail
    assert "max_response_kib" in caught.value.detail
    assert "xxx" not in caught.value.detail


def test_given_frame_cap_exceeded_when_request_runs_then_message_names_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_EXTRA_MODE", "hang")
    limits = SimpleNamespace(timeout_seconds=2, max_frame_kib=1, max_response_kib=1)
    agent = AcpProvider([sys.executable, str(FIXTURE)], limits, tmp_path)
    # when / then
    with pytest.raises(CompletionError) as caught:
        agent.complete(CompletionRequest("instructions", "x" * 5000))
    assert caught.value.detail is not None
    assert "limit exceeded" in caught.value.detail
    assert "max_frame_kib" in caught.value.detail


def test_given_missing_executable_when_request_runs_then_message_names_it_and_path(
    tmp_path: Path,
) -> None:
    # given
    limits = SimpleNamespace(timeout_seconds=2, max_frame_kib=4, max_response_kib=1)
    agent = AcpProvider(["no-such-agent-executable"], limits, tmp_path)
    # when / then
    with pytest.raises(CompletionError) as caught:
        agent.complete(CompletionRequest("instructions", "private input"))
    assert caught.value.kind == "connection"
    assert caught.value.detail is not None
    assert "no-such-agent-executable" in caught.value.detail
    assert "PATH" in caught.value.detail
    assert "private input" not in caught.value.detail + str(caught.value)


def test_given_acp_agent_when_strict_schema_is_required_then_request_is_refused_before_launch(
    tmp_path: Path,
) -> None:
    # given
    limits = SimpleNamespace(timeout_seconds=2, max_frame_kib=4, max_response_kib=1)
    agent = AcpProvider(["no-such-agent-executable"], limits, tmp_path)
    request = CompletionRequest("i", "d", {"type": "object"}, require_strict_schema=True)
    # when / then
    with pytest.raises(CompletionError) as caught:
        agent.complete(request)
    assert caught.value.kind == "unsupported"
    assert caught.value.detail is not None
    assert "strict JSON schema" in caught.value.detail
