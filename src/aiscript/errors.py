"""Exception types."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from aiscript.secret_scan import SecretFinding


class AiscriptError(Exception):
    """Base error; the CLI prints it and exits with ``exit_code``."""

    exit_code: int = 1


class ConfigError(AiscriptError):
    """Invalid or missing configuration."""


class AskError(AiscriptError):
    """Failure of an ``aiscript --ask`` call; ``exit_code`` tells the calling script why."""


class AskUsageError(AskError):
    """Invalid call shape (F6)."""

    exit_code = 2


class AskConfigError(AskError):
    """No usable provider configuration at run time (F1, F7)."""

    exit_code = 3


class AskInputError(AskError):
    """Input is too large or not valid UTF-8 (F8)."""

    exit_code = 4


class AskProviderError(AskError):
    """The provider could not be reached or rejected the call (F9)."""

    exit_code = 5


class AskRateLimitError(AskError):
    """The provider rate-limited the call (F10)."""

    exit_code = 6


class AskRefusalError(AskError):
    """The model refused or returned nothing usable (F11)."""

    exit_code = 7


class AskOutputError(AskError):
    """The reply was incomplete or did not match the schema (F12)."""

    exit_code = 8


class AskCapError(AskError):
    """The per-run call cap was reached (F13)."""

    exit_code = 9


# Shared with the shim, which also maps 127 (aiscript not found on PATH).
ASK_EXIT_CODES: Final[Mapping[str, int]] = {
    "AskUsageError": 2,
    "AskConfigError": 3,
    "AskInputError": 4,
    "AskProviderError": 5,
    "AskRateLimitError": 6,
    "AskRefusalError": 7,
    "AskOutputError": 8,
    "AskCapError": 9,
    "AskNotFoundError": 127,
}


class SecretFoundError(AiscriptError):
    """A credential was found in a prompt or generated code (F2, F3); never holds the value."""

    def __init__(self, stage: Literal["prompt", "code"], findings: Sequence[SecretFinding]) -> None:
        from aiscript.secret_scan import refusal_message  # deferred: secret_scan imports paths

        self.stage = stage
        self.lines = tuple(sorted({f.line for f in findings}))
        super().__init__(refusal_message(stage, findings))
