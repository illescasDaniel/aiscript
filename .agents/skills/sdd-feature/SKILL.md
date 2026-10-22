---
name: sdd-feature
description: Run Spec-Driven Development with explicit human approval gates (design, spec, architecture, then tests and implementation, then an independent grade). Use when adding or changing a feature in a frontend, backend or fullstack project (a screen or flow, an API endpoint, a data model, a background job, an event or a service), writing a wireframe, system design or SPEC.md, or implementing from acceptance criteria.
---

# SDD feature workflow

Build features in gated phases: **design → spec → architecture → tests → implementation → grade**. Each of the first
three phases ends with a deliverable the user reviews and approves **in chat** before the next one starts. The approved
spec is the source of truth: the code follows the spec, never the other way round.

## Project settings

Read `AGENTS.md` / `CLAUDE.md` first. The project may override any of these defaults:

| Setting | Default |
|---------|---------|
| Wireframes | `wireframes/<screen>.html` |
| System designs | `design/<feature>/DESIGN.md` |
| Diagrams | Mermaid code blocks inside the Markdown |
| Specs | `specs/<feature>/SPEC.md` |
| Domain types and interfaces (Phase 2) | the project's core layer, e.g. `domain/` + `ports/` in a hexagonal layout |
| Quality gate (lint, types, tests) | the project's documented check command |
| Test naming | `test_given_…_when_…_then_…` with `# given` / `# when` / `# then` comments (or the project's equivalent) |

Use the project's paths and commands wherever this document names a default.

## Mandatory gates (explicit human confirmation)

Do **not** skip or batch gates. After each gate deliverable, **end the turn** and ask the user to approve.

| User says | Agent may do |
|-----------|--------------|
| "Add feature X" / "implement the plan" / plan approved / "complete all todos" | **Phase 0 only** (design), then end the turn for **design approval** |
| User approves the design in chat | Phase 1 only (spec), then stop for **spec approval** |
| User approves the spec | Phase 2 (domain types and interfaces), then stop for **architecture approval** |
| User approves the architecture | Phases 3–4 (tests, then implementation), then Phase 5 (grade) |

An attached plan file, plan-mode approval, or a todo list that names every phase is **not** design or spec
approval. The user must confirm each gate in chat (for example "design approved", "spec approved").

### Anti-patterns (never do this)

- Writing the spec or production code in the **same turn** as the first design deliverable.
- Treating "implement the plan" as permission to run Phases 0–4 back to back.
- Skipping the review pause: always tell the user **where** to open the design and **wait** for their reply.
- Changing production source before spec approval, except refactors that keep existing specs green.
- Patching around a spec flaw found in Phase 4. Rewrite the spec (Phase 1), get re-approval, then continue.

## Phase 0 — Design

Pick the track(s) from what the feature touches, and say which you picked (the user can override):

| Track | Deliverable | When |
|-------|-------------|------|
| UI | `wireframes/<screen>.html` | it adds or changes screens |
| System | `design/<feature>/DESIGN.md` | it adds or changes APIs, data, jobs, events or services |

A fullstack feature gets both, reviewed at **one** gate, because each side shapes the other. Neither (a library or a
CLI)? Ask the user whether to skip Phase 0 or to sketch the interface instead (usage examples, output). Skipping is
itself a decision the user makes in chat.

### UI track

One self-contained HTML/CSS file (no build step, no network), using the real copy, states and edge cases rather than
lorem ipsum. Show every state the spec will mention (empty, loading, error, success), and a narrow/mobile width where
relevant. Notes meant only for the reviewer go in clearly labelled "Review only" boxes that never ship.

### System track

Write `DESIGN.md` from [`templates/DESIGN.md`](templates/DESIGN.md) (next to this file), keeping only the sections the
feature needs. Diagrams are Mermaid code blocks: plain text that diffs in review and renders on GitHub, GitLab and most
IDEs. Use real names, fields and status codes, not boxes labelled "Service".

- **Main flow**: a sequence diagram of the happy path and every failure path. Label each failure branch `F1`, `F2`, …
  (`break F1: quota exceeded`) in the order they appear in this diagram, top to bottom, nested branches included; the
  other diagrams reuse the same ids. In Phase 1 each one gets a scenario.
- **Components**: one diagram of the system after the change, with added, changed and removed parts coloured by the
  template's `classDef`s, so the reviewer sees how big the change is.
- **Data model**: an ER diagram of new or changed tables, plus the migration (backward compatible or not, order,
  backfill, rollback).
- **Lifecycle**: a state diagram, only for entities with states (order, job, subscription).
- **Contracts**: real request/response examples, error codes, idempotency and versioning; event payloads.
- **Contract seam** (fullstack): every wireframe state mapped to the call and the response that produces it.

Scripts run from the project root as `python3 <skill-dir>/scripts/<name>.py …`, where `<skill-dir>` is the folder
containing this file (e.g. `.claude/skills/sdd-feature`). Then run
`python3 <skill-dir>/scripts/design_preview.py design/<feature>/DESIGN.md --check`. `--check` validates every Mermaid
block headlessly (needs Node and network): fix every `FAIL` before the gate. If it exits 2 it could not run; tell the
user at the gate that the diagrams are unchecked instead of implying they are valid. The script also writes a
review-only `preview.html` beside the design that renders the diagrams in a browser (pinned Mermaid and Markdown
builds from a CDN, so viewing it needs network access).

**Stop. End the turn** with:

- The path of every deliverable (wireframe, `DESIGN.md`, `preview.html`)
- How to open them (`xdg-open …`, `open …` or `start …` for the user's OS)
- Any open design questions (`## Open questions` in `DESIGN.md`); answers given at this gate are carried into Phase 1
  as the proposed design decisions, not asked again from scratch
- Ask: "Please review the design — reply *design approved* (or the changes you want) before I write the spec."

## Phase 1 — Spec

**Step 1 — Agree five design decisions before writing the spec body.** Draft a proposed answer for each and ask the user
to confirm or adjust. Do not silently invent them. Each must be answered or marked `N/A — <reason>`; empty is not
allowed.

| Decision | Pin down |
|----------|----------|
| Success criteria | Observable "done" beyond the scenario list: the user outcome and measurable thresholds (no data loss, idempotent re-run, …) |
| Failure handling | What can fail, what the user sees, retry / skip / quarantine, partial state and resume |
| Performance & resource budget | Latency and throughput targets, CPU / memory / disk / network cost, size limits |
| Trust boundary | Which input is untrusted (paths, uploads, network clients, subprocess arguments), what is trusted, what may touch the filesystem or network, and where it is validated |
| Compatibility & rollout | Who depends on what changes (API clients, stored data, other services, older app versions), versioning, migration order, feature flag, rollback |

If a decision adds or changes a failure path, update the design's diagrams to match.

**Step 2 — Write `specs/<feature>/SPEC.md`** from [`templates/SPEC.md`](templates/SPEC.md) (next to this file):

- `## Metadata`: feature summary, wireframe and/or design links, approval dates
- `## Design decisions`: the five above, right after Metadata
- `## Triggers & routing`: how the user, client or event enters and leaves the flow
- `## Visual & UI rules` (UI track): aligned with the approved wireframe
- `## Interfaces & contracts` and `## Data & migration` (system track): aligned with the approved `DESIGN.md`
- `## Acceptance criteria`: `### Scenario:` blocks with **Given** / **When** / **Then**. Every failure-handling and
  trust-boundary decision needs at least one scenario, and so does every `F<n>` branch of the design; put its id in
  the scenario title, for example `### Scenario: export already running (F1)`.
- `## Out of scope`

Optionally run `python3 <skill-dir>/scripts/spec_check.py specs/<feature>/SPEC.md` to catch structural gaps,
including `F<n>` branches with no scenario.

**Stop.** Ask: "Please review `specs/<feature>/SPEC.md` (including Design decisions) — approve so I can add the
domain types and interfaces?" Record the approval dates in Metadata once given.

## Phase 2 — Architecture

Add or update only the core of the feature:

- Domain entities and value objects
- Inbound interface(s) for the use case (what the UI / API calls)
- Outbound interface(s) for what the use case needs from the outside world (storage, network, clock, processes)

No adapters, frameworks or UI yet. If there is an approved components diagram, these are its core in code; if the code
needs a different shape, update the diagram and point out the difference. **Stop for architecture approval** before
Phase 3.

## Phase 3 — Tests

Map each `### Scenario:` to at least one test named after it, for example
`test_given_long_url_when_rendered_then_stays_on_one_line`, with `# given` / `# when` / `# then` sections. Test
use cases and domain logic through their interfaces with in-memory fakes, not through HTTP routes or real I/O. Keep
them fast: no sleeps, network or subprocesses. Implementations may still be stubs; run the tests and confirm they fail
for the right reason.

## Phase 4 — Implementation

Use cases, adapters and production UI until the tests and the full quality gate pass. The UI must match the approved
wireframe, and the schema, endpoints, error codes and dependencies must match the approved `DESIGN.md`; if either has
to change, update the wireframe, design and/or spec and get re-approval first. If the project keeps a memory bank or
changelog, update it at milestones.

## Phase 5 — Grade

Runs automatically once Phase 4 is green. It only reads code, so it is **not** an approval gate.

1. Spawn the read-only **`code-grader`** subagent with the spec path(s) and the diff base (default `main`). If the
   project has not installed it, spawn a fresh general-purpose subagent whose prompt is the body of
   [`agents/code-grader.md`](agents/code-grader.md) (next to this file) plus the inputs. Never grade your own work in
   your own context: the grader must start fresh.
2. Fix every FAIL (and PARTIAL where cheap), re-run the quality gate, and re-spawn the grader. **At most 2 fix
   rounds**; if it still says NEEDS WORK, stop and report the remaining findings.
3. If a finding shows the spec itself is wrong, follow the spec-flaw rule: rewrite the spec and get re-approval.
4. Show the user the final scorecard verbatim (verdict, table, unresolved findings). The user makes the final call.
