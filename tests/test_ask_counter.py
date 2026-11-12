import subprocess
import sys
import threading
from pathlib import Path

import pytest

from aiscript.ask_counter import (
    COUNTER_ENV,
    SlotCounter,
    UncappedCounter,
    counter_from_env,
    run_counter,
)

CLAIM_SCRIPT = """
import sys
from pathlib import Path
from aiscript.ask_counter import SlotCounter

print(SlotCounter(Path(sys.argv[1])).claim(1))
"""


def test_given_limit_one_when_claiming_twice_then_second_is_refused(tmp_path: Path) -> None:
    # given
    counter = SlotCounter(tmp_path)
    # when
    results = [counter.claim(1), counter.claim(1)]
    # then
    assert results == [True, False]


def test_given_limit_two_when_claiming_three_times_then_third_is_refused(tmp_path: Path) -> None:
    # given
    counter = SlotCounter(tmp_path)
    # when
    results = [counter.claim(2) for _ in range(3)]
    # then
    assert results == [True, True, False]


def test_given_one_directory_when_two_counters_claim_then_they_share_slots(tmp_path: Path) -> None:
    # given
    first, second = SlotCounter(tmp_path), SlotCounter(tmp_path)
    # when
    results = [first.claim(1), second.claim(1)]
    # then
    assert results == [True, False]


def test_given_missing_directory_when_claiming_then_it_fails_closed(tmp_path: Path) -> None:
    # given
    counter = SlotCounter(tmp_path / "gone")
    # when
    result = counter.claim(1)
    # then
    assert result is False


def test_given_eight_threads_racing_on_limit_one_then_exactly_one_wins(tmp_path: Path) -> None:
    # given
    counter = SlotCounter(tmp_path)
    barrier = threading.Barrier(8)
    results: list[bool] = []

    def worker() -> None:
        barrier.wait()
        results.append(counter.claim(1))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    # when
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # then
    assert len(results) == 8
    assert results.count(True) == 1


def test_given_eight_processes_racing_on_limit_one_then_exactly_one_wins(tmp_path: Path) -> None:
    # given
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CLAIM_SCRIPT, str(tmp_path)],
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    # when
    outputs = [p.communicate()[0].strip() for p in procs]
    # then
    assert outputs.count("True") == 1
    assert outputs.count("False") == 7


def test_given_run_counter_when_entered_then_a_private_directory_exists() -> None:
    # when
    with run_counter() as directory:
        # then
        assert directory.is_dir()
        if sys.platform != "win32":  # POSIX modes are not meaningful on Windows
            assert (directory.stat().st_mode & 0o077) == 0
        assert list(directory.iterdir()) == []


def test_given_run_counter_when_left_then_directory_and_slots_are_removed(tmp_path: Path) -> None:
    # given
    with run_counter() as directory:
        SlotCounter(directory).claim(1)
        assert (directory / "1").exists()
    # then
    assert not directory.exists()


class BodyError(Exception):
    pass


def test_given_run_counter_when_body_raises_then_directory_is_removed() -> None:
    # when
    with pytest.raises(BodyError), run_counter() as directory:
        raise BodyError("boom")
    # then
    assert not directory.exists()


def test_given_run_counter_when_interrupted_then_directory_is_removed() -> None:
    # when
    with pytest.raises(KeyboardInterrupt), run_counter() as directory:
        raise KeyboardInterrupt
    # then
    assert not directory.exists()


def test_given_two_runs_then_counter_directories_differ() -> None:
    # when
    with run_counter() as first, run_counter() as second:
        # then
        assert first != second


def test_given_uncapped_counter_when_claiming_many_times_then_always_true() -> None:
    # given
    counter = UncappedCounter()
    # when / then
    assert all(counter.claim(1) for _ in range(5))


def test_given_no_counter_variable_when_building_from_env_then_uncapped() -> None:
    # when
    counter = counter_from_env({"PATH": "/usr/bin"})
    # then
    assert isinstance(counter, UncappedCounter)


def test_given_counter_variable_when_building_from_env_then_slot_counter(tmp_path: Path) -> None:
    # when
    counter = counter_from_env({COUNTER_ENV: str(tmp_path)})
    # then
    assert isinstance(counter, SlotCounter)
    assert [counter.claim(1), counter.claim(1)] == [True, False]
