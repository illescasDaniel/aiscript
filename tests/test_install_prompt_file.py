"""Offline installation and PATH behavior of the built wheel."""

from __future__ import annotations

import os
import shutil
import site
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="checks POSIX PATH and shell profiles")
def test_given_offline_wheel_install_when_path_is_configured_then_command_runs_and_profiles_stay(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required to build the project wheel offline")
    project = Path(__file__).resolve().parents[1]
    home = tmp_path / "home"
    home.mkdir()
    profiles = {
        home / ".profile": "# existing profile\n",
        home / ".bashrc": "# existing bash config\n",
        home / ".config" / "fish" / "config.fish": "# existing fish config\n",
    }
    for path, contents in profiles.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        UV_CACHE_DIR=str(tmp_path / "uv-cache"),
        PIP_NO_INDEX="1",
        PIP_CONFIG_FILE=os.devnull,
    )
    environment.pop("PYTHONPATH", None)
    environment.pop("VIRTUAL_ENV", None)
    wheels = tmp_path / "wheels"
    subprocess.run(
        [
            uv,
            "build",
            "--offline",
            "--wheel",
            "--python",
            sys.executable,
            "--out-dir",
            str(wheels),
            str(project),
        ],
        env=environment,
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheels.glob("aiscript-*.whl"))
    venv = tmp_path / "environment"
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        env=environment,
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    python = venv / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
        env=environment,
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    for path, original in profiles.items():
        assert path.read_text(encoding="utf-8") == original
    # Supply only the already-installed third-party dependencies, without adding the
    # project source directory to the subprocess import path or using the network.
    environment["PYTHONPATH"] = os.pathsep.join(site.getsitepackages())
    environment["PATH"] = str(venv / "bin") + os.pathsep + os.defpath
    result = subprocess.run(
        ["/bin/sh", "-c", "command -v aiscript && aiscript --version"],
        env=environment,
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    executable, version = result.stdout.splitlines()
    assert Path(executable) == venv / "bin" / "aiscript"
    assert version.startswith("aiscript ")
    imported = subprocess.run(
        [str(python), "-c", "import aiscript; print(aiscript.__file__)"],
        env=environment,
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert Path(imported.stdout.strip()).is_relative_to(venv)
    for path, original in profiles.items():
        assert path.read_text(encoding="utf-8") == original
