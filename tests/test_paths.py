from pathlib import Path

import pytest

from aiscript import paths
from aiscript.errors import AiscriptError


def test_home_prefers_aiscript_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert paths.aiscript_home() == tmp_path / "aiscript"


def test_home_uses_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AISCRIPT_HOME")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert paths.aiscript_home() == tmp_path / "xdg" / "aiscript"


def test_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AISCRIPT_HOME")
    assert paths.aiscript_home() == Path.home() / ".config" / "aiscript"


def test_home_reads_env_each_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISCRIPT_HOME", str(tmp_path / "a"))
    first = paths.aiscript_home()
    monkeypatch.setenv("AISCRIPT_HOME", str(tmp_path / "b"))
    assert paths.aiscript_home() != first


@pytest.mark.parametrize("name", ["foo", "a", "my-cmd", "my_cmd", "9lives", "Foo-Bar_1"])
def test_valid_names(name: str) -> None:
    assert paths.validate_command_name(name) == name


@pytest.mark.parametrize(
    "name", ["", "../x", "a/b", "a\\b", "-foo", "_foo", "a b", "a.b", ".hidden", "a\n", "é"]
)
def test_invalid_names(name: str) -> None:
    with pytest.raises(AiscriptError):
        paths.validate_command_name(name)


def test_dir_helpers(tmp_path: Path) -> None:
    home = tmp_path / "aiscript"
    assert paths.prompts_dir() == home / "prompts"
    assert paths.functions_dir() == home / "functions"
    assert paths.config_path() == home / "config.yaml"
    assert paths.legacy_secrets_path() == home / "secrets.yaml"


def test_shell_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert not paths.is_windows()
    assert paths.shell_kind() == "bash"
    assert paths.script_ext() == "sh"
    monkeypatch.setattr("platform.system", lambda: "Windows")
    assert paths.is_windows()
    assert paths.shell_kind() == "powershell"
    assert paths.script_ext() == "ps1"


def test_prompt_and_function_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert paths.prompt_path("foo") == tmp_path / "aiscript" / "prompts" / "foo.txt"
    assert paths.function_path("foo") == tmp_path / "aiscript" / "functions" / "foo.sh"
    monkeypatch.setattr("platform.system", lambda: "Windows")
    assert paths.function_path("foo").name == "foo.ps1"


def test_path_helpers_reject_traversal() -> None:
    with pytest.raises(AiscriptError):
        paths.prompt_path("../evil")
    with pytest.raises(AiscriptError):
        paths.function_path("../evil")


def test_ensure_dirs_creates_and_is_idempotent() -> None:
    paths.ensure_dirs()
    paths.ensure_dirs()
    assert paths.prompts_dir().is_dir()
    assert paths.functions_dir().is_dir()
    assert not paths.config_path().exists()


def _linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")


def test_function_path_lookup_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch)
    paths.ensure_dirs()
    fdir = paths.functions_dir()
    assert paths.function_path("foo") == fdir / "foo.sh"
    (fdir / "foo.sh").write_text("")
    assert paths.function_path("foo") == fdir / "foo.sh"
    (fdir / "foo.py").write_text("")
    assert paths.function_path("foo") == fdir / "foo.py"
    paths.project_dir("foo").mkdir()
    assert paths.function_path("foo") == fdir / "foo.py"  # dir without main.py is ignored
    (paths.project_dir("foo") / "main.py").write_text("")
    assert paths.function_path("foo") == fdir / "foo" / "main.py"


def test_function_target(monkeypatch: pytest.MonkeyPatch) -> None:
    fdir = paths.functions_dir()
    assert paths.function_target("a", "python", has_deps=True) == fdir / "a" / "main.py"
    assert paths.function_target("a", "python", has_deps=False) == fdir / "a.py"
    assert paths.function_target("a", "bash", has_deps=False) == fdir / "a.sh"
    assert paths.function_target("a", "powershell", has_deps=False) == fdir / "a.ps1"
    with pytest.raises(AiscriptError):
        paths.function_target("../a", "bash", has_deps=False)


def test_function_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    paths.ensure_dirs()
    fdir = paths.functions_dir()
    assert paths.function_artifacts("foo") == []
    (fdir / "foo.sh").write_text("")
    (fdir / "foo.py").write_text("")
    (fdir / "other.sh").write_text("")
    paths.project_dir("foo").mkdir()
    assert paths.function_artifacts("foo") == [fdir / "foo.sh", fdir / "foo.py"]
    (paths.project_dir("foo") / "main.py").write_text("")
    assert paths.function_artifacts("foo")[-1] == paths.project_dir("foo")
    with pytest.raises(AiscriptError):
        paths.function_artifacts("../x")


def test_language_of() -> None:
    assert paths.language_of(Path("a.py")) == "python"
    assert paths.language_of(Path("a/main.py")) == "python"
    assert paths.language_of(Path("a.ps1")) == "powershell"
    assert paths.language_of(Path("a.sh")) == "bash"


def test_venv_python(monkeypatch: pytest.MonkeyPatch) -> None:
    proj = Path("p")
    _linux(monkeypatch)
    assert paths.venv_python(proj) == proj / ".venv" / "bin" / "python"
    monkeypatch.setattr("platform.system", lambda: "Windows")
    assert paths.venv_python(proj) == proj / ".venv" / "Scripts" / "python.exe"
