"""Packaging: the QSIV extra is range-pinned and the base install is unchanged (S30)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict[str, object]:
    if sys.version_info < (3, 11):
        pytest.skip("tomllib needs Python 3.11")
    import tomllib

    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_given_pyproject_when_read_then_qsiv_extra_has_a_pinned_range() -> None:
    # given
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    # when / then (S30, Q9)
    assert project["optional-dependencies"]["qsiv"] == ["qsiv-runtime>=0.1,<0.2"]


def test_given_pyproject_when_read_then_qsiv_runtime_is_not_a_hard_dependency() -> None:
    # given
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    # when / then (Q9: the default install stays free of the Linux-only package)
    assert not any("qsiv" in dep for dep in project["dependencies"])


def test_given_the_import_when_aiscript_loads_then_qsiv_runtime_is_not_imported() -> None:
    # given / when
    import subprocess

    code = (
        "import sys, aiscript.cli, aiscript.reviewer, aiscript.qsiv;"
        "sys.exit('qsiv_runtime' in sys.modules)"
    )
    completed = subprocess.run([sys.executable, "-c", code], check=False)
    # then (lazy import)
    assert completed.returncode == 0
