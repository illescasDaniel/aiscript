# Technical decisions

## 2026-11-13: QSIV limits and scrub rule (measured on a real GPU)

Input limit is qsiv.constants.MAX_CONTEXT = 65,536 tokens over the rendered request; the service rejects over-limit input as too_large before inference (size check inside the inference lock: qsiv's tokenizer is not thread-safe). Service env scrub: names containing API_KEY, APIKEY, TOKEN, SECRET, PASSWORD, PASSWD, CREDENTIAL, PRIVATE_KEY, ACCESS_KEY, or a whole AUTH segment; caller PYTHONPATH not inherited. qsiv-runtime releases through release.yaml (PyPI trusted publisher, environment pypi).

## 2026-11-13: QSIV lives in a shared package, `qsiv-runtime`

Extracted from agemem into its own package (stdlib-only client, shared resident service, setup/doctor), used by aiscript as an optional extra and later by agemem. aiscript does not install the runtime. Release uses the pypi-publishing flow (trusted publishing). The service is started through a staged PYTHONPATH symlink and agemem's legacy model.lock until agemem migrates.

## 2026-11-12: AI inside scripts, build-time decisions D1-D5 and G5

- D1: the shim goes on PYTHONPATH only for Python scripts that import `aiscript`. D2: `--ask` check order F6, config, F7, input, cap, send. D3: one counter dir of slot files per run (`AISCRIPT_ASK_COUNTER`). D4: the first-use answer of a named command is secret-scanned before it is saved. D5: `--list` shows `+ai`.
- `default_provider` is the AI provider (no `ai.provider` key). Env keys are only used for api.openai.com.
- `store=False` is sent on Responses and on Chat for the official endpoint only (user approved).

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
