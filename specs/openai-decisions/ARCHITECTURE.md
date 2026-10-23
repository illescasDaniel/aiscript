# OpenAI Decisions — architecture

- **Spec:** [SPEC.md](SPEC.md), approved in chat on 2026-10-22.
- **Design:** [DESIGN.md](../../design/openai-decisions/DESIGN.md), approved in chat on 2026-10-22.
- **Architecture approval:** 2026-10-22 (chat).
- **Scope of this phase:** Types, protocol and uncalled function declarations only. No request adapter, response-policy implementation, configuration changes or new tests yet.

## Types and interfaces

One new module, `src/aiscript/decisions.py`, contains standard-library-only contracts:

| Declaration | Responsibility |
|-------------|----------------|
| `HazardName` | Literal union of the four stable Decisions question identifiers. |
| `ReviewInput` | Frozen value object containing script, language and immutable dependency tuple. |
| `HazardQuestion` | Frozen value object containing identifier, existing category, instructions and Jev true/false criteria. |
| `DecisionsCallError` | Structured exception containing a bounded failure kind and optional HTTP status, without payloads or SDK error strings. |
| `DecisionsGateway.classify(...) -> object` | Outbound protocol accepting the model, input and ordered questions; returns untrusted decoded response data for validation. |

`DecisionsCallError` is not frozen because Python exception handling may assign traceback/context fields. Immutable value objects remain frozen.

`src/aiscript/reviewer.py` retains `ReviewResult` and adds two declarations:

```python
def assess_decisions(
    review_input: ReviewInput,
    *,
    model: str,
    questions: tuple[HazardQuestion, ...],
    gateway: DecisionsGateway,
) -> ReviewResult: ...


def interpret_decisions_response(
    response: object,
    *,
    questions: tuple[HazardQuestion, ...],
) -> ReviewResult: ...
```

The saved functions raise `NotImplementedError` and are not called by existing dispatch. `assess_decisions` will own the single gateway call and failure-to-risk conversion. `interpret_decisions_response` will validate the entire result and apply the approved risk policy without I/O. Returning `object` from the gateway keeps untrusted SDK data distinct from validated domain values.

Reuse `ProviderConfig` in `config.py` and `ReviewResult` in `reviewer.py`; no moves, new framework or public CLI API. The concrete SDK gateway remains in `reviewer.py` alongside the existing Jev adapter. The component diagram now names the contracts module explicitly; this refines the design's existing Decisions component without changing product behavior.

## Hazard registry and adapter boundary after approval

Populate one ordered registry from the existing Jev hazard definitions. Existing Jev requests retain their instructions and true/false criteria. The Decisions adapter adds the approved untrusted-input prefix and uses stable wire identifiers.

The SDK adapter will construct and close a client using the explicit official URL, resolved reviewer key, 30-second timeout and zero retries. It will serialize the exact review input and convert SDK responses into ordinary data without coercing probabilities or discarding duplicate/unknown answers. SDK exceptions become structured `DecisionsCallError` categories; neither the use case nor diagnostics receive raw exception bodies. Unexpected ordinary errors use a fixed bounded diagnostic.

Implementation detail verified against the installed SDK: use `client.decisions.with_raw_response.create(...)` and `response.http_response.json()` so validation receives the original JSON values. The normal parsed `Decision` path coerces boolean/string probabilities to floats, which would bypass the approved strict validation. The raw wrapper calls the same Decisions endpoint with the same request contract.

## Phase 3: tests

All 25 approved scenarios remain the acceptance source. Add tests before implementation and run them, distinguishing expected failures for missing behavior from existing compatibility checks that already pass.

| Test files | Scenario groups from SPEC.md |
|------------|-----------------------------|
| `tests/test_config.py` | Opt-in and independent model; future model name; invalid role/kind/settings (F1); pinned/canonical/custom/conflicting endpoints (F1); key precedence; missing dedicated key (F2). |
| New `tests/test_decisions.py` | Safe/reordered answers; threshold/rounding/order; SDK/network/HTTP failures via fake gateway (F3); refusal, malformed answer sets and invalid probabilities (F4); safe diagnostics. |
| `tests/test_reviewer.py` | Exact request and untrusted data; SDK configuration and cleanup; model passthrough; oversized input (F3); static/dependency risk union; existing provider compatibility. Use fake SDK clients only at the adapter boundary. |
| `tests/test_builder.py`, existing CLI/confirmation tests | F5/F6 refuse/cancel without installs or saves and preserve previous scripts; interactive override; safe noninteractive continuation; unchanged cached execution. |
| `tests/test_init.py` and documentation review | Commented opt-in with unchanged active defaults, credentials/model/endpoint guidance and rollback. |

Core tests use in-memory gateway fakes, without network, subprocesses or sleeps. Keep existing compatibility tests. Parameterize invalid-answer and configuration variants rather than duplicating test logic. Test names and Given/When/Then sections follow project SDD conventions.

## Phase 4: implementation order

After architecture approval and the Phase 3 test run:

1. Implement Decisions-only configuration handling in `config.py` before generic key/model/endpoint fallbacks. Validate both endpoint aliases, role, kind and unsupported settings. Preserve existing branches.
2. Implement the registry, pure response interpretation, fakeable assessment use case, SDK gateway and dispatch in `reviewer.py`. Preserve Jev's wire inputs and wording, and static/model risk union. Steps 1 and 2 touch separate production files and may run in parallel once tests define their contracts.
3. Update the commented example in `init_cmd.py`, README and relevant configuration/safety documentation. No changes to active defaults.
4. Run pytest, Ruff lint and formatting checks from `docs/development.md`, plus focused type diagnostics for touched modules. Fix failures without weakening tests.
5. Run an independent read-only code-grader against the approved spec/design and diff base `35e1a04`; fix findings within the SDD limit and show the final scorecard.

Stop and request spec/design reapproval if implementation requires changing an approved contract. No commits or push are implied by this phase.

## Phase 2 verification

- Existing regression suite: 500 tests passed. No new tests added.
- Ruff lint and formatting: both touched Python files passed.
- Mypy: both touched Python files passed; codenav reported no errors.
- Spec checker: 25 scenarios, all F1–F6 branches covered, no hard failures.
- Design preview: regenerated, both Mermaid diagrams validated.
