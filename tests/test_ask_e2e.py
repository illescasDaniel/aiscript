"""End to end: real subprocesses through runner.run_script against the loopback fake server."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from fake_openai import FakeOpenAI, chat_reply

from aiscript import paths, runner

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")

SCHEMA = (
    '{"type": "object", "properties": {"a": {"type": "string"}},'
    ' "required": ["a"], "additionalProperties": false}'
)

SHELL_LOOP = """#!/usr/bin/env bash
for i in 1 2 3; do
  printf 'data' | aiscript --ask "t" --data-description "d" >/dev/null 2>&1
  echo "rc$i=$?"
done
"""

PY_LOOP = """import aiscript
for i in (1, 2, 3):
    try:
        aiscript.ask("t", "data", "d")
        print("rc%d=0" % i)
    except aiscript.AskError as exc:
        print("rc%d=%d %s" % (i, exc.exit_code, type(exc).__name__))
"""


def write_config(url: str, max_calls: int = 1) -> None:
    home = paths.aiscript_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "default_provider: fake\n"
        f"providers:\n  fake: {{base_url: '{url}', model: fake-model, api: chat}}\n"
        f"ai: {{max_calls_per_run: {max_calls}}}\n"
    )


@pytest.fixture
def launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp bin/aiscript running this checkout's package, first on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "aiscript"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m aiscript "$@"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


def script(tmp_path: Path, body: str, name: str = "s.py") -> Path:
    p = tmp_path / name
    p.write_text(body)
    p.chmod(0o755)
    return p


def lines(capfd: pytest.CaptureFixture[str]) -> list[str]:
    return capfd.readouterr().out.splitlines()


@pytest.mark.parametrize("existing", [None, "/some/existing/path"])
def test_given_python_script_when_run_then_shim_is_imported_and_ask_returns_str_and_dict(
    tmp_path: Path,
    fake_openai: FakeOpenAI,
    launcher: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    existing: str | None,
) -> None:
    # given
    write_config(fake_openai.base_url, max_calls=2)
    fake_openai.enqueue(chat_reply("12 updates"), chat_reply('{"a": "x"}'))
    if existing:
        monkeypatch.setenv("PYTHONPATH", existing)
    else:
        monkeypatch.delenv("PYTHONPATH", raising=False)
    body = (
        "import json, os, aiscript\n"
        "print(aiscript.__file__)\n"
        "print(os.environ.get('PYTHONPATH'))\n"
        "r = aiscript.ask('t', 'data', 'd')\n"
        "print(type(r).__name__, r)\n"
        f"s = aiscript.ask('t', 'data', 'd', schema=json.loads({SCHEMA!r}))\n"
        "print(type(s).__name__, json.dumps(s))\n"
    )
    # when
    rc = runner.run_script(script(tmp_path, body), [])
    # then
    out = lines(capfd)
    assert rc == 0
    assert out[0].startswith(str(runner.SHIM_DIR))
    assert out[1].split(os.pathsep)[0] == str(runner.SHIM_DIR)
    if existing:
        assert existing in out[1].split(os.pathsep)
    assert out[2] == "str 12 updates"
    assert out[3] == 'dict {"a": "x"}'
    assert len(fake_openai.requests) == 2


def test_given_bash_script_piping_data_when_run_then_ask_prints_the_answer(
    tmp_path: Path, fake_openai: FakeOpenAI, launcher: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # given
    write_config(fake_openai.base_url)
    fake_openai.enqueue(chat_reply("12 updates"))
    body = (
        "#!/usr/bin/env bash\n"
        "printf 'pkg list' | aiscript --ask 'summarise' --data-description 'pkgs'\n"
    )
    # when
    rc = runner.run_script(script(tmp_path, body, "s.sh"), [])
    # then
    assert rc == 0
    assert capfd.readouterr().out.strip() == "12 updates"
    assert len(fake_openai.requests) == 1


@pytest.mark.parametrize(
    ("cap", "expected"),
    [(1, ["rc1=0", "rc2=9", "rc3=9"]), (2, ["rc1=0", "rc2=0", "rc3=9"])],
)
def test_given_call_cap_when_shell_script_calls_repeatedly_then_calls_past_the_cap_exit_9(
    tmp_path: Path,
    fake_openai: FakeOpenAI,
    launcher: Path,
    capfd: pytest.CaptureFixture[str],
    cap: int,
    expected: list[str],
) -> None:
    # given
    write_config(fake_openai.base_url, max_calls=cap)
    fake_openai.enqueue(*[chat_reply("ok")] * 3)
    # when
    rc = runner.run_script(script(tmp_path, SHELL_LOOP, "s.sh"), [])
    # then
    assert rc == 0
    assert lines(capfd) == expected
    assert len(fake_openai.requests) == cap


@pytest.mark.parametrize(
    ("cap", "expected"),
    [
        (1, ["rc1=0", "rc2=9 AskCapError", "rc3=9 AskCapError"]),
        (2, ["rc1=0", "rc2=0", "rc3=9 AskCapError"]),
    ],
)
def test_given_call_cap_when_python_script_calls_repeatedly_then_calls_past_the_cap_raise(
    tmp_path: Path,
    fake_openai: FakeOpenAI,
    launcher: Path,
    capfd: pytest.CaptureFixture[str],
    cap: int,
    expected: list[str],
) -> None:
    # given
    write_config(fake_openai.base_url, max_calls=cap)
    fake_openai.enqueue(*[chat_reply("ok")] * 3)
    # when
    rc = runner.run_script(script(tmp_path, PY_LOOP), [])
    # then
    assert rc == 0
    assert lines(capfd) == expected
    assert len(fake_openai.requests) == cap


def test_given_no_aiscript_on_path_when_python_script_asks_then_not_found_and_nothing_sent(
    tmp_path: Path,
    fake_openai: FakeOpenAI,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # given
    write_config(fake_openai.base_url)
    only_python = tmp_path / "only-python"
    only_python.mkdir()
    python = shutil.which("python3") or sys.executable
    (only_python / "python3").symlink_to(python)
    monkeypatch.setenv("PATH", str(only_python))
    body = (
        "import aiscript\n"
        "try:\n"
        "    aiscript.ask('t', 'd', 'd')\n"
        "except aiscript.AskNotFoundError as exc:\n"
        "    print('notfound', exc.exit_code)\n"
    )
    # when
    rc = runner.run_script(script(tmp_path, body), [])
    # then
    assert rc == 0
    assert lines(capfd) == ["notfound 127"]
    assert fake_openai.requests == []


def test_given_routing_variables_in_the_environment_when_asking_then_the_yaml_server_is_used(
    tmp_path: Path,
    fake_openai: FakeOpenAI,
    launcher: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # given
    with FakeOpenAI() as elsewhere:
        write_config(fake_openai.base_url)
        fake_openai.enqueue(chat_reply("from yaml"))
        monkeypatch.setenv("OPENAI_BASE_URL", elsewhere.base_url)
        monkeypatch.setenv("AISCRIPT_PROVIDER", "other")
        monkeypatch.setenv("AISCRIPT_MODEL", "other-model")
        body = "#!/usr/bin/env bash\nprintf 'x' | aiscript --ask 't' --data-description 'd'\n"
        # when
        rc = runner.run_script(script(tmp_path, body, "s.sh"), [])
        # then
        assert rc == 0
        assert capfd.readouterr().out.strip() == "from yaml"
        assert len(fake_openai.requests) == 1
        assert fake_openai.requests[0].body["model"] == "fake-model"
        assert elsewhere.requests == []


PROJECT_SCRIPT = (
    "import aiscript\nprint(aiscript.__file__)\nprint(aiscript.ask('t', 'data', 'd'))\n"
)


def _run_project(tmp_path: Path, fake_openai: FakeOpenAI, make_venv: list[str]) -> list[str]:
    write_config(fake_openai.base_url)
    fake_openai.enqueue(chat_reply("from venv"))
    project = paths.functions_dir() / "proj"
    project.mkdir(parents=True)
    subprocess.run([*make_venv, str(project / ".venv")], check=True, capture_output=True)
    main = project / "main.py"
    main.write_text(PROJECT_SCRIPT)
    return [str(main)]


def test_given_project_venv_script_when_run_then_the_shim_is_imported_and_ask_works(
    tmp_path: Path,
    fake_openai: FakeOpenAI,
    launcher: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # given
    [main] = _run_project(tmp_path, fake_openai, [sys.executable, "-m", "venv", "--without-pip"])
    # when
    rc = runner.run_script(Path(main), [])
    # then
    out = lines(capfd)
    assert rc == 0
    assert out[0].startswith(str(runner.SHIM_DIR))
    assert out[1] == "from venv"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_given_uv_venv_script_when_run_then_the_shim_is_imported_and_ask_works(
    tmp_path: Path,
    fake_openai: FakeOpenAI,
    launcher: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # given
    [main] = _run_project(tmp_path, fake_openai, ["uv", "venv", "--quiet"])
    # when
    rc = runner.run_script(Path(main), [])
    # then
    out = lines(capfd)
    assert rc == 0
    assert out[0].startswith(str(runner.SHIM_DIR))
    assert out[1] == "from venv"
