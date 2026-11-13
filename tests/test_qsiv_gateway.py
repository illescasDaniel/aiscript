"""Runtime adapter with a fake ``qsiv_runtime`` module (S6-S16, S23, S28 message mapping)."""

from __future__ import annotations

import json

import fake_qsiv_runtime as fake
import pytest

from aiscript.config import ProviderConfig, QSIVSettings
from aiscript.decisions import ReviewInput
from aiscript.qsiv import QSIVCallError, RuntimeQSIVGateway
from aiscript.reviewer import _HAZARD_QUESTIONS, llm_review

REVIEW_INPUT = ReviewInput("ls -la", "bash", ("dep",))


def _score(settings: QSIVSettings | None = None) -> object:
    return RuntimeQSIVGateway(settings).score(
        review_input=REVIEW_INPUT, questions=_HAZARD_QUESTIONS
    )


def test_given_a_runtime_when_scored_then_state_and_questions_are_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    client = fake.install(monkeypatch, [0.02, 0.11, 0.03, 0.01])
    # when
    answers = _score()
    # then (S1 caller side, S31)
    assert answers == [0.02, 0.11, 0.03, 0.01]
    (instance,) = client.instances
    state, questions = instance.calls[0]
    assert json.loads(state) == {"language": "bash", "script": "ls -la", "dependencies": ["dep"]}
    assert questions == [q.instructions for q in _HAZARD_QUESTIONS]
    assert instance.closed is True


def test_given_settings_when_scored_then_they_are_passed_as_explicit_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    client = fake.install(monkeypatch)
    # when
    _score(QSIVSettings(model_directory="/m", python="/p", runtime="reference"))
    # then (S21 aiscript half: explicit config wins; the package resolves the rest)
    assert client.instances[0].arguments == ("/m", "/p", "reference")


def test_given_no_settings_when_scored_then_package_defaults_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    client = fake.install(monkeypatch)
    # when
    _score(None)
    # then (S19: no providers.qsiv section is valid; S21)
    assert client.instances[0].arguments == (None, None, None)


def test_given_the_package_is_missing_when_scored_then_call_error_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    fake.missing(monkeypatch)
    # when
    with pytest.raises(QSIVCallError) as raised:
        _score()
    # then (S23)
    assert raised.value.message == "the qsiv-runtime package is not installed"
    assert raised.value.hint is not None
    assert "qsiv-runtime setup" in raised.value.hint
    assert "uvx qsiv-runtime setup" in raised.value.hint
    assert "aiscript[qsiv]" in raised.value.hint


def test_given_the_package_is_missing_when_reviewed_then_risky_without_traceback_and_static_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from aiscript.reviewer import review

    fake.missing(monkeypatch)
    provider = ProviderConfig("qsiv", None, None, "", kind="qsiv", api="qsiv")
    # when
    result = review("sudo ls\n", "bash", provider)
    # then (S23)
    assert result.risky is True
    assert any(r.startswith("Privilege escalation (line 1)") for r in result.reasons)
    assert any(
        r.startswith("Reviewer unavailable: the qsiv-runtime package is not installed")
        for r in result.reasons
    )


CAUSES: list[tuple[fake.Cause, str, str | None]] = [
    (
        fake.Cause.NO_GPU,
        "QSIV needs Linux x86_64 and an NVIDIA GPU; found: GTX 1080 (6.1)",
        "Run `qsiv-runtime doctor`",
    ),
    (fake.Cause.NOT_INSTALLED, "QSIV is not installed", "Run: qsiv-runtime setup"),
    (
        fake.Cause.STARTUP_FAILED,
        "the QSIV service did not become ready within 120 s",
        "Read the log",
    ),
    (fake.Cause.SERVICE_EXITED, "the QSIV service exited during the review twice", "Retry"),
    (fake.Cause.MODEL_IN_USE, "another QSIV model is already loaded", "Same settings"),
    (
        fake.Cause.INVALID_ANSWER,
        "QSIV returned an invalid answer (expected 4 probabilities in [0, 1], got 3)",
        None,
    ),
    (fake.Cause.UNSAFE_DIRECTORY, "QSIV socket directory /tmp/q is not private", "Fix it"),
    (
        fake.Cause.BAD_CHECKSUM,
        "QSIV runtime is not installed (setup did not complete)",
        "Run: qsiv-runtime setup",
    ),
    (
        fake.Cause.TOO_LARGE,
        "this script is too long for the QSIV model (it is never truncated)",
        None,
    ),
    (fake.Cause.TIMEOUT, "the QSIV service did not answer within 60 s", "Retry"),
]


