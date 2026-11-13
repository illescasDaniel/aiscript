# Progress

## Multi-provider and ACP support

- [x] Initial Phase 0 design approved with ACP for generation and `--ask`.
- [x] Resolve conflict between ACP capabilities and existing `--ask` guarantees; obtain revised design approval.
- [x] Design and approve first-run provider selection and starter configuration examples.
- [x] Draft and approve spec.
- [x] Draft and approve architecture.
- [ ] Scenario tests, implementation, QA and independent grade.
- [ ] Future: investigate and add vLLM support (outside this feature).

## AI inside generated scripts (1.4.0)

- [x] Architect proposal and user decisions agreed in chat (2026-11-12).
- [x] Phase 0 design page drafted: `sdd/ai-in-scripts.html` (2026-11-12).
- [x] Design approval (2026-11-12).
- [x] Spec drafted in the page (2026-11-12).
- [x] Spec approval (2026-11-12).
- [x] Architecture drafted in the page (2026-11-12).
- [x] Architecture approval (2026-11-12).
- [x] Tests (565 new, failed for right reasons) and implementation; gate green (1314 tests).
- [x] QA: 25/25 scenarios. Grade round 1: NEEDS WORK (G1-G14); G1-G4, G6-G10, G12 fixed.
- [x] G5 fixed (store=false on official Chat, user-approved); M2 real OpenAI call OK (schema call, exit 0).
- [ ] Open: M1/M3 manual checks, re-grade skipped by user, nothing committed.
- [ ] (follow-up feature) native Anthropic/Gemini providers.

## Executable prompt scripts

- [x] Draft Phase 0 design for shebang execution and PATH guidance.
- [x] Obtain design approval.
- [x] Validate both Mermaid diagrams with the pinned Mermaid CLI.
- [x] Agree Phase 1 decisions and draft specification; spec check passes.
- [x] Obtain specification approval.
- [x] Draft Phase 2 interfaces and architecture plan.
- [x] Obtain architecture approval.
- [x] Implement feature and address first independent review's test gaps.
- [x] Complete quality gate and independent grade after two fix rounds.
- [x] Verify README PATH guidance and pass the fresh independent grade.
- [x] Verify direct invocation and locking on Windows CI.
- [x] Complete architecture, tests, implementation, and independent grade through the project gates.
- [x] Prepare 1.3.0 and pass local release checks.
- [x] Fix macOS test failure, push and verify release CI across all platforms.
- [x] Obtain explicit authorization for v1.3.0, publish and upgrade the existing uv tool.

## OpenAI Decisions reviewer

### Done

- [x] Confirmed local config selects Decisions and a live harmless-script review succeeds (2026-10-23).
- [x] Simplified Decisions provider comments in the starter YAML and README; listed its environment key with the other keys (2026-10-23).
- [x] Verified jevmem, codenav and utility subagent execution (2026-10-22).
- [x] Committed pending project workflows and configuration without pushing (2026-10-22).
- [x] Prepared system design and preview; both Mermaid diagrams validated (2026-10-22).
- [x] Obtained design approval and incorporated user corrections (2026-10-22).
- [x] Drafted five Phase 1 decisions for remaining-detail confirmation (2026-10-22).
- [x] Obtained approval of all five decisions and wrote the spec (2026-10-22).
- [x] Spec checker passed: 25 Given/When/Then scenarios, all F1–F6 branches covered (2026-10-22).
- [x] Obtained explicit spec approval (2026-10-22).
- [x] Added Phase 2 domain values, gateway protocol and uncalled policy/use-case declarations; documented implementation plan (2026-10-22).
- [x] Phase 2 verification: 500 existing tests pass, focused Ruff/mypy pass, spec check and both diagrams pass (2026-10-22).
- [x] Obtained explicit architecture approval (2026-10-22).
- [x] Phase 3 red runs confirmed expected core, config and integration failures before implementation (2026-10-22).
- [x] Phase 4 implemented reviewer, configuration, starter and docs; quality gate passes with 664 tests, Ruff, focused mypy and spec checks (2026-10-23).
- [x] Phase 5 independent grade PASS: all seven criteria, all 25 scenarios mapped, no findings or fix rounds (2026-10-23).

### Release 1.2.0

- [x] Prepare version 1.2.0 metadata/changelog/lockfile; 664 tests, full mypy, Ruff, spec and package inspection pass (2026-10-23).
- [x] Commit/push `aaee1a9` and verify main CI: all 11 jobs passed (2026-10-23).
- [x] Publish annotated `v1.2.0` through the existing Release workflow; verify PyPI/GitHub wheel and source archive checksums (2026-10-23).

### Open

None.

## Multi-provider / ACP

- [x] Architecture approved; tests and implementation built; gate green, 1403 tests (2026-11-13).
- [x] QA (6 defects) and grade (NEEDS WORK); both fix rounds used (2026-11-13).
- [ ] Decide G2 (connector qualification) and Q3/G6 (empty-answer exit code); update SPEC.md traceability; commit when authorized.


## 2026-11-13: QSIV reviewer provider

- [x] Multi-provider committed and pushed (3214a92), not released.
- [x] QSIV design, spec (+revision), architecture approved; qsiv-runtime built (122 tests), verified on a real GPU, regraded PASS, published 0.1.0 to PyPI.
- [x] aiscript adoption (1489 tests); dev path source removed, lock on PyPI.
- [ ] Release aiscript with QSIV (needs authorization); migrate agemem to qsiv-runtime (separate task, incl. its cwd hardening gap); live check with a real LLM generation + QSIV reviewer.

## SDD artifact organization

- [x] Move design and specification documents into `sdd/design/` and `sdd/specs/` and update references (2026-11-13).

- 2026-11-13: aiscript 1.5.0 released to PyPI (multi-provider + QSIV reviewer). Local tool replaced with the PyPI build; config uses claude-acp + qsiv. Next: migrate agemem to qsiv-runtime (not started).
