"""Compose provider adapters for generation and runtime ask."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

from aiscript.ask import AskPrompt, AskProvider, ProviderCallError, ProviderFailure, ProviderReply
from aiscript.config import AcpSettings
from aiscript.providers.acp import AcpProvider
from aiscript.providers.anthropic import AnthropicProvider
from aiscript.providers.contracts import CompletionError, CompletionProvider, CompletionRequest
from aiscript.providers.gemini import GeminiProvider

ACP_COMMANDS: dict[str, tuple[str, ...]] = {
    "codex-acp": ("codex-acp",),
    "claude-acp": ("claude-agent-acp",),
    "gemini-acp": ("gemini", "--acp"),
    "opencode-go-acp": ("opencode", "acp"),
    "glm-acp": ("glm-acp-agent",),
}
# Agents whose default model may belong to another plan: refuse to prompt otherwise.
ACP_REQUIRED_MODEL_PREFIX: dict[str, str] = {"opencode-go-acp": "opencode-go/"}


def make_provider(
    kind: str,
    name: str,
    model: str,
    base_url: str | None,
    key: str | None,
    timeout: float,
    acp: AcpSettings,
) -> CompletionProvider:
    """Compose an installed agent or a native provider; never install executables."""
    if kind == "acp":
        command = ACP_COMMANDS.get(name)
        if command is None:
            error = CompletionError("The selected ACP connector is not yet qualified")
            error.kind, error.status_code = "unsupported", None
            raise error
        return AcpProvider(command, acp, Path.cwd(), ACP_REQUIRED_MODEL_PREFIX.get(name))
    if kind == "anthropic":
        return AnthropicProvider(
            base_url or "https://api.anthropic.com/v1", model, key or "", timeout
        )
    if kind == "gemini":
        return GeminiProvider(
            base_url or "https://generativelanguage.googleapis.com/v1beta",
            model,
            key or "",
            timeout,
        )
    error = CompletionError("Unsupported provider")
    error.kind, error.status_code = "unsupported", None
    raise error


class AskBridge:
    """Apply application error mapping to a neutral provider."""

    def __init__(self, provider: CompletionProvider, *, is_acp: bool, timeout: int) -> None:
        self.provider, self.is_acp, self.timeout = provider, is_acp, timeout

    def complete(self, prompt: AskPrompt) -> ProviderReply:
        if self.is_acp:
            print(
                f"aiscript: This request can take up to {self.timeout} seconds.",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                f"aiscript: Timeout {self.timeout} seconds per attempt; retries may take longer.",
                file=sys.stderr,
                flush=True,
            )
        try:
            result = self.provider.complete(
                CompletionRequest(
                    instructions=prompt.system,
                    user_data=prompt.user,
                    schema=prompt.schema,
                    max_output_tokens=prompt.max_output_tokens,
                    require_strict_schema=not self.is_acp and prompt.schema is not None,
                )
            )
        except CompletionError as exc:
            kind = exc.kind
            if kind in ("unsupported", "protocol", "cancelled"):
                kind = "unexpected"
            raise ProviderCallError(
                cast(ProviderFailure, kind), exc.status_code, exc.detail
            ) from None
        return ProviderReply(result.status, result.text)


class NoticeProvider:
    """Announce the existing OpenAI provider without altering its call contract."""

    def __init__(self, provider: AskProvider, timeout: int) -> None:
        self.provider, self.timeout = provider, timeout

    def complete(self, prompt: AskPrompt) -> ProviderReply:
        print(
            f"aiscript: Timeout {self.timeout} seconds per attempt; retries may take longer.",
            file=sys.stderr,
            flush=True,
        )
        return self.provider.complete(prompt)
