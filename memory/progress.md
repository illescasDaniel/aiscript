# Progress

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
- [ ] Fix macOS test failure, push and verify release CI.
- [ ] Obtain explicit authorization for v1.3.0, publish and upgrade the existing uv tool.

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
