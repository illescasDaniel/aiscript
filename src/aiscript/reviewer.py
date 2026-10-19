"""Static and LLM safety review of generated scripts."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from aiscript.config import ProviderConfig, is_local


@dataclass
class ReviewResult:
    risky: bool
    reasons: list[str]


# --------------------------------------------------------------------------- #
# Static patterns
# --------------------------------------------------------------------------- #

PRIVILEGE = "Privilege escalation"
FILESYSTEM = "Filesystem"
NETWORK = "Networking"
REMOTE_EXEC = "Remote code execution"

_SYS_DIRS = r"(?:etc|usr|bin|sbin|boot|lib|lib32|lib64|var(?!/tmp\b)|opt)"
_SEP = r"[^\n;|&]*"  # stay within one simple command
_CMD = r"(?<![\w./$-])"  # start of a command word (not part of a path/name)

_FLAGS = re.IGNORECASE
_Pat = tuple[str, "re.Pattern[str]", str]


def _p(category: str, pattern: str, label: str, flags: int = 0) -> _Pat:
    return (category, re.compile(pattern, flags), label)


_BASH: list[_Pat] = [
    # --- privilege escalation ---
    _p(PRIVILEGE, rf"{_CMD}(?:sudo|doas|pkexec)(?![\w-])", "sudo/doas/pkexec"),
    _p(PRIVILEGE, r"(?:^|[;&|(]\s*|\b(?:then|do|else)\s+)su(?:\s|$)", "su"),
    # --- filesystem ---
    _p(
        FILESYSTEM,
        rf"{_CMD}rm\s+(?:{_SEP}\s)?(?:-[A-Za-z]*[rR][A-Za-z]*|--recursive)(?=\s|$)",
        "recursive rm",
    ),
    _p(
        FILESYSTEM,
        rf"{_CMD}rm\b{_SEP}\s[\"']?(?:/|~|\$HOME|\$\{{HOME\}})(?:/?\*)?[\"']?(?=\s|$)",
        "rm on root/home",
    ),
    _p(
        FILESYSTEM,
        rf"{_CMD}(?:rm|rmdir|shred|touch|mkdir|ln|tee|install|sed\s+-i\S*|truncate)\b"
        rf"{_SEP}\s[\"']?/{_SYS_DIRS}(?:/|[\"']?(?:\s|$))",
        "modifies system directory",
    ),
    _p(
        FILESYSTEM,
        rf"{_CMD}(?:mv|cp)\b{_SEP}\s[\"']?/{_SYS_DIRS}(?:/\S*)?[\"']?\s*(?:$|[;&|])",
        "mv/cp into system directory",
    ),
    _p(
        FILESYSTEM,
        rf">>?\s*[\"']?(?:/{_SYS_DIRS}(?:/|[\"']?(?:\s|$))|/dev/(?:sd|hd|vd|nvme|mmcblk))",
        "redirect into system path/device",
    ),
    _p(
        FILESYSTEM,
        rf"{_CMD}(?:chmod|chown|chgrp)\b{_SEP}\s(?:-[A-Za-z]*R|--recursive)",
        "recursive chmod/chown",
    ),
    _p(
        FILESYSTEM,
        rf"{_CMD}(?:mkfs(?:\.\w+)?|fdisk|sfdisk|cfdisk|parted|wipefs|shred)(?![\w-])",
        "disk/format tool",
    ),
    _p(FILESYSTEM, rf"{_CMD}dd\b{_SEP}\bof=(?!/dev/null)", "dd of="),
    _p(FILESYSTEM, rf"{_CMD}find\b{_SEP}\s-delete\b", "find -delete"),
    _p(FILESYSTEM, rf"{_CMD}crontab\b(?!\s+-l\b)", "crontab"),
    _p(FILESYSTEM, rf"{_CMD}systemctl\b{_SEP}\b(?:enable|disable|stop|mask)\b", "systemctl"),
    # --- networking ---
    _p(NETWORK, rf"{_CMD}(?:iptables|ip6tables|nft|ufw|firewall-cmd)(?![\w-])", "firewall"),
    _p(
        NETWORK,
        rf"{_CMD}ip\s+(?:-\w+\s+)*(?:addr|address|link|route|rule|neigh)\s+(?:add|del|delete|set|flush|replace|change)\b",
        "ip configuration change",
    ),
    _p(NETWORK, rf"{_CMD}ifconfig\s+\S+\s+\S+", "ifconfig change"),
    _p(
        NETWORK,
        rf"{_CMD}nmcli\b{_SEP}\b(?:add|modify|mod|delete|up|down|connect|disconnect|reload|radio|networking)\b",
        "nmcli change",
    ),
    _p(NETWORK, rf"{_CMD}route\s+(?:add|del|delete|change|flush)\b", "route change"),
    _p(
        NETWORK,
        r"(?:>>?|\btee\b|\bsed\s+-i\S*)[^\n;|&]*/etc/(?:hosts|resolv\.conf)\b"
        r"|\b(?:mv|cp)\b[^\n;|&]*\s[\"']?/etc/(?:hosts|resolv\.conf)[\"']?\s*(?:$|[;&|])",
        "edits /etc/hosts or resolv.conf",
    ),
    # --- remote code execution ---
    _p(
        REMOTE_EXEC,
        r"\b(?:curl|wget|fetch)\b[^\n]*\|\s*(?:sudo\s+)?(?:ba|z|da|k|fi)?sh\b",
        "pipe download to shell",
    ),
    _p(
        REMOTE_EXEC,
        r"\b(?:ba|z|da|k)?sh\s+(?:-c\s+)?[\"']?<?\(?\$?\(?\s*(?:curl|wget)\b",
        "shell executes download",
    ),
    _p(REMOTE_EXEC, r"\beval\s+[\"']?\$\(\s*(?:curl|wget)\b", "eval of download"),
    _p(
        REMOTE_EXEC,
        r"\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:python[\d.]*|perl|ruby|node)\b",
        "pipe download to interpreter",
    ),
    _p(
        REMOTE_EXEC,
        r"\bbase64\b[^\n]*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b|(?<![\w-])eval\b",
        "eval / decoded payload run by a shell",
    ),
    # --- code hidden inside an interpreter one-liner ---
    _p(
        FILESYSTEM,
        r"\b(?:python[\d.]*|perl|ruby|node)\s+(?:-\w+\s+)*-[ce]\b[^\n]*"
        r"(?:rmtree|unlink|rmdir|remove|os\.system|subprocess|exec|spawn)",
        "interpreter one-liner that deletes or spawns commands",
    ),
    _p(FILESYSTEM, rf"{_CMD}xargs\b{_SEP}\brm\b", "xargs rm"),
    _p(FILESYSTEM, rf"{_CMD}find\b{_SEP}-exec(?:dir)?\s+(?:rm|shred)\b", "find -exec rm"),
    _p(FILESYSTEM, r"--no-preserve-root", "--no-preserve-root"),
    # The command name itself comes from a variable, so no other pattern can see what runs.
    _p(
        REMOTE_EXEC,
        r"(?:^|[;&|(]\s*|\b(?:then|do|else)\s+)[\"']?\$\{?[A-Za-z_]\w*\}?[\"']?(?:\s|$)",
        "command name taken from a variable",
    ),
]

_PS_SYS = (
    r"(?:[A-Za-z]:[\\/]+Windows\b|[A-Za-z]:[\\/]+Program\s*Files|"
    r"\$env:(?:windir|SystemRoot|ProgramFiles|ProgramFiles\(x86\)))"
)
_PS: list[_Pat] = [
    # --- privilege escalation ---
    _p(PRIVILEGE, r"-Verb\s+RunAs\b", "Start-Process -Verb RunAs", _FLAGS),
    _p(PRIVILEGE, r"(?<![\w-])runas(?:\.exe)?(?![\w-])", "runas", _FLAGS),
    _p(PRIVILEGE, r"\bSet-ExecutionPolicy\b", "Set-ExecutionPolicy", _FLAGS),
    _p(PRIVILEGE, r"(?<![\w-])(?:sudo|gsudo)(?![\w-])", "sudo", _FLAGS),
    # --- filesystem ---
    _p(
        FILESYSTEM,
        r"(?<![\w-])(?:Remove-Item|ri|rm|rmdir|rd|del|erase)\b[^\n;|]*\s-(?:Recurse|r)\b",
        "recursive Remove-Item",
        _FLAGS,
    ),
    _p(
        FILESYSTEM,
        r"(?<![\w-])(?:Remove-Item|ri|rm|rmdir|rd|del|erase|Set-Content|Add-Content|Out-File|"
        r"Copy-Item|Move-Item|New-Item|Rename-Item|Tee-Object|Set-Acl)\b"
        rf"[^\n;|]*{_PS_SYS}|>>?\s*[\"']?{_PS_SYS}",
        "modifies Windows system directory",
        _FLAGS,
    ),
    _p(
        FILESYSTEM,
        r"\b(?:Format-Volume|Clear-Disk|Initialize-Disk|Remove-Partition|New-Partition|diskpart)\b",
        "disk/format tool",
        _FLAGS,
    ),
    _p(FILESYSTEM, r"(?<![\w-])format(?:\.com)?\s+[A-Za-z]:", "format drive", _FLAGS),
    _p(
        FILESYSTEM,
        r"(?<![\w-])reg(?:\.exe)?\s+(?:add|delete|import)\b",
        "registry modification",
        _FLAGS,
    ),
    _p(
        FILESYSTEM,
        r"\b(?:Set|New|Remove|Clear)-Item(?:Property)?\b[^\n]*\bHK(?:LM|EY_LOCAL_MACHINE|CR):",
        "HKLM registry modification",
        _FLAGS,
    ),
    _p(
        FILESYSTEM,
        r"\b(?:Stop|Set|Disable|Remove|New)-Service\b|\bschtasks(?:\.exe)?\s+/(?:create|delete|change)\b"
        r"|\b(?:Register|Unregister|Set)-ScheduledTask\b",
        "service/scheduled task change",
        _FLAGS,
    ),
    # --- networking ---
    _p(
        NETWORK,
        r"\b(?:New|Set|Remove|Disable|Enable)-NetFirewall\w*|\b(?:New|Set|Remove)-NetIPAddress\b"
        r"|\b(?:New|Set|Remove)-NetRoute\b|\bSet-DnsClientServerAddress\b|\b(?:Disable|Enable)-NetAdapter\b",
        "network configuration cmdlet",
        _FLAGS,
    ),
    _p(NETWORK, r"(?<![\w-])netsh(?:\.exe)?(?![\w-])", "netsh", _FLAGS),
    _p(NETWORK, r"(?<![\w-])route(?:\.exe)?\s+(?:add|delete|change)\b", "route change", _FLAGS),
    _p(
        NETWORK,
        r"(?:>>?|Set-Content|Add-Content|Out-File)[^\n;|]*drivers[\\/]+etc[\\/]+hosts\b",
        "edits hosts file",
        _FLAGS,
    ),
    # --- remote code execution ---
    _p(REMOTE_EXEC, r"\bInvoke-Expression\b", "Invoke-Expression", _FLAGS),
    _p(REMOTE_EXEC, r"(?<![\w-])iex(?![\w-])", "iex", _FLAGS),
]


def _strip_comment(line: str, shell: str) -> str:
    """Remove a trailing ``# comment`` that is outside quotes (simple heuristic)."""
    esc = "`" if shell == "powershell" else "\\"
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == esc and quote != "'":
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
        i += 1
    return line


