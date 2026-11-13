_Last updated: 2026-11-12_

## Branch

`main`.

## Current focus

Multi-provider and ACP support: built, QA'd and graded (NEEDS WORK; fix budget spent). Quality gate green (1403 tests). Q3 resolved: spec amended, empty answer exits 8. OpenCode Go enabled with a model guard and qualified live. Claude ACP also qualified live (README scripts pass). Remaining decision: G2 for codex/gemini/glm connectors (unqualified; glm executable unverified). See `sdd/multi-provider.html` Verify tab. Nothing committed. 1.4.0 remains awaiting release.

## Blockers

None. Manual checks not done: M1 (strict schema on a non-OpenAI server), M3 (Windows PowerShell 5.1).

## Next steps

Run scenario tests before implementation, then implement and run quality gate, QA and independent grade. vLLM support is a separate future task. Publish 1.4.0 when separately authorized. Image generation is deferred to 1.5.0.
