# Multi-provider and ACP support

## Metadata

- **Status:** Approved 2026-11-12; user said “spec approved”.
- **Approved system design:** [DESIGN.md](../../design/multi-provider/DESIGN.md) and [visual review](../../multi-provider.html), approved in chat on 2026-11-12. The Spec tab is the review interface; this file is the project-required Markdown contract. Any discrepancy must be reconciled before approval.
- **Scope:** Native Anthropic and Gemini APIs, and five individually qualified ACP selections for script generation and `aiscript.ask` / `aiscript --ask`.

## Design decisions

### Success criteria

A neutral provider subpackage supports the existing generation and ask entry points using common request, result and error shapes while reporting capability and effective-guarantee differences. Native Anthropic and Gemini and qualified Codex, Claude, Gemini, OpenCode Go and GLM ACP connectors can be selected. A built-in ACP selection needs no `providers` entry. Script generation retains the existing scanning, review, confirmation and save sequence; ask returns plain text or locally validated structured data. Existing OpenAI-compatible configurations and behavior remain supported. No claim of support is made for a connector until it passes its qualification checks below.

### Failure handling

F1–F7 produce actionable, bounded diagnostics without credential values, raw prompts, protocol payloads or stderr. For onboarding F8 invalid input is re-prompted and cancellation leaves no configuration; F9 write failure is reported and a creation race preserves and loads the winner; F10 detection failure is labeled unknown without blocking selection. Do not silently switch provider or accept partial output. Map ask failures to the existing error surfaces and exit codes: usage 2, config 3, input 4, provider 5, rate limit 6, refusal 7, invalid, empty or incomplete output 8, and call limit 9. Deny ACP permission requests and client filesystem or terminal callbacks; if a valid response still arrives it may be used. Never automatically replay an ACP prompt; on failure or cancellation cancel when available, terminate and reap owned processes. A later explicit invocation is a new attempt and may incur charges or side effects.

### Performance and resource budget

These approved values are not measurements. Both ACP generation and ask use `acp.timeout_seconds` as a total per-request deadline (default 100 seconds; integer range 1–600). `acp.max_frame_kib` and `acp.max_response_kib` default to 1024 KiB (1 MiB) each, with integer ranges 1–16384 KiB; they limit each individual ACP protocol frame and aggregate returned answer text respectively. Invalid types, including booleans, and out-of-range values produce a configuration error before any provider call or subprocess launch. Exceeding either size limit or the deadline aborts the request and discards partial output. One owned agent process per request; no automatic ACP retries. Existing ask input and call limits remain: by default input must be strictly less than 128 KiB, and the runner permits one call; configured values keep existing validation. Existing API timeout and retry semantics remain unchanged (for ask, `ai.timeout_seconds` defaults to 60 seconds per attempt and up to two retries). Time and byte limits do not cap provider tokens, charges, network access or agent-internal work.

### Trust boundary

The application owns configuration and role selection, input validation, credential resolution, secret scanning, schema validation, call counters, review/confirmation and output presentation. The subpackage translates explicit requests to SDKs or agents and returns neutral results/errors plus effective capabilities; it does not import application policy modules or the generated-script shim. Provider messages, returned data and agent diagnostics are untrusted. Expand known-secret collection for implicit supported native credential environment variables and preserve redaction. API credentials are sent only to their permitted provider endpoint under the existing endpoint/key trust policy; reject unsupported mappings rather than redirecting credentials silently.

For ACP **only**, accepted Q7 A differs from the existing API ask contract: instructions may not be a system-role message; local JSON/schema validation replaces a guarantee of provider-side strict decoding; permission requests are denied without promising no internal tools; and byte/time limits do not promise a model-side token limit. A local agent can independently use its OS permissions, environment, configuration, hooks, network and tools: neither an empty working directory nor denied callbacks is a sandbox. Disclose these limits and possible billing/side effects in user documentation. Keep the existing OpenAI API contract unchanged. Native API ask must request the existing supported strict-schema behavior and token bound, or fail with an actionable unsupported-capability error instead of silently relaxing them.

### Compatibility and rollout

Generation preserves its existing `AISCRIPT_PROVIDER` precedence over YAML; ask resolves YAML `default_provider` only and ignores aiscript routing environment overrides. Agent-owned settings may independently select a model or backend. Explicit configured provider definitions take precedence on name collisions; unrelated entries never hide built-in selections. Existing OpenAI defaults, reviewer behavior, cached scripts, Python shim compatibility, and per-run counters remain intact. Do not rewrite existing config files. Ship each ACP selection as supported only after connector-specific executable, authentication, model/plan routing, successful output, cancellation and OS compatibility are verified. Do not install, update or authenticate agents automatically. No stored-data migration. The shared subpackage remains in the current distribution; separate versioning, publication and stable public API are future decisions, not promised by this feature.

