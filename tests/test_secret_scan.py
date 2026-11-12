"""Credential scanner (C8): scenarios S4, S5, F2, F3 and the performance budget."""

import ast
import base64
import codecs
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

import pytest

from aiscript.paths import Language
from aiscript.secret_scan import KnownSecrets, SecretFinding, refusal_message, scan

KEY = "sk-9fQ2xLm7ZkR4tVb8NcW3yHd6Pe1Aj5"
FRAGMENT = KEY[10:22]
OTHERS = [
    "tsf_Hq7Vn2Bz9Kc4Xw8Ld3Mt6Ry1",
    "oll-Gp5Fs8Jx2Qa7Ve3Nb9Zc4Uh6",
    "dec-Wm4Tk9Rb2Ly7Xe5Cq8Nf3Ja1",
    "jev_Zd6Pu3Hs8Vg2Kt9Mw4Bn7Xc5",
]
PROJECT_KEY = "sk-proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"

LANGUAGES: list[Language] = ["python", "bash", "powershell"]


def known() -> KnownSecrets:
    return KnownSecrets.from_values([KEY])


def lines_of(findings: list[SecretFinding]) -> list[int]:
    return sorted({f.line for f in findings})


def assert_value_hidden(findings: list[SecretFinding], *values: str) -> None:
    messages = [refusal_message("prompt", findings), refusal_message("code", findings)]
    for value in values:
        for finding in findings:
            assert value not in repr(finding)
            assert value not in str(finding)
        for message in messages:
            assert value not in message


# -- prompts (S4 / F2) -------------------------------------------------------------------


def prompt_with(form: str) -> str:
    return f"List my packages.\nSummarise them in a table.\nUse {form} when asked.\nThanks.\n"


def test_given_prompt_with_exact_key_when_scanned_then_finding_on_its_line_without_value() -> None:
    # given
    text = prompt_with(KEY)
    # when
    findings = scan(text, known())
    # then
    assert lines_of(findings) == [3]
    assert findings[0].kind == "known"
    assert_value_hidden(findings, KEY)


def test_given_prompt_with_12_char_fragment_when_scanned_then_known_finding() -> None:
    # given
    text = prompt_with(FRAGMENT)
    # when
    findings = scan(text, known())
    # then
    assert lines_of(findings) == [3]
    assert findings[0].kind == "known"
    assert_value_hidden(findings, KEY, FRAGMENT)


def test_given_prompt_with_11_char_fragment_when_scanned_then_no_finding() -> None:
    # given
    text = prompt_with(FRAGMENT[:11])
    # when
    findings = scan(text, known())
    # then
    assert findings == []


@pytest.mark.parametrize(
    "encode",
    [
        lambda s: base64.b64encode(s.encode()).decode(),
        lambda s: s.encode().hex(),
        lambda s: quote(s, safe=""),
        lambda s: "".join(f"%{b:02x}" for b in s.encode()),
    ],
    ids=["base64", "hex", "percent-partial", "percent-all"],
)
def test_given_prompt_with_encoded_key_when_scanned_then_finding_without_value(
    encode: Callable[[str], str],
) -> None:
    # given
    encoded = encode(KEY)
    text = prompt_with(encoded)
    # when
    findings = scan(text, known())
    # then
    assert lines_of(findings) == [3]
    assert_value_hidden(findings, KEY, encoded)


def test_given_prompt_with_sk_proj_pattern_in_prose_when_scanned_then_pattern_finding() -> None:
    # given
    text = f"Call the API.\nMy key is {PROJECT_KEY}, please use it.\n"
    # when
    findings = scan(text, KnownSecrets.from_values([]))
    # then
    assert lines_of(findings) == [2]
    assert findings[0].kind == "pattern"
    assert_value_hidden(findings, PROJECT_KEY)


def test_given_clean_prompt_when_scanned_then_no_findings() -> None:
    # given
    text = "Check for package updates.\nPrint a short summary.\n"
    # when
    findings = scan(text, known())
    # then
    assert findings == []


# -- generated code (S5 / F3) ------------------------------------------------------------


def split_expr(value: str) -> str:
    return f'"{value[:9]}" + "{value[9:20]}" + "{value[20:]}"'


