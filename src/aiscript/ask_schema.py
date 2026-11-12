"""Schema subset check (F6) and instance validation (F12); stdlib only."""

from __future__ import annotations

from typing import Any, Final

from aiscript.errors import AskOutputError, AskUsageError

MAX_DEPTH: Final = 5
MAX_PROPERTIES: Final = 100
_TYPES: Final = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
_KEYWORDS: Final = frozenset(
    {"type", "description", "enum", "properties", "required", "additionalProperties", "items"}
)


def check_schema_subset(schema: object) -> None:
    """Raise ``AskUsageError`` unless ``schema`` is in the supported strict-schema subset (F6)."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise AskUsageError("schema must be a JSON object whose root has type 'object'")
    count = _check_node(schema, "schema", 1)
    if count > MAX_PROPERTIES:
        raise AskUsageError(f"schema has more than {MAX_PROPERTIES} properties")


def _check_node(node: object, path: str, depth: int) -> int:
    """Check one sub-schema; return the number of object properties it contains."""
    if not isinstance(node, dict):
        raise AskUsageError(f"{path}: must be an object")
    unknown = sorted(set(node) - _KEYWORDS)
    if unknown:
        raise AskUsageError(f"{path}: unsupported keyword '{unknown[0]}'")
    type_name = node.get("type")
    if type_name is None:
        if "enum" not in node:
            raise AskUsageError(f"{path}: needs 'type'")
    elif not isinstance(type_name, str) or type_name not in _TYPES:
        raise AskUsageError(f"{path}: unsupported type")
    if "enum" in node and not isinstance(node["enum"], list):
        raise AskUsageError(f"{path}: 'enum' must be a list")
    if type_name == "object":
        return _check_object(node, path, depth)
    if type_name == "array":
        if "items" not in node:
            raise AskUsageError(f"{path}: array needs 'items'")
        return _check_node(node["items"], f"{path}.items", depth)
    return 0


def _check_object(node: dict[str, Any], path: str, depth: int) -> int:
    if depth > MAX_DEPTH:
        raise AskUsageError(f"schema is nested deeper than {MAX_DEPTH} levels")
    properties = node.get("properties")
    required = node.get("required")
    if not isinstance(properties, dict):
        raise AskUsageError(f"{path}: object needs 'properties'")
    if (
        not isinstance(required, list)
        or not all(isinstance(item, str) for item in required)
        or set(required) != set(properties)
    ):
        raise AskUsageError(f"{path}: 'required' must list every property")
    if node.get("additionalProperties") is not False:
        raise AskUsageError(f"{path}: 'additionalProperties' must be false")
    total = len(properties)
    for name, child in properties.items():
        total += _check_node(child, f"{path}.{name}", depth + 1)
    return total


def validate_instance(value: object, schema: dict[str, Any]) -> None:
    """Raise ``AskOutputError`` unless ``value`` satisfies ``schema`` (F12)."""
    problem = _problem(value, schema, "$")
    if problem is not None:
        raise AskOutputError(f"The reply does not match the schema ({problem}).")


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def _matches_type(value: object, type_name: str) -> bool:
    actual = _json_type(value)
    if type_name == "number":
        return actual in ("integer", "number")
    return actual == type_name


def _problem(value: object, schema: dict[str, Any], path: str) -> str | None:
    type_name = schema.get("type")
    if isinstance(type_name, str) and not _matches_type(value, type_name):
        return f"{path}: expected {type_name}"
    allowed = schema.get("enum")
    if isinstance(allowed, list) and not any(
        _json_type(item) == _json_type(value) and item == value for item in allowed
    ):
        return f"{path}: not an allowed value"
    if isinstance(value, dict):
        properties: dict[str, Any] = schema.get("properties", {})
        for key in value:
            if key not in properties:
                return f"{path}: unexpected key"
        for key, child in properties.items():
            if key not in value:
                return f"{path}: missing key '{key}'"
            found = _problem(value[key], child, f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            found = _problem(item, schema["items"], f"{path}[{index}]")
            if found is not None:
                return found
    return None
