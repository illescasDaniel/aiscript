# Installation

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

Your config, prompts and cached scripts in `~/.config/aiscript/` are kept. To work on aiscript
itself, see [development](development.md).
