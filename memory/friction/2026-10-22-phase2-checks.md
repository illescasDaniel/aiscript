# Phase 2 tool checks — 2026-10-22

- Coder-python's `uv run` verification could not write its cache under the sandbox. Existing `.venv/bin/ruff` and `.venv/bin/mypy` completed the focused checks successfully.
- Mermaid's headless browser could not launch inside the sandbox. Approved escalation completed validation of both diagrams and regenerated the preview.
- During Phase 3, SDK exception fixtures initially imported unavailable `httpx`. The installed OpenAI SDK uses `httpx2`; fixtures now construct errors with that transport module.
- On 2026-10-23, an optional presentation-only follow-up to the completed grader failed because its model was at capacity. The full completed PASS review remains saved verbatim in `specs/openai-decisions/GRADE.md`; no re-review was needed.
