"""ACP boundary scenarios S3, S7, S8, S11 over a real local subprocess."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aiscript.providers.contracts import CompletionError, CompletionProvider, CompletionRequest

FIXTURE = Path(__file__).parent / "fixtures" / "fake_multi_provider_acp.py"


def make_provider(tmp_path: Path, *, seconds: int = 3, frame_kib: int = 4) -> CompletionProvider:
    from aiscript.providers.acp import AcpProvider

    limits = SimpleNamespace(timeout_seconds=seconds, max_frame_kib=frame_kib, max_response_kib=4)
    return AcpProvider(command=[sys.executable, str(FIXTURE)], limits=limits, cwd=tmp_path)


@pytest.mark.parametrize("scenario", ["success", "permission"])
def test_given_acp_agent_when_prompt_succeeds_then_result_is_normalized(
    scenario: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_ACP_SCENARIO", scenario)
    provider = make_provider(tmp_path)
    # when
    result = provider.complete(CompletionRequest(instructions="Be concise", user_data="hello"))
    # then
    assert result.status == "completed"
    assert result.text == "fixture answer"
    assert not result.capabilities.no_agent_tools
    assert not result.capabilities.output_token_limit


def test_given_malformed_frame_when_agent_replies_then_no_partial_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_ACP_SCENARIO", "malformed")
    provider = make_provider(tmp_path)
    # when / then
    with pytest.raises(CompletionError):
        provider.complete(CompletionRequest(instructions="", user_data="hello"))


def test_given_oversized_frame_when_agent_replies_then_call_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_ACP_SCENARIO", "large")
    provider = make_provider(tmp_path, frame_kib=1)
    # when / then
    with pytest.raises(CompletionError):
        provider.complete(CompletionRequest(instructions="", user_data="hello"))


def test_given_stalled_agent_when_deadline_passes_then_call_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_ACP_SCENARIO", "hang")
    provider = make_provider(tmp_path, seconds=1)
    # when / then
    with pytest.raises(CompletionError):
        provider.complete(CompletionRequest(instructions="", user_data="hello"))


def _guarded(tmp_path: Path) -> CompletionProvider:
    from aiscript.providers.acp import AcpProvider

    limits = SimpleNamespace(timeout_seconds=3, max_frame_kib=4, max_response_kib=4)
    return AcpProvider(
        [sys.executable, str(FIXTURE)], limits, tmp_path, required_model_prefix="opencode-go/"
    )


def test_given_opencode_default_model_when_guarded_then_no_prompt_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    log = tmp_path / "agent.log"
    monkeypatch.setenv("FAKE_ACP_SCENARIO", "opencode_default")
    monkeypatch.setenv("FAKE_ACP_LOG", str(log))
    # when
    with pytest.raises(CompletionError) as caught:
        _guarded(tmp_path).complete(CompletionRequest(instructions="", user_data="secret"))
    # then
    methods = log.read_text(encoding="utf-8").split()
    assert "session/new" in methods
    assert "session/prompt" not in methods
    assert caught.value.kind == "unsupported"
    assert caught.value.detail is not None
    assert '"model": "opencode-go/<model>"' in caught.value.detail
    assert "opencode models opencode-go" in caught.value.detail
    assert "opencode/iceman-free" in caught.value.detail


def test_given_model_option_absent_when_guarded_then_it_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    log = tmp_path / "agent.log"
    monkeypatch.setenv("FAKE_ACP_SCENARIO", "success")
    monkeypatch.setenv("FAKE_ACP_LOG", str(log))
    # when
    with pytest.raises(CompletionError) as caught:
        _guarded(tmp_path).complete(CompletionRequest(instructions="", user_data="x"))
    # then
    assert "session/prompt" not in log.read_text(encoding="utf-8").split()
    assert caught.value.detail is not None
    assert "opencode-go/<model>" in caught.value.detail


def test_given_opencode_go_model_when_guarded_then_prompt_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("FAKE_ACP_SCENARIO", "opencode_go")
    # when
    result = _guarded(tmp_path).complete(CompletionRequest(instructions="", user_data="x"))
    # then
    assert result.status == "completed"
    assert result.text == "fixture answer"


def test_given_opencode_go_selection_when_composed_then_it_launches_opencode_acp() -> None:
    # given
    from aiscript.config import AcpSettings
    from aiscript.provider_factory import make_provider as compose

    # when
    provider = compose("acp", "opencode-go-acp", "", None, None, 5, AcpSettings())
    # then
    assert provider._command == ("opencode", "acp")  # type: ignore[attr-defined]
    assert provider._required_model_prefix == "opencode-go/"  # type: ignore[attr-defined]
