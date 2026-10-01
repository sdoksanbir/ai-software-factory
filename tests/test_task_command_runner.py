"""Focused tests for guarded task command engine."""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from api import app as app_module
from factory.database import get_connection
from factory.task_command_models import (
    ARGV_REDACTION_MASK,
    REDACTION_MASK,
    ExecutionBoundary,
    NetworkPolicy,
    PermissionLevel,
    TaskCommandRequest,
    TaskCommandSandboxRuntimeError,
)
from factory.task_command_runner import (
    TaskCommandPathError,
    TaskCommandPolicyError,
    assert_command_allowed,
    build_host_safe_process_env,
    build_process_env,
    classify_execution_boundary,
    classify_git_permission_level,
    classify_network_policy,
    classify_permission_level,
    harden_host_safe_git_command,
    is_host_safe_git_argv,
    run_task_command,
)
from factory.task_command_sandbox import (
    TaskCommandSandboxResult,
)
from factory.task_command_store import (
    get_task_command,
    init_task_command_store,
    list_task_commands,
)


@pytest.fixture
def simulate_sandbox(monkeypatch):
    """Run PROJECT_CODE commands on host for unit tests."""
    import os
    from pathlib import Path

    from factory.task_command_dependency_environment import (
        CONTAINER_VENV_PYTHON,
        dependency_environment_name,
    )

    calls: list[dict] = []

    def _fake_ensure(
        *,
        project_root,
        task_id,
        image_name="ai-factory-python-test",
        host_environ=None,
        timeout_seconds=120,
    ):
        return dependency_environment_name(
            project_root=project_root,
            task_id=task_id,
        )

    def _fake(
        *,
        project_root,
        workdir,
        host_argv,
        request_env,
        network_policy,
        command_id,
        timeout_seconds,
        image_name="ai-factory-python-test",
        host_environ=None,
        dependency_volume_name=None,
    ):
        from factory.task_command_sandbox import (
            build_docker_run_argv,
            build_stdin_payload,
            map_argv_for_container,
        )

        container_argv = map_argv_for_container(
            host_argv=host_argv,
            project_root=project_root,
            workdir=workdir,
            use_dependency_environment=(
                dependency_volume_name is not None
            ),
        )
        short_id = command_id.replace("-", "")[:12]
        container_name = (
            f"ai-factory-taskcmd-{short_id}"
        )
        docker_argv = build_docker_run_argv(
            project_root=project_root,
            workdir=workdir,
            container_argv=container_argv,
            network_policy=network_policy,
            container_name=container_name,
            image_name=image_name,
            dependency_volume_name=(
                dependency_volume_name
            ),
        )
        payload = build_stdin_payload(
            container_argv=container_argv,
            request_env=request_env,
        )
        calls.append(
            {
                "docker_argv": docker_argv,
                "payload": payload,
                "network_policy": network_policy,
                "host_argv": host_argv,
                "dependency_volume_name": (
                    dependency_volume_name
                ),
            }
        )

        exe = Path(host_argv[0]).name.casefold()
        if exe in {
            "node",
            "node.exe",
            "npm",
            "npm.cmd",
            "npx",
            "npx.cmd",
        }:
            raise TaskCommandSandboxRuntimeError(
                "Node/npm runtime bu terminal sandbox "
                "image'inda desteklenmiyor; host fallback yok."
            )

        run_argv = list(container_argv)
        if run_argv and run_argv[0] in {
            "python",
            CONTAINER_VENV_PYTHON,
        }:
            run_argv[0] = sys.executable

        # Only request_env overlays a minimal base —
        # do not inherit host secrets into simulation
        # of container payload semantics for probes.
        process_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get(
                "SYSTEMROOT",
                "",
            ),
            "WINDIR": os.environ.get("WINDIR", ""),
        }
        process_env.update(request_env)

        try:
            completed = subprocess.run(
                run_argv,
                cwd=str(workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                check=False,
                timeout=timeout_seconds,
                env=process_env,
            )
        except subprocess.TimeoutExpired as exc:
            return TaskCommandSandboxResult(
                exit_code=None,
                stdout=(
                    exc.stdout
                    if isinstance(exc.stdout, str)
                    else ""
                ),
                stderr=(
                    exc.stderr
                    if isinstance(exc.stderr, str)
                    else ""
                ),
                timed_out=True,
                docker_argv=docker_argv,
                container_argv=container_argv,
                container_name=container_name,
            )

        return TaskCommandSandboxResult(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            timed_out=False,
            docker_argv=docker_argv,
            container_argv=container_argv,
            container_name=container_name,
        )

    monkeypatch.setattr(
        "factory.task_command_runner"
        ".ensure_dependency_environment",
        _fake_ensure,
    )
    monkeypatch.setattr(
        "factory.task_command_runner.run_in_task_command_sandbox",
        _fake,
    )
    return calls


def _run(
    tmp_path,
    argv,
    *,
    task_id="TASK-CMD-1",
    cwd=None,
    timeout_seconds=30,
    env=None,
    secret_env_keys=None,
    allow_mutating=False,
    allow_git_mutation=True,
    persist=True,
    db_path=None,
):
    request = TaskCommandRequest(
        task_id=task_id,
        argv=argv,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        env=env,
        secret_env_keys=secret_env_keys or [],
        allow_mutating=allow_mutating,
        allow_git_mutation=allow_git_mutation,
    )

    kwargs = {
        "project_path": tmp_path,
        "request": request,
        "persist": persist,
    }

    if db_path is not None:
        kwargs["db_path"] = db_path
    elif persist:
        kwargs["db_path"] = tmp_path / "factory.db"

    return run_task_command(**kwargs)


def test_safe_command_runs(tmp_path):
    result = _run(
        tmp_path,
        [sys.executable, "--version"],
    )

    assert result.status == "succeeded"
    assert result.exit_code == 0
    assert result.permission_level == (
        PermissionLevel.EXECUTE_SAFE.value
    )
    assert result.execution_boundary == (
        ExecutionBoundary.HOST_SAFE.value
    )
    combined = result.stdout + result.stderr
    assert "Python" in combined


def test_cwd_under_project_root(
    tmp_path,
    simulate_sandbox,
):
    nested = tmp_path / "subdir"
    nested.mkdir()

    script = nested / "where.py"
    script.write_text(
        "from pathlib import Path\n"
        "print(Path.cwd().name)\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        [sys.executable, "where.py"],
        cwd="subdir",
        allow_mutating=True,
    )

    assert result.status == "succeeded"
    assert result.cwd == "subdir"
    assert result.stdout.strip() == "subdir"
    assert result.execution_boundary == (
        ExecutionBoundary.PROJECT_CODE_SANDBOX.value
    )


def test_cwd_parent_escape_rejected(tmp_path):
    result = _run(
        tmp_path,
        [sys.executable, "--version"],
        cwd="../",
        persist=False,
    )
    assert result.status == "rejected"
    assert result.exit_code is None
    assert result.stderr


def test_absolute_external_cwd_rejected(
    tmp_path,
    tmp_path_factory,
):
    outside = tmp_path_factory.mktemp(
        "outside-cwd"
    )

    result = _run(
        tmp_path,
        [sys.executable, "--version"],
        cwd=str(outside),
        persist=False,
    )
    assert result.status == "rejected"
    assert result.exit_code is None
    assert result.stderr


def test_shell_metacharacters_not_interpreted(
    tmp_path,
    simulate_sandbox,
):
    marker = tmp_path / "should-not-exist.txt"
    script = tmp_path / "echo_arg.py"
    script.write_text(
        "import sys\n"
        "print(sys.argv[1])\n",
        encoding="utf-8",
    )

    injection = (
        f"; echo pwned > {marker.name}"
    )

    result = _run(
        tmp_path,
        [
            sys.executable,
            "echo_arg.py",
            injection,
        ],
        allow_mutating=True,
    )

    assert result.status == "succeeded"
    assert injection in result.stdout
    assert not marker.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "reset", "--hard"],
        ["git", "clean", "-fdx"],
        [sys.executable, "-c", "print(1)"],
        ["cmd", "/c", "echo hi"],
        [
            "powershell",
            "-Command",
            "Get-Date",
        ],
    ],
)
def test_dangerous_commands_rejected(
    tmp_path,
    argv,
):
    result = _run(
        tmp_path,
        argv,
        allow_mutating=True,
        persist=False,
    )
    assert result.status == "rejected"
    assert result.exit_code is None
    assert result.command_id
    assert result.stderr


