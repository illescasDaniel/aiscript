# Executable prompt scripts — architecture proposal

Phase 2 proposal for [the approved specification](../../specs/shebang-scripts/SPEC.md). Interfaces
are declarations only; the CLI continues to use its existing behavior until later phases.

## Boundaries

- `PromptSource` reads one canonical source and captures the exact prompt and content digest.
- `FileBuildCache` grants an exclusive per-source lease. The lease finds a matching reviewed build,
  allocates an unpublished version at its permanent path, and publishes artifact and identity
  together. Failed work can discard only an unpublished version.
- `PromptFileBuilder` builds and reviews that snapshot in the allocated destination.
- `ProgramRunner` executes a reviewed immutable entry point with unchanged arguments.
- `PromptFileExecution` coordinates these boundaries. Published versions stay immutable and are
  retained so a running process is not disrupted by a later build. Manual cache cleanup must be
  done when its artifacts are not in use.

Lock per canonical source across lookup, build and atomic publication, including across processes;
release before running. Allocate dependency environments at their final version path so installed
scripts with absolute interpreter paths remain valid. Cache keys must not be derived directly from
untrusted path text. Reuse existing generation and review while keeping named-command behavior.

## Implementation plan after approval

1. Derive unit tests from all 18 approved scenarios, run them and confirm the intended failures.
2. Implement source parsing, canonical identity, content matching, cross-process locks and atomic
   version publication. Test filesystem errors, concurrency and retention of previous versions.
3. Share generation and review with the current builder, and add file builds at permanent paths.
   Test a Python dependency with an installed executable as well as shell and standalone Python.
4. Wire explicit-path dispatch, argument and stream forwarding. Test real subprocess and shebang
   invocations, including path characters, failures and concurrent executions.
5. Update setup documentation with verified installer-specific PATH instructions and cache cleanup;
   run the full quality gate and obtain the independent spec grade.

Both system design Mermaid diagrams passed validation with the pinned Mermaid CLI.
