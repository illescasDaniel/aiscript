import sys
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import openai
import pytest

from aiscript import llm
from aiscript.config import ProviderConfig
from aiscript.errors import AiscriptError

P = ProviderConfig(name="openai", api_key="k", base_url=None, model="gpt-x")
REQ: Any = SimpleNamespace(method="POST", url="http://x/v1/chat/completions")


def fake_client(
    content: str | None = None,
    exc: Exception | None = None,
    calls: list[dict[str, Any]] | None = None,
    status: str = "completed",
    reason: str | None = None,
) -> SimpleNamespace:
    def record(kwargs: dict[str, Any]) -> None:
        if calls is not None:
            calls.append(kwargs)
        if exc:
            raise exc

    def chat_create(**kwargs: Any) -> SimpleNamespace:
        record(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    def responses_create(**kwargs: Any) -> SimpleNamespace:
        record(kwargs)
        return SimpleNamespace(
            output_text=content,
            status=status,
            incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        )

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=chat_create)),
        responses=SimpleNamespace(create=responses_create),
    )


def status_error(cls: type[openai.APIStatusError], code: int) -> openai.APIStatusError:
    return cls(
        "boom",
        response=cast(Any, SimpleNamespace(status_code=code, request=REQ, headers={})),
        body=None,
    )


# ---- clean_script


def test_fenced_with_lang() -> None:
    raw = "```bash\n#!/usr/bin/env bash\necho hi\n```"
    assert llm.clean_script(raw, "bash") == "#!/usr/bin/env bash\necho hi\n"


def test_fence_with_prose() -> None:
    raw = "Here you go:\n```sh\n#!/bin/sh\necho hi\n```\nHope it helps!"
    assert llm.clean_script(raw, "bash") == "#!/bin/sh\necho hi\n"


def test_no_fence_and_leading_blank() -> None:
    out = llm.clean_script("\n\n#!/usr/bin/env bash\necho hi", "bash")
    assert out == "#!/usr/bin/env bash\necho hi\n"


def test_shebang_added_for_bash() -> None:
    assert llm.clean_script("echo hi", "bash") == "#!/usr/bin/env bash\necho hi\n"


def test_powershell_no_shebang() -> None:
    out = llm.clean_script("```powershell\nWrite-Host hi\n```", "powershell")
    assert out == "Write-Host hi\n"


def test_unclosed_fence() -> None:
    assert llm.clean_script("```bash\necho hi\n", "bash").endswith("echo hi\n")


@pytest.mark.parametrize("raw", ["", "   \n", "```bash\n```"])
def test_empty_raises(raw: str) -> None:
    with pytest.raises(AiscriptError):
        llm.clean_script(raw, "bash")


# ---- system_prompt


def test_prompt_bash() -> None:
    s = llm.system_prompt("bash", "Linux 6 (Arch)").lower()
    for needle in (
        "linux 6 (arch)",
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "# aiscript: <name>",
        "# description:",
        "# usage:",
        "trash",
        "~/.trash",
        "sudo",
        "$1",
        "usage message",
        "raw script",
        "#!/usr/bin/env python3",
        "pep 723",
    ):
        assert needle in s, needle


def test_prompt_powershell() -> None:
    s = llm.system_prompt("powershell", "Windows 11")
    assert "Windows 11" in s
    assert "$args[0]" in s
    assert "Recycle" in s
    assert "# Description:" in s and "# Usage:" in s
    assert "Do NOT add a shebang" in s
    assert "set -euo pipefail" not in s
    assert "PYTHON SPECIFICS" in s and "PowerShell" in s


def test_prompt_python_rules() -> None:
    s = llm.system_prompt("bash", "- Python: 3.12.1 (python3)")
    assert "- Python: 3.12.1 (python3)" in s
    for needle in (
        "CHOOSING THE LANGUAGE",
        "PYTHON SPECIFICS",
        "in python",
        "never call pip",
        "shutil.rmtree",
        "shell=True",
        "pathlib",
        "sys.exit",
    ):
        assert needle in s, needle


# ---- make_client / chat


def test_make_client_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: seen.update(kw) or "c")
    llm.make_client(P)
    assert "base_url" not in seen and seen["api_key"] == "k" and seen["timeout"] > 0
    llm.make_client(ProviderConfig("o", None, "http://localhost:1/v1", "m"))
    assert seen["base_url"] == "http://localhost:1/v1" and seen["api_key"] == "not-needed"