def _logical_lines(script: str, shell: str) -> Iterator[tuple[int, str]]:
    """Yield ``(first_lineno, text)`` with continuation lines joined.

    Backslash (bash) and backtick (PowerShell) continuations are merged so that a command split
    over several lines is scanned as one.
    """
    cont = "`" if shell == "powershell" else "\\"
    pending: list[str] = []
    start = 0
    for n, raw in enumerate(script.splitlines(), 1):
        if not pending:
            start = n
        if raw.endswith(cont) and not raw.endswith(cont * 2):
            pending.append(raw[:-1] + " ")
            continue
        pending.append(raw)
        yield start, "".join(pending)
        pending = []
    if pending:
        yield start, "".join(pending)


def _code_lines(script: str, shell: str) -> Iterator[tuple[int, str]]:
    """Yield ``(lineno, code)`` for non-comment lines."""
    in_block = False
    for n, raw in _logical_lines(script, shell):
        line = raw
        if shell == "powershell":
            if in_block:
                if "#>" in line:
                    in_block = False
                    line = line.split("#>", 1)[1]
                else:
                    continue
            while "<#" in line:
                head, _, rest = line.partition("<#")
                if "#>" in rest:
                    line = head + rest.split("#>", 1)[1]
                else:
                    line = head
                    in_block = True
        code = _strip_comment(line, shell).strip()
        if code:
            yield n, code


