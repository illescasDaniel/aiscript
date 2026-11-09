# aiscript

[![PyPI version](https://img.shields.io/pypi/v/aiscript)](https://pypi.org/project/aiscript/)
[![Python versions](https://img.shields.io/pypi/pyversions/aiscript)](https://pypi.org/project/aiscript/)

Describe what you want in plain English and `aiscript` asks an LLM to write a script, caches
it, and runs it. The model picks the language: your native shell (Bash on Linux/macOS, PowerShell
on Windows) or Python when that fits better. Python scripts that need third-party packages get
their own virtual environment. The next run is instant:
no network, no config. Before anything risky is saved or run, every generated script is checked
by a built-in static scan and, optionally, by a decision model: [Jev](https://docs.typesafe.ai)
by TypeSafe AI (hosted), [OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions),
or a local model served by [Ollaya](https://ollaya.dev). Risky scripts
are shown to you and need an explicit `[y/N]` approval.

## Install

```sh
uv tool install aiscript
# or
pipx install aiscript
# or
pip install aiscript
```

Requires Python 3.10+.

On Linux or macOS, check that the installed command is on your `PATH`:

```sh
command -v aiscript
```

If it is not found, use your installer's PATH setup: `uv tool update-shell` for uv, or
`pipx ensurepath` for pipx. These commands update shell configuration when you run them; open a
new terminal for the changes to take effect. With pip, add the directory containing its installed
`aiscript` executable to your PATH using your shell's configuration. See the
[uv tool documentation](https://docs.astral.sh/uv/concepts/tools/) and
[pipx installation guide](https://pipx.pypa.io/latest/how-to/install-pipx.html) for details.
Installing aiscript itself does not edit shell profiles.

To upgrade to the latest version, use the same tool you installed with:

```sh
uv tool upgrade aiscript
# or
pipx upgrade aiscript
# or
pip install --upgrade aiscript
```

Your config, prompts and cached scripts in `~/.config/aiscript/` are kept. To work on aiscript itself, see [docs/development.md](docs/development.md).

## Quickstart

```sh
aiscript --init        # creates ~/.config/aiscript/config.yaml
```

Put your OpenAI and Jev API keys in `~/.config/aiscript/config.yaml` (or export `OPENAI_API_KEY`
and `TYPESAFE_API_KEY`). The same file is where you pick the models: the one that writes the
scripts (`default_provider`) and the decision model that reviews them (`reviewer_provider`).
For a local, keyless review, use Ollaya instead of Jev (see below). Jev keys come from
<https://console.typesafe.ai/keys>.

Environment variables are the alternative to keys in the file:

```sh
export OPENAI_API_KEY=...
export TYPESAFE_API_KEY=...
```

Then run your first command:

```sh
aiscript sizes                       # first run: asks "What should 'sizes' do?"
aiscript sizes ~/Downloads --top 5   # later runs: cached, arguments passed straight through
```

Everything after the command name is passed untouched to the script (including `--help`).
`aiscript` messages go to stderr; stdout belongs to the script, and the exit code is the script's.

## Executable prompt files

On Linux and macOS, write a UTF-8 file named `biggest`:

```text
#!/usr/bin/env aiscript
List the largest folders inside the directory given as the first argument.
```

Make it executable and run it with a directory:

```sh
chmod +x biggest
./biggest ~/Downloads
```

`/usr/bin/env` finds `aiscript` on `PATH`. Alternatively, use its absolute path in the shebang,
for example `#!/home/alex/.local/bin/aiscript`. The operating system does not expand `$HOME` or
`~` in a shebang.

You can also run a prompt file directly with `aiscript ./biggest ~/Downloads`; a shebang is
optional in this form. On Windows, use direct invocation with an explicit path, for example
`aiscript .\biggest Downloads`; Unix shebang execution is not supported there. The path must
include a path separator: a bare name such as `biggest` selects the existing named-command
workflow, even when a file with that name exists. Quote paths or arguments containing spaces.
Arguments after the path, including flags, are passed through unchanged, as are the program's
standard input, output and exit status.

The first run generates and reviews a script using the same safety checks as named commands.
Risky builds require approval and are refused when standard input is non-interactive. Later
runs reuse a matching reviewed build without calling a model; changing the prompt rebuilds and
reviews it. A changed shebang alone does not trigger a rebuild. If rebuilding fails or is
rejected, aiscript keeps the old build but does not execute it for the changed prompt.
File builds are stored separately from named commands under `~/.config/aiscript/file-cache/`
(or `$XDG_CONFIG_HOME/aiscript/file-cache/`, or `$AISCRIPT_HOME/file-cache/`). Paths resolving
to the same file share a cache; moving the file creates a new entry. Historical versions are
retained. To reclaim their space, remove the file-cache directory only when no prompt-file
invocation is using it; the next run will rebuild and review its script. Named-command
management options such as `--remove` do not manage this cache.

## Safety review / decision models

Every generated script is reviewed **before it is saved**:

- A **static regex scan** (always on) flags privilege escalation, recursive or system-wide file
  changes, networking/firewall changes and remote code execution (`curl | sh`, `iex`).
- A **decision model** (`reviewer_provider`) gives a second opinion: **Jev** (hosted; key from
  <https://console.typesafe.ai/keys>), **OpenAI Decisions** (see below), or **Ollaya** (local and keyless; set
  `reviewer_provider: ollaya`, default model `jevk5:4b` on `localhost:11435`; see
  <https://ollaya.dev>). Comment `reviewer_provider` out to use only the static scan.

If either check flags the script, you see the reasons and the code and must answer `[y/N]`;
declining saves nothing. The review **fails closed**: if the reviewer errors or is unreachable,
the script is treated as risky. With a non-interactive stdin, risky scripts are refused. This is
a best-effort safety net, not a sandbox: read what you approve. Details: [docs/safety.md](docs/safety.md).

## Configuration

`aiscript --init` writes this starter `~/.config/aiscript/config.yaml` (mode 600; keep it out of git):

```yaml
# aiscript config. Contains API keys: keep it private (chmod 600) and out of git.
# Keys can also come from the environment: OPENAI_API_KEY, OPENAI_DECISIONS_API_KEY,
# TYPESAFE_API_KEY, <PROVIDER>_API_KEY.

# Provider that writes the scripts (override with $AISCRIPT_PROVIDER).
default_provider: openai

# Decision model that reviews scripts on top of the built-in static scan.
# Use `ollaya` for a local, keyless review; comment out to use only the static scan.
reviewer_provider: jev

providers:
  # OpenAI (or any OpenAI-compatible API). API key: https://platform.openai.com/api-keys
  openai:
    api_key: "..."
    model: "gpt-6-luna"
    # reasoning_effort: low    # none | low | medium | high | xhigh | max (model-dependent)

  # OpenAI Decisions API reviewer provider.
  # openai_decisions:
  #   kind: openai
  #   api: decisions
  #   api_key: "..."
  #   model: "gpt-6-luna"

  # Jev (TypeSafe AI) safety reviewer. API key: https://console.typesafe.ai/keys
  jev:
    api_key: "..."

  # Uses Ollaya for a local decision model (https://ollaya.dev), model example: jevk5:4b
  # ollaya:
  #   model: "jevk5:4b"

  # Uses Ollama for a local LLM to create the scripts (set `default_provider: ollama`)
  # ollama:
  #   base_url: "http://localhost:11434/v1"
  #   model: "qwen3"
```

Placeholder keys (`"..."`) are ignored, so if you leave them, the environment variables above work as-is.
All options (provider kinds, `api`, `temperature`, key and model resolution, every environment
variable, the legacy `secrets.yaml`): [docs/configuration.md](docs/configuration.md).

### OpenAI Decisions reviewer

To use OpenAI Decisions instead of Jev, select `reviewer_provider: openai_decisions` and
uncomment the corresponding provider block above. Supply its own `api_key`, or export
`OPENAI_DECISIONS_API_KEY`; this named reviewer does not fall back to `OPENAI_API_KEY`.
The default model is `gpt-6-luna`, and `model` remains configurable for future models.

Decisions uses the official OpenAI endpoint only. One request checks the same four hazards,
flagging probabilities **>= 0.5**. Requests use a 30-second transport timeout with zero retries.
Errors, refusals and malformed answers require the existing risk confirmation; they are refused
in noninteractive builds. Static findings and dependency warnings always remain effective.

Existing reviewers and cached scripts keep working. To roll back, restore your previous
`reviewer_provider` before downgrading aiscript. See [configuration](docs/configuration.md#openai-decisions)
and [safety](docs/safety.md#openai-decisions) for the full contract.

## Usage

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

## Docs

- [Configuration reference](docs/configuration.md)
- [Safety review](docs/safety.md)
- [Development](docs/development.md)
