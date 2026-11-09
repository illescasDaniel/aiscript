"""Verify the README's executable examples remain usable by a POSIX shell."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name == "nt", reason="README describes POSIX shebang and shell commands")
def test_given_readme_setup_when_followed_then_path_and_shebang_examples_work(
    tmp_path: Path,
) -> None:
    # given: the actual installation and prompt-file guidance from the README
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    install = readme.split("## Install", 1)[1].split("## Quickstart", 1)[0]
    prompt_files = readme.split("## Executable prompt files", 1)[1].split("## Safety review", 1)[0]
    availability = re.search(r"```sh\s*\n(command -v [^\n]+)\n```", install)
    assert availability is not None, "README must show how to check command availability"
    setups = re.findall(r"`((?:uv tool update-shell|pipx ensurepath))`\s+for\s+(uv|pipx)", install)
    assert dict((installer, command) for command, installer in setups) == {
        "uv": "uv tool update-shell",
        "pipx": "pipx ensurepath",
    }
    # pip may install to different bin directories; its guidance must describe
    # adding the installed executable's directory to the shell's PATH.
    pip_guidance = re.search(
        r"With pip,\s+add the directory containing its installed\s+`aiscript` executable "
        r"to your PATH using your shell's configuration",
        install,
    )
    assert pip_guidance is not None, "README must explain pip-specific PATH setup"
    absolute = re.search(r"`(#!/[^\s`]+/aiscript)`", prompt_files)
    assert absolute is not None, "README must show an absolute aiscript shebang"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "setup.log"
    for executable in ("uv", "pipx"):
        stub = bin_dir / executable
        stub.write_text(
            '#!/bin/sh\nprintf "%s %s\\n" "$0" "$*" >> "$SETUP_LOG"\n', encoding="utf-8"
        )
        stub.chmod(0o755)
    interpreter = bin_dir / "aiscript"
    interpreter.write_text('#!/bin/sh\nprintf "interpreter:%s\\n" "$1"\n', encoding="utf-8")
    interpreter.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir), "SETUP_LOG": str(log)}

    # when: executing the documented check and installer commands with isolated stubs
    found = subprocess.run(
        ["/bin/sh", "-c", availability.group(1)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    for command, _installer in setups:
        subprocess.run(["/bin/sh", "-c", command], env=env, check=True)

    # then: the check finds the command and both setup commands are dispatched correctly
    assert found.stdout.strip() == str(interpreter)
    assert log.read_text(encoding="utf-8").splitlines() == [
        f"{bin_dir / 'uv'} tool update-shell",
        f"{bin_dir / 'pipx'} ensurepath",
    ]

    # The documented absolute path is an example; substitute the installed interpreter path.
    shebang = absolute.group(1).replace(absolute.group(1)[2:], str(interpreter))
    prompt = tmp_path / "biggest"
    prompt.write_text(f"{shebang}\nList folders.\n", encoding="utf-8")
    prompt.chmod(0o755)
    result = subprocess.run([str(prompt)], env=env, capture_output=True, text=True, check=True)
    assert result.stdout == f"interpreter:{prompt}\n"
