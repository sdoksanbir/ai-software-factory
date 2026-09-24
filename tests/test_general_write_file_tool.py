import pytest

from factory.general_agent_contracts import (
    Permission,
    ToolRequest,
)
from factory.general_filesystem_tools import (
    FileTooLargeError,
    MAX_WRITE_BYTES,
    ProtectedProjectPathError,
    UnsafeProjectPathError,
    build_filesystem_tool_registry,
)


def test_write_file_creates_nested_file(
    tmp_path,
):
    registry = build_filesystem_tool_registry(
        str(tmp_path)
    )

    result = registry.execute(
        ToolRequest(
            tool_name="write_file",
            arguments={
                "path": "src/demo.txt",
                "content": "merhaba",
            },
            permission=Permission.WRITE,
        )
    )

    assert (
        tmp_path
        / "src"
        / "demo.txt"
    ).read_text(
        encoding="utf-8"
    ) == "merhaba"

    assert result["created"] is True
    assert result["overwritten"] is False


def test_write_file_can_overwrite_existing_file(
    tmp_path,
):
    target = tmp_path / "README.md"
    target.write_text(
        "old",
        encoding="utf-8",
    )

    registry = build_filesystem_tool_registry(
        str(tmp_path)
    )

    result = registry.execute(
        ToolRequest(
            tool_name="write_file",
            arguments={
                "path": "README.md",
                "content": "new",
            },
            permission=Permission.WRITE,
        )
    )

    assert target.read_text(
        encoding="utf-8"
    ) == "new"

    assert result["created"] is False
    assert result["overwritten"] is True


def test_write_file_supports_cwd(
    tmp_path,
):
    project = tmp_path / "okulprojesi"
    project.mkdir()

    registry = build_filesystem_tool_registry(
        str(tmp_path)
    )

    result = registry.execute(
        ToolRequest(
            tool_name="write_file",
            arguments={
                "path": "users/apps.py",
                "content": "# apps",
            },
            permission=Permission.WRITE,
            cwd="okulprojesi",
        )
    )

    assert (
        project
        / "users"
        / "apps.py"
    ).exists()

    assert result["path"] == (
        "okulprojesi/users/apps.py"
    )


def test_write_file_rejects_parent_escape(
    tmp_path,
):
    registry = build_filesystem_tool_registry(
        str(tmp_path)
    )

    with pytest.raises(
        UnsafeProjectPathError,
    ):
        registry.execute(
            ToolRequest(
                tool_name="write_file",
                arguments={
                    "path": "../outside.txt",
                    "content": "x",
                },
                permission=Permission.WRITE,
            )
        )


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        "venv/bad.txt",
        ".venv/bad.txt",
        "node_modules/bad.txt",
    ],
)
def test_write_file_rejects_protected_paths(
    tmp_path,
    path,
):
    registry = build_filesystem_tool_registry(
        str(tmp_path)
    )

    with pytest.raises(
        ProtectedProjectPathError,
        match="Korunan",
    ):
        registry.execute(
            ToolRequest(
                tool_name="write_file",
                arguments={
                    "path": path,
                    "content": "x",
                },
                permission=Permission.WRITE,
            )
        )


def test_write_file_rejects_large_content(
    tmp_path,
):
    registry = build_filesystem_tool_registry(
        str(tmp_path)
    )

    with pytest.raises(
        FileTooLargeError,
        match="yazma sinirini",
    ):
        registry.execute(
            ToolRequest(
                tool_name="write_file",
                arguments={
                    "path": "large.txt",
                    "content": "x" * (
                        MAX_WRITE_BYTES + 1
                    ),
                },
                permission=Permission.WRITE,
            )
        )


def test_run_process_still_has_no_handler(
    tmp_path,
):
    registry = build_filesystem_tool_registry(
        str(tmp_path)
    )

    assert (
        registry.get(
            "run_process"
        ).handler
        is None
    )
