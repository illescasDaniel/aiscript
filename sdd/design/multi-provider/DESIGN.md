# Multi-provider generation and ask — system design

- **Track:** System (CLI and library).
- **Status:** Revised design, including Q7 A, the shared-package proposal, first-run provider selection and Q8–Q10 recommendations, approved 2026-11-12 (user: “agree to the open questions recomendations. design approved.”).
- **Review page:** [Design tab](../../multi-provider.html#p-design), which owns the review, open questions and approvals. This file owns the canonical Mermaid system flow.
- **Date:** 2026-11-12.

## Outcome and boundaries

A user can generate scripts and use `aiscript.ask` / `aiscript --ask` with a native Anthropic or Gemini API or a locally installed ACP agent selected using only a `default_provider` value, such as `claude-acp` or `codex-acp`. The user approved ACP support for both generation and calls inside scripts and Q7 A, an ACP-specific relaxation of certain ask guarantees. Preserve existing API behavior and OpenAI-compatible configurations and defaults. Native API provider entries still configure model, credentials and endpoint as appropriate. A user choosing an ACP name should not need a `providers` entry, but must install and authenticate the external agent separately. This design does not promise an agent supports any particular account or subscription, model, platform, plan, or permission setting.

The generator currently resolves `AISCRIPT_PROVIDER` before YAML `default_provider`; ask deliberately uses only YAML `default_provider`. Both current resolvers reject an unlisted provider name when a providers mapping exists; built-in selection requires deliberate compatibility changes to this behavior. Preserve that distinction. Existing review and generated-script safety/confirmation remain independent. The proposed `aiscript.providers` subpackage, in the existing distribution, owns a provider-neutral request, result and bounded error vocabulary plus explicit capabilities or effective guarantees; its adapters translate to API and ACP transports. The boundary gives callers a common shape without claiming identical semantics across providers. The application retains configuration, CLI, policy, validation, review and counters; dependency direction is from the application into the package and then external SDKs or agents, never back into application modules. The generated-script shim remains independent of this package.

The package should be organized to make possible later extraction with isolated tests and provider-neutral boundaries. Separate distribution, publication, stable public API, versioning and exact packaging are not promised or part of this feature. Exact interfaces and module layout belong to the architecture gate; configuration and connector commands remain subject to specification and verification.

## Proposed first-run selection

On an interactive first run for a configuration root, before provider-backed generation or as part of `--init`, present a list of the supported provider selections and allow the user to choose the default. Offer this only when neither `config.yaml` nor the legacy `secrets.yaml` exists for that root. Existing configuration and legacy users keep their current selection and receive no onboarding prompt. Non-interactive invocations, `--ask`, help, listing and cached-script execution never prompt; they retain the existing behavior for an absent configuration.

Availability indicators are advisory. Detection inspects executable presence on `PATH` for ACP candidates and whether a relevant API-key environment variable is present. It starts no agent, does not read or reveal key values, and makes no network, account or login checks. Mark presence as detected rather than authenticated or ready. Detection may be unavailable or inconclusive; display unknown and keep all listed providers selectable, including undetected ones. The user can install or authenticate later.

Write the complete selected configuration to a private temporary file, then publish it atomically without clobbering a file another process or the user created; the platform-specific mechanism belongs to architecture. If a creation race occurs, preserve the existing file and explain that it won; a failed create or cancellation leaves no partially written configuration at the target. This does not change existing `--init` behavior such as its permissions handling on an existing config. The starter YAML contains commented examples of all supported native and ACP providers after OpenAI, with optional native model examples and ACP agent-default model guidance. Commented examples are discoverable without creating provider definitions or shadowing the built-in ACP selections.

```mermaid
sequenceDiagram
    actor U as User
    participant A as aiscript CLI
    participant D as Local availability check
    participant C as Configuration files
    U->>A: Interactive --init or first provider-backed generation
    A->>C: Check config.yaml and legacy secrets.yaml
    alt Existing config or legacy file
        C-->>A: Existing file; keep selection
    else First run and interactive
        A->>D: Inspect PATH and API-key presence
        alt F10: Detection unavailable or inconclusive
            D-->>A: Unknown; all choices remain selectable
        else Detection succeeds
            D-->>A: Advisory detected indicators
        end
        A-->>U: List providers and request choice
        alt F8: Invalid input or user cancels
            A-->>U: Re-prompt or cancel with no config write
        else Valid choice
            U->>A: Select provider
            A->>C: Write private temp; publish atomically without clobber
            alt F9: Create fails or another process wins
                C-->>A: No overwrite; report failure or existing file
            else Created
                C-->>U: Selected default and commented examples saved
            end
        end
    end
```

## Main flow

```mermaid
sequenceDiagram
    autonumber
    actor U as User or generated script
    participant C as aiscript configuration
    participant P as aiscript.providers boundary
    participant A as API adapter or ACP client
    participant E as Remote API or local agent
    U->>C: Select generator or ask operation and provider
    alt F1: Invalid configuration or unsupported selection
        C-->>U: Actionable configuration error
    else Valid selection
        C->>P: Resolve selected provider and operation
        P->>A: Dispatch neutral request and required capabilities
        alt F2: Missing or rejected credentials or authentication
            A-->>U: Authentication error and setup guidance
        else Credentials available
            A->>E: API call or initialize and start ACP session
            alt F3: Connector missing or incompatible, process fails, or API unavailable
                E-->>U: Provider unavailable or incompatible error
            else F4: Agent requests permission for a tool action
                A-->>E: Deny request; no interactive grant
                A-->>U: Report unsupported action if task cannot finish
            else F5: Invalid, refused or unsupported output or capability
                E-->>U: Validation or unsupported-output error
            else F6: Timeout, size, quota, rate or resource limit
                A-->>E: Stop work and clean up owned process
                A-->>U: Bounded limit error; no partial success
            else F7: User cancellation
                A-->>E: Cancel and clean up owned process where possible
                A-->>U: Cancellation; no partial success
            else Successful response
                E-->>A: Text or requested structured output
                A->>P: Normalize response, errors and effective guarantees
                P-->>C: Result and effective guarantees
                C-->>U: App validates output; generation review continues
            end
        end
    end
```

ACP can emit streaming notifications and reverse requests; the exact error mapping, stop reasons and handling when a denied action is nonessential must be specified after design approval. No silent fallback to a different provider, credential or model is proposed. ACP's explicitly different ask guarantees are disclosed rather than represented as equivalent to API guarantees.

## Selection and connectors

Illustrative selections, not promises of verified launch commands or authentication compatibility:

```yaml
# API example: existing named-provider configuration applies.
default_provider: anthropic
providers:
  anthropic:
    kind: anthropic
    model: <user-selected-model>
    api_key: <credential>

# Alternative: no provider entry required for a built-in ACP name.
default_provider: claude-acp
```

| Proposed selection | Candidate agent or connector | Evidence and qualification |
|---|---|---|
| `codex-acp` (possibly `openai-acp` alias) | [ACP Codex adapter](https://github.com/agentclientprotocol/codex-acp) (`@agentclientprotocol/codex-acp`) | The former Zed repository is archived and points to this successor; exact supported versions and login behavior require testing. |
| `claude-acp` | [Claude Agent ACP](https://github.com/agentclientprotocol/claude-agent-acp) | ACP adapter using Claude Agent SDK; supported sign-in and plan terms require verification. |
| `gemini-acp` | [Gemini CLI ACP mode](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/acp-mode.md) | Official CLI documents `gemini --acp`; account and version compatibility require testing. |
| `opencode-go-acp` | [OpenCode ACP mode](https://opencode.ai/docs/cli/acp) | OpenCode is the agent; Go is a plan/model selection within its configuration, not a separate proven connector. Validate selection and billing behavior. |
| `glm-acp` | Candidate agent from the [ACP registry](https://github.com/agentclientprotocol/registry), or OpenCode configured for GLM | Identify and verify a maintained connector, issuer, authentication and plan before claiming support. |

The [ACP registry](https://github.com/agentclientprotocol/registry) is a discovery source, not an instruction to download or execute arbitrary registry entries. Do not automatically install or update agents during an aiscript invocation. Select a fixed documented connector mapping and launch an argument vector without shell interpolation. Authentication and charges belong to the agent/provider and depend on their terms and active configuration. ACP standardizes communication with agents; it does not itself grant subscription access.

## Failure inventory and recovery

| ID | Condition | Proposed behavior |
|---|---|---|
| F1 | Invalid provider configuration or unknown selection | Fail before invocation; diagnose selection and show corrective action. Existing explicit provider definitions take precedence over built-in names. |
| F2 | Missing, expired or rejected API credentials or agent authentication | Fail with authentication and setup guidance; never expose secrets. |
| F3 | Connector executable missing, startup or handshake fails, incompatible version, process crash or API unavailable | Fail with provider diagnostic; install or repair separately. |
| F4 | ACP agent requests a permission-gated tool action | Reject the permission request; if a usable answer cannot be produced, report failure. This policy is not an OS sandbox. |
| F5 | Refusal, empty, incomplete or malformed result, invalid schema or unsupported required capability | Validate before returning or using result. Fail rather than return a malformed or silently downgraded response. |
| F6 | Timeout, size or resource limit, quota or rate limit | Stop work, clean up owned process and report a bounded limit error without returning partial output as success. |
| F7 | User cancellation | Cancel when possible, terminate and reap owned process, and report cancellation. External side effects may already have occurred. |
| F8 | Invalid first-run selection or user cancels | Re-prompt for invalid input; cancellation exits onboarding without writing a partial configuration. |
| F9 | First-run configuration creation fails or another process creates it first | Preserve any existing configuration; report the failure or race without overwriting it and without leaving a partial file. |
| F10 | First-run availability detection is unavailable or inconclusive | Mark detection unknown; keep all listed provider selections available and do not claim authentication. |

Existing callers retain their established error surfaces where compatible; exact mappings and exit codes belong in the spec. No thresholds or cross-agent support are asserted without measurement.

## Design decisions and proposed revision

- **Success:** Native Anthropic and Gemini, and ACP agents, support both generation and ask. Verify each connector separately, including real authentication when authorized. A shared provider subpackage supplies a neutral exchange shape with explicit capability and guarantee differences.
- **Failure and recovery:** F1–F7 fail visibly with actionable, sanitized diagnostics, no cross-provider fallback and no partial-success claim. Retain existing review and confirmation behavior.
- **Performance and resource budget:** Reuse existing ask limits where meaningful; measure ACP startup and per-request behavior before setting a total timeout, output bound, process count and retry budget. ACP client byte and time limits are not a model-side output-token or billing cap. API or agent quotas and pricing are provider-owned.
- **Trust boundary:** Prompt, agent output, protocol messages and diagnostics are untrusted; validate output and avoid logging secrets. Deny ACP permission requests initially; useful tools may be considered later. A local agent is executable software with the user's OS permissions, may load its own instructions, tools, configuration and environment, and can take actions without an ACP permission request. Denying client permission requests and using an empty working directory do not constitute sandboxing. Establish isolation separately or clearly disclose residual risk.
- **Compatibility and rollout:** Keep current OpenAI-compatible defaults, keys, custom endpoints, generation override and YAML-only ask selection. Existing explicit definitions take precedence over built-ins. Add opt-in providers and document prerequisites, releasing connectors individually after verification. Roll back by restoring the old default provider; no stored-script migration is proposed.

## Agreed answers and remaining specification work

1. **Scope:** ACP is in scope for both generation and runtime ask, with the approved ACP-specific limitations in Q7 A. Support and guarantees must not be claimed without evidence.
2. **Agent actions:** Deny ACP permission requests initially; revisit useful tools later. Denial is not a sandbox, and connector-specific restrictions require verification.
3. **Names and collisions:** Existing explicit provider entries win over built-in names. An `openai-acp` alias remains subject to specification and verification.
4. **Model selection:** Use the agent's configured default initially; consider an optional documented override later when portable behavior is validated.
5. **Structured outputs:** Validate locally, fail clearly when validation fails, and do not claim provider-native enforcement where unavailable. Existing API guarantees remain unchanged; Q7 A proposes local validation for ACP.
6. **Rollout:** Use the shared client and release each of the five requested selections after individually verifying invocation, authentication, output, cancellation and supported platforms. OpenCode Go and GLM plan/model binding must be established rather than silently consuming another account or plan.
7. **Existing ask contract conflict — Q7 A approved:** The existing 1.4 ask contract requires fixed system-role instructions, no tools, a provider-side strict schema request and a model-side output-token cap. Generic ACP does not establish all these guarantees; denying permission requests does not prevent agent-internal tools. The user approved relaxing these guarantees for ACP only: locally validate output, deny ACP permission requests, and enforce client-side byte and time bounds without claiming a model-token cap, fixed system role or absence of tools. Existing API behavior remains unchanged. The [ACP client system prompt proposal](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/rfds/client-system-prompt.mdx) does not establish those guarantees. The precise disclosures and enforceable thresholds belong in the spec.
8. **Shared package — approved:** Use an internal `aiscript.providers` subpackage in the existing distribution for neutral requests, results, errors, capability reporting and API/ACP adapters. Keep application policy and the generated-script shim outside the package. Make later independent extraction feasible without committing to a separate release or stable public API now. Exact types, interfaces and packaging details await the architecture gate.
9. **Q8 — first-run trigger, approved:** Prompt on interactive `--init` or before the first provider-backed generation only when the current root has neither `config.yaml` nor legacy `secrets.yaml`; never prompt for `--ask`, help, listing, cached execution or a non-interactive invocation.
10. **Q9 — advisory availability, approved:** Label PATH/API-key-presence detection as detected or unknown, without claiming authentication or performing network checks. Allow an undetected or unknown selection so the user can finish setup later.
11. **Q10 — generation environment override, approved:** An existing `AISCRIPT_PROVIDER` environment override still chooses the provider for the current generation; the saved YAML choice controls `--ask` and future defaults when there is no override. Disclose this distinction at selection.

vLLM support is a future task and is outside this feature's scope.

## Verification planned

After approvals, exercise first-run detection and selection in isolated configuration roots, existing and legacy configurations, non-interactive paths, cancellation and concurrent creation. Also exercise provider dispatch and existing OpenAI behavior; API adapters with controlled HTTP tests; ACP lifecycle with deterministic test agents including reverse permission requests, malformed messages, crashes and cancellation; validate schemas at the caller boundary. Real connector, login and subscription tests require authorized accounts and should be reported separately. Cross-platform installation, agent behavior and actual subscription eligibility remain unverified in this design. The updated Mermaid diagrams remain unverified until the project diagram checker completes successfully.