## Interfaces and contracts

### Selection and configuration

Support built-in `codex-acp`, `claude-acp`, `gemini-acp`, `opencode-go-acp`, and `glm-acp` without a provider definition, plus native `anthropic` and `gemini` and existing OpenAI-compatible definitions. The exact maintained command, supported versions, plan routing and authentication for each connector must be established and documented before its support claim. OpenCode Go is a plan/model selection with OpenCode; GLM may require a distinct agent or a verified configured route. ACP does not itself grant subscription eligibility. Provider account terms and actual access remain external and unverified until checked.

`aiscript --init` starter YAML lists all supported native and ACP choices after the OpenAI example as commented examples, with representative native model examples and setup hints. Examples must parse, and activating one must follow documented selection instructions. ACP built-ins continue to work without an entry and use each agent's configured default model; an aiscript ACP model override is deferred. Existing named provider entries are not silently replaced. Existing user config contents are never rewritten; preserve the existing `--init` permission-handling behavior.

Starter configuration documents the three `acp` limits above, including their defaults and ranges. Absent values use those defaults; valid configured values replace them for both ACP entry points. ACP model selection remains in the agent's own configuration as recommended for Q12.

**Approved decisions:** Q11 uses the configurable ACP deadline and size limits above; Q12 uses the agent's own model configuration; Q13 emits the wait notice only when a provider request starts, not for preflight failures. These decisions were approved in chat with “spec approved” on 2026-11-12.

### First-use provider selection

When neither `config.yaml` nor legacy `secrets.yaml` exists for the current configuration root, interactive `--init` and the first interactive operation requiring provider-backed generation display a list of all supported selections. Existing or legacy configuration skips onboarding. `--ask`, help, version, list and cached execution never prompt. Non-interactive invocations retain current absent-config behavior; non-interactive `--init` creates the OpenAI template as before. Detection only checks executable presence on `PATH` and presence of relevant API-key environment variables. It reads or prints no key values, launches no agents, and does no network, login or installation work. Indicators identify local detection, not authentication, entitlement or readiness; unavailable or unknown choices remain selectable, and incomplete detection is shown as unknown. Show setup guidance for the selection.

On valid selection, write complete private starter configuration to a temporary file and atomically publish without clobbering a concurrently created destination. If another process wins, preserve and load its file; cancellation or publication failure leaves no partial destination. The exact cross-platform mechanism is an architecture decision. If `AISCRIPT_PROVIDER` is set, disclose that it continues to select the provider for the current generation; the saved YAML selection controls ask and future defaults when the override is absent. Invalid selections reprompt, while cancellation or EOF exits onboarding without publishing a configuration.

### Exchange and output

The internal `aiscript.providers` boundary accepts explicit instruction, user data, optional schema and requested limits; it returns completion, refusal or incomplete outcomes, text where applicable, sanitized error categories, and effective capabilities or guarantees without exposing SDK-specific objects. Exact types and module layout await the architecture gate. Instructions and untrusted data remain distinguishable in the request representation; ACP cannot promise an actual system-role message. For schema requests validate the full result locally against the existing supported schema subset; invalid JSON, schema mismatch, incomplete responses and unsupported required capabilities fail without partial success. Preserve API-provider strict schema requirements and current output-token controls. Do not advertise common format as identical semantics.

After input validation and a successful call-cap claim, immediately before a provider invocation, emit exactly one status line to stderr for both direct `--ask` and Python `aiscript.ask()` callers. For ACP the line reports the configured total deadline, e.g. “This request can take up to 100 seconds.” A configured value of 120 must produce 120 instead; never hard-code the displayed number. For APIs report the configured timeout **per attempt** and that retries may take longer, rather than claiming it bounds total elapsed time. The Python shim must make the trusted status visible while the request is running; merely capturing child stderr until completion does not satisfy this contract. Do not forward raw child or agent stderr, prompts, inputs or credentials; preserve existing sanitized error handling. The notice never enters stdout or the returned answer. Validation failures and exhausted call caps produce no provider-call notice. Tests cover direct and shim calls, live timing, failures, no duplicates, concurrent pipe draining and non-disclosure.

### Qualification and verification

Test deterministic provider-neutral behavior and real I/O boundaries with controlled HTTP endpoints and ACP subprocess fixtures, including reverse requests, invalid frames and cleanup. A fake alone does not qualify a real connector. Before calling an agent supported, record its maintained release, executable, supported platforms, login and route, output and cancellation evidence from a real permitted installation; tests requiring paid accounts or secrets are not run without authorization and must be marked not run. Never silently redirect OpenCode Go or GLM to a different plan. Separate packaging is not part of this release.

