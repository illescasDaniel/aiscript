# Changelog

## [1.2.0] - 2026-10-23

- Add OpenAI Decisions as an opt-in safety reviewer alongside Jev and Ollaya, using
  `kind: openai` and `api: decisions`.
- Default the Decisions reviewer to `gpt-6-luna` while retaining a configurable model name.
  Use a dedicated reviewer API key and the official OpenAI endpoint only.
- Evaluate the four existing hazards in one request with strict response validation, a
  30-second transport timeout and zero retries. Preserve static findings, dependency warnings
  and the existing confirmation behavior when review fails or detects risk.
- Include a commented starter configuration and document setup, safety behavior and rollback.

## [1.1.0] - 2026-10-20

- The model can now write Python as well as the native shell, choosing per command; "in python"
  or "as a shell script" in a description is honored unless clearly a poor fit.
- The generator prompt describes the host: OS, architecture, native shell, Python version and
  whether uv is installed.
- Python scripts with third-party dependencies (PEP 723) get their own folder and virtual
  environment (`uv sync`, or `venv` + `pip`), and always run in it. Dependencies always require
  approval.
- Python scripts are safety-scanned through their syntax tree, including commands they pass to
  `subprocess`/`os.system`.
- `--list` has a LANG column (`sh`, `ps1`, `py`, `py+deps`); `--remove` removes every build.

## [1.0.0] - 2026-10-19

First stable release.

- Turn a plain-English description into a cached Bash (Linux/macOS) or PowerShell (Windows)
  script via an OpenAI-compatible model; later runs are instant and need no network or config.
- Safety review before anything is saved: a built-in static scan plus an optional decision model
  (Jev hosted, Ollaya local, or any OpenAI-compatible model). Risky scripts need explicit
  approval; the review fails closed.
- Confirmation output escapes control characters so scripts cannot hide code with ANSI escapes.
- Commands: `--init`, `--list`, `--edit`, `--rebuild`, `--remove`.
