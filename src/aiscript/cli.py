"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys

from aiscript import __version__, builder, paths
from aiscript.config import load_settings
from aiscript.errors import AiscriptError
from aiscript.init_cmd import run_init
from aiscript.listing import list_commands
from aiscript.runner import run_script

_HELP = """\
usage: aiscript NAME [args...]       run a command (created/built on first use)
       aiscript --init               create config dir and config.yaml template
       aiscript --list               list commands
       aiscript --edit NAME          edit a command's prompt (rebuilds on next run)
       aiscript --rebuild NAME       regenerate a command's script (does not run it)
       aiscript --remove NAME        delete a command's prompt and script(s)
       aiscript --help | --version

Everything after NAME is passed untouched to the generated script.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiscript", add_help=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", action="store_true")
    group.add_argument("--list", action="store_true")
    group.add_argument("--edit", metavar="NAME")
    group.add_argument("--rebuild", metavar="NAME")
    group.add_argument("--remove", metavar="NAME")
    group.add_argument("--help", "-h", action="store_true")
    group.add_argument("--version", action="store_true")
    return parser


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _editor_command() -> list[str]:
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var, "").strip()
        if value:
            return shlex.split(value, posix=not paths.is_windows())
    if paths.is_windows():
        return ["notepad"]
    for candidate in ("nano", "vi"):
        if shutil.which(candidate):
            return [candidate]
    raise AiscriptError("No editor found; set $VISUAL or $EDITOR.")


def _edit(name: str) -> int:
    paths.validate_command_name(name)
    ppath = paths.prompt_path(name)
    if not ppath.exists():
        raise AiscriptError(f"No prompt for {name!r}. Run `aiscript {name}` to create it.")
    before = ppath.stat().st_mtime_ns
    cmd = [*_editor_command(), str(ppath)]
    try:
        proc = subprocess.run(cmd)
    except OSError as exc:
        raise AiscriptError(f"Could not launch editor {cmd[0]!r}: {exc}") from exc
    if proc.returncode != 0:
        _err(f"aiscript: editor exited with status {proc.returncode}")
    if ppath.stat().st_mtime_ns != before:
        _err(f"Prompt for {name!r} changed; it will be rebuilt on next run.")
    else:
        _err(f"Prompt for {name!r} unchanged.")
    return 0


def _rebuild(name: str) -> int:
    paths.validate_command_name(name)
    paths.ensure_dirs()
    if not paths.prompt_path(name).exists():
        raise AiscriptError(f"No prompt for {name!r}. Run `aiscript {name}` to create it.")
    # build() replaces the cached script atomically, so a failed or rejected
    # rebuild keeps the previous version.
    print(builder.build(name, load_settings()))
    return 0


def _remove(name: str) -> int:
    paths.validate_command_name(name)
    targets = [p for p in (paths.prompt_path(name), *paths.function_artifacts(name)) if p.exists()]
    if not targets:
        raise AiscriptError(f"No command named {name!r}.")
    for path in targets:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            raise AiscriptError(f"Could not remove {path}: {exc}") from exc
        _err(f"Removed {path}")
    return 0


def _run_command(name: str, args: list[str]) -> int:
    paths.validate_command_name(name)
    paths.ensure_dirs()
    ppath = paths.prompt_path(name)
    if not ppath.exists():
        sys.stderr.write(f"Command not found. What should '{name}' do? ")
        sys.stderr.flush()
        try:
            answer = input("").strip()
        except EOFError:
            answer = ""
        if not answer:
            _err("")
            raise AiscriptError("No description given; nothing saved.")
        ppath.write_text(answer + "\n", encoding="utf-8")
    if builder.needs_build(name):
        builder.build(name, load_settings())
    return run_script(paths.function_path(name), args)


def _dispatch(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(_HELP)
        return 2
    if argv[0].startswith("-"):
        try:
            ns = _build_parser().parse_args(argv)
        except SystemExit:
            return 2
        if ns.help:
            sys.stderr.write(_HELP)
            return 0
        if ns.version:
            print(f"aiscript {__version__}")
            return 0
        if ns.init:
            return run_init()
        if ns.list:
            return list_commands()
        if ns.edit is not None:
            return _edit(ns.edit)
        if ns.remove is not None:
            return _remove(ns.remove)
        return _rebuild(ns.rebuild)
    return _run_command(argv[0], argv[1:])


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return _dispatch(args)
    except AiscriptError as exc:
        _err(f"aiscript: error: {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        _err("")
        return 130