PYTHON_FORMS = {
    "exact": f'KEY = "{KEY}"',
    "plus": f"KEY = {split_expr(KEY)}",
    "join": f'KEY = "".join(["{KEY[:9]}", "{KEY[9:20]}", "{KEY[20:]}"])',
    "reversed": f'KEY = "{KEY[::-1]}"[::-1]',
    "rot13": f'KEY = codecs.decode("{codecs.encode(KEY, "rot13")}", "rot13")',
    "base64": f'KEY = base64.b64decode("{base64.b64encode(KEY.encode()).decode()}")',
    "hex": f'KEY = bytes.fromhex("{KEY.encode().hex()}")',
    "chr": "KEY = " + " + ".join(f"chr({ord(c)})" for c in KEY),
    "chr-join": 'KEY = "".join(chr(c) for c in [' + ", ".join(str(ord(c)) for c in KEY) + "])",
    "bytes": f"KEY = bytes([{', '.join(str(b) for b in KEY.encode())}]).decode()",
    "fragment": f'KEY = "{FRAGMENT}"',
}


@pytest.mark.parametrize("form", list(PYTHON_FORMS))
def test_given_python_code_hiding_key_when_scanned_then_finding_without_value(form: str) -> None:
    # given
    code = f"#!/usr/bin/env python3\nimport base64, codecs\n{PYTHON_FORMS[form]}\nprint(1)\n"
    # when
    findings = scan(code, known(), language="python")
    # then
    assert lines_of(findings) == [3]
    assert findings[0].kind == "known"
    assert_value_hidden(findings, KEY, FRAGMENT)


def escapes(value: str) -> str:
    return "".join(f"\\x{b:02x}" for b in value.encode())


BASH_FORMS = {
    "exact": f'KEY="{KEY}"',
    "printf": f"KEY=$(printf '{escapes(KEY)}')",
    "dollar-quote": f"KEY=$'{escapes(KEY)}'",
    "reversed": f'KEY="{KEY[::-1]}"; KEY=$(echo "$KEY" | rev)',
    "rot13": f"KEY=$(echo '{codecs.encode(KEY, 'rot13')}' | tr 'A-Za-z' 'N-ZA-Mn-za-m')",
    "base64": f"KEY=$(echo {base64.b64encode(KEY.encode()).decode()} | base64 -d)",
    "hex": f"KEY=$(echo {KEY.encode().hex()} | xxd -r -p)",
    "concat": f'KEY="{KEY[:9]}""{KEY[9:20]}""{KEY[20:]}"',
}


@pytest.mark.parametrize("form", list(BASH_FORMS))
def test_given_bash_code_hiding_key_when_scanned_then_finding_without_value(form: str) -> None:
    # given
    code = f"#!/usr/bin/env bash\nset -eu\n{BASH_FORMS[form]}\necho done\n"
    # when
    findings = scan(code, known(), language="bash")
    # then
    assert lines_of(findings) == [3]
    assert findings[0].kind == "known"
    assert_value_hidden(findings, KEY)


POWERSHELL_FORMS = {
    "exact": f'$key = "{KEY}"',
    "plus": f'$key = "{KEY[:9]}" + "{KEY[9:20]}" + "{KEY[20:]}"',
    "base64": (
        "$key = [Text.Encoding]::UTF8.GetString("
        f'[Convert]::FromBase64String("{base64.b64encode(KEY.encode()).decode()}"))'
    ),
    "char": "$key = -join (" + ", ".join(str(ord(c)) for c in KEY) + " | % { [char]$_ })",
}


@pytest.mark.parametrize("form", list(POWERSHELL_FORMS))
def test_given_powershell_code_hiding_key_when_scanned_then_finding_without_value(
    form: str,
) -> None:
    # given
    code = f"Set-StrictMode -Version Latest\n{POWERSHELL_FORMS[form]}\nWrite-Output done\n"
    # when
    findings = scan(code, known(), language="powershell")
    # then
    assert lines_of(findings) == [2]
    assert_value_hidden(findings, KEY)


def test_given_python_key_split_over_implicit_concatenation_when_scanned_then_finding() -> None:
    # given
    code = f'x = 1\nKEY = (\n    "{KEY[:12]}"\n    "{KEY[12:24]}"\n    "{KEY[24:]}"\n)\n'
    # when
    findings = scan(code, known(), language="python")
    # then
    assert findings
    assert all(3 <= f.line <= 5 for f in findings)
    assert_value_hidden(findings, KEY)


def test_given_bash_key_split_across_quotes_and_continuations_when_scanned_then_finding() -> None:
    # given
    code = f"#!/bin/sh\nKEY='{KEY[:10]}'\"{KEY[10:20]}\"\\\n'{KEY[20:]}'\n"
    # when
    findings = scan(code, known(), language="bash")
    # then
    assert findings
    assert all(2 <= f.line <= 4 for f in findings)
    assert_value_hidden(findings, KEY)


# Every piece is under 12 characters, so only the joined view or folding can catch them.
PIECES = [KEY[:11], KEY[11:22], KEY[22:28], KEY[28:]]
assert all(len(piece) < 12 for piece in PIECES)
_QUOTED_PIECES = [f'"{piece}"' for piece in PIECES]

