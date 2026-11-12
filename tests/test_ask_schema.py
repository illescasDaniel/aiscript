"""Strict-schema subset check (F6, S10) and instance validation (F12, S16)."""

from __future__ import annotations

from typing import Any

import pytest

from aiscript.ask_schema import check_schema_subset, validate_instance
from aiscript.errors import AskOutputError, AskUsageError


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _nested(levels: int) -> dict[str, Any]:
    """Objects nested ``levels`` deep; the root is level 1."""
    schema = _obj({"leaf": {"type": "string"}})
    for _ in range(levels - 1):
        schema = _obj({"child": schema})
    return schema


SUMMARY_SCHEMA = _obj(
    {
        "summary": {"type": "string", "description": "Short."},
        "security_related": {"type": "array", "items": {"type": "string"}},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
    }
)

VALID_SCHEMAS = {
    "all_scalar_types": _obj(
        {
            "s": {"type": "string"},
            "n": {"type": "number"},
            "i": {"type": "integer"},
            "b": {"type": "boolean"},
            "z": {"type": "null"},
        }
    ),
    "package_update_example": SUMMARY_SCHEMA,
    "empty_object": _obj({}),
    "nested_object": _obj({"inner": _obj({"x": {"type": "integer"}})}),
    "array_of_objects": _obj({"rows": {"type": "array", "items": _obj({"k": {"type": "string"}})}}),
    "depth_five": _nested(5),
    "hundred_properties": _obj({f"p{i}": {"type": "string"} for i in range(100)}),
}

INVALID_SCHEMAS = {
    "not_a_dict": ["object"],
    "none": None,
    "string_root": "object",
    "array_root": {"type": "array", "items": {"type": "string"}},
    "string_root_type": {"type": "string"},
    "missing_root_type": {
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
    },
    "property_missing_from_required": {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
    },
    "required_missing_entirely": {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "additionalProperties": False,
    },
    "additional_properties_missing": {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
    },
    "additional_properties_true": {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": True,
    },
    "nested_object_not_strict": _obj(
        {
            "inner": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": [],
                "additionalProperties": False,
            }
        }
    ),
    "nested_additional_properties_true": _obj(
        {
            "inner": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": True,
            }
        }
    ),
    "depth_six": _nested(6),
    "hundred_and_one_properties": _obj({f"p{i}": {"type": "string"} for i in range(101)}),
    "unknown_type": _obj({"a": {"type": "date"}}),
    "type_not_a_string": _obj({"a": {"type": 3}}),
    "array_without_items": _obj({"a": {"type": "array"}}),
    "unsupported_keyword": _obj({"a": {"type": "string", "pattern": "^x$"}}),
    "required_with_list_item": {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": [["a"]],
        "additionalProperties": False,
    },
    "required_with_object_item": {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": [{"a": 1}],
        "additionalProperties": False,
    },
    "properties_not_a_dict": {
        "type": "object",
        "properties": ["a"],
        "required": ["a"],
        "additionalProperties": False,
    },
}


@pytest.mark.parametrize("schema", VALID_SCHEMAS.values(), ids=VALID_SCHEMAS.keys())
def test_given_supported_schema_when_checked_then_accepted(schema: dict[str, Any]) -> None:
    # given a schema inside the strict subset
    # when it is checked
    check_schema_subset(schema)
    # then nothing is raised


@pytest.mark.parametrize("schema", INVALID_SCHEMAS.values(), ids=INVALID_SCHEMAS.keys())
def test_given_schema_outside_subset_when_checked_then_usage_error(schema: object) -> None:
    # given a schema outside the strict subset
    # when it is checked
    # then it is a usage error (F6, S10)
    with pytest.raises(AskUsageError):
        check_schema_subset(schema)


def test_given_conforming_value_when_validated_then_accepted() -> None:
    # given a value that matches the schema
    value = {"summary": "ok", "security_related": ["openssl"], "risk": "low"}
    # when it is validated
    validate_instance(value, SUMMARY_SCHEMA)
    # then nothing is raised


def test_given_nested_conforming_value_when_validated_then_accepted() -> None:
    # given a nested value with an integer, a null and an array of objects
    schema = _obj(
        {
            "n": {"type": "integer"},
            "z": {"type": "null"},
            "rows": {"type": "array", "items": _obj({"k": {"type": "number"}})},
        }
    )
    value = {"n": 3, "z": None, "rows": [{"k": 1}, {"k": 2.5}]}
    # when it is validated
    validate_instance(value, schema)
    # then nothing is raised


