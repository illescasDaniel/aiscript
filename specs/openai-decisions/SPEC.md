# OpenAI Decisions safety reviewer

## Metadata

- **Feature:** Opt-in OpenAI Decisions review as an alternative to Jev, preserving existing static checks and confirmation behavior.
- **System design:** [DESIGN.md](../../design/openai-decisions/DESIGN.md). **Design approved:** 2026-10-22 (chat).
- **Design decisions approved:** 2026-10-22 (chat), [decision record](DECISIONS.md).
- **Spec approved:** 2026-10-22 (chat).
- **Track:** System. No new screen or CLI flag.

## Design decisions

### Success criteria

Selecting a reviewer with `kind: openai` and `api: decisions` evaluates all four existing hazards: privilege escalation, filesystem, networking and remote code execution. Any probability >= 0.5 marks the corresponding hazard risky. The model cannot clear static findings or third-party dependency warnings. Rejected builds save no new script and preserve any prior cached script.

The default model is `gpt-6-luna`, independent of the generator. Explicit model names pass through without an application allowlist to support future models. Existing providers and defaults remain compatible.

### Failure handling

Invalid configuration or missing credentials raises an actionable `ConfigError` through the existing CLI error path. SDK/client/network/HTTP failures, refusals and invalid answer sets return a risky review with a concise diagnostic. There are no retries or provider fallbacks. A user can explicitly approve a risky script interactively; a risky noninteractive build is refused. Decline, EOF and interrupt at confirmation cancel the build without installing dependencies or saving the new script. A later explicit invocation can try again; no partial review is resumed.

### Performance & resource budget

One synchronous request per model review contains four predicates. Configure a 30-second SDK transport timeout and `max_retries=0`. This is not a hard wall-clock deadline. Add no streaming, concurrency mechanism, review cache, billing cap, script-size limit or truncation. Provider size-limit errors produce a risky review. No additional CPU/memory target or throughput SLA is required for this small synchronous adapter.

### Trust boundary

Generated script text, language/dependency metadata and provider responses are untrusted. Fixed application questions govern the review. Encode metadata and script as request data; never execute script content, fetch its URLs or include extra local files, environment variables or runtime arguments in the request.

Use only `https://api.openai.com/v1`, supplied explicitly to the SDK; `OPENAI_BASE_URL` cannot redirect Decisions. Explicit `base_url` or `endpoint` must equal that canonical URL with an optional trailing slash. Validate both aliases when supplied. Reject all custom, local, insecure, malformed and alternative-path URLs before a request.

Credentials resolve from the provider's YAML `api_key`, then its provider-specific environment key (for `openai_decisions`, `OPENAI_DECISIONS_API_KEY`). Preserve existing blank/placeholder handling. Do not use a global `OPENAI_API_KEY` fallback or a local dummy key. Validate responses completely before interpreting risk. Diagnostics must not expose credentials or raw request/response payloads; existing terminal-output sanitization remains in effect.

### Compatibility & rollout

Add `decisions` as an explicit API value under `kind: openai`, for reviewers only. Omitted API values retain existing inference. Keep Jev as the active starter reviewer and add a commented Decisions example with its own `api_key` and configurable `model`. Keep Jev, Ollaya, text reviewers, static-only review and cached execution behavior. No dependency bump or persisted-data migration is needed. Reject Decisions generation and configured `temperature`/`reasoning_effort`. Roll back by selecting the previous reviewer before downgrading to a version that rejects the new API value.

## Triggers & routing

- **Entry:** An existing command requires a build or rebuild and its resolved `reviewer_provider` selects `api: decisions`. Configuration validation occurs before generation in the existing pipeline.
- **Review:** After generation, run the existing static scan and dependency warnings, call the Decisions adapter once, and combine risk with logical OR and concatenate reasons.
- **Safe result:** Continue the existing install/save flow without a risk prompt.
- **Risky result:** Show existing warnings and script confirmation. Explicit `y`/`yes` permits continuation; otherwise cancel. A noninteractive risky build is refused.
- **Exit:** Existing successful build/run behavior or existing CLI error/rejection path. No new exit code. Up-to-date cached execution does not initiate a review.

## Interfaces & contracts

### Configuration

Merge this entry into the user's existing provider mapping:

```yaml
reviewer_provider: openai_decisions
providers:
  openai_decisions:
    kind: openai
    api: decisions
    model: gpt-6-luna
    api_key: "<your OpenAI API key>"
```

`model` may be omitted for the default or replaced with a future model name. The provider name can be customized using existing naming and provider-specific environment-key rules. No Decisions-specific provider-name inference is introduced. A selected Decisions generator, Jev/Ollaya kind combination, nonofficial endpoint or unsupported generation setting is F1. A missing permitted credential is F2.

### Outbound request

Use the installed OpenAI SDK's `client.decisions.create(model=..., input=..., questions=...)` with explicit `api_key`, `base_url="https://api.openai.com/v1"`, `timeout=30.0` and `max_retries=0` in client configuration. Release client resources after the call.

`input` is a JSON-encoded string containing exactly `language`, `script` and `dependencies` (a list). `questions` contains all four named predicates in this stable order:

| Wire name | Existing category |
|-----------|-------------------|
| `privilege_escalation` | Privilege escalation |
| `filesystem` | Filesystem |
| `networking` | Networking |
| `remote_code_execution` | Remote code execution |

Each question uses `type: predicate`, its name and the complete instructions in the approved design request example. Preserve the existing hazard definitions and add the instruction to treat input as data. Preserve Jev's transmitted instructions and criteria. Do not send Chat/Responses fields or sampling/reasoning settings to Decisions. `POST /v1/decisions` request/response examples in the approved design are normative for consumed fields.

### Response and risk policy

Require an `answers` collection containing exactly one answer for each requested name. Every answer must have `type: predicate` and a finite numeric `probability` in [0, 1], excluding booleans. Match by name regardless of response order. Refusals, unknown/missing/duplicate names, unsupported types, missing/malformed collections and invalid probabilities invalidate the entire model assessment (F4). Ignore unrelated response metadata such as usage.

Compare unrounded probabilities against the inclusive 0.5 threshold. Emit flagged reasons in the stable category order as `OpenAI Decisions review: <category> (p=<two decimals>)`. Valid answers below the threshold produce `ReviewResult(False, [])`. One or more flags produce `ReviewResult(True, reasons)`.

Any call failure (including an unsupported model HTTP error) is F3. F3/F4 return `ReviewResult(True, [diagnostic])`. Diagnostics begin with `Reviewer unavailable:` and identify Decisions plus a bounded failure description without echoing exception bodies, request data, response bodies or secrets. Do not convert any incomplete assessment into safe status.

### Failure mapping

| Design branch | Condition | Result |
|---------------|-----------|--------|
| F1 | Invalid role, kind, settings or endpoint | Actionable configuration error; no reviewer request |
| F2 | No permitted credential | Actionable configuration error; no reviewer request |
| F3 | SDK/client, network, timeout or HTTP failure | Risky assessment, no retry/fallback |
| F4 | Refusal or invalid answer contract | Risky assessment, no partial acceptance |
| F5 | Risky noninteractive build | Existing refusal, no install/save |
| F6 | Interactive decline, EOF or interrupt | Existing cancellation, no install/save |

Classification has no application idempotency key, persisted review state or deduplication. A repeated build can make another billable request. The new API value is additive for current clients; older versions require configuration rollback.

## Data & migration

No database, new persistent entity, backfill or stored-script format change. Existing `ProviderConfig.api` admits `decisions`; the existing `ReviewResult` fields remain unchanged. Retain both `openai>=3.35.1` and `typesafe-sdk`. Update README, relevant configuration/safety documentation and the commented starter example after implementation. Previously cached scripts remain intact and are not re-reviewed by this feature.

## Acceptance criteria

### Scenario: opt-in reviewer and independent default model

**Given** an existing generator with a different model and a selected OpenAI reviewer with explicit `api: decisions` and a permitted key, **When** settings are resolved with no reviewer model, **Then** the reviewer uses `gpt-6-luna` regardless of generator model or `AISCRIPT_MODEL`, and the generator's configuration remains unchanged.

### Scenario: future model name passes through

**Given** a Decisions reviewer with an explicit future model name, **When** settings resolve and a review is requested, **Then** that name is accepted locally and passed unchanged to Decisions without a model allowlist.

### Scenario: invalid role, kind or generation setting (F1)

**Given** each of a selected Decisions generator, Decisions with Jev or Ollaya kind, and Decisions with configured `temperature` or `reasoning_effort`, **When** settings resolve, **Then** an actionable configuration error prevents generation and any Decisions request.

### Scenario: official endpoint is pinned despite SDK environment settings

**Given** a valid Decisions configuration without an endpoint and an `OPENAI_BASE_URL` pointing elsewhere, **When** review constructs its client, **Then** it explicitly uses `https://api.openai.com/v1` and sends no request to the environment URL.

### Scenario: canonical explicit endpoint is accepted

**Given** either or both URL aliases explicitly equal the canonical endpoint, with or without its trailing slash, **When** settings resolve and review runs, **Then** configuration succeeds and the client uses the canonical official URL.

### Scenario: custom or conflicting endpoint aliases are rejected (F1)

**Given** a Decisions configuration containing a local/custom host, HTTP URL, malformed URL, alternative path, query/fragment, user-info URL, or a disallowed value hidden behind a canonical value in the other alias, **When** settings resolve, **Then** configuration fails before any reviewer request and neither alias bypasses validation.

### Scenario: configured reviewer key takes precedence

**Given** distinct YAML, provider-specific environment and global OpenAI keys, **When** the Decisions reviewer resolves its credential and constructs a client, **Then** it uses the YAML key; **Given** no usable YAML key but a provider-specific key, **Then** it uses that provider-specific key and never the global fallback.

### Scenario: absent dedicated credential is rejected (F2)

**Given** no usable YAML or provider-specific key, including existing blank/placeholder cases, and possibly a global `OPENAI_API_KEY`, **When** settings resolve, **Then** a credential configuration error explains the permitted field/environment source and no Decisions request occurs.

### Scenario: complete single request preserves untrusted input as data

