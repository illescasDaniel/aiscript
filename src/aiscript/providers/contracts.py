"""Provider-neutral request, response, and capability contracts."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

JsonSchema = dict[str, Any]
ProviderFailure = Literal[
    "timeout",
    "connection",
    "auth",
    "forbidden",
    "not_found",
    "bad_request",
    "quota",
    "rate_limit",
    "server",
    "unsupported",
    "protocol",
    "cancelled",
    "unexpected",
]


@dataclass(frozen=True)
class CompletionRequest:
    """Input to an API or agent provider."""

    instructions: str
    user_data: str
    schema: JsonSchema | None = None
    max_output_tokens: int | None = None
    require_strict_schema: bool = False


@dataclass(frozen=True)
class ProviderCapabilities:
    """Guarantees established for a particular exchange."""

    system_role: bool
    no_agent_tools: bool
    strict_schema: bool
    output_token_limit: bool


@dataclass(frozen=True)
class CompletionResult:
    """A normalized provider outcome and its effective guarantees."""

    status: Literal["completed", "refused", "incomplete"]
    text: str
    capabilities: ProviderCapabilities


class CompletionError(Exception):
    """Bounded provider failure metadata without provider payloads."""

    kind: ProviderFailure
    status_code: int | None
    # Optional fixed, actionable wording chosen by the adapter; never provider payload text.
    detail: str | None = None


def enforce_capabilities(request: CompletionRequest, offered: ProviderCapabilities) -> None:
    """Fail before any call when a capability the caller requires cannot be offered."""
    if request.require_strict_schema and request.schema is not None and not offered.strict_schema:
        error = CompletionError("required capability is unsupported")
        error.kind, error.status_code = "unsupported", None
        error.detail = (
            "this provider cannot guarantee strict JSON schema output; "
            "choose a provider that can, or remove the schema"
        )
        raise error


class CompletionProvider(Protocol):
    """Provider-neutral completion boundary."""

    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Produce a normalized completion."""
        ...
