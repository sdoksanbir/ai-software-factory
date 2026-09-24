import os

import pytest

from factory.general_agent_contracts import (
    Permission,
    ToolRequest,
)
from factory.general_filesystem_tools import (
    FileTooLargeError,
    MAX_READ_BYTES,
    UnsafeProjectPathError,
    build_filesystem_tool_registry,
)


def test_list_files_reads_real_project_tree(
    tmp_path,
):
    (tmp_path / "manage.py").write_text(
        "# manage",
        encoding="utf-8",
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "hidden.py").write_text(
        "hidden",
        encoding="utf-8",
    )

    registry = (
        build_filesystem_tool_registry(
            str(tmp_path)
        )
    )

    result = registry.execute(
        ToolRequest(
            tool_name="list_files",
            arguments={},
            permission=Permission.READ,
        )
    )

    names = {
        item["name"]
        for item in result["entries"]
    }

    assert "manage.py" in names
    assert "app" in names
    assert "venv" not in names


def test_find_files_finds_nested_manage_py(
    tmp_path,
):
    nested = (
        tmp_path
        / "okulprojesi"
    )
    nested.mkdir()
    (nested / "manage.py").write_text(
        "# manage",
        encoding="utf-8",
    )

    registry = (
        build_filesystem_tool_registry(
            str(tmp_path)
        )
    )

    result = registry.execute(
        ToolRequest(
            tool_name="find_files",
            arguments={
                "pattern": "manage.py",
            },
            permission=Permission.READ,
        )
    )

    assert result["matches"] == [
        "okulprojesi/manage.py",
    ]


def test_read_file_returns_content(
    tmp_path,
):
    (tmp_path / "README.md").write_text(
        "hello",
        encoding="utf-8",
    )

    registry = (
        build_filesystem_tool_registry(
            str(tmp_path)
        )
    )

    result = registry.execute(
        ToolRequest(
            tool_name="read_file",
            arguments={
                "path": "README.md",
            },
            permission=Permission.READ,
        )
    )

    assert result["content"] == "hello"
    assert result["path"] == "README.md"


def test_file_exists_supports_cwd(
    tmp_path,
):
    project = tmp_path / "okulprojesi"
    users = project / "users"
    users.mkdir(parents=True)
    (users / "apps.py").write_text(
        "",
        encoding="utf-8",
    )

    registry = (
        build_filesystem_tool_registry(
            str(tmp_path)
        )
    )

    result = registry.execute(
        ToolRequest(
            tool_name="file_exists",
            arguments={
                "path": "users/apps.py",
            },
            permission=Permission.READ,
            cwd="okulprojesi",
        )
    )

    assert result["exists"] is True
    assert (
        result["path"]
        == "okulprojesi/users/apps.py"
    )


def test_parent_escape_is_rejected(
    tmp_path,
):
    registry = (
        build_filesystem_tool_registry(
            str(tmp_path)
        )
    )

    with pytest.raises(
        UnsafeProjectPathError,
        match="disina",
    ):
        registry.execute(
            ToolRequest(
                tool_name="read_file",
                arguments={
                    "path": "../secret.txt",
                },
                permission=Permission.READ,
            )
        )


def test_absolute_path_outside_project_is_rejected(
    tmp_path,
):
    outside = (
        tmp_path.parent
        / "outside.txt"
    )
    outside.write_text(
        "secret",
        encoding="utf-8",
    )

    registry = (
        build_filesystem_tool_registry(
            str(tmp_path)
        )
    )

    with pytest.raises(
        UnsafeProjectPathError,
    ):
        registry.execute(
            ToolRequest(
                tool_name="read_file",
                arguments={
                    "path": str(outside),
                },
                permission=Permission.READ,
            )
        )


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "Windows symlink creation may require "
        "Developer Mode/admin privileges."
    ),
)
def test_symlink_escape_is_rejected(
    tmp_path,
):
    outside = (
        tmp_path.parent
        / "outside-symlink.txt"
    )
    outside.write_text(
        "secret",
        encoding="utf-8",
    )

    link = tmp_path / "link.txt"
    link.symlink_to(outside)

    registry = (
        build_filesystem_tool_registry(
            str(tmp_path)
        )
    )

    with pytest.raises(
        UnsafeProjectPathError,
    ):
        registry.execute(
            ToolRequest(
                tool_name="read_file",
                arguments={
                    "path": "link.txt",
                },
                permission=Permission.READ,
            )
        )


def test_large_file_is_rejected(
    tmp_path,
):
    large = tmp_path / "large.txt"
    large.write_bytes(
        b"x" * (
            MAX_READ_BYTES + 1
        )
    )

    registry = (
        build_filesystem_tool_registry(
            str(tmp_path)
        )
    )

    with pytest.raises(
        FileTooLargeError,
        match="sinirini",
    ):
        registry.execute(
            ToolRequest(
                tool_name="read_file",
                arguments={
                    "path": "large.txt",
                },
                permission=Permission.READ,
            )
        )


def test_write_tool_is_bound_but_execute_tool_is_not_yet(
    tmp_path,
):
    registry = (
        build_filesystem_tool_registry(
            str(tmp_path)
        )
    )

    assert (
        registry.get(
            "write_file"
        ).handler
        is not None
    )

    assert (
        registry.get(
            "run_process"
        ).handler
        is None
    )
