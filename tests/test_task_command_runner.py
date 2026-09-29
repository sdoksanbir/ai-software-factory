"""Focused tests for guarded task command engine (Step 1)."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from api import app as app_module
from factory.database import get_connection
from factory.task_command_models import (
    REDACTION_MASK,
    PermissionLevel,
    TaskCommandRequest,
)
from factory.task_command_runner import (
    TaskCommandPathError,
    TaskCommandPolicyError,
    assert_command_allowed,
    build_process_env,
    classify_permission_level,
    run_task_command,
)
from factory.task_command_store import (
    get_task_command,
    list_task_commands,
)


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
    combined = result.stdout + result.stderr
    assert "Python" in combined


def test_cwd_under_project_root(tmp_path):
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


def test_cwd_parent_escape_rejected(tmp_path):
    with pytest.raises(TaskCommandPathError):
        _run(
            tmp_path,
            [sys.executable, "--version"],
            cwd="../",
            persist=False,
        )


def test_absolute_external_cwd_rejected(
    tmp_path,
    tmp_path_factory,
):
    outside = tmp_path_factory.mktemp(
        "outside-cwd"
    )

    with pytest.raises(TaskCommandPathError):
        _run(
            tmp_path,
            [sys.executable, "--version"],
            cwd=str(outside),
            persist=False,
        )


def test_shell_metacharacters_not_interpreted(
    tmp_path,
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
    with pytest.raises(TaskCommandPolicyError):
        _run(
            tmp_path,
            argv,
            allow_mutating=True,
            persist=False,
        )


def test_timeout_returns_structured_result(
    tmp_path,
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


def test_stdout_stderr_captured(tmp_path):
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
    assert "DJANGO_SUPERUSER_PASSWORD" in (
        stored["secret_env_keys"]
    )

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


def test_secret_echo_in_stdout_is_masked(
    tmp_path,
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
    assert payload["state"] == "running"
    assert len(payload["commands"]) == 2

    ids = {
        item["command_id"]
        for item in payload["commands"]
    }
    assert first.command_id in ids
    assert second.command_id in ids

    serialized = json.dumps(payload)
    assert "super-secret" not in serialized


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
        classify_permission_level(
            "python",
            [
                "manage.py",
                "createsuperuser",
                "--noinput",
            ],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )
    assert (
        classify_permission_level(
            "python",
            ["manage.py", "migrate"],
        )
        == PermissionLevel.EXECUTE_MUTATING
    )


def test_mutating_pip_install_classification():
    # Classification only — do not hit network.
    level = classify_permission_level(
        "python",
        ["-m", "pip", "install", "django"],
    )
    assert level == (
        PermissionLevel.EXECUTE_MUTATING
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

    level = classify_permission_level(
        "python",
        ["manage.py", "migrate"],
    )
    assert level == (
        PermissionLevel.EXECUTE_MUTATING
    )


def test_dangerous_still_rejected_with_allow_mutating(
    tmp_path,
):
    with pytest.raises(TaskCommandPolicyError):
        _run(
            tmp_path,
            [sys.executable, "-c", "print(1)"],
            allow_mutating=True,
            persist=False,
        )


def test_manage_py_flush_is_dangerous():
    assert (
        classify_permission_level(
            "python",
            ["manage.py", "flush"],
        )
        == PermissionLevel.DANGEROUS
    )

    with pytest.raises(TaskCommandPolicyError):
        assert_command_allowed(
            PermissionLevel.DANGEROUS,
            allow_mutating=True,
        )


def test_host_secret_not_inherited(
    tmp_path,
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


def test_auto_sensitive_env_key_redaction(
    tmp_path,
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

    stored = get_task_command(
        result.command_id,
        db_path=db_path,
    )
    assert stored is not None
    assert secret not in json.dumps(stored)


def test_secret_echo_in_stderr_is_masked(
    tmp_path,
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

    stored = get_task_command(
        result.command_id,
        db_path=db_path,
    )
    assert stored is not None
    assert len(stored["stdout"]) <= 32
    assert len(stored["stderr"]) <= 32
    assert stored["stdout_truncated"] is True
    assert stored["stderr_truncated"] is True


def test_api_history_masks_real_secret_command(
    tmp_path,
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
    assert len(payload["commands"]) == 1


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
