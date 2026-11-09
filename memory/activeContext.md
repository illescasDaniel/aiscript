_Last updated: 2026-11-09_

## Branch

`main`.

## Current focus

Preparing aiscript 1.3.0 release for executable prompt scripts. Release checks passed: 694 tests, Ruff, mypy, spec and isolated wheel smoke. The GitHub PyPI environment now requires owner review. Next commit and push the release, verify CI including Windows, then obtain explicit authorization for v1.3.0 before tagging and dispatching the release. The existing system installation is uv tool 1.1.0 and should be upgraded after publication.

## Blockers

Release CI passed Windows and Linux but failed macOS because the README shebang test uses an overly long temporary interpreter path. Fix the test and rerun CI before release.

## Just changed

- Added file-mode runtime, documentation and scenario tests; addressed the first independent review.
- Committed and pushed 1.3.0 release preparation as d9d2ecd; local checks pass. Windows CI passes; macOS CI failed the README shebang test.

## Next steps

Fix macOS test, push and verify CI; obtain explicit v1.3.0 authorization, publish and upgrade the installed uv tool.
