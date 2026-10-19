"""OpenAI-compatible client, system prompt, and script generation."""

from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiscript import paths
from aiscript.errors import AiscriptError

if TYPE_CHECKING:
    import openai

    from aiscript.config import ProviderConfig

_TIMEOUT_SECONDS = 120.0
_BASH_SHEBANG = "#!/usr/bin/env bash"
_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)
_OPEN_FENCE_RE = re.compile(r"```[^\n`]*\n(.*)\Z", re.DOTALL)


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


_COMMON_RULES = """\
You are a script generator embedded in a command-line tool called aiscript. The user gives you a \
command name and a plain-English description of what the command should do. You write ONE \
complete, working {shell_name} script that implements it.

TARGET ENVIRONMENT
- Shell: {shell_name}
- Host OS: {os_name}
Use only commands and flags that exist on this OS. Prefer tools that ship with the OS; if you \
must rely on an optional tool, check for it with {check_cmd} and print a clear error that tells \
the user how to install it.

OUTPUT FORMAT (critical)
- Output ONLY the raw script source code.
- Do NOT wrap it in markdown fences (no ```), and write no explanations, greetings or prose \
before or after the code. Anything outside the script breaks the tool.

ARGUMENTS
- The script receives the user's arguments positionally: {args_doc}.
- Decide which arguments the intent needs. Validate required arguments up front; if any are \
missing or invalid, print a short usage message to stderr (e.g. "Usage: <name> <args...>") and \
exit with a non-zero status.
- If the intent needs no arguments, do not demand any.
- Never prompt interactively unless the intent explicitly calls for it.

SAFETY DEFAULTS
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
"""

_BASH_SPECIFIC = """\
BASH SPECIFICS
- The very first line must be `#!/usr/bin/env bash`, followed by the header comment lines, and \
then `set -euo pipefail`.
- Use `"$1"`, `"$2"`, `"$@"`, `$#` for arguments; use `"${1:-}"` when testing an optional \
argument under `set -u`.
- Write portable, readable Bash; avoid unnecessary cleverness. Use `[[ ... ]]` for tests and \
`local` for function variables.
- Use `mktemp` for temporary files and clean up with a `trap`."""

_POWERSHELL_SPECIFIC = """\
POWERSHELL SPECIFICS
- Do NOT add a shebang. Start directly with the header comment lines (using `#` comments only, \
never `<# #>` blocks for the header), then `$ErrorActionPreference = 'Stop'`.
- Read arguments with `$args[0]`, `$args[1]`, `$args.Count`; do not declare a `param()` block \
before the header.
- Write to the error stream with `Write-Error` or `[Console]::Error.WriteLine(...)` and use \
`exit 1` for failures.
- Use `-LiteralPath` for paths that come from arguments."""

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
        "# <optional further comment lines explaining the behaviour>"
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
        "The very first lines of the script must be exactly this comment block (no shebang):\n"
        "# aiscript: <name>\n"
        "# Description: <one line summary>\n"
        "# Usage: <name> <args...>\n"
        "# <optional further comment lines explaining the behaviour>"
    ),
}


def system_prompt(shell: str, os_name: str) -> str:
    """Build the system prompt for ``shell`` ('bash' or 'powershell') on ``os_name``."""
    if shell == "powershell":
        parts, specific = _POWERSHELL_PARTS, _POWERSHELL_SPECIFIC
    else:
        parts, specific = _BASH_PARTS, _BASH_SPECIFIC
    return _COMMON_RULES.format(os_name=os_name, shell_specific=specific, **parts).strip() + "\n"


def clean_script(raw: str, shell: str) -> str:
    """Extract script code from model output and normalise it."""
    text = raw or ""
    match = _FENCE_RE.search(text) or _OPEN_FENCE_RE.search(text)
    if match:
        text = match.group(1)
    text = text.strip()
    if not text:
        raise AiscriptError("The model returned an empty script.")
    if shell != "powershell" and not text.startswith("#!"):
        text = f"{_BASH_SHEBANG}\n{text}"
    return text + "\n"


def _os_description() -> str:
    system = platform.system() or "Unknown"
    desc = f"{system} {platform.release()}".strip()
    if system == "Linux":
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    pretty = line.split("=", 1)[1].strip().strip("\"'")
                    desc += f" ({pretty})"
                    break
        except OSError:
            pass
    return desc


def generate_script(p: ProviderConfig, name: str, intent: str) -> str:
    """Ask the model for a script implementing ``intent`` and return it cleaned."""
    shell = paths.shell_kind()
    system = system_prompt(shell, _os_description())
    user = f"Command name: {name}\n\nWhat the command should do:\n{intent.strip()}"
    return clean_script(chat(p, system, user), shell)
