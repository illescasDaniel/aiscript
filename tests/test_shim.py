import ast
import importlib.util
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from aiscript.errors import ASK_EXIT_CODES
from aiscript.runner import SHIM_DIR

SHIM_FILE = SHIM_DIR / "aiscript" / "__init__.py"


@pytest.fixture
def shim() -> ModuleType:
    # Loaded under another name: the real `aiscript` package is importable in the test run.
    spec = importlib.util.spec_from_file_location("aiscript_shim_under_test", SHIM_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Spawns:
    """Replaces the child boundary: records calls and returns a scripted result."""

    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(
        self, args: list[str], data: bytes, env: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((list(args), {"input": data, "env": env}))
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)


@pytest.fixture
def on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake `aiscript` executable first on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / ("aiscript.bat" if sys.platform == "win32" else "aiscript")
    exe.write_text("@echo off\n" if sys.platform == "win32" else "#!/bin/sh\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


@pytest.fixture
def spawns(
    monkeypatch: pytest.MonkeyPatch, on_path: Path, shim: ModuleType
) -> Callable[..., Spawns]:
    def install(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> Spawns:
        fake = Spawns(returncode, stdout, stderr)
        monkeypatch.setattr(shim, "_run_child", fake)
        return fake

    return install


def test_given_empty_path_when_asking_then_not_found_error_and_nothing_spawned(
    shim: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("PATH", "")
    fake = Spawns()
    monkeypatch.setattr(shim, "_run_child", fake)
    # when
    with pytest.raises(shim.AskNotFoundError) as info:
        shim.ask("task", "data", "desc")
    # then
    assert info.value.exit_code == 127
    assert "PATH" in str(info.value)
    assert "install" in str(info.value).lower()
    assert fake.calls == []


def test_given_bytes_data_when_asking_then_usage_error_and_nothing_spawned(
    shim: ModuleType, spawns: Callable[..., Spawns]
) -> None:
    # given
    fake = spawns()
    # when
    with pytest.raises(shim.AskUsageError):
        shim.ask("task", b"raw", "desc")
    # then
    assert fake.calls == []


def test_given_unserialisable_schema_when_asking_then_usage_error_and_nothing_spawned(
    shim: ModuleType, spawns: Callable[..., Spawns]
) -> None:
    # given
    fake = spawns()
    # when
    with pytest.raises(shim.AskUsageError):
        shim.ask("task", "data", "desc", {"type": object()})
    # then
    assert fake.calls == []


def test_given_text_call_when_asking_then_argv_and_stdin_follow_the_command_contract(
    shim: ModuleType, spawns: Callable[..., Spawns]
) -> None:
    # given
    fake = spawns(stdout=b"answer\n")
    # when
    shim.ask("summarise it", "héllo", "a greeting")
    # then
    argv, kwargs = fake.calls[0]
    assert argv[1:] == ["--ask=summarise it", "--data-description=a greeting"]
    assert kwargs["input"] == "héllo".encode()


def test_given_schema_call_when_asking_then_compact_schema_is_passed_and_dict_returned(
    shim: ModuleType, spawns: Callable[..., Spawns]
) -> None:
    # given
    fake = spawns(stdout=b'{"a":"x"}\n')
    # when
    result = shim.ask("t", "d", "desc", {"type": "object"})
    # then
    assert fake.calls[0][0][1:] == [
        "--ask=t",
        "--data-description=desc",
        '--schema={"type":"object"}',
    ]
    assert result == {"a": "x"}


def test_given_shim_on_pythonpath_when_asking_then_child_env_drops_the_shim_root(
    shim: ModuleType, spawns: Callable[..., Spawns], monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    root = str(SHIM_FILE.parent.parent)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([root, "/keep/me"]))
    fake = spawns(stdout=b"ok")
    # when
    shim.ask("t", "d", "desc")
    # then
    entries = fake.calls[0][1]["env"].get("PYTHONPATH", "").split(os.pathsep)
    assert root not in entries
    assert "/keep/me" in entries


@pytest.mark.parametrize("name", [n for n in ASK_EXIT_CODES if n != "AskNotFoundError"])
def test_given_exit_code_when_asking_then_matching_error_with_bounded_stderr(
    shim: ModuleType, spawns: Callable[..., Spawns], name: str
) -> None:
    # given
    spawns(returncode=ASK_EXIT_CODES[name], stderr=b"boom-marker " + b"x" * 10_000)
    # when
    with pytest.raises(getattr(shim, name)) as info:
        shim.ask("t", "d", "desc")
    # then
    assert type(info.value) is getattr(shim, name)
    assert info.value.exit_code == ASK_EXIT_CODES[name]
    assert "boom-marker" in str(info.value)
    assert len(str(info.value)) < 2000


def test_given_unknown_exit_code_when_asking_then_ask_error_keeps_the_value(
    shim: ModuleType, spawns: Callable[..., Spawns]
) -> None:
    # given
    spawns(returncode=42, stderr=b"weird")
    # when
    with pytest.raises(shim.AskError) as info:
        shim.ask("t", "d", "desc")
    # then
    assert info.value.exit_code == 42


def test_given_utf8_output_when_asking_then_exactly_one_trailing_newline_is_stripped(
    shim: ModuleType, spawns: Callable[..., Spawns]
) -> None:
    # given
    spawns(stdout="línea\n\n".encode())
    # when
    result = shim.ask("t", "d", "desc")
    # then
    assert result == "línea\n"


def test_given_old_aiscript_on_path_when_asking_then_usage_error_names_version_1_4_0(
    shim: ModuleType, spawns: Callable[..., Spawns]
) -> None:
    # given
    spawns(returncode=2, stderr=b"aiscript: error: unrecognized arguments: --ask=t")
    # when
    with pytest.raises(shim.AskUsageError) as info:
        shim.ask("t", "d", "desc")
    # then
    assert "1.4.0" in str(info.value)
    assert "older" in str(info.value)


def test_given_the_two_tables_then_errors_py_equals_the_shim(shim: ModuleType) -> None:
    # then
    assert dict(ASK_EXIT_CODES) == shim.EXIT_CODES
    for name, code in ASK_EXIT_CODES.items():
        assert getattr(shim, name).exit_code == code


def test_given_the_shim_source_then_it_parses_as_python_3_8() -> None:
    # then
    ast.parse(SHIM_FILE.read_text(encoding="utf-8"), feature_version=(3, 8))


def test_given_schema_json_then_it_round_trips(
    shim: ModuleType, spawns: Callable[..., Spawns]
) -> None:
    # given
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    fake = spawns(stdout=b"{}")
    # when
    shim.ask("t", "d", "desc", schema)
    # then
    sent = fake.calls[0][0][-1]
    assert sent.startswith("--schema=")
    assert json.loads(sent[len("--schema=") :]) == schema
    assert " " not in sent


class _TimedStderr:
    """Records when each write reaches the shim's stderr."""

    def __init__(self) -> None:
        self.writes: list[tuple[float, str]] = []

    def write(self, text: str) -> int:
        self.writes.append((time.time(), text))
        return len(text)

    def flush(self) -> None:
        pass

    @property
    def text(self) -> str:
        return "".join(text for _, text in self.writes)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable script")
def test_given_real_child_when_it_announces_then_notice_arrives_early_once_and_noise_is_dropped(
    shim: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    finished = tmp_path / "finished"
    notice = "aiscript: This request can take up to 120 seconds.\n"
    exe = bin_dir / "aiscript"
    exe.write_text(
        f"#!{sys.executable}\n"
        "import sys, time\n"
        "sys.stdin.read()\n"
        f"sys.stderr.write({notice!r}); sys.stderr.flush()\n"
        "sys.stderr.write('CHILD-NOISE private detail\\n')\n"
        f"sys.stderr.write({notice!r}); sys.stderr.flush()\n"
        "time.sleep(1.0)\n"
        f"open({str(finished)!r}, 'w').write(str(time.time()))\n"
        "sys.stdout.write('answer\\n')\n"
    )
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_dir))
    recorder = _TimedStderr()
    monkeypatch.setattr(shim.sys, "stderr", recorder)
    # when
    answer = shim.ask("task", "data", "desc")
    # then
    done_at = float(finished.read_text())
    assert answer == "answer"
    assert recorder.text == notice
    assert recorder.writes[0][0] < done_at - 0.5
    assert "CHILD-NOISE" not in recorder.text
