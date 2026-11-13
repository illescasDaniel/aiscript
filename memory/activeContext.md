_Last updated: 2026-11-13_

## Branch

`main`.

## Current focus

Multi-provider and ACP support: built, QA'd and graded (NEEDS WORK; fix budget spent). Quality gate green (1403 tests). Q3 resolved: spec amended, empty answer exits 8. OpenCode Go enabled with a model guard and qualified live. Claude ACP also qualified live (README scripts pass). Remaining decision: G2 for codex/gemini/glm connectors (unqualified; glm executable unverified). See `sdd/multi-provider.html` Verify tab. Nothing committed. 1.4.0 remains awaiting release.

## QSIV reviewer (2026-11-13)

Multi-provider is committed and pushed (3214a92, not released). QSIV (local GPU decision model) as `reviewer_provider: qsiv` is built and verified on a real RTX 4070 (design, spec incl. 2026-11-13 revision, architecture approved; QA and regrade PASS, `sdd/qsiv-provider.html`). The shared package `qsiv-runtime` 0.1.0 is PUBLISHED on PyPI (repo github.com/illescasDaniel/qsiv-runtime, release.yaml + trusted publishing). aiscript uses it as the optional extra `qsiv` (range >=0.1,<0.2); the dev path source is removed and uv.lock points at PyPI. aiscript itself is NOT released: CHANGELOG has an `[Unreleased]` entry. Known: QSIV limit 65,536 tokens (too_large before inference); 8 GB GPUs OOM above ~49K tokens; long scripts dilute the signal; agemem's own service has a cwd-import hardening gap (belongs to its migration to qsiv-runtime).

## Blockers

None. Manual checks not done: M1 (strict schema on a non-OpenAI server), M3 (Windows PowerShell 5.1).

## Next steps

Run scenario tests before implementation, then implement and run quality gate, QA and independent grade. vLLM support is a separate future task. Publish 1.4.0 when separately authorized. Image generation is deferred to 1.5.0.
