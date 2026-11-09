_Last updated: 2026-11-09_

## Branch

`main`.

## Current focus

Preparing aiscript 1.3.0 release for executable prompt scripts. Release checks passed: 694 tests, Ruff, mypy, spec and isolated wheel smoke. The GitHub PyPI environment now requires owner review. Next commit and push the release, verify CI including Windows, then obtain explicit authorization for v1.3.0 before tagging and dispatching the release. The existing system installation is uv tool 1.1.0 and should be upgraded after publication.

## Blockers

Windows execution awaits the release commit's Windows CI run.

## Just changed

- Added file-mode runtime, documentation and scenario tests; addressed the first independent review.
- Prepared 1.3.0 metadata and changelog; full release checks passed.

## Next steps

Commit and push release changes, verify CI, obtain explicit v1.3.0 authorization, publish and upgrade the installed uv tool.