SPLIT_PYTHON_FORMS = {
    "plus": "KEY = " + " + ".join(_QUOTED_PIECES),
    "join": 'KEY = "".join([' + ", ".join(_QUOTED_PIECES) + "])",
    "implicit": "KEY = (\n    " + "\n    ".join(_QUOTED_PIECES) + "\n)",
    "names": "\n".join(f"p{i} = {q}" for i, q in enumerate(_QUOTED_PIECES))
    + "\nKEY = p0 + p1 + p2 + p3",
}


@pytest.mark.parametrize("form", list(SPLIT_PYTHON_FORMS))
def test_given_python_key_split_into_short_pieces_when_scanned_then_finding(form: str) -> None:
    # given
    code = f"#!/usr/bin/env python3\n{SPLIT_PYTHON_FORMS[form]}\nprint(1)\n"
    # when
    findings = scan(code, known(), language="python")
    # then
    assert [f for f in findings if f.kind == "known"], form
    assert_value_hidden(findings, KEY)


SPLIT_BASH_FORMS = {
    "double-quotes": "KEY=" + "".join(_QUOTED_PIECES),
    "mixed-quotes": "KEY='" + f'{PIECES[0]}\'"{PIECES[1]}"\'{PIECES[2]}\'"{PIECES[3]}"',
    "continuation": f'KEY="{PIECES[0]}""{PIECES[1]}"\\\n"{PIECES[2]}""{PIECES[3]}"',
}


@pytest.mark.parametrize("form", list(SPLIT_BASH_FORMS))
def test_given_bash_key_split_into_short_pieces_when_scanned_then_finding(form: str) -> None:
    # given
    code = f"#!/bin/sh\n{SPLIT_BASH_FORMS[form]}\n"
    # when
    findings = scan(code, known(), language="bash")
    # then
    assert [f for f in findings if f.kind == "known"], form
    assert_value_hidden(findings, KEY)


def test_given_several_known_secrets_when_one_is_in_code_then_it_is_found() -> None:
    # given
    secrets = KnownSecrets.from_values([KEY, *OTHERS])
    code = f'#!/usr/bin/env python3\nk = "{OTHERS[2]}"\n'
    # when
    findings = scan(code, secrets, language="python")
    # then
    assert lines_of(findings) == [2]
    assert_value_hidden(findings, *OTHERS)


@pytest.mark.parametrize("language", LANGUAGES)
def test_given_clean_script_when_scanned_then_no_findings(language: Language) -> None:
    # given
    code = "echo hello\nprint('hello')\nWrite-Output hello\n"
    # when
    findings = scan(code, known(), language=language)
    # then
    assert findings == []


# -- KnownSecrets ------------------------------------------------------------------------


def test_given_short_or_placeholder_values_when_built_then_ignored() -> None:
    # given
    secrets = KnownSecrets.from_values(["short", "1234567", "not-needed", ""])
    text = "short 1234567 not-needed not-needed-not-needed 12345678 short-short-short"
    # when
    findings = scan(text, secrets)
    # then
    assert findings == []


def test_given_value_of_8_characters_when_built_then_it_is_a_known_secret() -> None:
    # given
    secrets = KnownSecrets.from_values(["Zq8Lm3Xv"])
    # when
    findings = scan("token is Zq8Lm3Xv here", secrets)
    # then
    assert lines_of(findings) == [1]
    assert_value_hidden(findings, "Zq8Lm3Xv")


def test_given_known_secrets_when_repr_then_values_are_hidden() -> None:
    # given
    secrets = KnownSecrets.from_values([KEY, *OTHERS])
    # when
    shown = repr(secrets) + str(secrets)
    # then
    for value in (KEY, FRAGMENT, *OTHERS):
        assert value not in shown
    assert KEY[::-1] not in shown
    assert codecs.encode(KEY, "rot13") not in shown


# -- refusal_message ---------------------------------------------------------------------


def test_given_prompt_stage_when_refusing_then_says_config_key_is_used_and_to_remove_it() -> None:
    # given
    findings = [SecretFinding(line=3, kind="known", view="raw")]
    # when
    message = refusal_message("prompt", findings)
    # then
    assert "3" in message
    assert "prompt" in message.lower()
    assert "config" in message
    assert "remove" in message.lower()


def test_given_code_stage_with_lines_when_refusing_then_names_every_line_and_kind() -> None:
    # given
    findings = [
        SecretFinding(line=7, kind="known", view="decoded"),
        SecretFinding(line=12, kind="pattern", view="raw"),
    ]
    # when
    message = refusal_message("code", findings)
    # then
    assert "7" in message
    assert "12" in message
    assert "code" in message.lower()
    assert "known" in message
    assert "pattern" in message


