# Configuration reference

aiscript reads `config.yaml` from its config directory (see [Locations](#locations)). Run
`aiscript --init` to create a starter file (see the [README](../README.md#configuration)).
With no file at all, the generator works from `OPENAI_API_KEY` alone.

## Top-level keys

| Key | Meaning |
|---|---|
| `default_provider` | Provider that writes the scripts. Default `openai`. `$AISCRIPT_PROVIDER` overrides it. |
| `reviewer_provider` | Provider used as the decision model for the safety review. Omit to use only the static scan. |
| `providers` | Mapping of provider name to its settings. |

If `providers` is non-empty, the generator and the reviewer must both be listed in it. If it is
empty or missing, any name is accepted and settings come from environment variables and defaults.

## Provider settings

| Key | Meaning |
|---|---|
| `kind` | `openai`, `jev` or `ollaya`. Inferred from the provider name: `jev` and `typesafe` give `jev`, `ollaya` gives `ollaya`, anything else `openai`. |
| `api_key` | API key. Values ending in `...` (template placeholders) are ignored. |
| `base_url` | Endpoint URL. `endpoint` is accepted as an alias. |
| `model` | Model name. |
| `api` | `responses` or `chat` (used by OpenAI-compatible providers). |
| `reasoning_effort` | `none`, `low`, `medium`, `high`, `xhigh` or `max`. Sent only when set; support varies by model. |
| `temperature` | Number. Sent only when set. |

### Kinds

- **openai**: any OpenAI-compatible API (OpenAI, Ollama, vLLM, ...). Can be the generator or an
  LLM-based reviewer (which returns a JSON verdict).
- **jev**: [Jev](https://docs.typesafe.ai) by TypeSafe AI, reached through the `typesafe-sdk`
  package. It is a classifier, not a chat model, so it can only be the `reviewer_provider`.
  `model` defaults to `jev-latest`; `base_url` defaults to the SDK's (`https://api.typesafe.ai`).
- **ollaya**: [Ollaya](https://ollaya.dev) serves Jev-style models locally and speaks the same
  protocol, so it is handled as `jev` with different defaults: `base_url`
  `http://localhost:11435` (or from `$OLLAYA_HOST`, as `host:port` or a URL) and `model`
  `jevk5:4b`. It also can only be the reviewer. Run `ollaya serve` first.

Using a `jev` or `ollaya` provider as `default_provider` is a configuration error.

### `api`: responses vs chat

When the endpoint is OpenAI's own (no `base_url`, or host `api.openai.com`), the default is
`responses` (the Responses API). Any other `base_url` defaults to `chat` (Chat Completions),
since servers like Ollama usually implement only that. Set `api` explicitly to override.

### `reasoning_effort` and `temperature`

Neither is sent unless you set it. GPT-6 models reject `temperature` unless `reasoning_effort`
is `none`, and some reject `none` itself (for example GPT-6 Astra and GPT-6.1 Sol), so leave
`temperature` unset for those.

## API key resolution

The first match wins:

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

## Model resolution

1. `model` in the provider's YAML
2. Generator only: `$AISCRIPT_MODEL`
3. Defaults: `jevk5:4b` for Ollaya, `jev-latest` for Jev
4. Otherwise the generator's model for an OpenAI-kind reviewer, or the built-in default
   `gpt-6-luna` for the generator

## Environment variables

| Variable | Effect |
|---|---|
| `AISCRIPT_HOME` | Config root; wins over `XDG_CONFIG_HOME` |
| `XDG_CONFIG_HOME` | Config root becomes `$XDG_CONFIG_HOME/aiscript` |
| `AISCRIPT_PROVIDER` | Generator provider name (overrides `default_provider`) |
| `AISCRIPT_MODEL` | Generator model when none is set in YAML |
| `OPENAI_API_KEY` | Fallback key for an `openai`-kind generator |
| `OPENAI_BASE_URL` | Fallback `base_url` for the generator |
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
