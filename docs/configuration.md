# Configuration reference

aiscript reads `config.yaml` from its config directory (see [Locations](#locations)). Run
`aiscript --init` to create a starter file. On an interactive first use that needs script
generation, aiscript also offers provider selection if neither the current nor legacy config
exists. It checks only local executable and environment-key presence, not login or entitlement;
you can select an undetected provider. Help, cached runs, `--ask` and non-interactive runs do not
prompt. With no file at all, non-interactive generation retains the OpenAI default.

## Starter configuration

The starter `~/.config/aiscript/config.yaml` is private (mode 600; keep it out of git). This is
an abbreviated example; `--init` includes additional comments and examples:

```yaml
# aiscript config. Contains API keys: keep it private (chmod 600) and out of git.
# Keys can also come from the environment: OPENAI_API_KEY, OPENAI_DECISIONS_API_KEY,
# TYPESAFE_API_KEY, <PROVIDER>_API_KEY.

# Provider that writes the scripts (override with $AISCRIPT_PROVIDER).
default_provider: openai

# Optional ACP request limits (defaults shown).
# acp:
#   timeout_seconds: 100
#   max_frame_kib: 1024
#   max_response_kib: 1024

# Decision model that reviews scripts on top of the built-in static scan.
# Use `ollaya` for a local, keyless review; comment out to use only the static scan.
reviewer_provider: jev

providers:
  # OpenAI (or any OpenAI-compatible API). API key: https://platform.openai.com/api-keys
  openai:
    api_key: "..."
    model: "gpt-6-luna"
    # reasoning_effort: low    # none | low | medium | high | xhigh | max (model-dependent)

  # Anthropic (Claude API); set default_provider: anthropic. Alternative to api_key: ANTHROPIC_API_KEY.
  anthropic:
    api_key: "..."
    model: "claude-sonnet-5-5"

  # Google Gemini API; set default_provider: gemini. Alternative to api_key: GEMINI_API_KEY or GOOGLE_API_KEY.
  gemini:
    api_key: "..."
    model: "gemini-3-pro"

  # ACP names need no provider entry; model and login belong to the agent:
  # codex-acp:   claude-acp:   gemini-acp:   opencode-go-acp:   glm-acp:

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

Placeholder keys (`"..."`) are ignored, so environment variables can supply them instead.
See [OpenAI Decisions](#openai-decisions) and [safety](safety.md#openai-decisions) for its full
review contract.

## Top-level keys

| Key | Meaning |
|---|---|
| `default_provider` | Provider that writes the scripts, and also answers the AI calls made by generated scripts (`aiscript.ask`). Default `openai`. `$AISCRIPT_PROVIDER` overrides it for generation only. |
| `reviewer_provider` | Provider used as the decision model for the safety review. Omit to use only the static scan. |
| `ai` | Optional [limits](#ai-limits) for AI calls inside scripts. |
| `acp` | Optional [ACP limits](#acp-limits) for generation and AI calls inside scripts. |
| `providers` | Mapping of provider name to its settings. |

Built-in `openai`, `anthropic`, `gemini` and the ACP names can be selected without an entry, even
when other entries exist. Other provider names must be defined. An explicit entry with the same
name takes precedence over a built-in; give a native API entry its explicit `kind`. Select
reviewers separately as described below.

## Provider settings

| Key | Meaning |
|---|---|
| `kind` | `openai`, `anthropic`, `gemini`, `jev` or `ollaya`. Built-in ACP selections use their agent without a provider definition. |
| `api_key` | API key. Values ending in `...` (template placeholders) are ignored. |
| `base_url` | Endpoint URL. `endpoint` is accepted as an alias. |
| `model` | Model name. |
| `api` | `responses` or `chat` for OpenAI-compatible text APIs; explicit `decisions` for an official OpenAI reviewer only. |
| `reasoning_effort` | `none`, `low`, `medium`, `high`, `xhigh` or `max`. Sent only when set; support varies by model. |
| `temperature` | Number. Sent only when set. |

### Kinds

- **openai**: an OpenAI-compatible text API (OpenAI, Ollama, vLLM, ...). Can be the generator or an
  LLM-based reviewer (which returns a JSON verdict). Explicit `api: decisions` instead selects
  the official OpenAI Decisions endpoint for review only.
- **anthropic** and **gemini**: the native provider APIs for generation and AI calls inside
  scripts. They use separate provider credentials and model settings; the built-in names require
  no provider entry. Native API reviewer support is not included.
- **ACP agents**: select `codex-acp`, `claude-acp`, `gemini-acp`, `opencode-go-acp` or
  `glm-acp` as `default_provider`, with no entry under `providers:`. The agent must be installed
  and authenticated separately, and it chooses its model through its own configuration. aiscript
  does not install agents or manage logins. Actual connector versions, account eligibility,
  authentication and platform support remain unverified. Executables launched: `codex-acp` (Codex),
  `claude-agent-acp` (Claude), `gemini --acp` (Gemini), `glm-acp-agent` (GLM) and `opencode acp`
  (OpenCode Go). `opencode-go-acp` fails closed unless your OpenCode config sets `"model": "opencode-go/<model>"` (see
  `opencode models opencode-go`). See [ACP limits](#acp-limits) and
  [ACP trust and privacy](safety.md#acp-agents).
- **jev**: [Jev](https://docs.typesafe.ai) by TypeSafe AI, reached through the `typesafe-sdk`
  package. It is a classifier, not a chat model, so it can only be the `reviewer_provider`.
  `model` defaults to `jev-latest`; `base_url` defaults to the SDK's (`https://api.typesafe.ai`).
- **ollaya**: [Ollaya](https://ollaya.dev) serves Jev-style models locally and speaks the same
  protocol, so it is handled as `jev` with different defaults: `base_url`
  `http://localhost:11435` (or from `$OLLAYA_HOST`, as `host:port` or a URL) and `model`
  `jevk5:4b`. It also can only be the reviewer. Run `ollaya serve` first.

Using a `jev` or `ollaya` provider as `default_provider` is a configuration error.

### Installing ACP agents

aiscript does not install or sign in to agents; do both once yourself. They must be on your `PATH`.

| Selection | Install | Sign in |
|---|---|---|
| `claude-acp` | `npm install -g @agentclientprotocol/claude-agent-acp` | sign in with Claude Code (`claude`) |
| `codex-acp` | `npm install -g @agentclientprotocol/codex-acp` | `codex login` |
| `gemini-acp` | `npm install -g @google/gemini-cli` | run `gemini` once |
| `opencode-go-acp` | install [OpenCode](https://opencode.ai/docs/) | `opencode auth login` (OpenCode Go) |
| `glm-acp` | no verified connector yet (aiscript looks for `glm-acp-agent`) | |

Only `claude-acp`, `codex-acp` and `opencode-go-acp` have been tried against real installs
(Codex with a single question); the others follow the connectors' documentation. If an agent is missing, aiscript says which
executable it could not find.

### `api`: responses vs chat

When the endpoint is OpenAI's own (no `base_url`, or host `api.openai.com`), the default is
`responses` (the Responses API). Any other `base_url` defaults to `chat` (Chat Completions),
since servers like Ollama usually implement only that. Set `api` explicitly to override.

### OpenAI Decisions

Decisions is an explicit reviewer option, independent of text-API inference. Add a separate
entry to the existing `providers` mapping and select it:

```yaml
reviewer_provider: openai_decisions
providers:
  # Keep your existing generator entry here as well.
  openai_decisions:
    kind: openai
    api: decisions
    api_key: "..."
    model: "gpt-6-luna"
```

The dedicated `api_key` field wins over `OPENAI_DECISIONS_API_KEY`. Blank keys and placeholders
ending in `...` are ignored in both sources. There is no global `OPENAI_API_KEY` fallback or
dummy key. For another provider name, the existing `<NAME>_API_KEY` normalization applies.
Missing credentials produce a configuration error naming the permitted sources.

When omitted, `model` defaults to `gpt-6-luna`, regardless of the generator model or
`AISCRIPT_MODEL`. Explicit model names pass through so future supported models can be selected
without changing aiscript. If OpenAI rejects a model, the review is treated as unavailable.

Only `https://api.openai.com/v1` is supported. Omit `base_url` and `endpoint`, or set either to
that exact URL with an optional trailing slash. Both aliases are checked if supplied; a
canonical value cannot hide a custom value in the other field. Custom/local endpoints,
insecure URLs, alternate paths, credentials in URLs, queries and fragments are rejected.
`OPENAI_BASE_URL` does not redirect Decisions.

Decisions requires `kind: openai` and can only be the reviewer. Selecting it for generation,
combining it with Jev/Ollaya, or configuring `temperature`/`reasoning_effort` is an error.
It makes one request with four predicates, a 30-second SDK transport timeout and zero retries;
there is no fallback provider, new size limit, truncation, review cache or billing cap.

The starter configuration keeps Jev selected and includes a commented Decisions example.
To roll back, restore the previous reviewer selection before downgrading: older versions reject
`api: decisions`. No script migration, dependency removal or re-review of cached scripts is needed.

### `reasoning_effort` and `temperature`

Neither is sent unless you set it. GPT-6 models reject `temperature` unless `reasoning_effort`
is `none`, and some reject `none` itself (for example GPT-6 Astra and GPT-6.1 Sol), so leave
`temperature` unset for those.

These settings apply to text APIs. A Decisions reviewer rejects either setting.

## API key resolution

For existing text/Jev/Ollaya providers, the first match wins. Decisions uses the dedicated
two-source rule [above](#openai-decisions).

For native `anthropic` and `gemini`, an explicit provider `api_key` wins. Otherwise the official
Anthropic endpoint uses `ANTHROPIC_API_KEY`; the official Gemini endpoint uses `GEMINI_API_KEY`
or `GOOGLE_API_KEY`. A custom endpoint needs an explicit YAML key: native environment keys are
not redirected to it. ACP agents use their own authentication, not an aiscript API key.

1. `api_key` in `config.yaml` (unless it ends in `...`)
2. `<NAME>_API_KEY`, where `<NAME>` is the provider name uppercased with non-alphanumerics as `_`
   (`jev` gives `JEV_API_KEY`, `my-local` gives `MY_LOCAL_API_KEY`)
3. Ollaya: `OLLAYA_API_KEY`, otherwise no key (a placeholder is sent; auth is optional)
4. `jev` kind: `TYPESAFE_API_KEY`
5. Generator of kind `openai` with a remote (or no) `base_url`: `OPENAI_API_KEY`
6. A `base_url` on `localhost`, `127.0.0.1` or `::1`: no key needed (a placeholder is sent)

A local `base_url` skips step 5, so an exported `OPENAI_API_KEY` is never sent to a local server
such as Ollama.

If nothing matches, aiscript stops with an error naming the variables to set. Ollaya needs a key
only if the server was started with `OLLAYA_API_KEY`.

## AI limits

Optional `ai:` block; every key is optional and unknown keys are a configuration error. Values
must be integers within the bounds. Defaults:

```yaml
ai:
  max_input_kb: 128        # 1-1024; input at or above this is refused, never truncated
  max_calls_per_run: 1     # 1-100; the next call in one run exits 9
  timeout_seconds: 60      # 1-600; API timeout per attempt
  max_output_tokens: 4000  # 1-32000
```

OpenAI API retries are fixed at 2. At run time the call uses only the YAML `default_provider`;
`AISCRIPT_PROVIDER`, `AISCRIPT_MODEL` and `OPENAI_BASE_URL` do not redirect it. The selection may
be an OpenAI-compatible API, native Anthropic or Gemini, or a built-in ACP agent. Agent-owned
configuration may independently choose its model or backend. A status line on stderr reports
the applicable deadline when a provider call starts; it does not enter the returned answer.

Key resolution for AI calls, first match wins:

1. `api_key` in the provider's `config.yaml` entry
2. `<NAME>_API_KEY`
3. `OPENAI_API_KEY`

For OpenAI-compatible calls, keys from the environment (2 and 3) are sent only to
`api.openai.com`; any other endpoint needs its key in the YAML entry. Loopback endpoints
(`localhost`, `127.0.0.1`, `::1`) need no key. Native keys follow the provider-specific rule
above; ACP authentication belongs to the agent. A broken reviewer configuration does not affect
AI calls.

## ACP limits

Optional `acp:` settings apply to both generation and AI calls inside scripts:

```yaml
acp:
  timeout_seconds: 100     # 1-600; total request deadline
  max_frame_kib: 1024      # 1-16384; per ACP protocol frame
  max_response_kib: 1024   # 1-16384; total returned answer text
```

All values must be integers in the shown ranges. Exceeding a deadline or size limit fails the
request without returning a partial answer. These limits do not cap model tokens, billing, or
agent-internal actions. They do not provide an operating-system sandbox.

## Model resolution

Decisions uses its explicit model or its independent `gpt-6-luna` default. Other providers use:

1. `model` in the provider's YAML
2. Generator only: `$AISCRIPT_MODEL`
3. Defaults: `jevk5:4b` for Ollaya, `jev-latest` for Jev, `claude-sonnet-4-5` for Anthropic,
   and `gemini-2.5-pro` for Gemini
4. Otherwise the generator's model for an OpenAI-kind reviewer, or the built-in default
   `gpt-6-luna` for the generator

ACP agents use the model selected by their own configuration; aiscript does not override it.

## Environment variables

| Variable | Effect |
|---|---|
| `AISCRIPT_HOME` | Config root; wins over `XDG_CONFIG_HOME` |
| `XDG_CONFIG_HOME` | Config root becomes `$XDG_CONFIG_HOME/aiscript` |
| `AISCRIPT_PROVIDER` | Generator provider name (overrides `default_provider`) |
| `AISCRIPT_MODEL` | Generator model when none is set in YAML |
| `OPENAI_API_KEY` | Fallback key for an `openai`-kind generator |
| `ANTHROPIC_API_KEY` | Key for the official Anthropic API |
| `GEMINI_API_KEY`, `GOOGLE_API_KEY` | Keys for the official Gemini API; Gemini key takes precedence |
| `OPENAI_BASE_URL` | Fallback `base_url` for the generator |
| `OPENAI_DECISIONS_API_KEY` | Key for a reviewer named `openai_decisions` when its YAML key is unset |
| `TYPESAFE_API_KEY` | Fallback key for `jev` providers |
| `OLLAYA_HOST` | Ollaya address (`host:port` or URL); default `http://localhost:11435` |
| `OLLAYA_API_KEY` | Optional Ollaya key (sent as a Bearer token) |
| `<NAME>_API_KEY` | Per-provider key, e.g. `JEV_API_KEY` |
| `VISUAL`, `EDITOR` | Editor for `--edit` |

## Locations

The config root is, in order: `$AISCRIPT_HOME`, `$XDG_CONFIG_HOME/aiscript`, then
`~/.config/aiscript`. It holds `config.yaml`, `prompts/` and `functions/`.

`config.yaml` should be mode `600`. `--init` creates it that way, and aiscript warns on stderr if
group or other users can access it (not checked on Windows).

### `.gitignore`

If the config directory is a git repository, `--init` appends `config.yaml`, `secrets.yaml`
(legacy) and `functions/` to its `.gitignore` when missing.

## Migrating from `secrets.yaml`

The file used to be called `secrets.yaml`. If there is no `config.yaml`, an existing
`secrets.yaml` is still read, with a deprecation warning. Rename it yourself:
`mv ~/.config/aiscript/secrets.yaml ~/.config/aiscript/config.yaml`. aiscript never moves it, and
`--init` will not create a second file next to it.
