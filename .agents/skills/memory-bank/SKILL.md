---
name: memory-bank
description: Keep a git-tracked markdown memory bank (memory/ folder) so the agent resumes work across sessions. Use at session start, when a task finishes or a blocker appears, when a significant technical decision is made, before ending a session with unfinished work, and when asked to set up or reset the memory bank for a project or branch.
---

# Memory bank

Project state lives in plain markdown files in `memory/`, tracked in git. Because the folder is tracked, every
branch and worktree carries its own version: context follows the branch, shows up in PR diffs, and needs no service.

## Files

| File | Role | Read at session start? |
|------|------|------|
| `memory/progress.md` | Macro checklist: what is done, what is open, known bugs. | yes |
| `memory/activeContext.md` | Scratchpad: current focus, blockers, files touched, the exact next step. | yes |
| `memory/decisions.md` | Append-only log of significant technical decisions and why (newest first). | no, search it when needed |
| `memory/archive.md` | Finished history moved out of the two files above. | no |
| `memory/friction/` | Optional. One file per tool/doc/workflow problem the agent hit. | no |

## Setup (only if `memory/` does not exist)

Copy the `templates/` folder that sits next to this `SKILL.md` to `memory/` in the project root (skip `friction/` if
the user does not want it), fill the "Branch" and "Current focus" lines of `activeContext.md` from what you know, and
tell the user what you created. If you cannot locate `templates/`, create the files above with the headings described in
this document. Never overwrite an existing `memory/` folder.

## Session start

1. Read `memory/activeContext.md`.
2. Read `memory/progress.md`.
3. Continue from "Next steps". If they look stale against the code or `git log`, say so and ask before acting on them.

## During work: update only on these triggers

- **`progress.md`**: a task is completed (`[ ]` to `[x]`), or you discover a new task or bug.
- **`activeContext.md`**: focus changes, you hit a blocker, or you conclude a step (touched files, state, exact next step).
- **`decisions.md`**: a significant technical, structural or dependency choice. Append at the top: context, decision, rationale.
- **`friction/`** (optional): a tool errors, a doc misleads, or you need a workaround. Add one small dated file at that moment and keep working.

Do not rewrite these files on every turn. Small, trigger-based edits keep the diffs reviewable.

## Keeping it lean

`activeContext.md` is a scratchpad, not a log: roughly the current thread, its blockers and next steps, plus a short
"just changed" list. When a thread concludes, move it to `archive.md` under a dated heading. `progress.md` lists open
items plus the in-flight feature's Done list; move a finished feature's Done list to `archive.md` once nothing in it is
likely to be referenced again. Never delete from `decisions.md` or `archive.md`.

## Hand-off (before finishing a turn that leaves work unfinished)

1. Checkbox state in `progress.md` is accurate.
2. `activeContext.md` names the exact next step, so a fresh session can start without asking.

## Version control

- Commit memory updates at milestones, with the feature commit or in a `memory:` commit. Do not leave the tree permanently dirty.
- Never track per-developer local chores (worktree cleanup, local setup) here: they only create merge noise.
- On merge, keep the feature branch's `progress.md` and `activeContext.md`; merge `decisions.md` by keeping both sides' entries, newest first.

## New feature branch

When the user starts a new branch or worktree and asks to initialise memory:

1. `progress.md`: new section for the feature, empty Done list, carry forward only still-relevant Open items.
2. `activeContext.md`: rewrite with the branch name, the new focus, no blockers, only relevant next steps.
3. `decisions.md`: leave untouched.

Commit the initialisation in the branch's first commit.

## Alongside a semantic memory (optional)

If the project also has a semantic or long-term memory tool (for example [jev-mem](https://github.com/illescasDaniel/jev-mem)),
keep the two from overlapping:

- **Current state** (focus, in-progress work, blockers, next steps) belongs here, never in the other tool, where it would go stale silently.
- **Dated facts that stay true** (decisions with reasons, bug causes, gotchas, user preferences) belong in the semantic memory. A significant decision gets both a `decisions.md` entry and a one-fact note there.
- **Rules** the agent must always follow belong in `AGENTS.md` / `CLAUDE.md`.