@pytest.mark.parametrize(("cause", "message", "hint"), CAUSES)
def test_given_a_package_failure_when_reviewed_then_unavailable_with_package_text(
    monkeypatch: pytest.MonkeyPatch, cause: fake.Cause, message: str, hint: str | None
) -> None:
    # given
    fake.install(monkeypatch, fake.QSIVUnavailable(message, fake.QSIVDiagnostic(cause, hint)))
    provider = ProviderConfig("qsiv", None, None, "", kind="qsiv", api="qsiv")
    # when
    result = llm_review("ls", "bash", provider)
    # then (S6-S16, S28: the package owns the text; aiscript only prefixes it)
    expected = f"Reviewer unavailable: {message}" + (f". {hint}" if hint else "")
    assert result.risky is True
    assert result.reasons == [expected]


def test_given_a_message_ending_in_a_period_when_reviewed_then_no_double_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    fake.install(
        monkeypatch,
        fake.QSIVUnavailable("x failed.", fake.QSIVDiagnostic(fake.Cause.NO_GPU, "Do y")),
    )
    # when
    result = llm_review(
        "ls", "bash", ProviderConfig("qsiv", None, None, "", kind="qsiv", api="qsiv")
    )
    # then
    assert result.reasons == ["Reviewer unavailable: x failed. Do y"]


def test_given_an_unexpected_package_error_when_scored_then_generic_call_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    fake.install(monkeypatch, RuntimeError("sk-secret-marker /home/user/trace"))
    # when
    with pytest.raises(QSIVCallError) as raised:
        _score()
    # then
    assert raised.value.message == "QSIV review failed unexpectedly"
    assert "sk-secret-marker" not in raised.value.message + (raised.value.hint or "")


@pytest.mark.parametrize("answers", [[0.1, 0.2, 0.3], [0.1, 1.2, 0.3, 0.4], [0.1, "0.5", 0.3, 0.4]])
def test_given_a_client_returning_a_bad_answer_when_reviewed_then_reviewer_rejects_it(
    monkeypatch: pytest.MonkeyPatch, answers: list[object]
) -> None:
    # given: a client that violates its own contract
    fake.install(monkeypatch, answers)
    # when
    result = llm_review(
        "ls", "bash", ProviderConfig("qsiv", None, None, "", kind="qsiv", api="qsiv")
    )
    # then (S12 aiscript half)
    assert result.risky is True
    assert result.reasons[0].startswith("Reviewer unavailable: QSIV returned an invalid answer")


def test_given_settings_on_the_provider_when_reviewed_then_the_client_gets_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    client = fake.install(monkeypatch, [0.0, 0.0, 0.0, 0.0])
    provider = ProviderConfig(
        "qsiv", None, None, "", kind="qsiv", api="qsiv", qsiv=QSIVSettings(runtime="reference")
    )
    # when
    result = llm_review("ls", "bash", provider)
    # then
    assert result.risky is False and result.reasons == []
    assert client.instances[0].arguments[2] == "reference"


def test_given_no_network_hooks_when_scored_then_nothing_else_is_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given: importing aiscript.qsiv must not import the runtime (lazy, S23, Q9)
    import sys

    monkeypatch.delitem(sys.modules, "qsiv_runtime", raising=False)
    monkeypatch.delitem(sys.modules, "aiscript.qsiv", raising=False)
    # when
    import aiscript.qsiv  # noqa: F401

    # then
    assert "qsiv_runtime" not in sys.modules
