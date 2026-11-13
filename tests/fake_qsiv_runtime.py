"""A fake ``qsiv_runtime`` module for the adapter tests (no GPU, socket or package needed)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from enum import Enum
from types import ModuleType

import pytest


class Cause(str, Enum):
    NO_GPU = "no_gpu"
    NOT_INSTALLED = "not_installed"
    STARTUP_FAILED = "startup_failed"
    SERVICE_EXITED = "service_exited"
    MODEL_IN_USE = "model_in_use"
    INVALID_ANSWER = "invalid_answer"
    UNSAFE_DIRECTORY = "unsafe_directory"
    BAD_CHECKSUM = "bad_checksum"
    TOO_LARGE = "too_large"
    TIMEOUT = "timeout"


class QSIVDiagnostic:
    def __init__(self, cause: Cause, hint: str | None = None) -> None:
        self.cause = cause
        self.hint = hint


class QSIVUnavailable(Exception):
    def __init__(self, message: str, diagnostic: QSIVDiagnostic) -> None:
        super().__init__(message)
        self.message = message
        self.diagnostic = diagnostic


class FakeClient:
    """Records constructor arguments and decide() calls; replies with ``outcome``."""

    outcome: object = [0.0, 0.0, 0.0, 0.0]
    instances: list[FakeClient] = []

    def __init__(
        self,
        model_directory: str | None = None,
        python: str | None = None,
        runtime: str | None = None,
    ) -> None:
        self.arguments = (model_directory, python, runtime)
        self.calls: list[tuple[str, list[str]]] = []
        self.closed = False
        type(self).instances.append(self)

    def decide(self, state: str, questions: Sequence[str]) -> object:
        self.calls.append((state, list(questions)))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def close(self) -> None:
        self.closed = True


def install(monkeypatch: pytest.MonkeyPatch, outcome: object = None) -> type[FakeClient]:
    """Put a fake ``qsiv_runtime`` in ``sys.modules``; ``outcome`` is returned or raised."""
    client: type[FakeClient] = type(
        "FakeClient",
        (FakeClient,),
        {"instances": [], "outcome": [0.0] * 4 if outcome is None else outcome},
    )
    module = ModuleType("qsiv_runtime")
    module.QSIVClient = client  # type: ignore[attr-defined]
    module.QSIVUnavailable = QSIVUnavailable  # type: ignore[attr-defined]
    module.QSIVDiagnostic = QSIVDiagnostic  # type: ignore[attr-defined]
    module.Cause = Cause  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "qsiv_runtime", module)
    return client


def missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import qsiv_runtime`` fail, whatever is installed."""
    monkeypatch.setitem(sys.modules, "qsiv_runtime", None)