def test_chat_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(llm, "make_client", lambda p: fake_client("hello", calls=calls))
    assert llm.chat(P, "sys", "usr") == "hello"
    assert calls[0]["model"] == "gpt-x"
    assert calls[0]["messages"][0] == {"role": "system", "content": "sys"}
    assert calls[0]["messages"][1] == {"role": "user", "content": "usr"}
    # GPT-6 models reject temperature unless effort is none: never send it by default.
    assert "temperature" not in calls[0] and "reasoning_effort" not in calls[0]


def test_chat_sends_configured_sampling(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(llm, "make_client", lambda p: fake_client("hi", calls=calls))
    llm.chat(replace(P, reasoning_effort="none", temperature=0.3), "s", "u")
    assert calls[0]["reasoning_effort"] == "none" and calls[0]["temperature"] == 0.3


def test_responses_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(llm, "make_client", lambda p: fake_client("out", calls=calls))
    assert llm.chat(replace(P, api="responses"), "sys", "usr") == "out"
    assert calls[0] == {"model": "gpt-x", "instructions": "sys", "input": "usr", "store": False}


def test_responses_api_effort_and_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(llm, "make_client", lambda p: fake_client("out", calls=calls))
    p = replace(P, api="responses", reasoning_effort="low", temperature=0.1)
    llm.chat(p, "s", "u")
    assert calls[0]["reasoning"] == {"effort": "low"} and calls[0]["temperature"] == 0.1


def test_responses_api_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fake_client("partial", status="incomplete", reason="max_output_tokens")
    monkeypatch.setattr(llm, "make_client", lambda p: client)
    with pytest.raises(AiscriptError, match="incomplete.*max_output_tokens"):
        llm.chat(replace(P, api="responses"), "s", "u")


@pytest.mark.parametrize("content", [None, ""])
def test_responses_api_empty(monkeypatch: pytest.MonkeyPatch, content: str | None) -> None:
    monkeypatch.setattr(llm, "make_client", lambda p: fake_client(content))
    with pytest.raises(AiscriptError, match="empty"):
        llm.chat(replace(P, api="responses"), "s", "u")


@pytest.mark.parametrize("content", [None, "", "  "])
def test_chat_empty(monkeypatch: pytest.MonkeyPatch, content: str | None) -> None:
    monkeypatch.setattr(llm, "make_client", lambda p: fake_client(content))
    with pytest.raises(AiscriptError, match="empty"):
        llm.chat(P, "s", "u")


@pytest.mark.parametrize(
    ("exc", "text"),
    [
        (openai.APIConnectionError(request=REQ), "connect"),
        (openai.APITimeoutError(request=REQ), "timed out"),
        (status_error(openai.AuthenticationError, 401), "Authentication"),
        (status_error(openai.NotFoundError, 404), "404"),
        (status_error(openai.RateLimitError, 429), "429"),
    ],
)
def test_chat_errors(monkeypatch: pytest.MonkeyPatch, exc: Exception, text: str) -> None:
    monkeypatch.setattr(llm, "make_client", lambda p: fake_client(exc=exc))
    with pytest.raises(AiscriptError, match=text) as ei:
        llm.chat(P, "s", "u")
    assert "gpt-x" in str(ei.value)


# ---- generate_script


def patch_gen(monkeypatch: pytest.MonkeyPatch, reply: str, shell: str = "bash") -> dict[str, Any]:
    got: dict[str, Any] = {}

    def fake_chat(p: ProviderConfig, system: str, user: str, **kw: Any) -> str:
        got.update(p=p, system=system, user=user)
        return reply

    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm.paths, "shell_kind", lambda: shell)
    monkeypatch.setattr(llm.env, "describe", lambda: "- Host OS: TestOS")
    return got


def test_generate_script(monkeypatch: pytest.MonkeyPatch) -> None:
    got = patch_gen(monkeypatch, "```bash\necho hi\n```")
    out = llm.generate_script(P, "hello", "say hi")
    assert out == llm.GeneratedScript("#!/usr/bin/env bash\necho hi\n", "bash", [])
    assert got["p"] is P
    assert "hello" in got["user"] and "say hi" in got["user"]
    assert "Bash" in got["system"] and "Host OS: TestOS" in got["system"]


