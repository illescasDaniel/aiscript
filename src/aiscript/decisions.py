"""Domain values and gateway contract for Decisions safety review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

HazardName = Literal["privilege_escalation", "filesystem", "networking", "remote_code_execution"]


@dataclass(frozen=True)
class ReviewInput:
    """Script and metadata supplied as untrusted review data."""

    script: str
    language: str
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class HazardQuestion:
    """Fixed hazard definition shared by reviewer adapters."""

    name: HazardName
    category: str
    instructions: str
    true_criteria: str
    false_criteria: str


@dataclass
class DecisionsCallError(Exception):
    """Bounded failure metadata without a provider payload."""

    kind: Literal["client", "connection", "timeout", "http", "unexpected"]
    status_code: int | None = None


class DecisionsGateway(Protocol):
    """Port returning untrusted decoded response data."""

    def classify(
        self,
        *,
        model: str,
        review_input: ReviewInput,
        questions: tuple[HazardQuestion, ...],
    ) -> object: ...