BAD_INSTANCES = {
    "missing_field": {"summary": "ok", "risk": "low"},
    "wrong_type_string": {"summary": 3, "security_related": [], "risk": "low"},
    "wrong_type_array": {"summary": "ok", "security_related": "openssl", "risk": "low"},
    "wrong_type_array_item": {"summary": "ok", "security_related": [1], "risk": "low"},
    "extra_key": {"summary": "ok", "security_related": [], "risk": "low", "note": "x"},
    "enum_violation": {"summary": "ok", "security_related": [], "risk": "critical"},
    "null_for_string": {"summary": None, "security_related": [], "risk": "low"},
}


@pytest.mark.parametrize("value", BAD_INSTANCES.values(), ids=BAD_INSTANCES.keys())
def test_given_nonconforming_value_when_validated_then_output_error(
    value: dict[str, Any],
) -> None:
    # given a value that violates the schema
    # when it is validated
    # then it is an output error (F12, S16)
    with pytest.raises(AskOutputError):
        validate_instance(value, SUMMARY_SCHEMA)


@pytest.mark.parametrize("value", [[], "text", 3, None, [{"summary": "ok"}]])
def test_given_non_object_value_when_validated_then_output_error(value: object) -> None:
    # given a value that is not an object while the root is an object
    # when it is validated
    # then it is an output error
    with pytest.raises(AskOutputError):
        validate_instance(value, SUMMARY_SCHEMA)


def test_given_extra_key_in_nested_object_when_validated_then_output_error() -> None:
    # given a nested object carrying a key the schema does not list
    schema = _obj({"inner": _obj({"x": {"type": "integer"}})})
    # when it is validated
    # then it is an output error
    with pytest.raises(AskOutputError):
        validate_instance({"inner": {"x": 1, "y": 2}}, schema)


@pytest.mark.parametrize("type_name", ["integer", "number"])
@pytest.mark.parametrize("flag", [True, False])
def test_given_bool_when_validated_as_number_then_output_error(type_name: str, flag: bool) -> None:
    # given a bool where an integer or a number is required (bool is not a number here)
    schema = _obj({"v": {"type": type_name}})
    # when it is validated
    # then it is an output error
    with pytest.raises(AskOutputError):
        validate_instance({"v": flag}, schema)


def test_given_float_when_validated_as_integer_then_output_error() -> None:
    # given a non-integral float where an integer is required
    schema = _obj({"v": {"type": "integer"}})
    # when it is validated
    # then it is an output error
    with pytest.raises(AskOutputError):
        validate_instance({"v": 1.5}, schema)


def test_given_int_when_validated_as_number_then_accepted() -> None:
    # given an int where a number is allowed
    schema = _obj({"v": {"type": "number"}})
    # when it is validated
    validate_instance({"v": 2}, schema)
    # then nothing is raised


def test_given_bool_when_validated_as_boolean_then_accepted() -> None:
    # given a bool where a boolean is required
    schema = _obj({"v": {"type": "boolean"}})
    # when it is validated
    validate_instance({"v": False}, schema)
    # then nothing is raised


@pytest.mark.parametrize(
    ("allowed", "value"),
    [
        ([0, 1], False),
        ([0, 1], True),
        ([1, 2], True),
        (["1", "2"], 1),
        ([1, 2], "1"),
        ([1, 2], 1.5),
    ],
)
def test_given_enum_and_value_of_other_type_when_validated_then_output_error(
    allowed: list[object], value: object
) -> None:
    # given an enum and a value equal under Python == but of another JSON type
    schema = _obj({"v": {"enum": allowed}})
    # when it is validated
    # then it is an output error (type-strict enum)
    with pytest.raises(AskOutputError):
        validate_instance({"v": value}, schema)


def test_given_enum_member_of_same_type_when_validated_then_accepted() -> None:
    # given an integer enum and one of its members
    schema = _obj({"v": {"type": "integer", "enum": [1, 2, 3]}})
    # when it is validated
    validate_instance({"v": 2}, schema)
    # then nothing is raised