def test_generate_script_powershell(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_gen(monkeypatch, "Write-Host hi", "powershell")
    assert llm.generate_script(P, "x", "y") == llm.GeneratedScript(
        "Write-Host hi\n", "powershell", []
    )


def test_generate_script_python_with_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    code = (
        "#!/usr/bin/env python3\n# aiscript: x\n# /// script\n"
        '# dependencies = ["requests>=2"]\n# ///\nimport requests\nprint(requests)'
    )
    patch_gen(monkeypatch, f"```python\n{code}\n```")
    out = llm.generate_script(P, "x", "y")
    assert out.language == "python" and out.dependencies == ["requests>=2"]
    assert out.code == code + "\n"


def test_generate_script_python_syntax_error(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_gen(monkeypatch, "#!/usr/bin/env python3\ndef f(:\n")
    with pytest.raises(AiscriptError, match="Python with a syntax error"):
        llm.generate_script(P, "x", "y")


def test_generate_script_bad_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_gen(
        monkeypatch,
        '#!/usr/bin/env python3\n# /// script\n# dependencies = ["-e ."]\n# ///\nprint(1)',
    )
    with pytest.raises(AiscriptError, match="-e ."):
        llm.generate_script(P, "x", "y")


# ---- detect_language / clean_script with python


@pytest.mark.parametrize(
    "first", ["#!/usr/bin/env python3", "#!/usr/bin/env python", "#!/usr/bin/python3"]
)
def test_detect_python(first: str) -> None:
    assert llm.detect_language(f"\n{first}\nprint(1)\n", "bash") == "python"
    assert llm.detect_language(f"{first}\n", "powershell") == "python"


def test_detect_shell() -> None:
    assert llm.detect_language("#!/usr/bin/env bash\n# python\n", "bash") == "bash"
    assert llm.detect_language("echo python3\n", "bash") == "bash"
    assert llm.detect_language("Write-Host hi\n", "powershell") == "powershell"


def test_clean_script_keeps_python_shebang() -> None:
    out = llm.clean_script("```python\n#!/usr/bin/env python3\nprint(1)\n```", "bash")
    assert out == "#!/usr/bin/env python3\nprint(1)\n"


# ---- parse_dependencies

BLOCK = "#!/usr/bin/env python3\n# aiscript: x\n# /// script\n{body}\n# ///\nprint(1)\n"


def block(*lines: str) -> str:
    return BLOCK.format(body="\n".join(lines))


def test_deps_none() -> None:
    assert llm.parse_dependencies("#!/usr/bin/env python3\nprint(1)\n") == []
    assert llm.parse_dependencies(block('# requires-python = ">=3.8"')) == []


def test_deps_valid() -> None:
    code = block(
        '# requires-python = ">=3.8"',
        '# dependencies = ["requests>=2", "rich", "httpx[http2]>=0.27,<1",',
        "#   \"tomli>=2; python_version < '3.11'\"]",
    )
    assert llm.parse_dependencies(code) == [
        "requests>=2",
        "rich",
        "httpx[http2]>=0.27,<1",
        "tomli>=2; python_version < '3.11'",
    ]


def test_deps_multiline_array() -> None:
    code = block(
        "# dependencies = [",
        '#     "requests>=2",  # http',
        '#     "rich[jupyter]",',
        "# ]",
    )
    assert llm.parse_dependencies(code) == ["requests>=2", "rich[jupyter]"]


def test_deps_fallback_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the Python 3.10 path (no tomllib).
    monkeypatch.setitem(sys.modules, "tomllib", None)
    code = block(
        '# requires-python = ">=3.8"',
        "# dependencies = [",
        '#     "requests>=2",  # a [comment]',
        '#     "rich[jupyter]",',
        "# ]",
    )
    assert llm.parse_dependencies(code) == ["requests>=2", "rich[jupyter]"]
    assert llm.parse_dependencies(block("# x = 1")) == []


@pytest.mark.parametrize(
    "dep",
    [
        "pkg @ https://example.com/p.whl",
        "git+https://github.com/a/b",
        "https://example.com/p.whl",
        "./local",
        "../x/y",
        "C:\\\\pkg",
        "-e .",
        "--index-url=x",
        "",
        "pkg@1",
        "bad name!",
    ],
)
def test_deps_rejected(dep: str) -> None:
    with pytest.raises(AiscriptError, match="Unsupported dependency"):
        llm.parse_dependencies(block(f"# dependencies = [{dep!r}]"))


def test_deps_not_a_list() -> None:
    with pytest.raises(AiscriptError):
        llm.parse_dependencies(block('# dependencies = "requests"'))
