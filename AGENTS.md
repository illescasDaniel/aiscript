## Agents and delegation

You are the orchestrator: delegate to the `architect`, `coder`, `code-grader` and `utility` subagents in
`.claude/agents/`, `.cursor/agents/` and `.codex/agents/`, and own every approval gate and memory write. Routing, briefs and the memory protocol (read this file
before delegating):

Read `.claude/development-workflow.md`.

## Python code goes to `coder-python`

Any task that adds, changes, renames, moves or deletes `.py`/`.pyi` code goes to `coder-python`, not the generic
`coder`: it uses the project's `codenav` MCP for type-checked navigation and refactoring. Keep `coder` for everything
else, and split a task that spans languages.

## TypeScript code goes to `coder-typescript`

Any task that adds, changes, renames, moves or deletes JavaScript/TypeScript/HTML/CSS (`.ts`, `.tsx`, `.js`, `.jsx`,
`.html`, `.css`) code goes to `coder-typescript`, not the generic `coder`: it uses the project's `webnav` MCP for
type-checked navigation and refactoring. Keep `coder` for everything else, and split a task that spans languages.

## Memory bank

Project state lives in `memory/` (git-tracked, so it follows the branch). At session start, read
`memory/activeContext.md` then `memory/progress.md`. Update on these triggers only: a task is completed or discovered
(`progress.md`); focus changes, a blocker is hit or work concludes (`activeContext.md`); a significant technical
decision is made (`decisions.md`, append-only, newest first). Full protocol: the `memory-bank` skill.

## Phase Gate Protocol (Spec-Driven Development)

Every feature or user-facing change goes through these phases. Full workflow: the `sdd-feature` skill.

| Phase | Deliverable | Gate |
|-------|-------------|------|
| **0 — Design** | UI track: `wireframes/<screen>.html` (self-contained HTML/CSS). System track (APIs, data, jobs, events, services): `design/<feature>/DESIGN.md` with Mermaid diagrams, checked with `design_preview.py --check`. Fullstack: both | **Stop.** Ask for design approval (one gate for both tracks). |
| **1 — Spec** | `specs/<feature>/SPEC.md`: agreed Design decisions (success criteria, failure handling, performance/resource budget, trust boundary, compatibility & rollout), a scenario for every `F<n>` failure branch of the design, BDD scenarios, Out of scope | **Stop.** Ask for spec approval. |
| **2 — Architecture** | Domain types and interfaces only | **Stop.** Ask for approval before tests/adapters. |
| **3 — Tests** | Unit tests from the BDD scenarios | Run them. |
| **4 — Implementation** | Use cases, adapters, UI | Until tests pass; must match the approved wireframe and `DESIGN.md`. |
| **5 — Grade** | Read-only `code-grader` subagent scores the branch against the spec | Automatic: fix FAILs, max 2 rounds, show the scorecard. |

- **Never skip a gate.** "Implement the plan", "complete all todos", an attached plan file or plan-mode approval is
  **not** design or spec approval; approval must be explicit, in chat. One gate per approval: after the wireframe, end
  the turn and wait.
- If implementation reveals a spec flaw, rewrite the spec, get re-approval, then continue. Don't patch around a bad spec.
- No production code before spec approval. Allowed before it: `wireframes/`, `design/`, `specs/` and docs.
