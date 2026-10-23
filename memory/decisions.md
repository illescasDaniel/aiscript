# Technical decisions

## 2026-10-22: Preserve raw Decisions response types

- **Context:** An installed SDK probe converted `False` and `"0.0"` predicate probabilities into `0.0` during `Decision` parsing.
- **Decision:** Use the SDK's raw-response wrapper and decode the HTTP JSON before policy validation.
- **Rationale:** The approved spec requires rejecting booleans and strings, so parsed model coercion would lose evidence needed for validation. Request and endpoint contracts remain unchanged.

## 2026-10-22: Phase 1 reviewer configuration details approved

- **Context:** Finalize the five design decisions before writing the Decisions spec.
- **Decision:** Resolve the Decisions key from its YAML field, then its provider-specific environment key, without global fallback.
- **Decision:** Accept only the canonical official endpoint (optional trailing slash), validating both URL aliases. Reject generator use and unsupported temperature/reasoning settings.
- **Decision:** Keep existing size behavior without a new cache, billing cap or size limit.
- **Rationale:** User explicitly approved the remaining proposal in chat, retaining separate reviewer credentials and the agreed scope.

## 2026-10-22: OpenAI Decisions reviewer design approved

- **Context:** Add OpenAI Decisions as an alternative to Jev review.
- **Decision:** Default to `gpt-6-luna` and retain configurable model names to support future models without an allowlist change.
- **Decision:** Use official OpenAI endpoints only, with a dedicated `openai_decisions.api_key` field matching the regular provider configuration style.
- **Decision:** Keep the inclusive 0.5 threshold, existing interactive override after reviewer failure, one request, a 30-second SDK timeout and zero retries.
- **Rationale:** User explicitly approved these choices and corrected the model and endpoint proposals in chat. Credential fallback details remain a Phase 1 proposal.

Append-only log, newest first. Record approved significant technical decisions here.
