# OpenAI Decisions — Phase 1 decision proposal

Design approved in chat on 2026-10-22: [DESIGN.md](../../design/openai-decisions/DESIGN.md).
All five decisions, including the remaining details, were approved in chat on 2026-10-22. The commitments below are the approved basis for `SPEC.md`.

| Decision | Approved spec commitment |
|----------|--------------------------|
| Success criteria | Explicitly selected Decisions review evaluates all four existing hazards, flags probabilities >= 0.5, and never clears static findings or dependency warnings. Default `model` is `gpt-6-luna`; explicit model names pass through for future support. A rejected build saves no new script and preserves any previous cached script. |
| Failure handling | Configuration errors are actionable and stop before the reviewer request. SDK/network/HTTP failures, refusals and invalid answer sets mark the review risky. Existing interactive override remains; risky noninteractive runs and declined confirmations are refused. No provider fallback or retries. |
| Performance and resource budget | One request with four predicates, SDK timeout 30 seconds and zero retries. Preserve existing size behavior; no new review cache, billing cap or hard end-to-end deadline. No truncation or partial assessment on oversized input. |
| Trust boundary | Official OpenAI endpoint only, pinned explicitly in the SDK client; no SDK environment routing. Script, language and dependencies are data; responses are validated before risk interpretation. Diagnostics exclude credentials and raw payloads. `openai_decisions` has its own YAML `api_key`. Credential precedence: that field, then `OPENAI_DECISIONS_API_KEY`, with no global `OPENAI_API_KEY` fallback. Explicit URL configuration may equal `https://api.openai.com/v1` with an optional trailing slash; reject all others, validating both URL aliases if supplied. |
| Compatibility and rollout | Opt-in `api: decisions` under `kind: openai`; existing defaults and reviewer providers remain compatible. No dependency bump, persisted-data migration or re-review of cached scripts. Roll back by selecting the previous reviewer before downgrading. Reject generator use and configured `temperature`/`reasoning_effort` for Decisions. |

## Confirmation

The user approved credential fallback, canonical explicit URL handling, unsupported-setting validation, and absence of new size/cache/billing limits in chat on 2026-10-22. `SPEC.md` requires its own approval before domain types or interfaces are added.
