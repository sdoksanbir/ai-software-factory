import pytest

from factory.general_agent_contracts import (
    Permission,
    ToolRequest,
)
from factory.tool_registry import (
    ToolDefinition,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRegistry,
    ToolRegistryError,
    ToolValidationError,
    build_contract_registry,
)


def test_contract_registry_has_initial_generic_tools():
    registry = build_contract_registry()

    assert {
        "list_files",
        "find_files",
        "read_file",
        "file_exists",
        "write_file",
        "run_process",
        "git_diff",
        "run_tests",
    }.issubset(
        set(registry.names())
    )


def test_model_description_does_not_expose_handler():
    registry = ToolRegistry(
        [
            ToolDefinition(
                name="demo",
                description="Demo tool",
                permission=Permission.READ,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                handler=lambda args, cwd: "secret",
            )
        ]
    )

    payload = registry.describe_for_model()

    assert payload == [
        {
            "name": "demo",
            "description": "Demo tool",
            "permission": "read",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }
    ]
    assert "handler" not in payload[0]


def test_duplicate_tool_registration_is_rejected():
    registry = ToolRegistry()

    tool = ToolDefinition(
        name="read_file",
        description="Read",
        permission=Permission.READ,
        input_schema={
            "type": "object",
            "properties": {},
        },
    )

    registry.register(tool)

    with pytest.raises(
        ToolRegistryError,
        match="zaten kayitli",
    ):
        registry.register(tool)


def test_unknown_tool_is_rejected():
    registry = ToolRegistry()

    with pytest.raises(
        ToolNotFoundError,
        match="bulunamadi",
    ):
        registry.get(
            "missing"
        )


def test_request_permission_must_match_definition():
    registry = build_contract_registry()

    request = ToolRequest(
        tool_name="read_file",
        arguments={
            "path": "README.md",
        },
        permission=Permission.WRITE,
    )

    with pytest.raises(
        ToolPermissionError,
        match="permission",
    ):
        registry.validate_request(
            request
        )


def test_required_argument_is_enforced():
    registry = build_contract_registry()

    request = ToolRequest(
        tool_name="read_file",
        arguments={},
        permission=Permission.READ,
    )

    with pytest.raises(
        ToolValidationError,
        match="eksik arguman",
    ):
        registry.validate_request(
            request
        )


def test_unknown_argument_is_rejected():
    registry = build_contract_registry()

    request = ToolRequest(
        tool_name="file_exists",
        arguments={
            "path": "manage.py",
            "surprise": True,
        },
        permission=Permission.READ,
    )

    with pytest.raises(
        ToolValidationError,
        match="bilinmeyen arguman",
    ):
        registry.validate_request(
            request
        )


def test_basic_argument_type_is_checked():
    registry = build_contract_registry()

    request = ToolRequest(
        tool_name="run_process",
        arguments={
            "argv": "python manage.py check",
        },
        permission=Permission.EXECUTE,
    )

    with pytest.raises(
        ToolValidationError,
        match="array olmali",
    ):
        registry.validate_request(
            request
        )


def test_handler_execution_goes_through_validation():
    captured = {}

    def handler(args, cwd):
        captured["args"] = args
        captured["cwd"] = cwd
        return {
            "ok": True,
        }

    registry = ToolRegistry(
        [
            ToolDefinition(
                name="echo",
                description="Echo",
                permission=Permission.EXECUTE,
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "text",
                    ],
                    "additionalProperties": False,
                },
                handler=handler,
            )
        ]
    )

    result = registry.execute(
        ToolRequest(
            tool_name="echo",
            arguments={
                "text": "merhaba",
            },
            permission=Permission.EXECUTE,
            cwd="project",
        )
    )

    assert result == {
        "ok": True,
    }
    assert captured == {
        "args": {
            "text": "merhaba",
        },
        "cwd": "project",
    }


def test_contract_only_tool_cannot_execute_yet():
    registry = build_contract_registry()

    with pytest.raises(
        ToolRegistryError,
        match="handler bagli degil",
    ):
        registry.execute(
            ToolRequest(
                tool_name="read_file",
                arguments={
                    "path": "README.md",
                },
                permission=Permission.READ,
            )
        )