## Acceptance criteria

### Scenario: S1 Native API generation
**Given** Anthropic or Gemini is selected and configured with a valid credential and model, **When** a user requests a script, **Then** the chosen API receives the request and the returned script goes through existing scanning, review and confirmation before save.

### Scenario: S2 Native API ask
**Given** a supported native API and a valid text or supported-schema ask, **When** a generated script calls ask, **Then** it returns text or locally validated JSON while requesting the existing provider-side strict-schema and output-token controls when applicable.

### Scenario: S3 ACP generation
**Given** a qualified installed and authenticated ACP agent selected by built-in name without a provider entry, **When** generation succeeds, **Then** its text passes the existing script review and save pipeline.

### Scenario: S4 ACP ask
**Given** a qualified ACP agent selected by built-in name, **When** a script requests text or a supported schema, **Then** aiscript returns the final text or locally validated JSON and applies the documented ACP-specific Q7 A limitations.

### Scenario: S5 Selection precedence (F1)
**Given** unrelated provider entries and a built-in selection, **When** resolution runs, **Then** the built-in resolves; an explicit same-name entry wins, and an unknown or invalid name fails before a provider call.

### Scenario: S6 Authentication (F2)
**Given** missing, expired or rejected API or agent credentials, **When** the provider is invoked, **Then** it returns sanitized setup guidance without exposing credentials, with no fallback.

### Scenario: S7 Connector unavailable (F3)
**Given** a missing executable, incompatible handshake, malformed frame, unexpected exit or unreachable API, **When** a request runs, **Then** it fails with an actionable bounded error, discards partial output and reaps any owned process.

### Scenario: S8 Permission requests (F4)
**Given** an ACP agent requests client permission or a filesystem or terminal callback, **When** aiscript handles the request, **Then** it denies it without an interactive grant and accepts a response only if the agent still completes successfully.

### Scenario: S9 Invalid or unsupported output (F5)
**Given** malformed JSON, schema mismatch, incomplete output or an unsupported required API capability, **When** output is interpreted, **Then** aiscript returns an output or capability error, emits no partial answer and does not retry the prompt.

### Scenario: S10 Refusal and empty answer (F5)
**Given** a provider refuses or returns no usable answer, **When** ask interprets the response, **Then** a refusal returns the existing refusal category (exit 7) and an empty or unusable answer returns the existing invalid-output category (exit 8), with no successful output.

### Scenario: S11 Deadline and size boundaries (F6)
**Given** an ACP request exceeds its configured total deadline, an individual frame exceeds its configured frame cap, or aggregate answer text exceeds its configured response cap, **When** the limit is reached, **Then** aiscript stops, discards partial output, returns an error and reaps the process.

### Scenario: S12 Rate or quota limit (F6)
**Given** the selected provider reports a rate or quota limit, **When** the call fails, **Then** aiscript reports the appropriate existing failure category, does not switch provider and does not replay an ACP request.

### Scenario: S13 Cancellation (F7)
**Given** a running ACP request, **When** the user cancels, **Then** aiscript requests cancellation where available, terminates and reaps its owned process, and does not return partial success; already completed external actions may persist.

### Scenario: S14 Input and call limits
**Given** ask input at or above its configured size limit, invalid UTF-8, invalid schema or an exhausted per-run call cap, **When** ask is invoked, **Then** it returns the existing validation or cap error without sending a provider prompt.

### Scenario: S15 Distinct routing
**Given** YAML selects one provider and an aiscript routing environment override selects another, **When** generation and ask resolve their providers, **Then** generation preserves its existing environment precedence and ask uses YAML only; agent-owned configuration is separately documented.

### Scenario: S16 Secret handling
**Given** a supported Anthropic or Gemini credential exists only in a recognized environment variable, **When** secret scanning and failure diagnostics execute, **Then** known credential values are detected and never echoed in diagnostics or raw provider payloads.

### Scenario: S17 Starter configuration
**Given** a new initialization, **When** starter YAML is generated, **Then** it lists the native and five ACP choices after OpenAI as valid commented examples, includes representative native models and ACP agent-default guidance, and leaves ACP built-ins usable without entries; existing file contents are not rewritten.

### Scenario: S18 Qualification and shared boundary
**Given** a candidate connector and the shared provider boundary, **When** release support is claimed, **Then** real connector qualification evidence exists for its documented platform, authentication, routing, output and cancellation, and neutral request/result/error shapes expose effective capability differences without application or shim imports.

