# Memory bank

Project state for AI coding agents, as plain markdown tracked in git. Each branch or worktree carries its own copy, so
context follows the branch and changes show up in PR diffs. Managed by the `memory-bank` skill.

| File | Role |
|------|------|
| `progress.md` | Macro checklist: what is done, what is open, known bugs. |
| `activeContext.md` | Scratchpad: current focus, blockers, touched files, the exact next step. |
| `decisions.md` | Append-only log of significant technical decisions and why (newest first). |
| `archive.md` | Finished history moved out of the two files above. Not read at session start. |
| `friction/` | Optional. One file per tool, doc or workflow problem an agent hit. |

Agents read `activeContext.md` then `progress.md` at session start. Humans can edit any file; it is just markdown.

## Starting a new feature branch

`progress.md` and `activeContext.md` describe the current branch and go stale fast, so reset them when starting a new
branch: fresh section in `progress.md` with an empty Done list and only the Open items that still apply, and an
`activeContext.md` with the new branch, focus and next steps. `decisions.md` is permanent: never clean it.
