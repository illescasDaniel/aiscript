# Changelog

## [1.0.0] - 2026-10-19

First stable release.

- Turn a plain-English description into a cached Bash (Linux/macOS) or PowerShell (Windows)
  script via an OpenAI-compatible model; later runs are instant and need no network or config.
- Safety review before anything is saved: a built-in static scan plus an optional decision model
  (Jev hosted, Ollaya local, or any OpenAI-compatible model). Risky scripts need explicit
  approval; the review fails closed.
- Confirmation output escapes control characters so scripts cannot hide code with ANSI escapes.
- Commands: `--init`, `--list`, `--edit`, `--rebuild`, `--remove`.
