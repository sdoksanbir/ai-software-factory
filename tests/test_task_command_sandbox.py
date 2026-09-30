"""Unit tests for TaskCommandSandbox (mocked Docker)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from factory.task_command_models import (
    NetworkPolicy,
    TaskCommandSandboxRuntimeError,
)
from factory.task_command_sandbox import (
    build_docker_run_argv,
    build_stdin_payload,
    map_argv_for_container,
    run_in_task_command_sandbox,
)


def test_docker_argv_has_no_shell_and_no_tmpfs(
    tmp_path,
):
    docker_argv = build_docker_run_argv(
        project_root=tmp_path,
        workdir=tmp_path,
        container_argv=["python", "manage.py", "check"],
        network_policy=NetworkPolicy.NETWORK_NONE,
        container_name="ai-factory-taskcmd-abc",
    )

    assert docker_argv[0] == "docker"
    assert "run" in docker_argv
    assert "--rm" in docker_argv
    assert "-i" in docker_argv
    assert "--network" in docker_argv
    assert "none" in docker_argv
    assert "--tmpfs" not in docker_argv
    assert "sh" not in docker_argv
    assert "-c" not in docker_argv

    volume = f"{tmp_path.resolve()}:/app"
    assert "-v" in docker_argv
    assert volume in docker_argv
    assert "-w" in docker_argv
    assert "/app" in docker_argv


def test_package_install_uses_bridge_network(
    tmp_path,
):
    docker_argv = build_docker_run_argv(
        project_root=tmp_path,
        workdir=tmp_path,
        container_argv=[
            "python",
            "-m",
            "pip",
            "install",
            "django",
        ],
        network_policy=(
            NetworkPolicy.NETWORK_PACKAGE_INSTALL
        ),
        container_name="ai-factory-taskcmd-pkg",
    )

    idx = docker_argv.index("--network")
    assert docker_argv[idx + 1] == "bridge"


def test_spaces_in_project_path_single_volume_arg(
    tmp_path_factory,
):
    project = tmp_path_factory.mktemp(
        "proj with spaces"
    )
    docker_argv = build_docker_run_argv(
        project_root=project,
        workdir=project,
        container_argv=["python", "--version"],
        network_policy=NetworkPolicy.NETWORK_NONE,
        container_name="ai-factory-taskcmd-space",
    )

    volume = f"{project.resolve()}:/app"
    assert volume in docker_argv
    # Volume string is one argv element (no shell split).
    assert any(
        "proj with spaces" in item
        for item in docker_argv
        if item.startswith(str(project.resolve())[:3])
        or ":/app" in item
    )


def test_secrets_go_to_stdin_not_docker_argv(
    tmp_path,
):
    payload = build_stdin_payload(
        container_argv=[
            "python",
            "manage.py",
            "createsuperuser",
            "--noinput",
        ],
        request_env={
            "DJANGO_SUPERUSER_PASSWORD": "s3cret",
        },
    )
    docker_argv = build_docker_run_argv(
        project_root=tmp_path,
        workdir=tmp_path,
        container_argv=payload["argv"],
        network_policy=NetworkPolicy.NETWORK_NONE,
        container_name="ai-factory-taskcmd-sec",
    )

    joined = " ".join(docker_argv)
    assert "s3cret" not in joined
    assert "-e" not in docker_argv
    assert "--env-file" not in joined
    assert payload["env"][
        "DJANGO_SUPERUSER_PASSWORD"
    ] == "s3cret"


def test_host_openai_key_not_in_payload():
    payload = build_stdin_payload(
        container_argv=["python", "x.py"],
        request_env={"APP_FLAG": "1"},
    )
    assert "OPENAI_API_KEY" not in payload["env"]


def test_map_python_and_pytest_argv(tmp_path):
    mapped = map_argv_for_container(
        host_argv=[
            str(Path("/venv/python.exe")),
            "manage.py",
            "check",
        ],
        project_root=tmp_path,
        workdir=tmp_path,
    )
    assert mapped[0] == "python"
    assert mapped[1:] == ["manage.py", "check"]

    mapped_pytest = map_argv_for_container(
        host_argv=["pytest", "-q"],
        project_root=tmp_path,
        workdir=tmp_path,
    )
    assert mapped_pytest[:3] == [
        "python",
        "-m",
        "pytest",
    ]


def test_map_with_dependency_environment(tmp_path):
    mapped = map_argv_for_container(
        host_argv=["python", "manage.py", "check"],
        project_root=tmp_path,
        workdir=tmp_path,
        use_dependency_environment=True,
    )
    assert mapped[0] == (
        "/opt/ai-factory/venv/bin/python"
    )

    docker_argv = build_docker_run_argv(
        project_root=tmp_path,
        workdir=tmp_path,
        container_argv=mapped,
        network_policy=NetworkPolicy.NETWORK_NONE,
        container_name="ai-factory-taskcmd-dep",
        dependency_volume_name=(
            "ai-factory-pyenv-abcdef0123456789abcdef01"
        ),
    )
    assert (
        "ai-factory-pyenv-abcdef0123456789abcdef01:"
        "/opt/ai-factory/venv"
    ) in docker_argv


def test_invalid_dependency_volume_not_mounted(tmp_path):
    from factory.task_command_models import (
        TaskCommandValidationError,
    )

    with pytest.raises(TaskCommandValidationError):
        build_docker_run_argv(
            project_root=tmp_path,
            workdir=tmp_path,
            container_argv=["python", "--version"],
            network_policy=NetworkPolicy.NETWORK_NONE,
            container_name="ai-factory-taskcmd-bad",
            dependency_volume_name="not-a-factory-volume",
        )


def test_node_runtime_rejected_without_host_fallback(
    tmp_path,
):
    with pytest.raises(
        TaskCommandSandboxRuntimeError
    ):
        run_in_task_command_sandbox(
            project_root=tmp_path,
            workdir=tmp_path,
            host_argv=["node", "app.js"],
            request_env={},
            network_policy=NetworkPolicy.NETWORK_NONE,
            command_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            timeout_seconds=5,
        )


def test_timeout_calls_docker_rm(
    tmp_path,
    monkeypatch,
):
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if argv[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(
                cmd=argv,
                timeout=1,
                output="",
                stderr="",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            "",
            "",
        )

    monkeypatch.setattr(
        "factory.task_command_sandbox.subprocess.run",
        fake_run,
    )

    result = run_in_task_command_sandbox(
        project_root=tmp_path,
        workdir=tmp_path,
        host_argv=["python", "x.py"],
        request_env={},
        network_policy=NetworkPolicy.NETWORK_NONE,
        command_id="11111111-2222-3333-4444-555555555555",
        timeout_seconds=1,
    )

    assert result.timed_out is True
    assert any(
        call[:3] == ["docker", "rm", "-f"]
        for call in calls
    )


def test_run_passes_stdin_json_to_docker(
    tmp_path,
    monkeypatch,
):
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["input"] = kwargs.get("input")
        captured["shell"] = kwargs.get("shell")
        return subprocess.CompletedProcess(
            argv,
            0,
            "ok\n",
            "",
        )

    monkeypatch.setattr(
        "factory.task_command_sandbox.subprocess.run",
        fake_run,
    )

    result = run_in_task_command_sandbox(
        project_root=tmp_path,
        workdir=tmp_path,
        host_argv=["python", "hi.py"],
        request_env={"MY_TOKEN": "tok"},
        network_policy=NetworkPolicy.NETWORK_NONE,
        command_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        timeout_seconds=10,
    )

    assert result.exit_code == 0
    assert captured["shell"] is False
    payload = json.loads(captured["input"])
    assert payload["env"]["MY_TOKEN"] == "tok"
    assert "tok" not in " ".join(captured["argv"])
    assert payload["argv"][0] == "python"