# A plain echo/printf of text (no redirect, pipe, chaining or substitution) runs nothing.
_INERT_BASH = re.compile(r"^(?:echo|printf)\s(?!.*\$\()[^|;&`<>]*$")


def printable(text: str) -> str:
    """Show control characters (ANSI escapes, carriage returns, ...) as escapes, not live."""
    out: list[str] = []
    for ch in text:
        if ch == "\t" or (ch.isprintable() and ch != "\x7f"):
            out.append(ch)
        elif ord(ch) < 0x100:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(f"\\u{ord(ch):04x}")
    return "".join(out)


def _short(code: str, limit: int = 100) -> str:
    return code if len(code) <= limit else code[: limit - 1] + "…"


def static_review(script: str, shell: str) -> ReviewResult:
    """Regex scan; one reason per (category, line) match."""
    if shell == "powershell":
        patterns = _PS
    elif shell == "bash":
        patterns = _BASH
    else:
        patterns = _BASH + _PS
    reasons: list[str] = []
    for n, code in _code_lines(script, shell):
        if shell == "bash" and _INERT_BASH.match(code):
            continue
        seen: set[str] = set()
        for category, regex, _label in patterns:
            if category in seen or not regex.search(code):
                continue
            seen.add(category)
            reasons.append(f"{category} (line {n}): {_short(printable(code))}")
    return ReviewResult(bool(reasons), reasons)


