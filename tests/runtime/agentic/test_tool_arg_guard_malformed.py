"""Malformed schemas and malformed argument payloads for the arg guard.

MCP adapters forward whatever JSON Schema the upstream server ships, and
providers send argument payloads the schema never promised, so the guard's
schema walk and the absent/blank split must survive junk without raising.
These tests pin the defensive branches: non-string required names, wrong
container types, non-list enums, ``None`` values, and the message framing
each case produces.
"""

from __future__ import annotations

from deeptutor.core.tool_protocol import ToolDefinition, ToolParameter
from deeptutor.runtime.agentic.tool_arg_guard import (
    RequiredArg,
    missing_args_message,
    missing_required_args,
    required_args,
    unsatisfied_required_args,
)


def _raw(schema: dict) -> ToolDefinition:
    return ToolDefinition(name="mcp_tool", description="", raw_parameters=schema)


def test_raw_schema_required_entries_that_are_not_strings_are_skipped() -> None:
    definition = _raw(
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path", 42, None, ""],
        }
    )

    assert [arg.name for arg in required_args(definition)] == ["path"]


def test_raw_schema_required_that_is_not_a_list_reports_nothing() -> None:
    definition = _raw(
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": "path",
        }
    )

    assert required_args(definition) == []
    assert missing_required_args(definition, {}) == []


def test_raw_schema_properties_missing_or_malformed_degrades_to_plain_args() -> None:
    no_props = _raw({"type": "object", "required": ["path"]})
    junk_props = _raw({"type": "object", "properties": ["path"], "required": ["path"]})

    for definition in (no_props, junk_props):
        (arg,) = required_args(definition)
        assert arg.name == "path"
        assert arg.type == ""
        assert arg.enum == ()


def test_raw_schema_enum_that_is_not_a_list_yields_no_enum_values() -> None:
    definition = _raw(
        {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": "append"}},
            "required": ["mode"],
        }
    )

    (arg,) = required_args(definition)
    assert arg.enum == ()


def test_required_arg_describe_renders_type_and_enum_shape() -> None:
    assert RequiredArg(name="q").describe() == "q (value)"
    assert RequiredArg(name="mode", type="string").describe() == "mode (string)"
    assert (
        RequiredArg(name="mode", type="string", enum=("append", "edit")).describe()
        == "mode (string, one of: append | edit)"
    )


def test_none_value_counts_as_absent_not_blank() -> None:
    definition = ToolDefinition(
        name="t",
        description="",
        parameters=[ToolParameter(name="path", type="string")],
    )

    absent, blank = unsatisfied_required_args(definition, {"path": None})

    assert [arg.name for arg in absent] == ["path"]
    assert blank == []


def test_missing_required_args_orders_absent_before_blank() -> None:
    definition = ToolDefinition(
        name="t",
        description="",
        parameters=[
            ToolParameter(name="path", type="string"),
            ToolParameter(name="content", type="string"),
        ],
    )

    missing = missing_required_args(definition, {"content": ""})

    assert [arg.name for arg in missing] == ["path", "content"]


def test_message_with_no_missing_arguments_falls_back_to_generic_body() -> None:
    message = missing_args_message("write_note", [])

    assert "write_note` was called with incomplete arguments" in message
    assert "rejected again" in message


def test_legacy_caller_passing_blank_args_in_missing_keeps_missing_framing() -> None:
    blank = RequiredArg(name="content", type="string")

    message = missing_args_message("t", [blank])

    assert "without its required argument(s): `content`" in message
    assert "received empty value(s)" not in message


def test_tab_only_string_argument_is_blank_too() -> None:
    definition = ToolDefinition(
        name="t",
        description="",
        parameters=[ToolParameter(name="command", type="string")],
    )

    absent, blank = unsatisfied_required_args(definition, {"command": "\t \n"})

    assert absent == []
    assert [arg.name for arg in blank] == ["command"]
