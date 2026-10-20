"""OpenAI-compatible client, system prompt, and script generation."""

from __future__ import annotations

import ast
import importlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aiscript import env, paths
from aiscript.errors import AiscriptError
from aiscript.paths import Language

if TYPE_CHECKING:
    import openai

    from aiscript.config import ProviderConfig

_TIMEOUT_SECONDS = 120.0
_BASH_SHEBANG = "#!/usr/bin/env bash"
_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)
_OPEN_FENCE_RE = re.compile(r"```[^\n`]*\n(.*)\Z", re.DOTALL)
_PEP723_RE = re.compile(
    r"^# /// script[ \t]*$\n((?:#(?:[ \t].*)?$\n)*?)^# ///[ \t]*$", re.MULTILINE
)
# name[extras] version-specifiers ; markers  (no URLs, direct references, paths or options)
_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_SPEC = r"(?:~=|===|==|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+"
_REQUIREMENT_RE = re.compile(
    rf"{_NAME}\s*(?:\[[A-Za-z0-9._,\s-]*\])?\s*"
    rf"(?:\(?\s*{_SPEC}(?:\s*,\s*{_SPEC})*\s*\)?)?\s*(?:;[^;]+)?"
)


def make_client(p: ProviderConfig) -> openai.OpenAI:
    """Build an OpenAI client; ``base_url`` is passed only when configured."""
    import openai

    kwargs: dict[str, Any] = {"api_key": p.api_key or "not-needed", "timeout": _TIMEOUT_SECONDS}
    if p.base_url is not None:
        kwargs["base_url"] = p.base_url
    return openai.OpenAI(**kwargs)


def _where(p: ProviderConfig) -> str:
    return f"provider '{p.name}' (model '{p.model}', base_url {p.base_url or 'default'})"


