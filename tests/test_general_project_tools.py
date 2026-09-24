import json
import shutil
import subprocess
import sys

import pytest

from factory.general_agent_contracts import (
    Permission,
    ToolRequest,
)
from factory.general_project_tools import (
    ProjectToolError,
    build_full_project_tool_registry,
)


def test_git_diff_reports_real_repository_diff(
    tmp_path,
):
    if shutil.which("git") is None:
        pytest.skip("git PATH'te yok")

    subprocess.run(
        [
            "git",
            "init",
        ],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "test@example.com",
        ],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "config",
            "user.name",
            "Test User",
        ],
        cwd=tmp_path,
        check=True,
    )

    readme = tmp_path / "README.md"
    readme.write_text(
        "one\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            "git",
            "add",
            "README.md",
        ],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "initial",
        ],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    readme.write_text(
        "one\ntwo\n",
        encoding="utf-8",
    )

    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    result = registry.execute(
        ToolRequest(
            tool_name="git_diff",
            arguments={},
            permission=Permission.READ,
        )
    )

    assert result["success"] is True
    assert result["has_diff"] is True
    assert "two" in result["stdout"]


def test_run_tests_executes_pytest(
    tmp_path,
):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    (tests_dir / "test_demo.py").write_text(
        "def test_ok():\n"
        "    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )

    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    result = registry.execute(
        ToolRequest(
            tool_name="run_tests",
            arguments={},
            permission=Permission.EXECUTE,
        )
    )

    assert result["runner"] == "pytest"
    assert result["success"] is True
    assert result["exit_code"] == 0


def test_run_tests_returns_failed_observation(
    tmp_path,
):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    (tests_dir / "test_demo.py").write_text(
        "def test_bad():\n"
        "    assert False\n",
        encoding="utf-8",
    )

    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    result = registry.execute(
        ToolRequest(
            tool_name="run_tests",
            arguments={},
            permission=Permission.EXECUTE,
        )
    )

    assert result["runner"] == "pytest"
    assert result["success"] is False
    assert result["exit_code"] != 0
    assert "failed" in result["stdout"].casefold()


def test_run_tests_supports_target(
    tmp_path,
):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    (tests_dir / "test_one.py").write_text(
        "def test_one():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (tests_dir / "test_two.py").write_text(
        "def test_two():\n"
        "    assert False\n",
        encoding="utf-8",
    )

    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    result = registry.execute(
        ToolRequest(
            tool_name="run_tests",
            arguments={
                "target": "tests/test_one.py",
            },
            permission=Permission.EXECUTE,
        )
    )

    assert result["success"] is True
    assert (
        "tests/test_one.py"
        in result["command"]
    )


def test_run_tests_rejects_unknown_project_type(
    tmp_path,
):
    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    with pytest.raises(
        ProjectToolError,
        match="tespit edilemedi",
    ):
        registry.execute(
            ToolRequest(
                tool_name="run_tests",
                arguments={},
                permission=Permission.EXECUTE,
            )
        )


def test_node_test_command_is_detected_without_running(
    tmp_path,
    monkeypatch,
):
    package = {
        "scripts": {
            "test": "vitest",
        }
    }

    (tmp_path / "package.json").write_text(
        json.dumps(package),
        encoding="utf-8",
    )

    fake_npm = str(
        tmp_path / (
            "npm.cmd"
            if sys.platform.startswith("win")
            else "npm"
        )
    )

    monkeypatch.setattr(
        "factory.general_project_tools.shutil.which",
        lambda name: fake_npm,
    )

    captured = {}

    def fake_run(
        argv,
        *,
        cwd,
        timeout,
    ):
        captured["argv"] = argv
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        return {
            "success": True,
            "timed_out": False,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(
        "factory.general_project_tools._run",
        fake_run,
    )

    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    result = registry.execute(
        ToolRequest(
            tool_name="run_tests",
            arguments={},
            permission=Permission.EXECUTE,
        )
    )

    assert result["runner"] == "npm-test"
    assert "--run" in captured["argv"]


def test_full_registry_has_all_core_handlers(
    tmp_path,
):
    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    for name in (
        "list_files",
        "find_files",
        "read_file",
        "file_exists",
        "write_file",
        "run_process",
        "git_diff",
        "run_tests",
    ):
        assert (
            registry.get(name).handler
            is not None
        )
