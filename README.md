# aiscript

[![PyPI version](https://img.shields.io/pypi/v/aiscript)](https://pypi.org/project/aiscript/)
[![Python versions](https://img.shields.io/pypi/pyversions/aiscript)](https://pypi.org/project/aiscript/)

Describe what you want in plain English and `aiscript` asks an LLM to write a shell script
(Bash on Linux/macOS, PowerShell on Windows), caches it, and runs it. The next run is instant:
no network, no config. Before anything risky is saved or run, every generated script is checked
by a built-in static scan and, optionally, by a decision model: [Jev](https://docs.typesafe.ai)
by TypeSafe AI (hosted) or a local model served by [Ollaya](https://ollaya.dev). Risky scripts
are shown to you and need an explicit `[y/N]` approval.

## Install

```sh
uv tool install aiscript
# or
pipx install aiscript
# or
pip install aiscript
```

Requires Python 3.10+. To work on aiscript itself, see [docs/development.md](docs/development.md).

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

## Safety review / decision models

Every generated script is reviewed **before it is saved**:

- A **static regex scan** (always on) flags privilege escalation, recursive or system-wide file
  changes, networking/firewall changes and remote code execution (`curl | sh`, `iex`).
- A **decision model** (`reviewer_provider`) gives a second opinion: **Jev** (hosted; key from
  <https://console.typesafe.ai/keys>) or **Ollaya** (local and keyless; set
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
# Keys can also come from the environment: OPENAI_API_KEY, TYPESAFE_API_KEY, <PROVIDER>_API_KEY.

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

## Usage

| Command | Action |
|---|---|
| `aiscript NAME [args...]` | Run a command; created and built on first use |
| `aiscript --init` | Create config dirs and a `config.yaml` template (never overwrites) |
| `aiscript --list` | Table of commands, descriptions and usage (`*` = prompt changed, will rebuild) |
| `aiscript --edit NAME` | Open the prompt in `$VISUAL` / `$EDITOR` (fallback nano/vi, notepad on Windows) |
| `aiscript --rebuild NAME` | Regenerate the script and print its path; does not run it |
| `aiscript --remove NAME` | Delete the command's prompt and cached script |
| `aiscript --help`, `--version` | Help / version |

Command names must match `[A-Za-z0-9][A-Za-z0-9_-]*`.

## How it works

```
~/.config/aiscript/          # or $XDG_CONFIG_HOME/aiscript, or $AISCRIPT_HOME
├── config.yaml              # providers and keys
├── prompts/<name>.txt       # your intent for each command
└── functions/<name>.sh      # generated, reviewed scripts (.ps1 on Windows)
```

The first run of `NAME` saves your description to `prompts/NAME.txt`, asks the LLM for a script,
reviews it, and stores it in `functions/`. Later runs just execute the cached script. If the
prompt is newer than the script (after `--edit` or a manual change), the script is rebuilt on the
next run. A `--rebuild` that fails or is rejected keeps the previous script.

## Docs

- [Configuration reference](docs/configuration.md)
- [Safety review](docs/safety.md)
- [Development](docs/development.md)
