_Last updated: 2026-10-23_

## Branch

`main`.

## Current focus

User tested the Decisions reviewer successfully and authorized saving, committing, pushing and publishing version 1.2.0 on 2026-10-23. Release prepared: 664 tests pass, global Ruff lint/format and full mypy pass; wheel/sdist metadata and contents verified. Version fields and lockfile are 1.2.0. Existing manual Release workflow publishes PyPI and GitHub artifacts after main CI and pushed tag.

## Blockers

None.

## Just changed

- Verified the configured OpenAI Decisions reviewer with a live harmless-script request on 2026-10-23: `risky=False`, no reasons. Successful reviews are silent; cached command execution skips review.
- Simplified starter YAML and matching README comments for OpenAI Decisions; moved its environment key guidance to the header. Configuration behavior is unchanged.
- Implemented opt-in `api: decisions` reviewer, dedicated credentials and official endpoint, independent configurable model default and strict raw JSON validation.
- Updated starter, README and configuration/safety docs; retained existing providers, risk confirmation and cached execution.
- Saved independent PASS scorecard with 25-scenario mapping. No grader fixes required.

## Next steps

1. Commit reviewed project changes, push main without force, and wait for CI success on that exact commit.
2. Create/push `v1.2.0` tag and dispatch existing Release workflow with that tag.
3. Verify PyPI/GitHub publication, record the outcome and commit/push final memory update. No force pushes or tag replacement.
