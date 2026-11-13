"""QSIV safety review: the reviewer port and its only adapter (the local qsiv-runtime package)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from aiscript.config import QSIVSettings
from aiscript.decisions import HazardQuestion, ReviewInput

INSTALL_HINT = (
    'Install aiscript with the extra: uv tool install "aiscript[qsiv]", '
    "then run once: uvx qsiv-runtime setup"
)


@dataclass
class QSIVCallError(Exception):
    """Bounded failure: pre-rendered text, no payload.

    Shown as ``Reviewer unavailable: <message>. <hint>``.
    """

    message: str
    hint: str | None = None


class QSIVGateway(Protocol):
    """Port returning untrusted decoded answers."""

    def score(self, *, review_input: ReviewInput, questions: tuple[HazardQuestion, ...]) -> object:
        """One probability per question, in order."""
        ...


def review_state(review_input: ReviewInput) -> str:
    """The state the model sees: the same three fields as the Decisions review."""
    return json.dumps(
        {
            "language": review_input.language,
            "script": review_input.script,
            "dependencies": list(review_input.dependencies),
        }
    )


def question_text(question: HazardQuestion) -> str:
    """The question instructions, verbatim."""
    return question.instructions


class RuntimeQSIVGateway:
    """Adapter over ``qsiv_runtime.QSIVClient``; the package is an optional extra."""

    def __init__(self, settings: QSIVSettings | None) -> None:
        self.settings = settings

    def score(self, *, review_input: ReviewInput, questions: tuple[HazardQuestion, ...]) -> object:
        try:
            import qsiv_runtime
        except ImportError:
            raise QSIVCallError("the qsiv-runtime package is not installed", INSTALL_HINT) from None
        settings = self.settings or QSIVSettings()
        try:
            client = qsiv_runtime.QSIVClient(
                settings.model_directory, settings.python, settings.runtime
            )
            try:
                return client.decide(
                    review_state(review_input), [question_text(q) for q in questions]
                )
            finally:
                client.close()
        except qsiv_runtime.QSIVUnavailable as exc:
            raise QSIVCallError(str(exc.message), exc.diagnostic.hint) from None
        except Exception:
            raise QSIVCallError("QSIV review failed unexpectedly") from None