def test_timeout_returns_structured_result(
    tmp_path,
    simulate_sandbox,
):
    script = tmp_path / "sleep.py"
    script.write_text(
        "import time\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        [sys.executable, "sleep.py"],
        timeout_seconds=1,
        allow_mutating=True,
    )

    assert result.status == "timed_out"
    assert result.exit_code is None
    assert result.duration_ms >= 0


def test_stdout_stderr_captured(
    tmp_path,
    simulate_sandbox,
):
    script = tmp_path / "streams.py"
    script.write_text(
        "import sys\n"
        "print('OUT')\n"
        "print('ERR', file=sys.stderr)\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        [sys.executable, "streams.py"],
        allow_mutating=True,
    )

    assert result.status == "succeeded"
    assert "OUT" in result.stdout
    assert "ERR" in result.stderr


def test_secret_env_reaches_process_but_not_persisted(
    tmp_path,
    simulate_sandbox,
):
    db_path = tmp_path / "factory.db"
    secret = "super-secret-password-xyz"

    script = tmp_path / "read_env.py"
    script.write_text(
        "import os\n"
        "print(os.environ.get("
        "'DJANGO_SUPERUSER_PASSWORD', ''))\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        [sys.executable, "read_env.py"],
        env={
            "DJANGO_SUPERUSER_PASSWORD": secret,
            "DJANGO_SUPERUSER_USERNAME": "admin",
        },
        secret_env_keys=[
            "DJANGO_SUPERUSER_PASSWORD",
        ],
        allow_mutating=True,
        db_path=db_path,
    )

    assert result.status == "succeeded"
    assert secret not in result.stdout
    assert REDACTION_MASK in result.stdout
    assert "DJANGO_SUPERUSER_PASSWORD" in (
        result.secret_env_keys
    )

    stored = get_task_command(
        result.command_id,
        db_path=db_path,
    )
    assert stored is not None
    assert secret not in json.dumps(stored)

    connection = get_connection(db_path)

    try:
        blob = " ".join(
            str(row)
            for row in connection.execute(
                "SELECT * FROM task_commands"
            ).fetchall()
        )
    finally:
        connection.close()

    assert secret not in blob


