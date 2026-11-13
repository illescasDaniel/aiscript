"""QSIV reviewer use case: thresholds, re-validation, fail-closed behaviour.

Scenarios S3-S5, S12 (aiscript half), S24, S25 and S31.
"""

from __future__ import annotations

import io
import math

import fake_qsiv_runtime as fake
import pytest
from helpers import TTY

from aiscript.config import ProviderConfig
from aiscript.decisions import HazardQuestion, ReviewInput
from aiscript.qsiv import QSIVCallError, question_text, review_state
from aiscript.reviewer import (
    _HAZARD_QUESTIONS,
    ReviewResult,
    assess_qsiv,
    confirm,
    interpret_qsiv_answers,
    review,
)

REVIEW_INPUT = ReviewInput("ls -la", "bash", ("requests",))


class FakeGateway:
    def __init__(self, answers: object = None, error: Exception | None = None) -> None:
        self.answers = answers
        self.error = error
        self.calls: list[tuple[ReviewInput, tuple[HazardQuestion, ...]]] = []

    def score(self, *, review_input: ReviewInput, questions: tuple[HazardQuestion, ...]) -> object:
        self.calls.append((review_input, questions))
        if self.error is not None:
            raise self.error
        return self.answers


def _assess(answers: object = None, error: Exception | None = None) -> ReviewResult:
    return assess_qsiv(
        REVIEW_INPUT, questions=_HAZARD_QUESTIONS, gateway=FakeGateway(answers, error)
    )


QSIV_PROVIDER = ProviderConfig("qsiv", None, None, "", kind="qsiv", api="qsiv")


def _review(
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    language: str,
    answers: object,
    dependencies: tuple[str, ...] = (),
) -> ReviewResult:
    """review() with a qsiv ProviderConfig and the fake runtime module."""
    fake.install(monkeypatch, answers)
    return review(script, language, QSIV_PROVIDER, list(dependencies))


def test_given_a_filesystem_answer_when_assessed_then_flagged_with_probability() -> None:
    # given / when
    result = _assess([0.01, 0.93, 0.02, 0.01])
    # then (S3)
    assert result.risky is True
    assert result.reasons == ["QSIV review: Filesystem (p=0.93)"]


