"""Test doubles shared by several test modules."""

from typing import TypeVar

from aiscript.config import ProviderConfig

T = TypeVar("T")


def need(value: T | None) -> T:
    """Narrow an Optional for the type checker and fail clearly if it is None."""
    assert value is not None
    return value


class TTY:
    """Fake interactive stdin; answers are consumed by ``input()`` via readline."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        return self.answers.pop(0) + "\n"


class FakeLLM:
    """Stand-in for ``llm.generate_script`` that records calls."""

    def __init__(self, script: str) -> None:
        self.script = script
        self.calls: list[tuple[str, str]] = []

    def __call__(self, p: ProviderConfig, name: str, intent: str) -> str:
        self.calls.append((name, intent))
        return self.script