**Given** script text containing quotes, newlines, embedded instructions or URL references, language metadata and dependencies, **When** review runs, **Then** one request carries their exact values in the JSON-encoded data string, all four fixed questions are sent in order, and the reviewer executes no script or URL and includes no additional local/environment data.

### Scenario: valid low probabilities produce no model finding

**Given** exactly four valid named predicate answers with probabilities below 0.5, **When** the response is interpreted, **Then** the model result is `risky=False` with no reasons, including when answers are reordered or unrelated metadata is present.

### Scenario: threshold, rounding and stable finding order

**Given** valid probabilities including 0, 0.4999, 0.5 and 1 across the four hazards, **When** the response is interpreted, **Then** only values >= 0.5 are flagged using unrounded comparisons and reasons use stable category order with two-decimal probability formatting.

### Scenario: static and dependency findings survive a safe model answer

**Given** a static finding or a declared third-party dependency and a valid safe Decisions answer set, **When** review results combine, **Then** the overall result remains risky, preserves all existing reasons and requires existing confirmation.

### Scenario: SDK, network and HTTP failures become risky (F3)

**Given** client construction failure, missing SDK capability, connection failure, timeout, or HTTP 400/401/403/404/429/5xx including model rejection, **When** a Decisions review is attempted, **Then** it returns a risky unavailable-review diagnostic without retry, alternate API or provider fallback.

### Scenario: oversized input is not truncated (F3)

**Given** input large enough for the provider to reject, **When** the provider returns a size-limit error, **Then** the model review is risky and no shortened or partial review request is attempted.

### Scenario: refused answer invalidates the assessment (F4)

**Given** a refusal answer, alone or mixed with valid predicates, **When** the response is interpreted, **Then** the entire assessment becomes risky with a Decisions unavailable-review diagnostic.

### Scenario: incomplete or malformed answer set is risky (F4)

**Given** missing/malformed `answers`, an empty collection, a missing expected name, duplicate name, unexpected name, malformed answer or non-predicate type, **When** the response is interpreted, **Then** the entire assessment is risky even if the remaining answers are low risk.

### Scenario: invalid probabilities are rejected (F4)

**Given** an answer with a missing probability, null, string, boolean, NaN, infinity or a number outside [0, 1], **When** the response is interpreted, **Then** the assessment is risky rather than coerced into a safe result.

### Scenario: sensitive payloads do not appear in diagnostics (F3, F4)

**Given** an exception or invalid response containing a credential, script contents, raw request/response text or terminal control characters, **When** review reports failure and confirmation displays its reason, **Then** diagnostics contain only a bounded failure description, expose no credential or raw payload, and retain existing printable-output handling.

### Scenario: risky noninteractive build is refused (F5)

**Given** a static/model/dependency risk or unavailable Decisions reviewer and noninteractive stdin, **When** build reaches confirmation, **Then** it refuses through the existing CLI rejection path without installing dependencies or saving a new script, preserving any previous cached script.

### Scenario: declined interactive confirmation preserves prior build (F6)

**Given** a risky build and interactive stdin, **When** the user declines, enters anything except `y`/`yes`, sends EOF or interrupts confirmation, **Then** the build is cancelled without installing dependencies or saving a new script and any previous cached script remains intact.

### Scenario: explicit interactive override remains available

**Given** a risky result including an unavailable or refused Decisions assessment and interactive stdin, **When** the user sees warnings and the numbered script and explicitly confirms with `y` or `yes`, **Then** the existing install/save flow may proceed.

### Scenario: safe combined review needs no confirmation

**Given** no static finding, no declared dependency and a valid safe Decisions answer set, **When** build reaches confirmation, **Then** the existing flow continues without prompting, including with noninteractive stdin.

### Scenario: request budget and resource cleanup

**Given** a valid Decisions reviewer, **When** a successful or failed review completes, **Then** the client was configured with a 30-second SDK timeout and zero retries, at most one Decisions request was attempted, no review cache or fallback was used, and client resources are closed.

### Scenario: existing providers, defaults and cached execution remain compatible

**Given** an existing Jev, Ollaya, Chat/Responses, omitted-API or static-only configuration, or an up-to-date cached script, **When** the existing flow runs, **Then** its provider behavior and defaults remain unchanged and no Decisions request is introduced; cached execution does not re-review.

### Scenario: documented opt-in and rollback

**Given** the starter configuration and documentation, **When** the user follows the Decisions example, **Then** it shows explicit `api: decisions`, `kind: openai`, its own `api_key` and configurable default model while leaving active Jev defaults unchanged; rollback guidance selects the previous reviewer before downgrade without a data migration or dependency removal.

## Out of scope

- Decisions for script generation, custom endpoints, automatic provider switching or changed defaults.
- Probability calibration, a configurable threshold, a new refusal policy or mandatory blocking of interactive overrides.
- Review caching, cached-script re-review, retry/backoff, streaming, tools, images, new size/cost caps or persistent review records.
- A sandbox, safety guarantee, retention guarantee or live account-access validation.
- Changes to existing build/install/save behavior, new CLI flags, dependency upgrades or removal of Jev/Ollaya support.