def test_secret_bearing_argv_rejected_and_redacted(
    tmp_path,
    simulate_sandbox,
):
    db_path = tmp_path / "factory.db"
    secret = "argv-leak-password-777"

    result = _run(
        tmp_path,
        [
            sys.executable,
            "-c",
            f"print({secret!r})",
        ],
        env={"MY_PASSWORD": secret},
        secret_env_keys=["MY_PASSWORD"],
        allow_mutating=True,
        db_path=db_path,
    )

    assert result.status == "rejected"
    assert secret not in result.argv
    assert any(
        ARGV_REDACTION_MASK in arg
        for arg in result.argv
    )
    assert secret not in result.stderr
    assert secret not in json.dumps(
        result.to_dict()
    )

    stored = get_task_command(
        result.command_id,
        db_path=db_path,
    )
    assert stored is not None
    assert secret not in json.dumps(stored)
    # Rejected before sandbox launch.
    assert simulate_sandbox == []


def test_secret_echo_in_stdout_is_masked(
    tmp_path,
    simulate_sandbox,
):
    secret = "leak-me-now-123"

    script = tmp_path / "echo_secret.py"
    script.write_text(
        "import os\n"
        "print('before')\n"
        "print(os.environ['SECRET_TOKEN'])\n"
        "print('after')\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        [sys.executable, "echo_secret.py"],
        env={"SECRET_TOKEN": secret},
        secret_env_keys=["SECRET_TOKEN"],
        allow_mutating=True,
    )

    assert secret not in result.stdout
    assert REDACTION_MASK in result.stdout
    assert "before" in result.stdout
    assert "after" in result.stdout


