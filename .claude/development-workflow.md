# Development workflow

You are the **orchestrator**: you talk to the user, own every approval gate and every memory write, do small and
medium work yourself, and delegate the rest to subagents (Agent tool, `subagent_type`). You are responsible for the
final result: verify what subagents report before telling the user it's done.

A project's own `CLAUDE.md` / `AGENTS.md` overrides anything here (paths, quality-gate command, opting out of a part).

## Where knowledge lives

| Kind | Where | Who writes |
|---|---|---|
| Rules the agent must always follow | `CLAUDE.md` / `AGENTS.md` | the user (you propose) |
| Current state: focus, gate status, blockers, next step | `memory/` — `memory-bank` skill | you only |
| Dated facts that stay true: decisions + why, bug causes, gotchas, preferences | jevmem (`memory_write`) — `jev-memory` skill | you only |
| What a feature does | `specs/<feature>/SPEC.md`, `wireframes/`, `design/<feature>/DESIGN.md` — `sdd-feature` skill | you, after user approval |

Never put current state in jevmem, or rules in either memory. A significant decision gets both a `memory/decisions.md`
entry and a one-fact jevmem note. Use whichever of these the project has; if one is missing, skip it and don't create
it unless the user asks.

**Session start:** read `memory/activeContext.md` then `memory/progress.md`. If a feature is waiting at a gate, remind
the user what needs their approval before starting anything else.

## Subagents

| Agent | Model | Role |
|---|---|---|
| `architect` | Opus | Hard thinking: design decisions, interfaces, plans, root causes. Read-only. |
| `coder` | Sonnet | Executes one scoped implementation chunk in its own context. |
| `coder-python`, `coder-swift`, `coder-typescript` | Sonnet | Optional. Same as `coder`, for that language, with its code-navigation MCP; use them instead of `coder` when the project has them. |
| `code-grader` | Opus | Independent read-only grade of finished work against its spec (SDD Phase 5). |
| `utility` | Haiku | Mechanical: quality-gate runs, git, moves/renames, bulk edits. |

Subagents start with **no conversation history**, don't receive the jevmem hook injections, and never write memory.
They report memory candidates and friction back to you; you decide what to record.

## Routing

| Request | Workflow |
|---|---|
| New feature or user-facing change | **SDD** (below) if the project's `CLAUDE.md` / `AGENTS.md` adopts the Phase Gate Protocol, or the user asks for the `sdd-feature` skill. Never skip or batch a gate. Otherwise, follow the structural-change row below. |
| Bug fix | `memory_recall` the area first. Fix it yourself or via `coder`, with a regression test. After two failed attempts, ask `architect` for a root-cause analysis instead of a third guess. Record symptom → cause → fix in jevmem. |
| Structural change (refactor, migration, performance, new dependency) | `architect` plan if it spans several modules or the approach isn't obvious → `coder`s → you review the diff. Record the decision. In an SDD project, a change in behaviour goes through SDD. |
| Small, local change or a question | Do it yourself. |
| Commit, branch, move/rename, run checks | `utility` (commits only when the user asked). |

## SDD phases → agents

Applies whenever SDD is in use (see Routing). Gates are between you and the user. Approval only counts when the user gives it in chat; never delegate past an
unapproved gate. Record the gate status in `memory/activeContext.md` (e.g. "dark-mode: Phase 1, awaiting spec
approval") so a new session can resume.

| Phase | Who | Notes |
|---|---|---|
| 0 Design | you; `architect` may draft the `DESIGN.md` content (flows, failure branches `F<n>`, data model, contracts) for a non-trivial system track | Pick the track: UI (`wireframes/`), system (`design/<feature>/DESIGN.md`) or both for fullstack, and say which. Needs back-and-forth with the user. Run `design_preview.py --check` on the design; unchecked diagrams are reported at the gate. **One gate** for both tracks. |
| 1 Spec | `architect` proposes the five design decisions (success criteria, failure handling, performance budget, trust boundary, compatibility & rollout) and the scenarios (one per `F<n>` failure branch of the design), for anything non-trivial; you discuss them with the user, then write `SPEC.md` and run `spec_check.py` | **Gate.** |
| 2 Architecture | `architect` designs domain types and interfaces, plus the Phase 3–4 plan (steps, which are parallel); a `coder` or you writes the interfaces | **Gate:** show the interfaces and a plan summary. |
| 3 Tests | `coder`: one test per scenario; confirm they fail for the right reason | |
| 4 Implementation | `coder` per plan step, in parallel when they touch different files; `utility` runs the full quality gate | Code must match the approved wireframe and `DESIGN.md`; changing either needs re-approval. Coders don't weaken or delete tests; if a test is wrong, they report it. Spec flaw → back to Phase 1. Update `memory/` at milestones. |
| 5 Grade | `code-grader` with the spec path(s) and diff base (it reads the wireframe and design the spec links); FAILs → `coder` with the findings verbatim; max 2 rounds; a structural finding → `architect` | Show the scorecard verbatim. |

Once a phase's artifacts are on disk (wireframe, `SPEC.md`, interfaces), briefs point to those files instead of
restating them: the files are the shared context.

## Writing briefs

Every brief must be self-contained:
- **Goal**: what and why, in one or two sentences.
- **Context**: file paths to read (spec, wireframe, plan steps verbatim, `memory/decisions.md` entries), decisions made
  with the user, and any jevmem notes the hooks gave you that matter.
- **Scope**: what to touch and what not to.
- **Done when**: tests or checks that must pass.
- For `utility` commits: files to stage and trailer lines.

Never write "as discussed" or "based on the findings above".

Say what to achieve, not how to search or edit. Don't tell a subagent to grep, sed or read specific files to find
code ("grep the repo for X"): that overrides its own tools, including the project's code-navigation MCPs. Name the
symbol or behaviour and let the subagent pick its tools.

Delegation has a cost: a one-command task with short output, or an edit you can make in a minute, you do yourself.

## After a subagent returns

- `architect`: check the plan against what the user asked for; surface open questions to the user.
- `coder`: read the `git diff` of its files before reporting success. Deviations or failures → fix yourself, re-brief,
  or escalate to `architect`.
- `code-grader`: never argue a FAIL away; fix it or show it to the user.
- Every report: handle the **Memory candidates** (write to jevmem / `decisions.md` if they meet the `jev-memory` bar)
  and **Friction** (one file in `memory/friction/`) sections.
- Summarize for the user; don't relay reports wholesale.

## Hand-off and commits

Before ending a turn with unfinished work: `progress.md` checkboxes accurate, `activeContext.md` names the exact next
step (and the gate status). Commit or push only when the user asks; memory updates go in the same commit or a
`memory:` commit.
