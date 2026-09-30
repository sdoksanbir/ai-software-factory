import json

import pytest
from pydantic import ValidationError

from factory.schemas import FileChange, MultiFilePatch
from factory.tools.patch import PatchTool, PatchToolError


def test_legacy_write_defaults_operation():
    change = FileChange(
        path="a.py",
        content="x = 1\n",
    )

    assert change.operation == "write"
    assert change.content == "x = 1\n"


def test_explicit_write_accepted():
    change = FileChange(
        path="a.py",
        operation="write",
        content="ok\n",
    )

    assert change.operation == "write"


def test_explicit_empty_write_accepted():
    change = FileChange(
        path="a.py",
        operation="write",
        content="",
    )

    assert change.operation == "write"
    assert change.content == ""


def test_write_without_content_rejected():
    with pytest.raises(ValidationError):
        FileChange(path="a.py")


def test_explicit_write_without_content_rejected():
    with pytest.raises(ValidationError):
        FileChange(
            path="a.py",
            operation="write",
        )


def test_delete_without_content_accepted():
    change = FileChange(
        path="a.py",
        operation="delete",
    )

    assert change.operation == "delete"
    assert change.content == ""


def test_delete_with_empty_content_accepted():
    change = FileChange(
        path="a.py",
        operation="delete",
        content="",
    )

    assert change.operation == "delete"


def test_delete_with_non_empty_content_rejected():
    with pytest.raises(ValidationError):
        FileChange(
            path="a.py",
            operation="delete",
            content="nope",
        )


def test_invalid_operation_rejected():
    with pytest.raises(ValidationError):
        FileChange(
            path="a.py",
            operation="rename",
            content="x",
        )


def test_empty_files_list_rejected():
    with pytest.raises(ValidationError):
        MultiFilePatch(
            files=[],
            explanation="delete users",
        )


def test_parse_empty_files_list_rejected():
    with pytest.raises(PatchToolError):
        PatchTool.parse_multi_file_response(
            json.dumps(
                {
                    "files": [],
                    "explanation": "delete users",
                }
            )
        )


def test_parse_legacy_write_defaults_operation():
    patch = PatchTool.parse_multi_file_response(
        json.dumps(
            {
                "files": [
                    {
                        "path": "a.py",
                        "content": "x = 1",
                    }
                ]
            }
        )
    )

    assert patch.files[0].operation == "write"


def test_parse_write_without_content_rejected():
    with pytest.raises(PatchToolError):
        PatchTool.parse_multi_file_response(
            json.dumps(
                {
                    "files": [
                        {
                            "path": "a.py",
                        }
                    ]
                }
            )
        )
