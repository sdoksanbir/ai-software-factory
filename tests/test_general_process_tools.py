import sys

import pytest

from factory.general_agent_contracts import (
    Permission,
    ToolRequest,
)
from factory.general_process_tools import (
    UnsafeExecutableError,
    UnsafeProcessArgumentsError,
    build_project_tool_registry,
)


def test_run_process_executes_structured_python_file(
    tmp_path,
):
    script = tmp_path / "hello.py"
    script.write_text(
        'print("merhaba")',
        encoding="utf-8",
    )

    registry = build_project_tool_registry(
        str(tmp_path)
    )

    result = registry.execute(
        ToolRequest(
            tool_name="run_process",
            arguments={
                "argv": [
                    sys.executable,
                    "hello.py",
                ],
            },
            permission=Permission.EXECUTE,
        )
    )

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "merhaba"
    assert result["timed_out"] is False


def test_run_process_supports_project_cwd(
    tmp_path,
):
    nested = tmp_path / "okulprojesi"
    nested.mkdir()

    script = nested / "where.py"
    script.write_text(
        "from pathlib import Path\n"
        "print(Path.cwd().name)\n",
        encoding="utf-8",
    )

    registry = build_project_tool_registry(
        str(tmp_path)
    )

    result = registry.execute(
        ToolRequest(
            tool_name="run_process",
            arguments={
                "argv": [
                    sys.executable,
                    "where.py",
                ],
            },
            permission=Permission.EXECUTE,
            cwd="okulprojesi",
        )
    )

    assert result["success"] is True
    assert (
        result["stdout"].strip()
        == "okulprojesi"
    )
    assert result["cwd"] == "okulprojesi"


def test_nonzero_exit_is_observation_not_registry_crash(
    tmp_path,
):
    script = tmp_path / "fail.py"
    script.write_text(
        "raise SystemExit(7)",
        encoding="utf-8",
    )

    registry = build_project_tool_registry(
        str(tmp_path)
    )

    result = registry.execute(
        ToolRequest(
            tool_name="run_process",
            arguments={
                "argv": [
                    sys.executable,
                    "fail.py",
                ],
            },
            permission=Permission.EXECUTE,
        )
    )

    assert result["success"] is False
    assert result["exit_code"] == 7


def test_run_process_rejects_python_inline_eval(
    tmp_path,
):
    registry = build_project_tool_registry(
        str(tmp_path)
    )

    with pytest.raises(
        UnsafeProcessArgumentsError,
        match="inline eval",
    ):
        registry.execute(
            ToolRequest(
                tool_name="run_process",
                arguments={
                    "argv": [
                        sys.executable,
                        "-c",
                        "print('unsafe')",
                    ],
                },
                permission=Permission.EXECUTE,
            )
        )


def test_run_process_rejects_unknown_executable(
    tmp_path,
):
    registry = build_project_tool_registry(
        str(tmp_path)
    )

    with pytest.raises(
        UnsafeExecutableError,
        match="izinli degil",
    ):
        registry.execute(
            ToolRequest(
                tool_name="run_process",
                arguments={
                    "argv": [
                        "powershell",
                        "-Command",
                        "echo bad",
                    ],
                },
                permission=Permission.EXECUTE,
            )
        )


def test_run_process_rejects_cwd_escape(
    tmp_path,
):
    registry = build_project_tool_registry(
        str(tmp_path)
    )

    with pytest.raises(
        Exception,
        match="cwd",
    ):
        registry.execute(
            ToolRequest(
                tool_name="run_process",
                arguments={
                    "argv": [
                        sys.executable,
                        "anything.py",
                    ],
                },
                permission=Permission.EXECUTE,
                cwd="../outside",
            )
        )


def test_run_process_rejects_destructive_git_clean(
    tmp_path,
):
    registry = build_project_tool_registry(
        str(tmp_path)
    )

    git_tool = registry.get(
        "run_process"
    )

    # Git PATH'te yoksa resolver once hata verebilir.
    # Policy testini doğrudan handler seviyesinde
    # ortam bagimsiz tutmak icin git varsa calistir.
    import shutil

    if shutil.which("git") is None:
        pytest.skip("git PATH'te yok")

    with pytest.raises(
        UnsafeProcessArgumentsError,
        match="Destructive git",
    ):
        registry.execute(
            ToolRequest(
                tool_name="run_process",
                arguments={
                    "argv": [
                        "git",
                        "clean",
                        "-fdx",
                    ],
                },
                permission=Permission.EXECUTE,
            )
        )


def test_run_process_rejects_invalid_timeout(
    tmp_path,
):
    script = tmp_path / "hello.py"
    script.write_text(
        'print("ok")',
        encoding="utf-8",
    )

    registry = build_project_tool_registry(
        str(tmp_path)
    )

    with pytest.raises(
        UnsafeProcessArgumentsError,
        match="timeout_seconds",
    ):
        registry.execute(
            ToolRequest(
                tool_name="run_process",
                arguments={
                    "argv": [
                        sys.executable,
                        "hello.py",
                    ],
                    "timeout_seconds": 9999,
                },
                permission=Permission.EXECUTE,
            )
        )


def test_project_registry_keeps_filesystem_tools(
    tmp_path,
):
    (tmp_path / "README.md").write_text(
        "hello",
        encoding="utf-8",
    )

    registry = build_project_tool_registry(
        str(tmp_path)
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
    assert (
        registry.get(
            "write_file"
        ).handler
        is not None
    )
