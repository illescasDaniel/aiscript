# Development

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                        # install the package and dev dependencies
uv run aiscript --help         # run the CLI from the checkout
uv run task test               # tests
uv run task lint               # ruff check, ruff format --check and mypy (line length 100)
```

## Trying it with your own config

`uv run task dev` runs the checkout with its config, prompts and generated scripts in a gitignored
`.dev/` folder, so your real `~/.config/aiscript` is never touched:

```sh
uv run task dev --init       # creates .dev/config.yaml; edit it and add your API key
uv run task dev --ask="reply with one word" --data-description="a word" <<< "hi"
```

Any other aiscript command works the same way (`uv run task dev sizes ~/Downloads`). Set
`AISCRIPT_HOME` yourself to use another folder. To start over, delete `.dev/`.

The optional `qsiv` extra installs [`qsiv-runtime`](https://pypi.org/project/qsiv-runtime/) from PyPI
(`uv sync --extra qsiv`). The QSIV tests use a fake `qsiv_runtime` module (`tests/fake_qsiv_runtime.py`) and need
neither the package nor a GPU.

Tests make no external network calls: the LLM layer is monkeypatched, and the AI-call tests run
against `tests/fake_openai.py`, a local fake OpenAI-compatible HTTP server.

## Project layout

```
src/aiscript/
├── cli.py        # argument dispatch, --edit / --rebuild / --remove, run flow
├── config.py     # config.yaml + environment loading, provider resolution
├── init_cmd.py   # `--init`: dirs, config template, .gitignore
├── qsiv.py       # QSIV reviewer port and adapter (lazy import of the optional qsiv-runtime package)
├── paths.py      # config root, prompt/function paths, name validation, OS/shell detection
├── builder.py    # staleness check and build pipeline (generate, review, atomic write)
├── llm.py        # OpenAI client, system prompt, script generation, language/dependency parsing
├── env.py        # host description for the prompt (OS, arch, Python, uv); Python lookup
├── pysetup.py    # project folder + private venv for Python scripts with dependencies
├── reviewer.py   # static scan (regex for shell, AST for Python), decision-model review, confirmation
├── listing.py    # header parsing and `--list` output
├── runner.py     # runs the cached script; adds the shim to PYTHONPATH and a per-run call counter
├── ask.py        # `--ask` core: validation, limits, request and response handling
├── ask_cli.py    # `--ask` command-line front end and exit codes
├── ask_openai.py # OpenAI client (Responses / Chat adapters) for AI calls; key resolution is in config.py
├── ask_schema.py # supported JSON-schema subset: validation of schemas and responses
├── ask_counter.py# per-run call counter file
├── secret_scan.py# key scanner for prompts and generated code
├── sweep.py      # `--check-secrets` sweep of cached builds and prompts
├── _shim/aiscript/__init__.py  # stdlib-only `import aiscript` for scripts; runs `aiscript --ask`
└── errors.py     # error types and exit codes
tests/            # pytest suite; fake_openai.py is the local fake provider server
```

The build backend is `uv_build`; the `aiscript` entry point is `aiscript.cli:main`.
