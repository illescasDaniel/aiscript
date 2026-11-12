"""Per-run call cap (F13), shared by the runner and ``--ask``."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from aiscript.ask import CallCounter

COUNTER_ENV: Final = "AISCRIPT_ASK_COUNTER"


@contextmanager
def run_counter() -> Iterator[Path]:
    """Private temp directory for one script run, removed in a ``finally``."""
    directory = Path(tempfile.mkdtemp(prefix="aiscript-ask-"))  # mode 0700
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class SlotCounter:
    """``claim`` creates slot files ``1``..``limit`` with ``O_CREAT|O_EXCL``; no locks."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def claim(self, limit: int) -> bool:
        for slot in range(1, limit + 1):
            try:
                fd = os.open(self._directory / str(slot), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            except OSError:  # missing or unwritable directory: fail closed
                return False
            os.close(fd)
            return True
        return False


class UncappedCounter:
    """No counter variable (direct terminal call): every claim succeeds."""

    def claim(self, limit: int) -> bool:
        return True


def counter_from_env(environ: Mapping[str, str]) -> CallCounter:
    """``SlotCounter`` when ``COUNTER_ENV`` is set, else ``UncappedCounter``."""
    directory = environ.get(COUNTER_ENV)
    return SlotCounter(Path(directory)) if directory else UncappedCounter()
