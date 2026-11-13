"""Python shim for AI calls inside generated scripts (stdlib only, Python >= 3.8).

``ask()`` runs ``aiscript --ask=TASK`` as a subprocess with the data on stdin.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional, Union

_STDERR_LIMIT = 500


class AskError(Exception):
    """Base class of every failure of ``ask()``; ``exit_code`` is the aiscript exit code."""

    exit_code = 1


class AskUsageError(AskError):
    exit_code = 2


class AskConfigError(AskError):
    exit_code = 3


class AskInputError(AskError):
    exit_code = 4


class AskProviderError(AskError):
    exit_code = 5


class AskRateLimitError(AskError):
    exit_code = 6


class AskRefusalError(AskError):
    exit_code = 7


class AskOutputError(AskError):
    exit_code = 8


class AskCapError(AskError):
    exit_code = 9


class AskNotFoundError(AskError):
    exit_code = 127


EXIT_CODES = {
    "AskUsageError": 2,
    "AskConfigError": 3,
    "AskInputError": 4,
    "AskProviderError": 5,
    "AskRateLimitError": 6,
    "AskRefusalError": 7,
    "AskOutputError": 8,
    "AskCapError": 9,
    "AskNotFoundError": 127,
}


def _shim_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _child_env() -> Dict[str, str]:
    """Environment for the real aiscript: this shim's directory is removed from PYTHONPATH."""
    env = dict(os.environ)
    root = os.path.normcase(_shim_root())
    entries = [
        e
        for e in env.get("PYTHONPATH", "").split(os.pathsep)
        if e and os.path.normcase(os.path.abspath(e)) != root
    ]
    if entries:
        env["PYTHONPATH"] = os.pathsep.join(entries)
    else:
        env.pop("PYTHONPATH", None)
    return env


def _error_for(code: int, stderr: bytes) -> AskError:
    detail = stderr.decode("utf-8", errors="replace").strip()
    if len(detail) > _STDERR_LIMIT:
        detail = detail[:_STDERR_LIMIT] + "..."
    if code == 2 and "unrecognized arguments" in detail:
        return AskUsageError(
            "The aiscript on PATH is older than 1.4.0 and has no --ask; upgrade aiscript."
        )
    message = f"aiscript --ask failed (exit {code}): {detail}"
    for name, known in EXIT_CODES.items():
        if known == code:
            return globals()[name](message)
    error = AskError(message)
    error.exit_code = code
    return error


def _run_child(argv: List[str], data: bytes, env: Dict[str, str]) -> subprocess.CompletedProcess:
    """Stream only the known status while subprocess.run drains stdout and stdin."""
    read_fd, write_fd = os.pipe()
    stderr = bytearray()
    notice = re.compile(
        rb"aiscript: (?:This request can take up to [0-9]+ seconds\.|"
        rb"Timeout [0-9]+ seconds per attempt; retries may take longer\.)\r?\n$"
    )

    def read_errors() -> None:
        shown = False
        with os.fdopen(read_fd, "rb") as stream:
            while True:
                line = stream.readline(1024)
                if not line:
                    break
                if not shown and notice.fullmatch(line):
                    sys.stderr.write(line.decode("ascii"))
                    sys.stderr.flush()
                    shown = True
                elif line.startswith(b"aiscript: error: ") and len(stderr) < _STDERR_LIMIT:
                    stderr.extend(line[: _STDERR_LIMIT - len(stderr)])

    thread = threading.Thread(target=read_errors, daemon=True)
    thread.start()
    try:
        result = subprocess.run(argv, input=data, stdout=subprocess.PIPE, stderr=write_fd, env=env)
    finally:
        os.close(write_fd)
        thread.join()
    return subprocess.CompletedProcess(argv, result.returncode, result.stdout, bytes(stderr))


def ask(
    task: str,
    data: str,
    data_description: str,
    schema: Optional[Dict[str, Any]] = None,
) -> Union[str, Dict[str, Any]]:
    """Run ``aiscript --ask`` and return its answer (a string, or a dict with a schema)."""
    if not isinstance(task, str) or not task.strip():
        raise AskUsageError("task must be a non-empty string")
    if not isinstance(data_description, str) or not data_description.strip():
        raise AskUsageError("data_description must be a non-empty string")
    if not isinstance(data, str):
        raise AskUsageError("data must be a str (decode bytes first)")
    args = ["--ask=" + task, "--data-description=" + data_description]
    if schema is not None:
        try:
            args.append("--schema=" + json.dumps(schema, separators=(",", ":")))
        except (TypeError, ValueError) as exc:
            raise AskUsageError(f"schema is not JSON serialisable: {exc}") from None
    exe = shutil.which("aiscript")
    if exe is None:
        raise AskNotFoundError(
            "aiscript was not found on PATH; install aiscript so that `aiscript` is on PATH."
        )
    proc = _run_child([exe] + args, data.encode("utf-8"), _child_env())
    if proc.returncode != 0:
        raise _error_for(proc.returncode, proc.stderr)
    out = proc.stdout.decode("utf-8")
    if out.endswith("\n"):
        out = out[:-1]
    if schema is None:
        return out
    try:
        result = json.loads(out)
    except ValueError:
        raise AskOutputError("aiscript returned invalid JSON for the schema") from None
    if not isinstance(result, dict):
        raise AskOutputError("aiscript returned JSON that is not an object")
    return result