# -- false positives ---------------------------------------------------------------------

BENIGN_PROMPTS = [
    "Show the SHA of HEAD and the last ten commits.\n",
    "Rename task-manager-integration-test-runner-service to task-runner.\n",
    "Create a task-2024-report and a task-id-generator.\n",
    "Embed the image data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk\n",
    "Look up commit 9fceb02d0ae598e95dc970b74767f19372d61af7 in the repo.\n",
    "Find user 550e8400-e29b-41d4-a716-446655440000 in the table.\n",
    "Use sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 as a check.\n",
    "Call the function parse_configuration_file_with_defaults_and_overrides on every file.\n",
    "Use the sk- prefix naming for skeleton files and sk-learn notes.\n",
    "Explain what an API key is and how OPENAI_API_KEY is read by other tools.\n",
]

BENIGN_SCRIPTS: list[tuple[Language, str]] = [
    (
        "python",
        "#!/usr/bin/env python3\n"
        "import hashlib, uuid, subprocess\n"
        "LONG_IDENTIFIER_NAME_FOR_THE_PACKAGE_UPDATE_SUMMARY_REPORT = 'x'\n"
        "sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()\n"
        "# 9fceb02d0ae598e95dc970b74767f19372d61af7\n"
        "print(uuid.UUID('550e8400-e29b-41d4-a716-446655440000'))\n"
        "print(hashlib.sha256(b'x').hexdigest())\n"
        "PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhf'\n"
        "task = 'task-update-all-outdated-packages-and-report'\n",
    ),
    (
        "bash",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "rev=$(git rev-parse HEAD)\n"
        'echo "commit $rev e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"\n'
        "id=550e8400-e29b-41d4-a716-446655440000\n"
        'printf "%s\\n" "task-update-all-outdated-packages-and-report"\n'
        "printf '\\x68\\x65\\x6c\\x6c\\x6f\\n'\n"
        "echo $'\\x68\\x65\\x6c\\x6c\\x6f'\n",
    ),
    (
        "powershell",
        "Set-StrictMode -Version Latest\n"
        "$sha = (git rev-parse HEAD)\n"
        "Write-Output 'task-update-all-outdated-packages-and-report'\n"
        "Write-Output 550e8400-e29b-41d4-a716-446655440000\n"
        "$h = (Get-FileHash -Algorithm SHA256 $PSCommandPath).Hash\n",
    ),
]


@pytest.mark.parametrize("prompt", BENIGN_PROMPTS)
def test_given_benign_prompt_when_scanned_then_no_findings(prompt: str) -> None:
    # given
    secrets = KnownSecrets.from_values([KEY, *OTHERS])
    # when
    findings = scan(prompt, secrets)
    # then
    assert findings == []


@pytest.mark.parametrize(("language", "code"), BENIGN_SCRIPTS)
def test_given_benign_script_when_scanned_then_no_findings(language: Language, code: str) -> None:
    # given
    secrets = KnownSecrets.from_values([KEY, *OTHERS])
    # when
    findings = scan(code, secrets, language=language)
    # then
    assert findings == []


_EXCLUDED = ("test_secret_scan", "test_sweep", "test_ask", "test_shim")


def existing_script_samples() -> list[tuple[Language, str]]:
    """Every script-looking string constant in the repo's existing tests."""
    samples: list[tuple[Language, str]] = []
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        if path.stem.startswith(_EXCLUDED):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith("#!") and "\n" in node.value:
                    language: Language = "python" if "python" in node.value[:40] else "bash"
                    samples.append((language, node.value))
    return samples


def test_given_existing_test_script_samples_when_scanned_then_no_findings() -> None:
    # given
    samples = existing_script_samples()
    secrets = KnownSecrets.from_values([KEY, *OTHERS])
    # when
    results = [(code, scan(code, secrets, language=language)) for language, code in samples]
    # then
    assert samples
    assert [code for code, findings in results if findings] == []


# -- performance -------------------------------------------------------------------------


def test_given_100kb_script_and_five_secrets_when_scanned_then_under_250_ms() -> None:
    # given
    secrets = KnownSecrets.from_values([KEY, *OTHERS])
    line = "result_value = compute_total(items, offset=17) + 'ok-text-lorem-ipsum'  # note\n"
    code = "#!/usr/bin/env python3\n" + line * (100_000 // len(line) + 1) + f'k = "{KEY}"\n'
    # when
    start = time.perf_counter()
    findings = scan(code, secrets, language="python")
    elapsed = time.perf_counter() - start
    # then
    assert len(code) >= 100_000
    assert lines_of(findings) == [code.count("\n")]
    assert elapsed < 0.25
