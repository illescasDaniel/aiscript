"""``aiscript --ask``: composition root and CLI routing (S1-S3, S10-S18, S21)."""

import io
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NoReturn

import pytest
from fake_openai import (
    FakeOpenAI,
    FakeReply,
    chat_reply,
    error_reply,
    responses_reply,
)

from aiscript import ask_cli, cli, config, paths, prompt_file
from aiscript.config import Settings

KEY = "sk-test-KEYSENTINEL0123456789abcdef"
MARKER = "RAW-PAYLOAD-MARKER"
SCHEMA = {
    "type": "object",
    "properties": {"count": {"type": "integer"}},
    "required": ["count"],
    "additionalProperties": False,
}
SCHEMA_JSON = json.dumps(SCHEMA)
DEFAULT_LIMIT = 128 * 1024


def write_config(
    base_url: str,
    *,
    api: str = "chat",
    key: str | None = None,
    ai: str = "",
    provider_extra: str = "",
    extra: str = "",
) -> None:
    key_line = f"    api_key: {key}\n" if key else ""
    text = (
        "default_provider: fake\n"
        "providers:\n"
        "  fake:\n"
        "    kind: openai\n"
        f"    api: {api}\n"
        f"    base_url: {base_url}\n"
        "    model: m\n"
        f"{key_line}{provider_extra}"
        f"{ai}{extra}"
    )
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o600)


def ask(
    data: bytes = b"data",
    *,
    task: str = "summarise",
    description: str = "some text",
    schema: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[int, bytes]:
    stdout = io.BytesIO()
    code = ask_cli.run(
        task,
        description,
        schema,
        stdin=io.BytesIO(data),
        stdout=stdout,
        environ={} if environ is None else environ,
    )
    return code, stdout.getvalue()


def text_of(out: bytes) -> str:
    return out.decode().removesuffix("\n")


@pytest.fixture
def server(fake_openai: FakeOpenAI, tmp_path: Path) -> FakeOpenAI:
    write_config(fake_openai.base_url)
    return fake_openai


@pytest.mark.parametrize("api", ["chat", "responses"])
def test_given_text_answer_when_ask_then_stdout_is_exactly_the_answer(
    api: str, fake_openai: FakeOpenAI
) -> None:
    # given
    write_config(fake_openai.base_url, api=api)
    fake_openai.enqueue(
        chat_reply("12 updates") if api == "chat" else responses_reply("12 updates")
    )
    # when
    code, out = ask(b"pkg list")
    # then
    assert code == 0
    assert text_of(out) == "12 updates"
    assert len(fake_openai.requests) == 1


def test_given_schema_answer_when_ask_then_one_compact_json_line(
    server: FakeOpenAI,
) -> None:
    # given
    server.enqueue(chat_reply('{"count": 12}'))
    # when
    code, out = ask(schema=SCHEMA_JSON)
    # then
    assert code == 0
    assert out == b'{"count":12}\n'


def test_given_schema_when_cli_main_then_stdout_is_exactly_the_json_line(
    server: FakeOpenAI, monkeypatch: pytest.MonkeyPatch, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    server.enqueue(chat_reply('{"count": 3}'))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"x")))
    # when
    code = cli.main(["--ask=count", "--data-description=d", f"--schema={SCHEMA_JSON}"])
    # then
    assert code == 0
    assert capfdbinary.readouterr().out == b'{"count":3}\n'


def test_given_path_like_data_description_first_when_cli_main_then_it_reaches_ask(
    server: FakeOpenAI, monkeypatch: pytest.MonkeyPatch, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given: argv[0] holds a path separator but is an option, not a prompt file
    server.enqueue(chat_reply("ok"))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"x")))
    # when
    code = cli.main(["--data-description=Output of /usr/bin/x", "--ask", "summarise"])
    # then
    assert code == 0
    assert capfdbinary.readouterr().out == b"ok\n"
    assert len(server.requests) == 1


# S10: usage errors send nothing and print nothing on stdout


@pytest.mark.parametrize(
    ("task", "description", "schema"),
    [
        ("  ", "d", None),
        ("", "d", None),
        ("t", "", None),
        ("t", "  ", None),
        ("t", "d", "{not json"),
        ("t", "d", "[]"),
        ("t", "d", json.dumps({**SCHEMA, "required": []})),
        ("t", "d", json.dumps({k: v for k, v in SCHEMA.items() if k != "additionalProperties"})),
        ("t", "d", json.dumps({**SCHEMA, "additionalProperties": True})),
    ],
)
def test_given_invalid_call_shape_when_ask_then_exit_2_and_nothing_sent(
    task: str, description: str, schema: str | None, server: FakeOpenAI
) -> None:
    # when
    code, out = ask(task=task, description=description, schema=schema)
    # then
    assert code == 2
    assert out == b""
    assert server.requests == []