# --------------------------------------------------------------------------- #
# LLM review
# --------------------------------------------------------------------------- #

_LLM_SYSTEM = (
    "You are a security reviewer for shell scripts that were auto-generated and are "
    "about to be run on the user's machine. Decide whether the script is risky. A "
    "script is risky if it modifies the filesystem outside the user's working "
    "directory or home folder, deletes data irreversibly or in bulk, alters "
    "networking or firewall settings, escalates privileges, changes system or "
    "registry configuration, or downloads and executes remote code. Ordinary "
    "read-only commands and edits within the user's own scope are not risky. "
    'Respond with strict JSON only, no prose: {"risky": true|false, "reasons": '
    '["short reason", ...]}. Use an empty reasons list when not risky.'
)


def _parse_llm_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in reviewer response") from None
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict) or "risky" not in data:
        raise ValueError("reviewer response missing 'risky'")
    return data


# Jev answers typed questions with probabilities rather than free text, so the
# review is a battery of yes/no (Noul) questions, one per hazard category.
_JEV_QUESTIONS = {
    PRIVILEGE: (
        "Does `script` escalate privileges, e.g. with sudo, su, doas, pkexec or RunAs?",
        "It runs commands with elevated privileges.",
        "It runs everything as the current user.",
    ),
    FILESYSTEM: (
        "Does `script` modify or delete files outside the user's working directory and home "
        "folder, delete data recursively or in bulk, or change system configuration?",
        "It changes system-wide files or settings, or deletes data in bulk.",
        "It only reads files, or changes files within the user's own scope.",
    ),
    NETWORK: (
        "Does `script` change network, firewall, routing, DNS or hosts configuration?",
        "It alters networking configuration.",
        "It leaves networking configuration unchanged; ordinary requests are fine.",
    ),
    REMOTE_EXEC: (
        "Does `script` download code from the internet and execute it?",
        "It downloads and runs remote code.",
        "It does not execute downloaded code.",
    ),
}
JEV_THRESHOLD = 0.5


