# Friction log

Every error, wrong or misleading tool result, slowdown, or workaround an agent hits while working here. It is a backlog
for improving tools, docs and skills. Unlike `decisions.md` (why we chose X) it records what hurt.

## Rules for agents

- Log at the moment of friction, then keep working. One small file per entry, not a batch at the end.
- One file per entry (`YYYY-MM-DD-short-slug.md`) so parallel branches never conflict. Never edit history; when it is fixed, only flip `status`.
- Log: a tool that returned something wrong, missing or slow; a doc that lied; a rule that blocked legitimate work; a workaround you needed. Do not log your own typos or one-off environment issues.
- Include enough to reproduce. Redact secrets and personal paths.

## Entry template

```markdown
---
date: YYYY-MM-DD
area: <tool, docs, code, ...>
severity: wrong-result | missing-feature | slow | confusing | blocked
status: open | fixed (<commit or PR>) | wontfix (<why>)
---

**Call:** what you ran
**Expected:** what you thought would happen
**Got:** what happened
**Workaround:** what you did instead
**Idea:** (optional) how the tool or doc could avoid this
```

## Triage

Read `status: open` entries first: `grep -l "status: open" memory/friction/*.md`. Move fixed entries older than about a
month to `memory/archive.md` if the folder gets long.
