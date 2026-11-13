"""Runtime notice and stdout isolation scenarios S27–S28."""

import io

import pytest
from fake_openai import FakeOpenAI, chat_reply

from aiscript import ask_cli, paths


def test_given_api_ask_when_provider_starts_then_notice_is_on_stderr_not_stdout(
    fake_openai: FakeOpenAI, capsys: pytest.CaptureFixture[str]
) -> None:
    # given
    paths.aiscript_home().mkdir(parents=True)
    paths.config_path().write_text(
        "default_provider: fake\n"
        "providers:\n"
        "  fake:\n"
        "    kind: openai\n"
        "    api: chat\n"
        f"    base_url: {fake_openai.base_url}\n"
        "    model: m\n"
        "ai:\n"
        "  timeout_seconds: 12\n",
        encoding="utf-8",
    )
    fake_openai.enqueue(chat_reply("fixture answer"))
    stdout = io.BytesIO()
    # when
    code = ask_cli.run(
        "summarise",
        "a document",
        None,
        stdin=io.BytesIO(b"sensitive input"),
        stdout=stdout,
        environ={},
    )
    # then
    stderr = capsys.readouterr().err
    assert code == 0
    assert stdout.getvalue() == b"fixture answer\n"
    assert "12" in stderr
    assert "attempt" in stderr.lower()
    assert "retr" in stderr.lower()
    assert "sensitive input" not in stderr


def test_given_invalid_ask_when_no_provider_call_then_no_wait_notice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given / when
    code = ask_cli.run(
        "", "description", None, stdin=io.BytesIO(b""), stdout=io.BytesIO(), environ={}
    )
    # then
    assert code != 0
    stderr = capsys.readouterr().err.lower()
    assert "attempt" not in stderr
    assert "take up to" not in stderr
