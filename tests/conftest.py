from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_openai import FakeOpenAI


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISCRIPT_HOME", str(tmp_path / "aiscript"))
    for var in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "AISCRIPT_PROVIDER",
        "AISCRIPT_MODEL",
        "JEV_API_KEY",
        "TYPESAFE_API_KEY",
        "TYPESAFE_BASE_URL",
        "TYPESAFE_DEFAULT_MODEL",
        "OLLAYA_HOST",
        "OLLAYA_API_KEY",
        "XDG_CONFIG_HOME",
        "AISCRIPT_ASK_COUNTER",
        "QSIV_RUNTIME_MODEL_DIRECTORY",
        "QSIV_RUNTIME_PYTHON",
        "QSIV_RUNTIME_RUNTIME",
        "QSIV_RUNTIME_SOCKET_DIRECTORY",
        "QSIV_RUNTIME_IDLE_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def fake_openai() -> Iterator[FakeOpenAI]:
    with FakeOpenAI() as server:
        yield server
