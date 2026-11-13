"""Provider boundary contract scenarios S4 and S18."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from aiscript.providers.contracts import (
    CompletionError,
    CompletionRequest,
    ProviderCapabilities,
    enforce_capabilities,
)
from aiscript.runner import SHIM_DIR

PROVIDERS_DIR = Path(__file__).parent.parent / "src" / "aiscript" / "providers"


def _imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name} uses a relative import"
            names.add(node.module or "")
    return names


def test_given_provider_modules_when_imports_are_read_then_no_application_module_is_used() -> None:
    # given
    modules = sorted(PROVIDERS_DIR.glob("*.py"))
    # when
    application = {
        f"{path.name}: {name}"
        for path in modules
        for name in _imported_modules(path)
        if (name == "aiscript" or name.startswith("aiscript."))
        and not name.startswith("aiscript.providers")
    }
    # then
    assert len(modules) >= 4
    assert application == set()


def test_given_provider_boundary_when_imported_then_no_application_module_is_loaded() -> None:
    # given
    code = (
        "import sys, aiscript.providers.acp, aiscript.providers.anthropic, "
        "aiscript.providers.gemini, aiscript.providers.contracts\n"
        "bad = sorted(m for m in sys.modules if m.startswith('aiscript.') "
        "and not m.startswith('aiscript.providers'))\n"
        "print(bad)"
    )
    # when
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    # then
    assert done.stdout.strip() == "[]"


def test_given_shim_when_imports_are_read_then_it_does_not_use_the_provider_boundary() -> None:
    # given
    shim = SHIM_DIR / "aiscript" / "__init__.py"
    # when
    names = _imported_modules(shim)
    # then
    assert not [n for n in names if n.startswith("aiscript")]


def test_given_strict_schema_required_but_not_offered_then_unsupported_error_is_actionable() -> (
    None
):
    # given
    request = CompletionRequest("i", "d", {"type": "object"}, 10, require_strict_schema=True)
    offered = ProviderCapabilities(False, False, False, False)
    # when / then
    with pytest.raises(CompletionError) as caught:
        enforce_capabilities(request, offered)
    assert caught.value.kind == "unsupported"
    assert caught.value.detail is not None
    assert "strict" in caught.value.detail


def test_given_strict_schema_not_required_when_not_offered_then_request_is_allowed() -> None:
    # given
    request = CompletionRequest("i", "d", {"type": "object"}, 10)
    # when / then
    enforce_capabilities(request, ProviderCapabilities(False, False, False, False))