def _request(client: openai.OpenAI, p: ProviderConfig, system: str, user: str) -> str:
    """Send one request with the provider's API flavour and return the text."""
    if p.api == "responses":
        kwargs: dict[str, Any] = {
            "model": p.model,
            "instructions": system,
            "input": user,
            "store": False,
        }
        if p.reasoning_effort:
            kwargs["reasoning"] = {"effort": p.reasoning_effort}
        if p.temperature is not None:
            kwargs["temperature"] = p.temperature
        response = client.responses.create(**kwargs)
        if getattr(response, "status", None) == "incomplete":
            details = getattr(response, "incomplete_details", None)
            reason = getattr(details, "reason", None) or "unknown reason"
            raise AiscriptError(f"{_where(p)} returned an incomplete response ({reason}).")
        return getattr(response, "output_text", None) or ""

    kwargs = {
        "model": p.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if p.reasoning_effort:
        kwargs["reasoning_effort"] = p.reasoning_effort
    if p.temperature is not None:
        kwargs["temperature"] = p.temperature
    response = client.chat.completions.create(**kwargs)
    choices = getattr(response, "choices", None)
    return (choices[0].message.content if choices else None) or ""


def chat(p: ProviderConfig, system: str, user: str) -> str:
    """Run one system+user exchange and return the model's text.

    ``temperature`` and ``reasoning_effort`` are sent only when set on the provider:
    GPT-6 models reject ``temperature`` unless reasoning effort is ``none``.
    """
    import openai

    try:
        content = _request(make_client(p), p, system, user)
    except openai.AuthenticationError as e:
        raise AiscriptError(
            f"Authentication failed for {_where(p)}: check the API key in config.yaml. ({e})"
        ) from e
    except openai.APITimeoutError as e:
        raise AiscriptError(
            f"Request to {_where(p)} timed out after {_TIMEOUT_SECONDS:.0f}s."
        ) from e
    except openai.APIConnectionError as e:
        raise AiscriptError(
            f"Could not connect to {_where(p)}: check the endpoint URL and your network. ({e})"
        ) from e
    except openai.APIStatusError as e:
        raise AiscriptError(f"{_where(p)} returned HTTP {e.status_code}: {e.message}") from e
    except openai.OpenAIError as e:
        raise AiscriptError(f"Error calling {_where(p)}: {e}") from e

    if not content.strip():
        raise AiscriptError(f"{_where(p)} returned an empty response.")
    return content


@dataclass(frozen=True)
class GeneratedScript:
    code: str  # cleaned source, ends with "\n"
    language: Language  # "python" or the native shell
    dependencies: list[str]  # from the PEP 723 block; [] for shell / stdlib-only


_COMMON_RULES = """\
You are a script generator embedded in a command-line tool called aiscript. The user gives you a \
command name and a plain-English description of what the command should do. You write ONE \
complete, working script that implements it, in either {shell_name} (the native shell) or Python.

TARGET ENVIRONMENT
{environment}
Use only commands and flags that exist on this OS. Prefer tools that ship with the OS; if you \
must rely on an optional tool, check for it ({check_cmd} in {shell_name}, `shutil.which` in \
Python) and print a clear error that tells the user how to install it.

CHOOSING THE LANGUAGE
- Use {shell_name} for thin wrappers around CLI tools, pipelines, and simple file moves/copies.
- Use Python for parsing JSON/CSV/HTML/XML, real data processing, date math, HTTP APIs, \
cross-platform logic, or anything that would be long or fragile in {shell_name}.
- If the user's description asks for a language (e.g. "in python", "as a shell script"), honor \
it unless it is clearly a poor fit. In that case pick the better language and say why in one \
extra header comment line (e.g. "# Note: written in Python because ...").
- A Python script is recognised by its first line `#!/usr/bin/env python3`; a {shell_name} \
script follows the rules of its own section below.

OUTPUT FORMAT (critical)
- Output ONLY the raw script source code.
- Do NOT wrap it in markdown fences (no ```), and write no explanations, greetings or prose \
before or after the code. Anything outside the script breaks the tool.

ARGUMENTS
- The script receives the user's arguments positionally: in {shell_name} {args_doc}; in Python \
`sys.argv` (or argparse).
- Decide which arguments the intent needs. Validate required arguments up front; if any are \
missing or invalid, print a short usage message to stderr (e.g. "Usage: <name> <args...>") and \
exit with a non-zero status.
- If the intent needs no arguments, do not demand any.
- Never prompt interactively unless the intent explicitly calls for it.

SAFETY DEFAULTS (apply to both languages)
- Prefer non-destructive actions. {delete_doc}
- Never use {elevation} unless the intent explicitly requires it. Operate within the user's home \
directory or the current working directory whenever possible.
- Do not change network, firewall, DNS or system settings unless the intent explicitly asks.
- Do not download and execute remote code.
- For bulk or irreversible changes, show what will happen and ask for confirmation, or support a \
dry-run mode, unless the intent clearly says to proceed without asking.
- {quote_doc}
- Fail loudly: stop on errors and print helpful messages to stderr.

SCRIPT HEADER (critical, parsed by `aiscript --list`)
{header_doc}
Keep "Description" and "Usage" each on a single line, using exactly those labels. Replace \
<name> with the command name given by the user.

{shell_specific}

{python_specific}
"""

_BASH_SPECIFIC = """\
BASH SPECIFICS (when you choose Bash)
- The very first line must be `#!/usr/bin/env bash`, followed by the header comment lines, and \
then `set -euo pipefail`.
- Use `"$1"`, `"$2"`, `"$@"`, `$#` for arguments; use `"${1:-}"` when testing an optional \
argument under `set -u`.
- Write portable, readable Bash; avoid unnecessary cleverness. Use `[[ ... ]]` for tests and \
`local` for function variables.
- Use `mktemp` for temporary files and clean up with a `trap`."""

_POWERSHELL_SPECIFIC = """\
POWERSHELL SPECIFICS (when you choose PowerShell)
- Do NOT add a shebang. Start directly with the header comment lines (using `#` comments only, \
never `<# #>` blocks for the header), then `$ErrorActionPreference = 'Stop'`.
- Read arguments with `$args[0]`, `$args[1]`, `$args.Count`; do not declare a `param()` block \
before the header.
- Write to the error stream with `Write-Error` or `[Console]::Error.WriteLine(...)` and use \
`exit 1` for failures.
- Use `-LiteralPath` for paths that come from arguments."""

_PYTHON_SPECIFIC = """\
PYTHON SPECIFICS (when you choose Python)
- The very first line must be `#!/usr/bin/env python3`, then the same header block (`# aiscript: \
<name>`, `# Description: ...`, `# Usage: ...`, optional further comment lines), then the optional \
PEP 723 block, then the code. Example start:
#!/usr/bin/env python3
# aiscript: <name>
# Description: <one line summary>
# Usage: <name> <args...>
# /// script
# requires-python = ">=3.8"
# dependencies = ["requests>=2"]
# ///
- Target exactly the Python version reported in TARGET ENVIRONMENT; do not use newer syntax or \
library features than that version provides.
- Prefer the standard library. Use a third-party package only when it clearly helps, and then \
declare it ONLY in the PEP 723 block (`# /// script` ... `# ///`), using well-known PyPI \
packages; omit the block entirely when there are no dependencies. Never install packages at \
runtime and never call pip.
- Read arguments from `sys.argv` or argparse; on bad arguments print the usage to stderr and \
exit non-zero.
- Structure the code as `main()` plus `if __name__ == "__main__":` calling `sys.exit(main())` \
(or `main()` returning an exit code). Print errors to stderr.
- Never use `shutil.rmtree` or any other permanent deletion; move things to the trash instead: \
run `trash` (or `gio trash`) if available via `subprocess` with a list argv, otherwise move into \
`~/.Trash` on Linux/macOS, or the Recycle Bin on Windows, and tell the user where things went.
- No privilege elevation, no `shell=True`, no `eval`/`exec`, and never download and run code.
- Use `pathlib` for paths."""

_BASH_PARTS = {
    "shell_name": "Bash",
    "check_cmd": "`command -v`",
    "args_doc": "`$1`, `$2`, ... and `$@` / `$#`",
    "elevation": "`sudo`, `doas` or any privilege escalation",
    "delete_doc": (
        "Never use recursive forced deletion (`rm -r`, `rm -rf`). To delete things, move them to "
        "the trash instead: use `trash` (`trash-put` from trash-cli) if available, otherwise "
        "move the items into `~/.Trash` (create it if needed, avoiding name collisions), and "
        "tell the user where they went."
    ),
    "quote_doc": (
        'Quote every variable expansion (`"$var"`, `"${arr[@]}"`) and handle spaces in names.'
    ),
    "header_doc": (
        "Immediately after the shebang line, write exactly this comment block:\n"
        "#!/usr/bin/env bash\n"
        "# aiscript: <name>\n"
        "# Description: <one line summary>\n"
        "# Usage: <name> <args...>\n"
        "# <optional further comment lines explaining the behaviour>\n"
        "(Python scripts use the same block after their own `#!/usr/bin/env python3` line.)"
    ),
}

_POWERSHELL_PARTS = {
    "shell_name": "PowerShell",
    "check_cmd": "`Get-Command`",
    "args_doc": "`$args[0]`, `$args[1]`, ... and `$args.Count`",
    "elevation": "Run-as-administrator, `Start-Process -Verb RunAs` or any elevation",
    "delete_doc": (
        "Never permanently delete with `Remove-Item -Recurse -Force`. Send items to the Recycle "
        "Bin instead (for example `Add-Type -AssemblyName Microsoft.VisualBasic` and then "
        "`[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($path, 'OnlyErrorDialogs', "
        "'SendToRecycleBin')`), and tell the user what was moved."
    ),
    "quote_doc": "Quote paths and strings properly and handle spaces in names.",
    "header_doc": (
        "The very first lines of a PowerShell script must be exactly this comment block (no "
        "shebang):\n"
        "# aiscript: <name>\n"
        "# Description: <one line summary>\n"
        "# Usage: <name> <args...>\n"
        "# <optional further comment lines explaining the behaviour>\n"
        "(Python scripts use the same block after their own `#!/usr/bin/env python3` line.)"
    ),
}


def system_prompt(shell: str, environment: str) -> str:
    """Build the system prompt for native ``shell`` ('bash' or 'powershell').

    ``environment`` is the ``env.describe()`` block.
    """
    if shell == "powershell":
        parts, specific = _POWERSHELL_PARTS, _POWERSHELL_SPECIFIC
    else:
        parts, specific = _BASH_PARTS, _BASH_SPECIFIC
    return (
        _COMMON_RULES.format(
            environment=environment,
            shell_specific=specific,
            python_specific=_PYTHON_SPECIFIC,
            **parts,
        ).strip()
        + "\n"
    )


def detect_language(code: str, shell: str) -> Language:
    """'python' if the first non-blank line is a Python shebang, else the native ``shell``."""
    for line in code.splitlines():
        if line.strip():
            if line.startswith("#!") and "python" in line:
                return "python"
            break
    return "powershell" if shell == "powershell" else "bash"


def clean_script(raw: str, shell: str) -> str:
    """Extract script code from model output and normalise it."""
    text = raw or ""
    match = _FENCE_RE.search(text) or _OPEN_FENCE_RE.search(text)
    if match:
        text = match.group(1)
    text = text.strip()
    if not text:
        raise AiscriptError("The model returned an empty script.")
    # Any existing shebang (bash, python, ...) is kept as is.
    if shell != "powershell" and not text.startswith("#!"):
        text = f"{_BASH_SHEBANG}\n{text}"
    return text + "\n"


def _toml_dependencies(content: str) -> object:
    """Extract ``dependencies`` from PEP 723 TOML text (tomllib, or a tiny fallback on 3.10)."""
    try:
        tomllib: Any = importlib.import_module("tomllib")
    except ImportError:
        tomllib = None
    if tomllib is not None:
        try:
            return tomllib.loads(content).get("dependencies", [])
        except tomllib.TOMLDecodeError as e:
            raise AiscriptError(f"Invalid PEP 723 script block in the generated Python: {e}") from e

    match = re.search(r"^dependencies\s*=\s*\[", content, re.MULTILINE)
    if not match:
        return []
    out: list[str] = []
    depth, quote, i = 1, "", match.end()
    while i < len(content) and depth:
        ch = content[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":  # comment: skip to end of line
            while i < len(content) and content[i] != "\n":
                i += 1
            continue
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if not depth:
                break
        out.append(ch)
        i += 1
    if depth:
        raise AiscriptError("Invalid PEP 723 script block: unterminated dependencies array.")
    try:
        return ast.literal_eval("[" + "".join(out) + "]")
    except (ValueError, SyntaxError) as e:
        raise AiscriptError(f"Invalid PEP 723 script block: cannot read dependencies ({e}).") from e


def parse_dependencies(code: str) -> list[str]:
    """Return the validated PyPI requirements of a PEP 723 ``# /// script`` block ([] if none)."""
    match = _PEP723_RE.search(code)
    if not match:
        return []
    content = "".join(
        line[2:] if line.startswith("# ") else line[1:] for line in match.group(1).splitlines(True)
    )
    raw = _toml_dependencies(content)
    if not isinstance(raw, list):
        raise AiscriptError("Invalid PEP 723 script block: 'dependencies' must be a list.")
    deps: list[str] = []
    for item in raw:
        dep = item.strip() if isinstance(item, str) else ""
        bad = (
            not dep
            or dep.startswith("-")
            or any(token in dep for token in ("://", " @ ", "@", "/", "\\"))
            or not _REQUIREMENT_RE.fullmatch(dep)
        )
        if bad:
            raise AiscriptError(
                f"Unsupported dependency {item!r} in the generated Python script: "
                "only plain PyPI requirements (name, extras, version, markers) are allowed."
            )
        deps.append(dep)
    return deps


def generate_script(p: ProviderConfig, name: str, intent: str) -> GeneratedScript:
    """Ask the model for a script implementing ``intent``; return it cleaned and classified."""
    shell = paths.shell_kind()
    system = system_prompt(shell, env.describe())
    user = f"Command name: {name}\n\nWhat the command should do:\n{intent.strip()}"
    code = clean_script(chat(p, system, user), shell)
    language = detect_language(code, shell)
    if language != "python":
        return GeneratedScript(code, language, [])
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise AiscriptError(f"The model returned Python with a syntax error: {e}") from e
    return GeneratedScript(code, language, parse_dependencies(code))