def test_given_ask_without_data_description_when_cli_main_then_exit_2(
    server: FakeOpenAI, monkeypatch: pytest.MonkeyPatch, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"x")))
    # when
    code = cli.main(["--ask=summarise"])
    # then
    assert code == 2
    assert capfdbinary.readouterr().out == b""
    assert server.requests == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--schema", SCHEMA_JSON],
        ["--data-description", "d"],
    ],
)
def test_given_ask_only_option_without_ask_when_cli_main_then_exit_2(
    argv: list[str], server: FakeOpenAI, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # when
    code = cli.main(argv)
    # then
    assert code == 2
    assert capfdbinary.readouterr().out == b""
    assert server.requests == []


# S3: invalid ai: limits


@pytest.mark.parametrize(
    "ai",
    [
        "ai:\n  max_input_kb: 0\n",
        "ai:\n  max_calls_per_run: 101\n",
        "ai:\n  timeout_seconds: 1.5\n",
        "ai:\n  max_output_tokens: 32001\n",
        "ai:\n  bogus_key: 1\n",
    ],
)
def test_given_invalid_ai_limits_when_ask_then_exit_3_naming_the_key(
    ai: str, fake_openai: FakeOpenAI, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    write_config(fake_openai.base_url, ai=ai)
    key = ai.splitlines()[1].split(":")[0].strip()
    # when
    code, out = ask()
    # then
    assert code == 3
    assert out == b""
    assert key in capfdbinary.readouterr().err.decode()
    assert fake_openai.requests == []


def test_given_broken_yaml_next_to_api_key_when_ask_then_error_has_no_snippet(
    capfdbinary: pytest.CaptureFixture[bytes],
) -> None:
    # given: PyYAML's error would quote the offending line, which holds the key
    secret = "sk-topsecret-0123456789abcdef"
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"providers:\n  fake:\n    api_key: {secret}: oops\n")
    path.chmod(0o600)
    # when
    code, out = ask()
    # then
    err = capfdbinary.readouterr().err.decode()
    assert code == 3
    assert out == b""
    assert secret not in err
    assert f"Invalid YAML in {path} (line 3)" in err


# S11: provider and key resolution


def test_given_provider_that_is_not_openai_compatible_when_ask_then_exit_3(
    fake_openai: FakeOpenAI, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    write_config(fake_openai.base_url, provider_extra="", extra="")
    paths.config_path().write_text(
        f"default_provider: fake\nproviders:\n  fake:\n    kind: jev\n"
        f"    base_url: {fake_openai.base_url}\n    api_key: {KEY}\n"
    )
    # when
    code, out = ask()
    # then
    assert code == 3
    assert out == b""
    assert fake_openai.requests == []


def test_given_no_key_for_remote_endpoint_when_ask_then_exit_3_naming_key_sources(
    fake_openai: FakeOpenAI, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    write_config("https://example.invalid/v1")
    # when
    code, out = ask()
    # then
    assert code == 3
    assert out == b""
    err = capfdbinary.readouterr().err.decode()
    assert "config.yaml" in err
    assert "FAKE_API_KEY" in err
    assert "OPENAI_API_KEY" in err


def test_given_broken_reviewer_key_when_ask_then_call_still_succeeds(
    fake_openai: FakeOpenAI,
) -> None:
    # given
    write_config(
        fake_openai.base_url,
        extra=("reviewer_provider: rev\n"),
        provider_extra="  rev:\n    kind: openai\n    base_url: https://example.invalid/v1\n",
    )
    fake_openai.enqueue(chat_reply("fine"))
    # when
    code, out = ask()
    # then
    assert code == 0
    assert text_of(out) == "fine"


# S12: input size and encoding


def test_given_input_of_exactly_the_limit_when_ask_then_exit_4_and_nothing_sent(
    server: FakeOpenAI,
) -> None:
    # when
    code, out = ask(b"a" * DEFAULT_LIMIT)
    # then
    assert code == 4
    assert out == b""
    assert server.requests == []


def test_given_input_one_byte_under_the_limit_when_ask_then_it_is_sent(
    server: FakeOpenAI,
) -> None:
    # given
    server.enqueue(chat_reply("ok"))
    # when
    code, out = ask(b"a" * (DEFAULT_LIMIT - 1))
    # then
    assert code == 0
    assert text_of(out) == "ok"
    assert len(server.requests) == 1


def test_given_invalid_utf8_when_ask_then_exit_4_and_nothing_sent(server: FakeOpenAI) -> None:
    # when
    code, out = ask(b"\xff\xfe\x00bad")
    # then
    assert code == 4
    assert out == b""
    assert server.requests == []


# S13-S16: provider failures


def _assert_quiet_failure(
    out: bytes, capfdbinary: pytest.CaptureFixture[bytes], *, key_in_config: bool = True
) -> None:
    assert out == b""
    err = capfdbinary.readouterr().err.decode()
    assert len(err) < 2000
    assert MARKER not in err
    if key_in_config:
        assert KEY not in err


@pytest.mark.parametrize("status", [500, 401, 400])
def test_given_provider_error_when_ask_then_exit_5_with_bounded_clean_stderr(
    status: int, fake_openai: FakeOpenAI, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    write_config(fake_openai.base_url, key=KEY)
    fake_openai.enqueue(*[error_reply(status, f"{MARKER} {KEY} " + "x" * 5000) for _ in range(3)])
    # when
    code, out = ask()
    # then
    assert code == 5
    _assert_quiet_failure(out, capfdbinary)
    if status == 500:
        assert len(fake_openai.requests) == 3


def test_given_persistent_429_when_ask_then_exit_6_after_retries(
    server: FakeOpenAI, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    server.enqueue(*[error_reply(429, MARKER) for _ in range(3)])
    # when
    code, out = ask()
    # then
    assert code == 6
    _assert_quiet_failure(out, capfdbinary)
    assert len(server.requests) == 3


@pytest.mark.parametrize("api", ["chat", "responses"])
def test_given_refusal_when_ask_then_exit_7(
    api: str, fake_openai: FakeOpenAI, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    write_config(fake_openai.base_url, api=api)
    fake_openai.enqueue(
        chat_reply("", refusal=MARKER) if api == "chat" else responses_reply("", refusal=MARKER)
    )
    # when
    code, out = ask()
    # then
    assert code == 7
    _assert_quiet_failure(out, capfdbinary)


@pytest.mark.parametrize(
    ("reply", "schema"),
    [
        (chat_reply(""), None),
        (chat_reply("partial", finish_reason="length"), None),
        (chat_reply("not json " + MARKER), SCHEMA_JSON),
        (chat_reply('{"count": "twelve"}'), SCHEMA_JSON),
        (chat_reply('{"count": 1, "extra": 2}'), SCHEMA_JSON),
        (chat_reply("{}"), SCHEMA_JSON),
    ],
)
def test_given_bad_output_when_ask_then_exit_8_after_exactly_one_request(
    reply: FakeReply,
    schema: str | None,
    server: FakeOpenAI,
    capfdbinary: pytest.CaptureFixture[bytes],
) -> None:
    # given
    server.enqueue(reply, chat_reply("12 updates"))
    # when
    code, out = ask(schema=schema)
    # then
    assert code == 8
    _assert_quiet_failure(out, capfdbinary)
    assert len(server.requests) == 1


# S17: check order and call cap


def _good(fake: FakeOpenAI) -> dict[str, Any]:
    return {"base_url": fake.base_url}


@pytest.mark.parametrize(
    ("name", "config_kwargs", "task", "data", "code"),
    [
        pytest.param("f6", {}, " ", b"x", 2, id="f6"),
        pytest.param("config", {"ai": "ai:\n  max_calls_per_run: 0\n"}, "t", b"x", 3, id="config"),
        pytest.param("f7", {"base_url": "https://example.invalid/v1"}, "t", b"x", 3, id="f7"),
        pytest.param("f8", {}, "t", b"\xff", 4, id="f8"),
        pytest.param("f8-size", {}, "t", b"a" * DEFAULT_LIMIT, 4, id="f8-size"),
    ],
)
def test_given_failing_earlier_check_when_ask_then_no_cap_slot_is_claimed(
    name: str,
    config_kwargs: dict[str, Any],
    task: str,
    data: bytes,
    code: int,
    fake_openai: FakeOpenAI,
    tmp_path: Path,
) -> None:
    # given
    counter = tmp_path / "counter"
    counter.mkdir()
    environ = {"AISCRIPT_ASK_COUNTER": str(counter)}
    write_config(**{**_good(fake_openai), **config_kwargs})
    # when
    failed, _ = ask(data, task=task, environ=environ)
    # then
    assert failed == code
    assert list(counter.iterdir()) == []
    # and the one allowed call still succeeds
    write_config(fake_openai.base_url)
    fake_openai.enqueue(chat_reply("ok"))
    assert ask(environ=environ)[0] == 0


def test_given_no_counter_variable_when_ask_twice_then_no_cap_applies(
    server: FakeOpenAI,
) -> None:
    # given
    server.enqueue(chat_reply("a"), chat_reply("b"))
    # when
    first, _ = ask()
    second, _ = ask()
    # then
    assert (first, second) == (0, 0)
    assert len(server.requests) == 2


def test_given_counter_and_limit_1_when_ask_twice_then_second_exits_9(
    server: FakeOpenAI, tmp_path: Path, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    counter = tmp_path / "counter"
    counter.mkdir()
    environ = {"AISCRIPT_ASK_COUNTER": str(counter)}
    server.enqueue(chat_reply("a"), chat_reply("b"))
    # when
    first, _ = ask(environ=environ)
    second, out = ask(environ=environ)
    # then
    assert (first, second) == (0, 9)
    assert out == b""
    assert len(server.requests) == 1


# S18: run-time redirection is ignored


def test_given_routing_variables_when_ask_then_default_provider_gets_the_call(
    server: FakeOpenAI,
) -> None:
    # given
    with FakeOpenAI() as other:
        server.enqueue(chat_reply("ok"))
        environ = {
            "OPENAI_BASE_URL": other.base_url,
            "AISCRIPT_PROVIDER": "other",
            "AISCRIPT_MODEL": "env-model",
        }
        # when
        code, out = ask(environ=environ)
        # then
        assert code == 0
        assert text_of(out) == "ok"
        assert other.requests == []
    assert len(server.requests) == 1
    assert server.requests[0].body["model"] == "m"


def test_given_routing_variables_in_os_environ_when_cli_main_then_they_are_ignored(
    server: FakeOpenAI, monkeypatch: pytest.MonkeyPatch, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    # given
    with FakeOpenAI() as other:
        server.enqueue(chat_reply("ok"))
        monkeypatch.setenv("OPENAI_BASE_URL", other.base_url)
        monkeypatch.setenv("AISCRIPT_PROVIDER", "other")
        monkeypatch.setenv("AISCRIPT_MODEL", "env-model")
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"x")))
        # when
        code = cli.main(["--ask=t", "--data-description=d"])
        # then
        assert code == 0
        assert text_of(capfdbinary.readouterr().out) == "ok"
        assert other.requests == []
    assert len(server.requests) == 1


# S21: a cache hit loads no config


@pytest.mark.skipif(sys.platform == "win32", reason="bash scripts")
def test_given_cache_hit_when_run_then_no_config_is_loaded(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    # given
    paths.ensure_dirs()
    paths.prompt_path("hello").write_text("say hello\n")
    script = paths.function_path("hello")
    script.write_text("#!/usr/bin/env bash\necho hello\n")
    script.chmod(0o755)
    future = time.time_ns() + 5_000_000_000
    os.utime(script, ns=(future, future))

    def boom(*a: Any, **k: Any) -> NoReturn:
        raise AssertionError("config must not be read on a cache hit")

    monkeypatch.setattr(config, "load_raw_config", boom)
    # when
    code = cli.main(["hello"])
    # then
    assert code == 0
    assert capfd.readouterr().out == "hello\n"


# Routing: --ask=TASK reaches ask_cli even when the task has a path separator or starts with "-"


@pytest.mark.parametrize(
    "task",
    ["summarise apt list/upgradable output", "-weird task", "a/b", "../x", "-/-"],
)
def test_given_ask_task_form_when_cli_main_then_it_reaches_ask_cli(
    task: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    seen: list[tuple[str, str, str | None]] = []

    def fake_run(task: str, data_description: str, schema_json: str | None, **_: Any) -> int:
        seen.append((task, data_description, schema_json))
        return 0

    def no_prompt_file(*a: Any, **k: Any) -> NoReturn:
        raise AssertionError("prompt_file.execute must not run for --ask")

    monkeypatch.setattr(ask_cli, "run", fake_run)
    monkeypatch.setattr(prompt_file, "execute", no_prompt_file)
    # when
    code = cli.main([f"--ask={task}", "--data-description=d"])
    # then
    assert code == 0
    assert seen == [(task, "d", None)]


def test_given_real_file_path_when_cli_main_then_prompt_file_still_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    prompt = tmp_path / "task.prompt"
    prompt.write_text("do it\n")
    executed: list[tuple[Path, list[str]]] = []

    def fake_execute(path: Path, args: list[str], settings: Callable[[], Settings]) -> int:
        executed.append((path, args))
        return 0

    def no_ask(*a: Any, **k: Any) -> NoReturn:
        raise AssertionError("ask_cli.run must not run for a file path")

    monkeypatch.setattr(prompt_file, "execute", fake_execute)
    monkeypatch.setattr(ask_cli, "run", no_ask)
    # when
    code = cli.main([str(prompt), "--ask", "x"])
    # then
    assert code == 0
    assert executed == [(prompt, ["--ask", "x"])]
