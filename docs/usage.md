# Usage

| Command | Action |
|---|---|
| `aiscript NAME [args...]` | Run a command; created and built on first use |
| `aiscript PATH [args...]` | Run a prompt file using an explicit path |
| `aiscript --init` | Create config dirs and a `config.yaml` template (never overwrites) |
| `aiscript --list` | Table of commands, descriptions and usage (`*` = prompt changed, will rebuild) |
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
