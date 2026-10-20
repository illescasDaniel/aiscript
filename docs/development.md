# Development

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                        # install the package and dev dependencies
uv run aiscript --help         # run the CLI from the checkout
uv run pytest -q               # tests
uv run ruff check              # lint
uv run ruff format --check     # formatting (line length 100)
```

Tests make no network calls: the LLM layer is monkeypatched.

## Project layout

```
src/aiscript/
├── cli.py        # argument dispatch, --edit / --rebuild / --remove, run flow
├── config.py     # config.yaml + environment loading, provider resolution
├── init_cmd.py   # `--init`: dirs, config template, .gitignore
├── paths.py      # config root, prompt/function paths, name validation, OS/shell detection
├── builder.py    # staleness check and build pipeline (generate, review, atomic write)
├── llm.py        # OpenAI client, system prompt, script generation, language/dependency parsing
├── env.py        # host description for the prompt (OS, arch, Python, uv); Python lookup
├── pysetup.py    # project folder + private venv for Python scripts with dependencies
├── reviewer.py   # static scan (regex for shell, AST for Python), decision-model review, confirmation
├── listing.py    # header parsing and `--list` output
├── runner.py     # runs the cached script
└── errors.py     # error types and exit codes
tests/            # pytest suite
```

The build backend is `uv_build`; the `aiscript` entry point is `aiscript.cli:main`.
