"""Domain values and ports for executable prompt files."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager as ContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PromptSnapshot:
    """A canonical source and the exact prompt content used for a build."""

    source: Path
    prompt: str
    digest: str


@dataclass(frozen=True)
class ReviewedBuild:
    """A reviewed, immutable entrypoint associated with a prompt digest."""

    prompt_digest: str
    entrypoint: Path


@dataclass(frozen=True)
class BuildDestination:
    """A unique, permanent version directory, invisible until publication."""

    version_dir: Path


class PromptSource(Protocol):
    """Read a prompt file into an immutable snapshot."""

    def read(self, path: Path) -> PromptSnapshot: ...


class BuildLease(Protocol):
    """Exclusive per-source lease for matching and publishing builds."""

    def find(self, snapshot: PromptSnapshot) -> ReviewedBuild | None:
        """Find a complete reviewed build matching this snapshot."""
        ...

    def allocate(self) -> BuildDestination:
        """Allocate a unique destination at its final path."""
        ...

    def publish(
        self, snapshot: PromptSnapshot, destination: BuildDestination, entrypoint: Path
    ) -> ReviewedBuild:
        """Atomically publish the artifact and its identity together."""
        ...

    def discard(self, destination: BuildDestination) -> None:
        """Discard an unpublished destination without affecting published versions."""
        ...


class FileBuildCache(Protocol):
    """Coordinate file builds independently of named-command caches."""

    def acquire(self, source: Path) -> ContextManager[BuildLease]:
        """Acquire an exclusive lease for a canonical source."""
        ...


class PromptFileBuilder(Protocol):
    """Build and review a prompt snapshot at its permanent destination."""

    def build(self, snapshot: PromptSnapshot, destination: BuildDestination) -> Path: ...


class ProgramRunner(Protocol):
    """Run a reviewed build with the supplied arguments."""

    def run(self, build: ReviewedBuild, args: Sequence[str]) -> int: ...


class PromptFileExecution(Protocol):
    """Execute a prompt file and return its program's exit status."""

    def execute(self, path: Path, args: Sequence[str]) -> int: ...