def test_get_task_commands_endpoint_returns_history(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-API-CMD-1"

    first = _run(
        tmp_path,
        [sys.executable, "--version"],
        task_id=task_id,
        db_path=db_path,
    )
    second = _run(
        tmp_path,
        [sys.executable, "--version"],
        task_id=task_id,
        db_path=db_path,
    )

    monkeypatch.setitem(
        app_module.TASKS,
        task_id,
        SimpleNamespace(state="running"),
    )
    monkeypatch.setattr(
        app_module,
        "list_task_commands",
        lambda value: list_task_commands(
            value,
            db_path=db_path,
        ),
    )

    payload = (
        app_module
        .get_task_commands_endpoint(
            task_id
        )
    )

    assert payload["task_id"] == task_id
    assert len(payload["commands"]) == 2
    ids = {
        item["command_id"]
        for item in payload["commands"]
    }
    assert first.command_id in ids
    assert second.command_id in ids


def test_get_task_commands_endpoint_404(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "TASKS",
        {},
    )

    with pytest.raises(
        app_module.HTTPException
    ) as exc_info:
        app_module.get_task_commands_endpoint(
            "missing-task"
        )

    assert exc_info.value.status_code == 404


def test_classify_django_manage_levels():
    assert (
        classify_permission_level(
            "python",
            ["manage.py", "check"],
        )
        == PermissionLevel.EXECUTE_SAFE
    )
    assert (
        classify_execution_boundary(
            "python",
            ["manage.py", "check"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )
    assert (
        classify_permission_level(
            "python",
            ["manage.py", "migrate"],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )
    assert (
        classify_execution_boundary(
            "python",
            ["manage.py", "migrate"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )


def test_mutating_pip_install_classification():
    level = classify_permission_level(
        "python",
        ["-m", "pip", "install", "django"],
    )
    assert level == (
        PermissionLevel.EXECUTE_MUTATING
    )
    assert (
        classify_network_policy(
            "python",
            ["-m", "pip", "install", "django"],
        )
        == NetworkPolicy.NETWORK_PACKAGE_INSTALL
    )


def test_migrate_rejected_without_allow_mutating():
    with pytest.raises(TaskCommandPolicyError):
        assert_command_allowed(
            PermissionLevel.EXECUTE_MUTATING,
            allow_mutating=False,
        )


def test_migrate_allowed_with_allow_mutating_true():
    assert_command_allowed(
        PermissionLevel.EXECUTE_MUTATING,
        allow_mutating=True,
    )


def test_dangerous_still_rejected_with_allow_mutating(
    tmp_path,
):
    result = _run(
        tmp_path,
        [sys.executable, "-c", "print(1)"],
        allow_mutating=True,
        persist=False,
    )
    assert result.status == "rejected"
    assert "DANGEROUS" in result.stderr or (
        "-c" in " ".join(result.argv)
    )


def test_manage_py_flush_is_dangerous():
    assert (
        classify_permission_level(
            "python",
            ["manage.py", "flush"],
        )
        == PermissionLevel.DANGEROUS
    )


def test_host_secret_not_inherited(
    tmp_path,
    simulate_sandbox,
    monkeypatch,
):
    host_secret = "super-secret-host-value"
    monkeypatch.setenv(
        "FACTORY_TEST_HOST_API_KEY",
        host_secret,
    )

    script = tmp_path / "probe_host.py"
    script.write_text(
        "import os\n"
        "print(os.environ.get("
        "'FACTORY_TEST_HOST_API_KEY', 'MISSING'))\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        [sys.executable, "probe_host.py"],
        allow_mutating=True,
    )

    assert result.status == "succeeded"
    assert host_secret not in result.stdout
    assert "MISSING" in result.stdout
    assert (
        "FACTORY_TEST_HOST_API_KEY"
        not in simulate_sandbox[0]["payload"]["env"]
    )


def test_auto_sensitive_env_key_redaction(
    tmp_path,
    simulate_sandbox,
):
    db_path = tmp_path / "factory.db"
    secret = "auto-detected-secret-value"

    script = tmp_path / "echo_api_key.py"
    script.write_text(
        "import os\n"
        "print(os.environ['MY_API_KEY'])\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        [sys.executable, "echo_api_key.py"],
        env={"MY_API_KEY": secret},
        allow_mutating=True,
        db_path=db_path,
    )

    assert result.status == "succeeded"
    assert "MY_API_KEY" in result.secret_env_keys
    assert secret not in result.stdout
    assert REDACTION_MASK in result.stdout


def test_secret_echo_in_stderr_is_masked(
    tmp_path,
    simulate_sandbox,
):
    secret = "stderr-secret-999"

    script = tmp_path / "echo_stderr.py"
    script.write_text(
        "import os\n"
        "import sys\n"
        "print(os.environ['MY_PASSWORD'], "
        "file=sys.stderr)\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        [sys.executable, "echo_stderr.py"],
        env={"MY_PASSWORD": secret},
        allow_mutating=True,
    )

    assert secret not in result.stderr
    assert REDACTION_MASK in result.stderr


def test_symlink_cwd_escape_rejected(
    tmp_path,
    tmp_path_factory,
):
    outside = tmp_path_factory.mktemp(
        "outside-link-target"
    )
    link = tmp_path / "escape-link"

    try:
        link.symlink_to(
            outside,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip(
            "symlink not supported on this platform"
        )

    with pytest.raises(TaskCommandPathError):
        _run(
            tmp_path,
            [sys.executable, "--version"],
            cwd="escape-link",
            persist=False,
        )


def test_capture_truncation_flags(
    tmp_path,
    simulate_sandbox,
    monkeypatch,
):
    monkeypatch.setattr(
        "factory.task_command_models.MAX_CAPTURE_CHARS",
        32,
    )

    script = tmp_path / "big_out.py"
    script.write_text(
        "print('X' * 200)\n"
        "import sys\n"
        "print('Y' * 200, file=sys.stderr)\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "factory.db"
    result = _run(
        tmp_path,
        [sys.executable, "big_out.py"],
        allow_mutating=True,
        db_path=db_path,
    )

    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert len(result.stdout) <= 32
    assert len(result.stderr) <= 32


def test_api_history_masks_real_secret_command(
    tmp_path,
    simulate_sandbox,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-API-SECRET-1"
    secret = "api-history-secret-xyz"

    script = tmp_path / "print_secret.py"
    script.write_text(
        "import os\n"
        "print(os.environ['MY_TOKEN'])\n",
        encoding="utf-8",
    )

    _run(
        tmp_path,
        [sys.executable, "print_secret.py"],
        task_id=task_id,
        env={"MY_TOKEN": secret},
        allow_mutating=True,
        db_path=db_path,
    )

    monkeypatch.setitem(
        app_module.TASKS,
        task_id,
        SimpleNamespace(state="completed"),
    )
    monkeypatch.setattr(
        app_module,
        "list_task_commands",
        lambda value: list_task_commands(
            value,
            db_path=db_path,
        ),
    )

    payload = (
        app_module
        .get_task_commands_endpoint(
            task_id
        )
    )
    serialized = json.dumps(payload)
    assert secret not in serialized
    assert REDACTION_MASK in serialized


def test_build_process_env_allowlist_only():
    host = {
        "PATH": "/bin",
        "FACTORY_TEST_HOST_API_KEY": "nope",
        "OPENAI_API_KEY": "sk-host",
        "TEMP": "/tmp",
    }

    built = build_process_env(
        {"APP_SETTING": "ok"},
        host_environ=host,
    )

    assert built["PATH"] == "/bin"
    assert built["TEMP"] == "/tmp"
    assert built["APP_SETTING"] == "ok"
    assert "FACTORY_TEST_HOST_API_KEY" not in built
    assert "OPENAI_API_KEY" not in built


def test_python_project_script_is_sandbox():
    assert (
        classify_execution_boundary(
            "python",
            ["project.py"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )


def test_pytest_is_sandbox():
    assert (
        classify_execution_boundary(
            "pytest",
            ["-q"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )


def test_migrate_without_allow_mutating_rejects_before_sandbox(
    tmp_path,
    monkeypatch,
):
    called = {"sandbox": False}

    def _boom(**kwargs):
        called["sandbox"] = True
        raise AssertionError("sandbox should not run")

    monkeypatch.setattr(
        "factory.task_command_runner.run_in_task_command_sandbox",
        _boom,
    )

    result = _run(
        tmp_path,
        [
            sys.executable,
            "manage.py",
            "migrate",
        ],
        allow_mutating=False,
        persist=False,
    )

    assert result.status == "rejected"
    assert called["sandbox"] is False
    assert "allow_mutating" in result.stderr.casefold() or (
        "mutating" in result.stderr.casefold()
    )


def test_package_install_with_secret_rejected(
    tmp_path,
):
    result = _run(
        tmp_path,
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "django",
        ],
        env={"MY_TOKEN": "secret"},
        allow_mutating=True,
        persist=False,
    )
    assert result.status == "rejected"
    assert result.exit_code is None


def test_package_install_any_request_env_rejected(
    tmp_path,
):
    result = _run(
        tmp_path,
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "six",
        ],
        env={"PIP_INDEX_URL": "https://evil.example"},
        allow_mutating=True,
        persist=False,
    )
    assert result.status == "rejected"
    assert "request.env" in result.stderr.casefold()


def test_package_install_reaches_sandbox_with_bridge(
    tmp_path,
    simulate_sandbox,
):
    """NETWORK_PACKAGE_INSTALL uses bridge + trusted pip env."""
    result = _run(
        tmp_path,
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "six",
        ],
        allow_mutating=True,
        persist=False,
    )

    assert len(simulate_sandbox) == 1
    call = simulate_sandbox[0]
    assert (
        call["network_policy"]
        == NetworkPolicy.NETWORK_PACKAGE_INSTALL
    )
    idx = call["docker_argv"].index("--network")
    assert call["docker_argv"][idx + 1] == "bridge"
    assert call["dependency_volume_name"]
    volume_mount = (
        f"{call['dependency_volume_name']}:"
        "/opt/ai-factory/venv"
    )
    assert volume_mount in call["docker_argv"]
    assert call["payload"]["argv"][:4] == [
        "/opt/ai-factory/venv/bin/python",
        "-m",
        "pip",
        "install",
    ]
    env = call["payload"]["env"]
    assert env.get("PIP_NO_INPUT") == "1"
    assert env.get("PIP_CONFIG_FILE") == "/dev/null"
    assert "PIP_INDEX_URL" not in env
    # Host simulation remaps venv python → may fail
    # without network; status is structured either way.
    assert result.status in {
        "succeeded",
        "failed",
        "timed_out",
    }


def test_requirements_expands_before_sandbox(
    tmp_path,
    simulate_sandbox,
):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# deps\nsix\nDjango==5.2.17\n",
        encoding="utf-8",
    )
    result = _run(
        tmp_path,
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            "requirements.txt",
        ],
        allow_mutating=True,
        persist=False,
    )
    call = simulate_sandbox[0]
    assert call["payload"]["argv"] == [
        "/opt/ai-factory/venv/bin/python",
        "-m",
        "pip",
        "install",
        "six",
        "Django==5.2.17",
    ]
    # History keeps original user argv.
    assert result.argv[-2:] == [
        "-r",
        "requirements.txt",
    ]


def test_malicious_requirements_rejected_before_sandbox(
    tmp_path,
    monkeypatch,
):
    called = {"sandbox": False, "ensure": False}

    def boom_ensure(**kwargs):
        called["ensure"] = True
        raise AssertionError("ensure should not run")

    def boom_sandbox(**kwargs):
        called["sandbox"] = True
        raise AssertionError("sandbox should not run")

    monkeypatch.setattr(
        "factory.task_command_runner"
        ".ensure_dependency_environment",
        boom_ensure,
    )
    monkeypatch.setattr(
        "factory.task_command_runner"
        ".run_in_task_command_sandbox",
        boom_sandbox,
    )

    req = tmp_path / "requirements.txt"
    req.write_text(
        "--index-url https://example.com/simple\nsix\n",
        encoding="utf-8",
    )
    result = _run(
        tmp_path,
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            "requirements.txt",
        ],
        allow_mutating=True,
        persist=False,
    )
    assert result.status == "rejected"
    assert called["sandbox"] is False
    assert called["ensure"] is False


def test_python_project_code_uses_venv_and_network_none(
    tmp_path,
    simulate_sandbox,
):
    script = tmp_path / "hello.py"
    script.write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    result = _run(
        tmp_path,
        [sys.executable, "hello.py"],
        allow_mutating=True,
        persist=False,
    )
    assert result.status == "succeeded"
    call = simulate_sandbox[0]
    assert (
        call["network_policy"]
        == NetworkPolicy.NETWORK_NONE
    )
    assert call["payload"]["argv"][0] == (
        "/opt/ai-factory/venv/bin/python"
    )
    assert call["dependency_volume_name"]


def test_host_safe_git_status_templates():
    assert is_host_safe_git_argv(["status"])
    assert is_host_safe_git_argv(
        ["status", "--short"]
    )
    assert is_host_safe_git_argv(
        ["status", "--porcelain"]
    )
    assert is_host_safe_git_argv(
        ["status", "--porcelain=v1"]
    )
    assert is_host_safe_git_argv(
        ["--no-pager", "status"]
    )
    assert not is_host_safe_git_argv(
        ["status", "--ignored"]
    )
    assert (
        classify_execution_boundary(
            "git",
            ["status"],
        )
        == ExecutionBoundary.HOST_SAFE
    )


def test_host_safe_git_rev_parse_and_ls_files():
    assert is_host_safe_git_argv(
        ["rev-parse", "--is-inside-work-tree"]
    )
    assert is_host_safe_git_argv(
        ["rev-parse", "HEAD"]
    )
    assert is_host_safe_git_argv(["ls-files"])
    assert is_host_safe_git_argv(
        ["ls-files", "--cached"]
    )
    assert is_host_safe_git_argv(
        [
            "ls-files",
            "--others",
            "--exclude-standard",
            "*manage.py",
        ]
    )
    assert (
        classify_permission_level(
            "git",
            ["ls-files", "*manage.py"],
        )
        == PermissionLevel.EXECUTE_SAFE
    )
    assert (
        classify_permission_level(
            "git",
            [
                "ls-files",
                "--others",
                "--exclude-standard",
                "*manage.py",
            ],
        )
        == PermissionLevel.EXECUTE_SAFE
    )
    assert (
        classify_execution_boundary(
            "git",
            ["rev-parse", "--show-toplevel"],
        )
        == ExecutionBoundary.HOST_SAFE
    )
    assert (
        classify_execution_boundary(
            "git",
            ["ls-files", "--exclude-standard"],
        )
        == ExecutionBoundary.HOST_SAFE
    )
    assert (
        classify_execution_boundary(
            "git",
            [
                "ls-files",
                "--others",
                "--exclude-standard",
                "*manage.py",
            ],
        )
        == ExecutionBoundary.HOST_SAFE
    )
    assert (
        classify_network_policy(
            "git",
            [
                "ls-files",
                "--others",
                "--exclude-standard",
                "*manage.py",
            ],
        )
        == NetworkPolicy.NETWORK_NONE
    )


def test_host_safe_git_branch_read_only_only():
    assert is_host_safe_git_argv(["branch"])
    assert is_host_safe_git_argv(
        ["branch", "--show-current"]
    )
    assert is_host_safe_git_argv(
        ["branch", "--list"]
    )
    assert not is_host_safe_git_argv(
        ["branch", "new-name"]
    )
    assert not is_host_safe_git_argv(
        ["branch", "-D", "x"]
    )
    assert (
        classify_execution_boundary(
            "git",
            ["branch", "new-name"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )
    assert (
        classify_execution_boundary(
            "git",
            ["branch", "-D", "x"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )
    assert (
        classify_execution_boundary(
            "git",
            ["branch", "--show-current"],
        )
        == ExecutionBoundary.HOST_SAFE
    )


def test_host_safe_git_diff_dangerous_flags_rejected():
    assert not is_host_safe_git_argv(
        ["diff", "--ext-diff"]
    )
    assert not is_host_safe_git_argv(
        ["diff", "--textconv"]
    )
    assert not is_host_safe_git_argv(
        ["diff", "--output=x"]
    )
    assert not is_host_safe_git_argv(["diff"])
    assert (
        classify_execution_boundary(
            "git",
            ["diff", "--ext-diff"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )
    assert (
        classify_execution_boundary(
            "git",
            ["diff", "--textconv"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )
    assert (
        classify_execution_boundary(
            "git",
            ["diff", "--output=x"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )


def test_harden_host_safe_git_rebuilds_from_template():
    hardened = harden_host_safe_git_command(
        "git",
        ["status", "--short"],
    )
    assert hardened[0] == "git"
    assert hardened[1] == "--no-pager"
    assert "status" in hardened
    assert "--short" in hardened
    # Caller -c config must not open HOST_SAFE.
    assert not is_host_safe_git_argv(
        ["-c", "core.pager=less", "status"]
    )
    with pytest.raises(TaskCommandPolicyError):
        harden_host_safe_git_command(
            "git",
            ["branch", "new-name"],
        )


def test_git_permission_branch_remote_tag_argv_aware():
    assert (
        classify_permission_level(
            "git",
            ["branch", "new-name"],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )
    assert (
        classify_git_permission_level(
            ["branch", "-D", "x"]
        )
        == PermissionLevel.DANGEROUS
    )
    assert (
        classify_permission_level(
            "git",
            ["remote", "add", "origin", "https://example.com/r.git"],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )
    assert (
        classify_permission_level(
            "git",
            ["tag", "v1"],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )
    assert (
        classify_permission_level(
            "git",
            ["tag", "-d", "v1"],
        )
        == PermissionLevel.DANGEROUS
    )
    assert (
        classify_permission_level(
            "git",
            ["branch", "--show-current"],
        )
        == PermissionLevel.EXECUTE_SAFE
    )
    assert (
        classify_permission_level(
            "git",
            ["status", "--short"],
        )
        == PermissionLevel.EXECUTE_SAFE
    )
    # Read-only diff template may be SAFE but not HOST_SAFE.
    assert (
        classify_permission_level(
            "git",
            ["diff", "--stat"],
        )
        == PermissionLevel.EXECUTE_SAFE
    )
    assert (
        classify_execution_boundary(
            "git",
            ["diff", "--stat"],
        )
        == ExecutionBoundary.PROJECT_CODE_SANDBOX
    )
    # Suspicious diff flags → MUTATING fail-closed.
    assert (
        classify_permission_level(
            "git",
            ["diff", "--ext-diff"],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )


def test_git_branch_create_rejected_without_allow_mutating(
    tmp_path,
    monkeypatch,
):
    called = {"sandbox": False}

    def _boom(**kwargs):
        called["sandbox"] = True
        raise AssertionError("sandbox should not run")

    monkeypatch.setattr(
        "factory.task_command_runner"
        ".run_in_task_command_sandbox",
        _boom,
    )

    result = _run(
        tmp_path,
        ["git", "branch", "new-name"],
        allow_mutating=False,
        persist=False,
    )

    assert result.status == "rejected"
    assert called["sandbox"] is False


def test_host_safe_ignores_request_env(
    tmp_path,
    monkeypatch,
):
    from pathlib import Path

    captured: dict = {}

    real_run = subprocess.run

    def fake_run(argv, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        exe = ""
        if isinstance(argv, (list, tuple)) and argv:
            exe = Path(str(argv[0])).name.casefold()
        if exe in {"git", "git.exe"}:
            return subprocess.CompletedProcess(
                argv,
                0,
                "ok\n",
                "",
            )
        return real_run(argv, **kwargs)

    monkeypatch.setattr(
        "factory.task_command_runner.subprocess.run",
        fake_run,
    )

    result = _run(
        tmp_path,
        ["git", "status"],
        env={
            "GIT_DIR": "C:\\evil\\gitdir",
            "MY_TOKEN": "secret",
        },
        persist=False,
    )

    assert result.status == "succeeded"
    assert result.execution_boundary == (
        ExecutionBoundary.HOST_SAFE.value
    )
    env = captured["env"]
    assert "GIT_DIR" not in env
    assert "MY_TOKEN" not in env

    # python --version HOST_SAFE also drops request.env
    captured.clear()
    result_py = _run(
        tmp_path,
        [sys.executable, "--version"],
        env={"MY_TOKEN": "secret"},
        persist=False,
    )
    assert result_py.status == "succeeded"
    assert result_py.execution_boundary == (
        ExecutionBoundary.HOST_SAFE.value
    )
    assert "MY_TOKEN" not in captured["env"]


def test_build_host_safe_process_env_drops_request_env():
    built = build_host_safe_process_env(
        {
            "GIT_DIR": "/tmp/evil",
            "MY_TOKEN": "secret",
            "GIT_CONFIG_COUNT": "1",
        },
        host_environ={
            "PATH": "/bin",
            "TEMP": "/tmp",
        },
        for_git=True,
    )
    assert built["PATH"] == "/bin"
    assert "GIT_DIR" not in built
    assert "MY_TOKEN" not in built
    assert "GIT_CONFIG_COUNT" not in built
    assert built["GIT_TERMINAL_PROMPT"] == "0"


def test_project_code_sandbox_still_gets_request_env(
    tmp_path,
    simulate_sandbox,
):
    script = tmp_path / "echo_env.py"
    script.write_text(
        "import os\n"
        "print(os.environ.get('APP_FLAG', 'MISSING'))\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        [sys.executable, "echo_env.py"],
        env={"APP_FLAG": "from-request"},
        allow_mutating=True,
        persist=False,
    )

    assert result.status == "succeeded"
    assert "from-request" in result.stdout
    assert (
        simulate_sandbox[0]["payload"]["env"][
            "APP_FLAG"
        ]
        == "from-request"
    )


def test_sqlite_migration_adds_boundary_columns(
    tmp_path,
):
    db_path = tmp_path / "legacy.db"
    connection = get_connection(db_path)

    try:
        connection.execute(
            """
            CREATE TABLE task_commands (
                command_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                argv_json TEXT NOT NULL,
                cwd TEXT NOT NULL,
                permission_level TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms INTEGER,
                exit_code INTEGER,
                stdout TEXT,
                stderr TEXT,
                status TEXT NOT NULL,
                secret_env_keys_json TEXT NOT NULL
                    DEFAULT '[]',
                stdout_truncated INTEGER NOT NULL
                    DEFAULT 0,
                stderr_truncated INTEGER NOT NULL
                    DEFAULT 0
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    init_task_command_store(db_path)

    connection = get_connection(db_path)
    try:
        cols = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(task_commands)"
            ).fetchall()
        }
    finally:
        connection.close()

    assert "execution_boundary" in cols
    assert "network_policy" in cols


def test_django_admin_rejected_no_subprocess_persisted(
    tmp_path,
    monkeypatch,
):
    called = {"run": False}

    def boom(*args, **kwargs):
        called["run"] = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(
        "factory.task_command_runner.subprocess.run",
        boom,
    )
    monkeypatch.setattr(
        "factory.task_command_runner"
        ".run_in_task_command_sandbox",
        boom,
    )

    db_path = tmp_path / "factory.db"
    result = _run(
        tmp_path,
        ["django-admin", "startproject", "ajan"],
        allow_mutating=True,
        persist=True,
        db_path=db_path,
        task_id="TASK-DJANGO-1",
    )

    assert result.status == "rejected"
    assert result.exit_code is None
    assert result.command_id
    assert "django-admin" in result.stderr
    assert "izinli" in result.stderr.casefold()
    assert called["run"] is False

    rows = list_task_commands(
        "TASK-DJANGO-1",
        db_path=db_path,
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"
    assert rows[0]["command_id"] == result.command_id
    assert rows[0]["argv"][0] == "django-admin"


def test_python_m_django_and_manage_classification():
    assert (
        classify_permission_level(
            "python",
            ["-m", "django", "--version"],
        )
        == PermissionLevel.EXECUTE_SAFE
    )
    assert (
        classify_permission_level(
            "python",
            ["-m", "django", "startproject", "ajan"],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )
    assert (
        classify_permission_level(
            "python",
            ["manage.py", "startapp", "users"],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )
    assert (
        classify_permission_level(
            "python",
            ["manage.py", "check"],
        )
        == PermissionLevel.EXECUTE_SAFE
    )
    assert (
        classify_network_policy(
            "python",
            ["-m", "pip", "install", "django"],
        )
        == NetworkPolicy.NETWORK_PACKAGE_INSTALL
    )
    assert (
        classify_permission_level(
            "python",
            ["-m", "pip", "install", "django"],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )


def test_shell_wrappers_still_rejected(tmp_path):
    for argv in (
        ["bash", "-c", "echo hi"],
        ["sh", "-c", "echo hi"],
        ["cmd", "/c", "echo hi"],
        ["powershell", "-Command", "1"],
    ):
        result = _run(
            tmp_path,
            argv,
            allow_mutating=True,
            persist=False,
        )
        assert result.status == "rejected"
        assert result.exit_code is None


def test_execute_disallows_git_mutation_even_with_allow_mutating(
    tmp_path,
    monkeypatch,
):
    from factory.task_command_runner import (
        GIT_MUTATION_REJECTED_MESSAGE,
    )

    sandbox_calls = []

    def _boom(**kwargs):
        sandbox_calls.append(kwargs)
        raise AssertionError("sandbox must not run")

    monkeypatch.setattr(
        "factory.task_command_runner"
        ".run_in_task_command_sandbox",
        _boom,
    )

    mutating = (
        ["git", "branch", "leaked-branch"],
        ["git", "tag", "leaked-tag"],
        ["git", "stash", "push", "-m", "x"],
        ["git", "config", "--local", "test.key", "v"],
        [
            "git",
            "remote",
            "add",
            "leaked",
            "https://example.com/r.git",
        ],
        ["git", "worktree", "add", "../other"],
        [
            "git",
            "update-ref",
            "refs/heads/leaked-ref",
            "HEAD",
        ],
        ["git", "add", "."],
        ["git", "commit", "-m", "x"],
        ["git", "checkout", "main"],
        ["git", "switch", "main"],
        ["git", "reset"],
        ["git", "restore", "f"],
        ["git", "notes", "add", "-m", "n"],
        ["git", "gc"],
    )

    for argv in mutating:
        result = _run(
            tmp_path,
            argv,
            allow_mutating=True,
            allow_git_mutation=False,
            persist=False,
        )
        assert result.status == "rejected", argv
        assert result.exit_code is None
        assert GIT_MUTATION_REJECTED_MESSAGE in (
            result.stderr
        )

    assert sandbox_calls == []


def test_execute_allows_safe_git_with_git_mutation_disabled(
    tmp_path,
    monkeypatch,
):
    host_calls = []

    def fake_run(*args, **kwargs):
        host_calls.append((args, kwargs))

        class _Completed:
            returncode = 0
            stdout = "ok\n"
            stderr = ""

        return _Completed()

    monkeypatch.setattr(
        "factory.task_command_runner.subprocess.run",
        fake_run,
    )

    safe = (
        ["git", "status", "--short"],
        ["git", "rev-parse", "HEAD"],
        ["git", "ls-files"],
        ["git", "branch", "--show-current"],
    )

    for argv in safe:
        result = _run(
            tmp_path,
            argv,
            allow_mutating=True,
            allow_git_mutation=False,
            persist=False,
        )
        assert result.status == "succeeded", argv
        assert result.permission_level == (
            PermissionLevel.EXECUTE_SAFE.value
        )

    assert len(host_calls) == len(safe)


def test_allow_git_mutation_true_still_permits_git_branch(
    tmp_path,
    monkeypatch,
    simulate_sandbox,
):
    # Not a git repo — sandbox may fail the process, but the
    # command must not be rejected by allow_git_mutation gate.
    result = _run(
        tmp_path,
        ["git", "branch", "legacy-ok"],
        allow_mutating=True,
        allow_git_mutation=True,
        persist=False,
    )
    assert result.status != "rejected"
    assert len(simulate_sandbox) == 1


def test_filesystem_mutating_python_still_allowed_without_git_mutation(
    tmp_path,
    monkeypatch,
    simulate_sandbox,
):
    script = tmp_path / "script.py"
    script.write_text(
        "from pathlib import Path\n"
        "Path('generated.txt').write_text('hi')\n",
        encoding="utf-8",
    )
    result = _run(
        tmp_path,
        ["python", "script.py"],
        allow_mutating=True,
        allow_git_mutation=False,
        persist=False,
    )
    assert result.status == "succeeded"
    assert len(simulate_sandbox) == 1
    assert result.permission_level == (
        PermissionLevel.EXECUTE_MUTATING.value
    )


def test_dangerous_git_keeps_dangerous_message_when_git_locked(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "factory.task_command_runner"
        ".run_in_task_command_sandbox",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("must not run")
        ),
    )
    result = _run(
        tmp_path,
        ["git", "reset", "--hard"],
        allow_mutating=True,
        allow_git_mutation=False,
        persist=False,
    )
    assert result.status == "rejected"
    assert "DANGEROUS" in result.stderr
