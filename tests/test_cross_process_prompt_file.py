"""Cross-platform, cross-process coverage for explicit prompt-file invocation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from aiscript.prompt_file import LocalFileBuildCache


def test_given_another_process_holds_file_lease_when_invoked_then_waits_and_runs(
    tmp_path: Path,
) -> None:
    # given: an explicit file path and a different process contending for its lease
    source = tmp_path / "prompt file"
    source.write_text("print the arguments", encoding="utf-8")
    cache_home = tmp_path / "aiscript-home"
    env = {**os.environ, "AISCRIPT_HOME": str(cache_home)}
    child = """
import sys
from contextlib import contextmanager
from aiscript import cli, llm, prompt_file
from aiscript.config import ProviderConfig, Settings
original_lock = prompt_file._lock
@contextmanager
def announced_lock(path):
    print("attempting", flush=True)
    with original_lock(path):
        yield
prompt_file._lock = announced_lock
cli.load_settings = lambda: Settings(ProviderConfig("fake", "key", None, "m"), None)
llm.generate_script = lambda provider, name, intent: llm.GeneratedScript(
    "import sys\\nprint('child args:', repr(sys.argv[1:]))\\n", "python", []
)
sys.exit(cli.main([sys.argv[1], "space value", "--flag"]))
"""
    cache = LocalFileBuildCache()
    process: subprocess.Popen[str] | None = None
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("AISCRIPT_HOME", str(cache_home))
            with cache.acquire(source.resolve()):
                process = subprocess.Popen(
                    [sys.executable, "-u", "-c", child, str(source)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                )
                assert process.stdout is not None
                assert process.stdout.readline().strip() == "attempting"
                # when: the child attempts the explicit file invocation
                with pytest.raises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.5)
            # then: releasing the lease lets it generate and run the program
            stdout, stderr = process.communicate(timeout=20)
            assert process.returncode == 0, stderr
            assert "child args: ['space value', '--flag']" in stdout
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