def _jev_review(script: str, shell: str, p: ProviderConfig) -> ReviewResult:
    from typesafe_sdk import Noul, NoulCriteria, TypeSafeClient

    questions = {
        category: Noul(instructions=q, criteria=NoulCriteria(true=yes, false=no))
        for category, (q, yes, no) in _JEV_QUESTIONS.items()
    }
    with TypeSafeClient(
        api_key=p.api_key, model=p.model, base_url=p.base_url, timeout=30.0
    ) as client:
        response = client.system_one(state={"shell": shell, "script": script}, questions=questions)
    reasons = [
        f"Jev review: {category} (p={answer.noul:.2f})"
        for category, answer in response.nouls.items()
        if answer.noul >= JEV_THRESHOLD
    ]
    return ReviewResult(bool(reasons), reasons)


def llm_review(script: str, shell: str, p: ProviderConfig) -> ReviewResult:
    """Ask the reviewer model; any failure fails closed (risky)."""
    if p.kind == "jev":
        try:
            return _jev_review(script, shell, p)
        except Exception as exc:  # noqa: BLE001 - fail closed on anything
            hint = " (is `ollaya serve` running?)" if is_local(p.base_url) else ""
            return ReviewResult(True, [f"Reviewer unavailable: {exc}{hint}"])
    try:
        from aiscript import llm

        user = f"Shell: {shell}\n\nScript:\n{script}"
        raw = llm.chat(p, _LLM_SYSTEM, user)
        data = _parse_llm_json(raw)
        risky = data["risky"]
        if isinstance(risky, str):
            risky = risky.strip().lower() in ("true", "yes", "1")
        risky = bool(risky)
        reasons_raw = data.get("reasons") or []
        if isinstance(reasons_raw, str):
            reasons_raw = [reasons_raw]
        reasons = [f"LLM review: {r}" for r in map(str, reasons_raw)]
        if risky and not reasons:
            reasons = ["LLM review: flagged as risky (no reason given)"]
        return ReviewResult(risky, reasons if risky else [])
    except Exception as exc:  # noqa: BLE001 - fail closed on anything
        return ReviewResult(True, [f"Reviewer unavailable: {exc}"])


def review(script: str, shell: str, reviewer: ProviderConfig | None) -> ReviewResult:
    result = static_review(script, shell)
    if reviewer is None:
        return result
    llm_result = llm_review(script, shell, reviewer)
    return ReviewResult(result.risky or llm_result.risky, result.reasons + llm_result.reasons)


# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #


def confirm(
    script: str,
    result: ReviewResult,
    *,
    input_fn: Callable[[str], str] = input,
    stdin_isatty: bool | None = None,
) -> bool:
    if not result.risky:
        return True
    if stdin_isatty is None:
        try:
            stdin_isatty = sys.stdin.isatty()
        except (AttributeError, ValueError):
            stdin_isatty = False

    def err(msg: str = "") -> None:
        print(msg, file=sys.stderr)

    err()
    err("!" * 60)
    err("WARNING: this generated script may be risky:")
    for reason in result.reasons:
        err(f"  - {printable(reason)}")
    err("!" * 60)

    if not stdin_isatty:
        err("aiscript: refusing to run a risky script in non-interactive mode.")
        return False

    lines = script.splitlines()
    width = len(str(len(lines)))
    err()
    for i, line in enumerate(lines, 1):
        err(f"{i:>{width}}  {printable(line)}")
    err()
    sys.stderr.write("Run this script? [y/N] ")
    sys.stderr.flush()
    try:
        answer = input_fn("")
    except (EOFError, KeyboardInterrupt):
        err()
        return False
    return answer.strip().lower() in ("y", "yes")
