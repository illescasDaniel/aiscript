# Usage

| Command | Action |
|---|---|
| `aiscript NAME [args...]` | Run a command; created and built on first use |
| `aiscript PATH [args...]` | Run a prompt file using an explicit path |
| `aiscript --init` | Create config dirs and a `config.yaml` template (never overwrites) |
| `aiscript --list` | Table of commands, descriptions and usage (`*` = prompt changed, will rebuild; `+ai` after the language, e.g. `py+ai`, `sh+ai`, = the script calls the model) |
| `aiscript --check-secrets` | Scan every cached build and stored prompt for API keys; exit 0 if clean, 1 otherwise |
| `aiscript --ask TASK --data-description D [--schema JSON]` | Ask the configured model about stdin (used by generated scripts) |
| `aiscript --edit NAME` | Open the prompt in `$VISUAL` / `$EDITOR` (fallback nano/vi, notepad on Windows) |
| `aiscript --rebuild NAME` | Regenerate the script and print its path; does not run it |
| `aiscript --remove NAME` | Delete the command's prompt and cached script |
| `aiscript --help`, `--version` | Help / version |

Command names must match `[A-Za-z0-9][A-Za-z0-9_-]*`.

## Shell or Python

The model is told your OS, architecture, native shell, the Python version it will run under and
whether [uv](https://docs.astral.sh/uv/) is installed, and chooses the language: the shell for thin
wrappers around CLI tools and pipelines, Python for parsing JSON/CSV/HTML, data processing, HTTP
APIs and anything that would be fragile in shell. Say "in python" or "as a shell script" in your
description to ask for one; the model follows it unless it is clearly a poor fit (and then notes
why in the script header). `aiscript --list` shows each command's language.

- **Standard-library Python** is saved as `functions/NAME.py` and run with the system `python3`
  (`py -3` on Windows), or with aiscript's own interpreter if there is none.
- **Python with dependencies** declares them in an inline
  [PEP 723](https://peps.python.org/pep-0723/) block. After you approve (any dependency requires a
  `[y/N]` approval that lists the packages), aiscript creates `functions/NAME/` with `main.py` and
  a private `.venv`: with uv (`pyproject.toml` + `uv.lock`, `uv sync`) or otherwise with
  `python -m venv` + `pip install -r requirements.txt`. The script always runs with that venv's
  interpreter, so later runs are offline. A rebuild with the same dependencies reuses the venv; a
  failed install keeps the previous version. Without uv, Debian/Ubuntu need `python3-venv`.

## AI inside scripts

A generated script can hand a hard judgement step (summarise, classify, extract) to the model
configured as `default_provider`, without ever holding the API key. Describe it in your prompt
("summarise the pending updates") and the generator uses:

- Python: `aiscript.ask(task, data, data_description, schema=None)`. Without `schema` it returns a
  `str`; with a `schema` it returns a validated `dict`.
- Shell: `aiscript --ask TASK --data-description DESC [--schema JSON] < data`. Data is read from
  stdin as UTF-8; stdout is the text, or one line of compact JSON with `--schema`.

```python
import aiscript

result = aiscript.ask(
    task="Summarise the pending updates and flag security-related packages.",
    data=updates,
    data_description="Output of `checkupdates`: one 'name old -> new' line per package.",
    schema={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["summary", "risk"],
        "additionalProperties": False,
    },
)
```

```sh
summary=$(printf '%s\n' "$updates" | aiscript --ask "Summarise in 5 bullets." --data-description "checkupdates output") || exit 1
```

`task`, `data` and `data_description` are required. `schema` must be an object whose properties
are all listed in `required`, with `additionalProperties: false`, at most 5 levels deep and 100
properties; supported types are object, array, string, number, integer, boolean and null. The
model's answer is untrusted: scripts must never execute it.

Every failure leaves stdout empty and exits with a distinct code; Python raises the matching
`AskError` subclass (with `.exit_code`):

| Exit | Python exception | Meaning |
|---|---|---|
| 2 | `AskUsageError` | Missing task or description, invalid schema or JSON |
| 3 | `AskConfigError` | Invalid `ai:` limits, provider not OpenAI-compatible, or no key |
| 4 | `AskInputError` | Input at or above `max_input_kb`, or not UTF-8 (never truncated) |
| 5 | `AskProviderError` | Network, timeout, auth, quota or HTTP error after 2 retries |
| 6 | `AskRateLimitError` | Rate limited (429) on every attempt |
| 7 | `AskRefusalError` | The model refused |
| 8 | `AskOutputError` | Empty, incomplete, non-JSON or schema-invalid output (no re-ask) |
| 9 | `AskCapError` | More than `ai.max_calls_per_run` calls in one run |
| 127 | `AskNotFoundError` | Python only: `aiscript` is not on the script's PATH |

Limits are configurable in the optional [`ai:` block](configuration.md#ai-limits). Any script that
uses AI needs your interactive confirmation when built, and its input is sent to the provider on
every run: see [safety](safety.md#privacy). A key in your prompt or in generated code refuses the
build; `aiscript --check-secrets` applies the same scan to existing builds and prompts, names
`name:line` and never prints the value.

## How it works

```
~/.config/aiscript/          # or $XDG_CONFIG_HOME/aiscript, or $AISCRIPT_HOME
├── config.yaml              # providers and keys
├── prompts/<name>.txt       # your intent for each command
├── file-cache/              # reviewed builds for prompt files
└── functions/
    ├── <name>.sh            # generated, reviewed scripts (.ps1 on Windows)
    ├── <name>.py            # standard-library Python
    └── <name>/              # Python with dependencies
        ├── main.py
        ├── .venv/
        └── pyproject.toml + uv.lock  (or requirements.txt)
```

The first run of `NAME` saves your description to `prompts/NAME.txt`, asks the LLM for a script,
reviews it, and stores it in `functions/` (only one build per command: switching language
replaces the old one). Later runs just execute the cached script. If the
prompt is newer than the script (after `--edit` or a manual change), the script is rebuilt on the
next run. A `--rebuild` that fails or is rejected keeps the previous script.
