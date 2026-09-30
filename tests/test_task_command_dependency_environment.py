"""Unit tests for persistent sandbox dependency environments."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from factory.task_command_dependency_environment import (
    CONTAINER_VENV_PYTHON,
    CONTAINER_VENV_ROOT,
    VOLUME_NAME_PREFIX,
    build_bootstrap_docker_argv,
    build_volume_create_argv,
    create_dependency_volume,
    dependency_environment_name,
    ensure_dependency_environment,
    prepare_package_install_argv,
    remove_dependency_environment,
    validate_dependency_volume_name,
    validate_package_install_argv,
)
from factory.task_command_models import (
    NetworkPolicy,
    PermissionLevel,
    TaskCommandPolicyError,
    TaskCommandSandboxRuntimeError,
    TaskCommandValidationError,
)
from factory.task_command_runner import (
    classify_permission_level,
)
from factory.task_command_sandbox import (
    build_docker_run_argv,
    map_argv_for_container,
)


VALID_VOLUME = "ai-factory-pyenv-" + ("ab" * 12)


def test_same_root_and_task_same_volume_name(tmp_path):
    a = dependency_environment_name(
        project_root=tmp_path,
        task_id="TASK-1",
    )
    b = dependency_environment_name(
        project_root=tmp_path,
        task_id="TASK-1",
    )
    assert a == b
    assert a.startswith(VOLUME_NAME_PREFIX)
    validate_dependency_volume_name(a)


def test_same_root_different_task_different_name(tmp_path):
    a = dependency_environment_name(
        project_root=tmp_path,
        task_id="TASK-A",
    )
    b = dependency_environment_name(
        project_root=tmp_path,
        task_id="TASK-B",
    )
    assert a != b


def test_different_root_different_name(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    a = dependency_environment_name(
        project_root=tmp_path,
        task_id="TASK-1",
    )
    b = dependency_environment_name(
        project_root=other,
        task_id="TASK-1",
    )
    assert a != b


def test_volume_name_docker_safe_no_leakage(tmp_path):
    name = dependency_environment_name(
        project_root=tmp_path,
        task_id="TASK-WIN-PATH",
    )
    assert name.startswith(VOLUME_NAME_PREFIX)
    suffix = name[len(VOLUME_NAME_PREFIX) :]
    assert len(suffix) == 24
    assert all(c in "0123456789abcdef" for c in suffix)
    assert ":" not in name
    assert "\\" not in name
    assert "/" not in name
    assert " " not in name
    assert "task-win-path" not in name.casefold()
    assert "users" not in name.casefold()
    resolved = str(tmp_path.resolve())
    assert resolved.casefold() not in name.casefold()


def test_volume_name_validator_rejects_arbitrary():
    with pytest.raises(TaskCommandValidationError):
        validate_dependency_volume_name(
            "my-important-db-volume"
        )
    with pytest.raises(TaskCommandValidationError):
        validate_dependency_volume_name(
            "ai-factory-pyenv-../../x"
        )
    with pytest.raises(TaskCommandValidationError):
        validate_dependency_volume_name(
            "ai-factory-pyenv-" + ("A" * 24)
        )
    with pytest.raises(TaskCommandValidationError):
        validate_dependency_volume_name(
            "ai-factory-pyenv-" + ("a" * 23)
        )
    with pytest.raises(TaskCommandValidationError):
        validate_dependency_volume_name(
            "ai-factory-pyenv-" + ("a" * 25)
        )
    with pytest.raises(TaskCommandValidationError):
        validate_dependency_volume_name(
            "wrong-prefix-" + ("a" * 24)
        )


def test_remove_rejects_invalid_name_without_docker(
    monkeypatch,
):
    called = {"run": False}

    def boom(*args, **kwargs):
        called["run"] = True
        raise AssertionError("docker must not run")

    monkeypatch.setattr(
        "factory.task_command_dependency_environment"
        ".subprocess.run",
        boom,
    )
    with pytest.raises(TaskCommandValidationError):
        remove_dependency_environment(
            volume_name="my-important-db-volume",
        )
    assert called["run"] is False


def test_sandbox_rejects_invalid_dependency_volume(
    tmp_path,
):
    with pytest.raises(TaskCommandValidationError):
        build_docker_run_argv(
            project_root=tmp_path,
            workdir=tmp_path,
            container_argv=["python", "--version"],
            network_policy=NetworkPolicy.NETWORK_NONE,
            container_name="ai-factory-taskcmd-x",
            dependency_volume_name="evil-volume",
        )


def test_volume_create_argv_shell_false_shape():
    argv = build_volume_create_argv(VALID_VOLUME)
    assert argv == [
        "docker",
        "volume",
        "create",
        VALID_VOLUME,
    ]


def test_bootstrap_argv_unique_name_no_shell_network_none():
    argv = build_bootstrap_docker_argv(
        volume_name=VALID_VOLUME,
        container_name="ai-factory-depboot-abc123def456",
    )
    assert argv[0] == "docker"
    assert "run" in argv
    assert "--rm" in argv
    name_idx = argv.index("--name")
    assert argv[name_idx + 1] == (
        "ai-factory-depboot-abc123def456"
    )
    idx = argv.index("--network")
    assert argv[idx + 1] == "none"
    assert f"{VALID_VOLUME}:{CONTAINER_VENV_ROOT}" in argv
    assert "sh" not in argv
    assert "-c" not in argv
    assert argv[-2] == "python"
    assert argv[-1].endswith(
        "task_command_dependency_bootstrap.py"
    )


def test_create_volume_uses_shell_false(monkeypatch):
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["shell"] = kwargs.get("shell")
        return subprocess.CompletedProcess(
            argv,
            0,
            f"{VALID_VOLUME}\n",
            "",
        )

    monkeypatch.setattr(
        "factory.task_command_dependency_environment"
        ".subprocess.run",
        fake_run,
    )
    create_dependency_volume(VALID_VOLUME)
    assert captured["shell"] is False
    assert captured["argv"][:3] == [
        "docker",
        "volume",
        "create",
    ]


def test_ensure_bootstrap_has_unique_name(
    tmp_path,
    monkeypatch,
):
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            "ok\n",
            "",
        )

    monkeypatch.setattr(
        "factory.task_command_dependency_environment"
        ".subprocess.run",
        fake_run,
    )

    name = ensure_dependency_environment(
        project_root=tmp_path,
        task_id="TASK-ENSURE",
    )
    assert name == dependency_environment_name(
        project_root=tmp_path,
        task_id="TASK-ENSURE",
    )
    bootstrap_calls = [
        call
        for call in calls
        if call[:2] == ["docker", "run"]
    ]
    assert len(bootstrap_calls) == 1
    boot = bootstrap_calls[0]
    assert "--name" in boot
    cname = boot[boot.index("--name") + 1]
    assert cname.startswith("ai-factory-depboot-")
    assert len(cname) > len("ai-factory-depboot-")
    assert boot[boot.index("--network") + 1] == "none"
    assert "sh" not in boot
    assert "-c" not in boot


def test_bootstrap_timeout_triggers_docker_rm(
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
        "factory.task_command_dependency_environment"
        ".subprocess.run",
        fake_run,
    )

    with pytest.raises(
        TaskCommandSandboxRuntimeError
    ) as exc_info:
        ensure_dependency_environment(
            project_root=tmp_path,
            task_id="TASK-TIMEOUT",
            timeout_seconds=1,
        )

    assert "timed out" in str(exc_info.value).casefold()
    rm_calls = [
        call
        for call in calls
        if call[:3] == ["docker", "rm", "-f"]
    ]
    assert len(rm_calls) == 1
    assert rm_calls[0][3].startswith(
        "ai-factory-depboot-"
    )


def test_bootstrap_cleanup_failure_does_not_mask_timeout(
    tmp_path,
    monkeypatch,
):
    def fake_run(argv, **kwargs):
        if argv[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(
                cmd=argv,
                timeout=1,
                output="",
                stderr="",
            )
        if argv[:3] == ["docker", "rm", "-f"]:
            raise OSError("cleanup failed")
        return subprocess.CompletedProcess(
            argv,
            0,
            "",
            "",
        )

    monkeypatch.setattr(
        "factory.task_command_dependency_environment"
        ".subprocess.run",
        fake_run,
    )

    with pytest.raises(
        TaskCommandSandboxRuntimeError
    ) as exc_info:
        ensure_dependency_environment(
            project_root=tmp_path,
            task_id="TASK-CLEANUP-FAIL",
            timeout_seconds=1,
        )

    assert "timed out" in str(exc_info.value).casefold()
    assert "cleanup failed" not in str(
        exc_info.value
    ).casefold()


def test_ensure_broken_bootstrap_raises(
    tmp_path,
    monkeypatch,
):
    def fake_run(argv, **kwargs):
        if argv[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(
                argv,
                1,
                "",
                "bootstrap: venv create failed",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            "vol\n",
            "",
        )

    monkeypatch.setattr(
        "factory.task_command_dependency_environment"
        ".subprocess.run",
        fake_run,
    )

    with pytest.raises(TaskCommandSandboxRuntimeError):
        ensure_dependency_environment(
            project_root=tmp_path,
            task_id="TASK-BROKEN",
        )


def test_remove_idempotent_missing_volume(monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            1,
            "",
            f"Error: No such volume: {VALID_VOLUME}",
        )

    monkeypatch.setattr(
        "factory.task_command_dependency_environment"
        ".subprocess.run",
        fake_run,
    )
    remove_dependency_environment(
        volume_name=VALID_VOLUME,
    )


def test_sandbox_mounts_dependency_volume(tmp_path):
    volume = "ai-factory-pyenv-deadbeefdeadbeefdeadbeef"
    docker_argv = build_docker_run_argv(
        project_root=tmp_path,
        workdir=tmp_path,
        container_argv=[
            CONTAINER_VENV_PYTHON,
            "manage.py",
            "check",
        ],
        network_policy=NetworkPolicy.NETWORK_NONE,
        container_name="ai-factory-taskcmd-abc",
        dependency_volume_name=volume,
    )
    assert f"{volume}:{CONTAINER_VENV_ROOT}" in docker_argv
    assert "--tmpfs" not in docker_argv
    assert "sh" not in docker_argv
    assert "-c" not in docker_argv


def test_map_python_pip_pytest_to_venv(tmp_path):
    mapped = map_argv_for_container(
        host_argv=["python", "manage.py", "check"],
        project_root=tmp_path,
        workdir=tmp_path,
        use_dependency_environment=True,
    )
    assert mapped == [
        CONTAINER_VENV_PYTHON,
        "manage.py",
        "check",
    ]

    mapped_pip = map_argv_for_container(
        host_argv=["pip", "install", "django"],
        project_root=tmp_path,
        workdir=tmp_path,
        use_dependency_environment=True,
    )
    assert mapped_pip == [
        CONTAINER_VENV_PYTHON,
        "-m",
        "pip",
        "install",
        "django",
    ]

    mapped_pytest = map_argv_for_container(
        host_argv=["pytest", "-q"],
        project_root=tmp_path,
        workdir=tmp_path,
        use_dependency_environment=True,
    )
    assert mapped_pytest == [
        CONTAINER_VENV_PYTHON,
        "-m",
        "pytest",
        "-q",
    ]


def test_map_without_dep_env_keeps_image_python(tmp_path):
    mapped = map_argv_for_container(
        host_argv=["python", "x.py"],
        project_root=tmp_path,
        workdir=tmp_path,
        use_dependency_environment=False,
    )
    assert mapped[0] == "python"


def test_safe_package_specs_accepted(tmp_path):
    validate_package_install_argv(
        project_root=tmp_path,
        executable="python",
        args=["-m", "pip", "install", "six"],
    )
    validate_package_install_argv(
        project_root=tmp_path,
        executable="pip",
        args=["install", "Django==5.1.1"],
    )
    validate_package_install_argv(
        project_root=tmp_path,
        executable="python",
        args=[
            "-m",
            "pip",
            "install",
            "six",
            "requests==2.32.3",
        ],
    )


def test_requirements_expands_safe_packages(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# comment\n"
        "\n"
        "six\n"
        "Django==5.2.17\n"
        "requests==2.32.3\n",
        encoding="utf-8",
    )
    prepared = prepare_package_install_argv(
        project_root=tmp_path,
        executable="pip",
        args=["install", "-r", "requirements.txt"],
    )
    assert prepared == [
        "install",
        "six",
        "Django==5.2.17",
        "requests==2.32.3",
    ]
    assert "-r" not in prepared
    assert "requirements.txt" not in prepared

    prepared_py = prepare_package_install_argv(
        project_root=tmp_path,
        executable="python",
        args=["-m", "pip", "install", "-r", "requirements.txt"],
    )
    assert prepared_py == [
        "-m",
        "pip",
        "install",
        "six",
        "Django==5.2.17",
        "requests==2.32.3",
    ]


@pytest.mark.parametrize(
    "content",
    [
        "--index-url https://example.com/simple\nsix\n",
        "-r other.txt\n",
        "-c constraints.txt\n",
        "-e .\n",
        ".\n",
        "../pkg\n",
        "git+https://example.com/r.git\n",
        "https://example.com/pkg.whl\n",
        "pkg ; python_version >= '3'\n",
        "six ${ENV}\n",
        "six\\\n",
        "--extra-index-url https://evil\n",
        "--find-links /tmp\n",
    ],
)
def test_malicious_requirements_rejected(tmp_path, content):
    req = tmp_path / "requirements.txt"
    req.write_text(content, encoding="utf-8")
    with pytest.raises(TaskCommandPolicyError):
        prepare_package_install_argv(
            project_root=tmp_path,
            executable="pip",
            args=["install", "-r", "requirements.txt"],
        )


def test_empty_and_comment_only_requirements_rejected(
    tmp_path,
):
    req = tmp_path / "requirements.txt"
    req.write_text("# only comments\n\n", encoding="utf-8")
    with pytest.raises(TaskCommandPolicyError):
        prepare_package_install_argv(
            project_root=tmp_path,
            executable="pip",
            args=["install", "-r", "requirements.txt"],
        )


def test_invalid_encoding_requirements_rejected(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_bytes(b"\xff\xfe\x00\x73\x00\x69\x00\x78")
    with pytest.raises(TaskCommandPolicyError):
        prepare_package_install_argv(
            project_root=tmp_path,
            executable="pip",
            args=["install", "-r", "requirements.txt"],
        )


def test_requirements_resolved_against_project_root_not_cwd(
    tmp_path,
):
    """Nested cwd must not select a different requirements file."""
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "requirements.txt").write_text(
        "six\n",
        encoding="utf-8",
    )
    (nested / "requirements.txt").write_text(
        "--index-url https://evil.example\nsix\n",
        encoding="utf-8",
    )
    prepared = prepare_package_install_argv(
        project_root=tmp_path,
        executable="pip",
        args=["install", "-r", "requirements.txt"],
    )
    assert prepared == ["install", "six"]


def test_requirements_outside_root_rejected(tmp_path):
    with pytest.raises(TaskCommandPolicyError):
        validate_package_install_argv(
            project_root=tmp_path,
            executable="pip",
            args=["install", "-r", "../outside.txt"],
        )


@pytest.mark.parametrize(
    "token",
    [
        "git+https://example.com/r.git",
        "svn+ssh://example.com/r",
        "hg+https://example.com/r",
        "https://example.com/pkg.whl",
        "http://example.com/pkg.whl",
    ],
)
def test_url_vcs_rejected(tmp_path, token):
    with pytest.raises(TaskCommandPolicyError):
        validate_package_install_argv(
            project_root=tmp_path,
            executable="pip",
            args=["install", token],
        )


@pytest.mark.parametrize(
    "flag",
    [
        "--target",
        "--prefix",
        "--root",
        "--user",
        "--index-url",
        "--extra-index-url",
        "--find-links",
        "--no-index",
    ],
)
def test_destination_index_flags_rejected(tmp_path, flag):
    with pytest.raises(TaskCommandPolicyError):
        validate_package_install_argv(
            project_root=tmp_path,
            executable="pip",
            args=["install", flag, "/tmp/x", "six"],
        )


def test_local_path_and_editable_rejected(tmp_path):
    with pytest.raises(TaskCommandPolicyError):
        validate_package_install_argv(
            project_root=tmp_path,
            executable="pip",
            args=["install", "."],
        )
    with pytest.raises(TaskCommandPolicyError):
        validate_package_install_argv(
            project_root=tmp_path,
            executable="pip",
            args=["install", "-e", "."],
        )
    with pytest.raises(TaskCommandPolicyError):
        validate_package_install_argv(
            project_root=tmp_path,
            executable="pip",
            args=["install", "--editable", "pkg"],
        )


def test_dangerous_policy_unchanged():
    assert (
        classify_permission_level(
            "python",
            ["-c", "print(1)"],
        )
        == PermissionLevel.DANGEROUS
    )
    assert (
        classify_permission_level(
            "python",
            ["manage.py", "flush"],
        )
        == PermissionLevel.DANGEROUS
    )


def test_bootstrap_ready_marker_schema():
    """Bootstrap module constants align with host expectations."""
    from factory import (
        task_command_dependency_bootstrap as boot,
    )

    assert boot.SCHEMA_VERSION == 1
    assert boot.ENV_DIR == CONTAINER_VENV_ROOT
    assert boot.READY_NAME == ".ai-factory-ready.json"
    assert boot.LOCK_NAME == (
        ".ai-factory-bootstrap.lock"
    )