def test_given_risky_script_when_reviewed_then_static_and_qsiv_reasons_listed(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # given / when
    result = _review(monkeypatch, "rm -rf /var/lib/app", "bash", [0.01, 0.93, 0.02, 0.01])
    confirm("rm -rf /var/lib/app", result, stdin_isatty=False)
    # then (S3)
    assert any(r.startswith("Filesystem (line 1)") for r in result.reasons)
    assert "QSIV review: Filesystem (p=0.93)" in result.reasons
    err = capsys.readouterr().err
    assert "QSIV review: Filesystem (p=0.93)" in err and "Filesystem (line 1)" in err


def test_given_boundary_probabilities_when_interpreted_then_unrounded_value_decides() -> None:
    # given / when
    result = interpret_qsiv_answers([0.4996, 0.5, 0.0, 1.0], questions=_HAZARD_QUESTIONS)
    # then (S4)
    assert result.reasons == [
        "QSIV review: Filesystem (p=0.50)",
        "QSIV review: Remote code execution (p=1.00)",
    ]


def test_given_a_safe_answer_when_script_has_static_finding_then_still_risky(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given / when
    result = _review(monkeypatch, "sudo apt update", "bash", [0.01, 0.02, 0.03, 0.04])
    # then (S5)
    assert result.risky is True
    assert any(r.startswith("Privilege escalation (line 1)") for r in result.reasons)
    assert not any(r.startswith("QSIV") for r in result.reasons)


def test_given_a_safe_answer_when_script_declares_dependencies_then_still_risky(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given / when: review() merges static, dependency and reviewer findings
    result = _review(
        monkeypatch, "import requests\n", "python", [0.01, 0.01, 0.01, 0.01], ("requests",)
    )
    # then (S5)
    assert result.risky is True
    assert any(r.startswith("Dependencies:") for r in result.reasons)
    assert not any(r.startswith("QSIV") for r in result.reasons)


@pytest.mark.parametrize(
    ("answers", "count"),
    [
        ([0.1, 0.2, 0.3], 3),
        ([0.1, 0.2, 0.3, 0.4, 0.5], 5),
        ([0.1, 1.2, 0.3, 0.4], 4),
        ([0.1, -0.1, 0.3, 0.4], 4),
        ([0.1, math.nan, 0.3, 0.4], 4),
        ([0.1, math.inf, 0.3, 0.4], 4),
        ([0.1, "0.5", 0.3, 0.4], 4),
        ([0.1, True, 0.3, 0.4], 4),
        ([0.1, None, 0.3, 0.4], 4),
        ("0.1 0.2 0.3 0.4", 4),
        (None, 0),
        ({"answers": [0.1, 0.2, 0.3, 0.4]}, 4),
    ],
)
def test_given_an_invalid_answer_when_interpreted_then_rejected_as_a_whole(
    answers: object, count: int
) -> None:
    # given / when
    result = interpret_qsiv_answers(answers, questions=_HAZARD_QUESTIONS)
    # then (S12, aiscript half): no probability from that answer is used
    assert result.risky is True
    assert len(result.reasons) == 1
    assert result.reasons[0].startswith("Reviewer unavailable: QSIV returned an invalid answer")
    assert not any("p=" in r for r in result.reasons)


def test_given_ints_zero_and_one_when_interpreted_then_valid() -> None:
    # given / when
    result = interpret_qsiv_answers([0, 1, 0, 0], questions=_HAZARD_QUESTIONS)
    # then
    assert result.reasons == ["QSIV review: Filesystem (p=1.00)"]


def test_given_a_call_error_when_assessed_then_unavailable_with_message_and_hint() -> None:
    # given
    error = QSIVCallError("QSIV is not installed", "Run: qsiv-runtime setup")
    # when
    result = _assess(error=error)
    # then (S6, S7, S23 text shape)
    assert result == ReviewResult(
        True, ["Reviewer unavailable: QSIV is not installed. Run: qsiv-runtime setup"]
    )


def test_given_a_call_error_without_hint_when_assessed_then_message_only() -> None:
    # given / when
    result = _assess(error=QSIVCallError("the QSIV service did not answer within 60 s"))
    # then (S28)
    assert result.reasons == ["Reviewer unavailable: the QSIV service did not answer within 60 s"]


def test_given_an_unexpected_exception_when_assessed_then_fails_closed_without_payload() -> None:
    # given
    secret = "sk-secret-marker"
    # when
    result = _assess(error=RuntimeError(secret + "\nTraceback x" * 50))
    # then
    assert result.risky is True
    assert len(result.reasons) == 1
    assert result.reasons[0].startswith("Reviewer unavailable:")
    assert secret not in result.reasons[0]


def test_given_questions_when_assessed_then_gateway_receives_all_four_in_order() -> None:
    # given
    gateway = FakeGateway([0.0, 0.0, 0.0, 0.0])
    # when
    assess_qsiv(REVIEW_INPUT, questions=_HAZARD_QUESTIONS, gateway=gateway)
    # then (S31)
    assert gateway.calls == [(REVIEW_INPUT, _HAZARD_QUESTIONS)]
    assert [q.category for q in _HAZARD_QUESTIONS] == [
        "Privilege escalation",
        "Filesystem",
        "Networking",
        "Remote code execution",
    ]


def test_given_a_question_when_rendered_then_instructions_verbatim() -> None:
    # given / when / then (S31, Q14)
    for question in _HAZARD_QUESTIONS:
        assert question_text(question) == question.instructions


def test_given_review_input_when_encoded_then_state_has_the_three_fields_only() -> None:
    # given / when
    state = review_state(ReviewInput("echo é", "bash", ("a", "b")))
    # then (S31)
    import json

    assert json.loads(state) == {"language": "bash", "script": "echo é", "dependencies": ["a", "b"]}


def test_given_reviewer_failure_when_not_interactive_then_refused_with_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given
    result = _assess(error=QSIVCallError("QSIV is not installed", "Run: qsiv-runtime setup"))
    # when
    approved = confirm("ls\n", result, stdin_isatty=False)
    # then (S24)
    err = capsys.readouterr().err
    assert approved is False
    assert "Reviewer unavailable: QSIV is not installed. Run: qsiv-runtime setup" in err
    assert err.rstrip().endswith(
        "aiscript: refusing to run a risky script in non-interactive mode."
    )


@pytest.mark.parametrize(("answer", "expected"), [("y", True), ("n", False), ("", False)])
def test_given_reviewer_failure_when_interactive_then_user_decides(
    monkeypatch: pytest.MonkeyPatch, answer: str, expected: bool
) -> None:
    # given
    monkeypatch.setattr("sys.stdin", TTY(answer))
    result = _assess(error=QSIVCallError("QSIV is not installed"))
    # when
    approved = confirm("ls\n", result, stdin_isatty=True)
    # then (S25)
    assert approved is expected


def test_given_reviewer_failure_when_eof_then_declined(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    result = _assess(error=QSIVCallError("QSIV is not installed"))
    # when / then (S25)
    assert confirm("ls\n", result, stdin_isatty=True) is False


def test_given_a_control_character_in_package_text_when_confirmed_then_printed_safely(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given: GPU names from nvidia-smi are untrusted
    result = _assess(error=QSIVCallError("found: Evil\x1b[31mGPU"))
    # when
    confirm("ls\n", result, stdin_isatty=False)
    # then
    assert "\x1b" not in capsys.readouterr().err
