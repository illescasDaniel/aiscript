from pathlib import Path

import pytest

from aiscript import cli, paths, sweep
from aiscript.secret_scan import KnownSecrets

KEY = "Zq7Lm2Xv9Rt4Wk8Pn3Yc6Hd5Jb"
CONFIG = f"providers:\n  openai: {{api_key: {KEY}}}\n"
CLEAN_SH = "#!/usr/bin/env bash\necho hello\n"
LEAKY_SH = f'#!/usr/bin/env bash\n# aiscript: foo\ncurl -H "Authorization: Bearer {KEY}" x\n'


def put(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def write_config(text: str = CONFIG) -> None:
    put(paths.config_path(), text)
    paths.config_path().chmod(0o600)


def snapshot(root: Path) -> dict[Path, tuple[bytes, int]]:
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def test_given_cached_layout_when_listing_sources_then_all_builds_and_prompts_found() -> None:
    # given
    home = paths.aiscript_home()
    expected = {
        put(home / "prompts" / "a.txt", "p"),
        put(home / "functions" / "a.sh", CLEAN_SH),
        put(home / "functions" / "b.ps1", "Write-Host hi\n"),
        put(home / "functions" / "c.py", "print(1)\n"),
        put(home / "functions" / "proj" / "main.py", "print(2)\n"),
        put(home / "file-cache" / "id1" / "version-abc" / "script.sh", CLEAN_SH),
        put(home / "file-cache" / "id1" / "version-abc" / "main.py", "print(3)\n"),
        put(home / "file-cache" / "id2" / "version-def" / "script.py", "print(4)\n"),
    }
    # when
    found = sweep.cached_sources(home)
    # then
    assert {p.resolve() for p in found} == {p.resolve() for p in expected}


def test_given_venv_temp_and_backup_files_when_listing_sources_then_skipped() -> None:
    # given
    home = paths.aiscript_home()
    keep = put(home / "functions" / "a.sh", CLEAN_SH)
    put(home / "functions" / "proj" / ".venv" / "lib" / "site.py", "x = 1\n")
    put(home / "functions" / "proj" / "main.py", "print(2)\n")
    put(home / "functions" / ".tmp.py", "x = 1\n")
    put(home / "functions" / ".a.sh.tmp", "x\n")
    put(home / "functions" / "a.sh.bak", "x\n")
    put(home / "functions" / "a.sh~", "x\n")
    put(home / "file-cache" / "id1" / "version-abc" / ".venv" / "lib" / "main.py", "x = 1\n")
    put(home / "file-cache" / "id1" / ".lock", "")
    put(home / "file-cache" / "id1" / "manifest.json", "{}")
    # when
    found = {p.resolve() for p in sweep.cached_sources(home)}
    # then
    assert found == {keep.resolve(), (home / "functions" / "proj" / "main.py").resolve()}


def test_given_missing_home_when_listing_sources_then_empty(tmp_path: Path) -> None:
    # when / then
    assert sweep.cached_sources(tmp_path / "nothing") == []


def test_given_one_leaky_one_clean_when_sweeping_then_only_leaky_reported() -> None:
    # given
    home = paths.aiscript_home()
    leaky = put(home / "functions" / "foo.sh", LEAKY_SH)
    clean = put(home / "functions" / "ok.sh", CLEAN_SH)
    secrets = KnownSecrets.from_values([KEY])
    # when
    result = sweep.sweep([leaky, clean], secrets)
    # then
    assert [p for p, _ in result] == [leaky]
    assert [f.line for f in result[0][1]] == [3]
    assert KEY not in repr(result)


def test_given_clean_home_when_checking_secrets_then_exit_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given
    write_config()
    home = paths.aiscript_home()
    put(home / "functions" / "ok.sh", CLEAN_SH)
    put(home / "prompts" / "ok.txt", "say hello\n")
    # when
    code = sweep.check_secrets()
    # then
    cap = capsys.readouterr()
    assert code == 0
    assert KEY not in cap.out + cap.err


@pytest.mark.parametrize(
    ("relative", "text"),
    [
        ("functions/foo.sh", LEAKY_SH),
        ("prompts/foo.txt", f"use key {KEY} to call the api\n"),
        ("file-cache/id1/version-abc/script.sh", LEAKY_SH),
        ("functions/proj/main.py", f'x = 1\ny = 2\nTOKEN = "{KEY}"\n'),
    ],
)
def test_given_key_in_a_stored_file_when_checking_secrets_then_exit_1_with_label_and_line(
    relative: str, text: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # given
    write_config()
    home = paths.aiscript_home()
    put(home / "functions" / "ok.sh", CLEAN_SH)
    put(home / relative, text)
    line = next(i for i, ln in enumerate(text.splitlines(), 1) if KEY in ln)
    # when
    code = sweep.check_secrets()
    # then
    cap = capsys.readouterr()
    output = (cap.out + cap.err).replace("\\", "/")
    assert code == 1
    assert f"{Path(relative).name}:{line}" in output
    assert KEY not in output
    assert "ok.sh" not in output


def test_given_leaky_build_when_checking_secrets_then_report_names_build_and_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given
    write_config()
    put(paths.aiscript_home() / "functions" / "foo.sh", LEAKY_SH)
    # when
    code = sweep.check_secrets()
    # then
    cap = capsys.readouterr()
    assert code == 1
    assert "functions/foo.sh:3: looks like an API key" in (cap.out + cap.err).replace("\\", "/")


def test_given_broken_reviewer_config_when_checking_secrets_then_sweep_still_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given: load_settings() would raise ConfigError for an undefined reviewer provider
    write_config(CONFIG + "reviewer_provider: does-not-exist\n")
    put(paths.aiscript_home() / "functions" / "foo.sh", LEAKY_SH)
    # when
    code = sweep.check_secrets()
    # then
    cap = capsys.readouterr()
    assert code == 1
    assert "foo.sh:3" in (cap.out + cap.err)


def test_given_broken_reviewer_config_and_clean_home_when_checking_secrets_then_exit_0() -> None:
    # given
    write_config(CONFIG + "reviewer_provider: does-not-exist\n")
    put(paths.aiscript_home() / "functions" / "ok.sh", CLEAN_SH)
    # when / then
    assert sweep.check_secrets() == 0


def test_given_key_only_in_environment_when_checking_secrets_then_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    put(paths.aiscript_home() / "functions" / "foo.sh", LEAKY_SH)
    # when / then
    assert sweep.check_secrets() == 1


def test_given_leaky_home_when_checking_secrets_then_nothing_is_modified() -> None:
    # given
    write_config()
    home = paths.aiscript_home()
    put(home / "functions" / "foo.sh", LEAKY_SH)
    put(home / "prompts" / "foo.txt", f"key {KEY}\n")
    put(home / "file-cache" / "id1" / "version-abc" / "script.sh", LEAKY_SH)
    before = snapshot(home)
    # when
    sweep.check_secrets()
    # then
    assert snapshot(home) == before


def test_given_leaky_home_when_running_cli_check_secrets_then_exit_1_and_clean_exit_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given
    write_config()
    home = paths.aiscript_home()
    put(home / "functions" / "ok.sh", CLEAN_SH)
    assert cli.main(["--check-secrets"]) == 0
    put(home / "functions" / "foo.sh", LEAKY_SH)
    # when
    code = cli.main(["--check-secrets"])
    # then
    cap = capsys.readouterr()
    assert code == 1
    assert KEY not in cap.out + cap.err