### Scenario: S19 First-use provider selection
**Given** an interactive initialization or provider-backed generation with neither current nor legacy config, **When** the user selects a listed provider, **Then** the complete private starter config is published with that YAML default and the requested operation continues, subject to its normal prerequisites.

### Scenario: S20 Existing, legacy and unattended invocations
**Given** an existing or legacy config, a non-interactive invocation, `--ask`, an informational command or cached execution, **When** aiscript runs, **Then** it displays no onboarding menu, preserves existing config contents and follows the existing routing and non-interactive behavior.

### Scenario: S21 Invalid input and cancellation (F8)
**Given** the first-use menu, **When** a user enters an invalid selection, **Then** the menu reprompts; **When** the user cancels or input reaches EOF, **Then** onboarding exits without publishing a config or a partial destination file.

### Scenario: S22 Atomic publication and race (F9)
**Given** a complete private temporary config, **When** publication fails, **Then** the error is reported and no partial destination remains; **When** another process creates the destination first, **Then** its contents are preserved and loaded rather than overwritten.

### Scenario: S23 Advisory detection (F10)
**Given** an agent or API key is not detected or local detection is unavailable, **When** the first-use menu is displayed, **Then** its status is shown as not detected or unknown without asserting authentication, and the provider remains selectable; no network call, agent launch, login, install or secret value disclosure occurs.

### Scenario: S24 Environment override at onboarding
**Given** first-use selection saves one provider and `AISCRIPT_PROVIDER` names another, **When** generation proceeds, **Then** the current generation uses the environment override with disclosure, while ask and later defaults without the override use the saved YAML choice.

### Scenario: S25 Starter example activation
**Given** a newly created starter config containing commented provider examples after OpenAI, **When** a user follows the documented instructions for a native API or built-in ACP selection, **Then** the YAML remains valid, the chosen default resolves, and an ACP selection needs no uncommented provider entry or aiscript model override.

### Scenario: S26 Configurable ACP limits
**Given** ACP limits omitted from config, **When** generation or ask resolves settings, **Then** the total deadline is 100 seconds and each size cap is 1024 KiB; **Given** valid configured alternatives, **When** either entry point runs, **Then** it applies those values, while invalid, boolean or out-of-range settings fail before launching or calling a provider.

### Scenario: S27 Live ask timeout notice
**Given** a valid ask and a successful call-cap claim, **When** direct `--ask` or Python `aiscript.ask()` starts an ACP provider call, **Then** exactly one status line reaches stderr before completion and displays the configured total deadline, including 120 when configured to 120; stdout and the returned answer contain no notice.

### Scenario: S28 API timeout notice and safe failure
**Given** a valid API ask, **When** the provider call starts, **Then** exactly one timely stderr notice states its configured per-attempt timeout and that retries may take longer; **Given** a validation failure or exhausted call cap, **When** no provider call starts, **Then** no provider-call notice is emitted, and child/agent stderr, credentials and input data are not leaked.

## Traceability

| Design path | Scenario IDs | Planned verification | Actual tests and code |
|---|---|---|---|
| Native and ACP success | S1–S4 | Controlled API and real qualified ACP calls | Pending |
| F1 configuration | S5, S15 | Resolution and environment matrix | Pending |
| F2 authentication | S6, S16 | Adapter failure and redaction tests | Pending |
| F3 unavailable | S7 | HTTP and subprocess fixtures | Pending |
| F4 permission | S8 | ACP reverse-request fixture | Pending |
| F5 output | S9–S10 | Schema, refusal and capability tests | Pending |
| F6 limits | S11–S12, S14, S26 | Configured deadline, frame, output and call-boundary tests | Pending |
| F7 cancellation | S13 | Subprocess interruption and cleanup | Pending |
| First-use success and bypass | S19–S20, S24 | Interactive and non-interactive isolated config roots | Pending |
| F8 invalid input or cancellation | S21 | Menu input and EOF/cancel tests | Pending |
| F9 config write failure or race | S22 | Atomic publication, failure and concurrent initialization tests | Pending |
| F10 unavailable detection | S23 | PATH and key-presence fixtures with unavailable detection | Pending |
| Setup and package | S17–S18, S25 | Starter YAML, dependency boundary and connector evidence | Pending |
| Ask notices and timeout semantics | S27–S28 | Live CLI and shim stderr, retries, failure and non-disclosure tests | Pending |

## Out of scope

Publishing or separately versioning the subpackage; guaranteeing a stable external API; automatic installation, updates, authentication or subscription management; arbitrary ACP commands; automatic failover; granting agent tools; changing reviewer behavior; OS sandboxing of external agents; and vLLM support, tracked as future work.
