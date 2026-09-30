"""Task-command Docker sandbox (terminal engine).

Independent of factory.tools.sandbox.DockerSandbox
used by WRITE verify. Do not change that module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import subprocess
from typing import Any

from factory.task_command_models import (
    NetworkPolicy,
    TaskCommandSandboxRuntimeError,
)


# Separate config from WRITE verify image wiring.
DEFAULT_TASK_COMMAND_IMAGE = os.environ.get(
    "AI_FACTORY_TASK_COMMAND_IMAGE",
    "ai-factory-python-test",
)

LAUNCHER_CONTAINER_PATH = (
    "/opt/ai-factory/task_command_launcher.py"
)

CONTAINER_PROJECT_ROOT = "/app"

# Minimal hardening compatible with Docker Desktop.
SANDBOX_PIDS_LIMIT = "256"
SANDBOX_MEMORY = "1g"
SANDBOX_CPUS = "1"

NODE_EXECUTABLES = {
    "node",
    "node.exe",
    "npm",
    "npm.cmd",
    "npx",
    "npx.cmd",
}


@dataclass(frozen=True)
class TaskCommandSandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    docker_argv: list[str]
    container_argv: list[str]
    container_name: str


def launcher_host_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "task_command_container_launcher.py"
    )


def build_docker_cli_env(
    host_environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Minimal host env for the docker CLI only."""
    host = (
        host_environ
        if host_environ is not None
        else dict(os.environ)
    )
    allow = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "DOCKER_HOST",
        "DOCKER_CERT_PATH",
        "DOCKER_TLS_VERIFY",
    }
    by_fold = {
        key.casefold(): (key, value)
        for key, value in host.items()
    }
    result: dict[str, str] = {}
    for name in allow:
        hit = by_fold.get(name.casefold())
        if hit is not None:
            result[hit[0]] = hit[1]
    return result


def requires_node_runtime(
    executable_name: str,
) -> bool:
    return (
        Path(executable_name).name.casefold()
        in NODE_EXECUTABLES
    )


def map_argv_for_container(
    *,
    host_argv: list[str],
    project_root: Path,
    workdir: Path,
) -> list[str]:
    """Map host argv to Linux container argv (no shell)."""
    if not host_argv:
        raise TaskCommandSandboxRuntimeError(
            "Sandbox argv bos olamaz."
        )

    root = project_root.resolve()
    first = Path(host_argv[0]).name.casefold()

    if first in {
        "python",
        "python.exe",
        "python3",
        "python3.exe",
        "py",
        "py.exe",
    }:
        mapped = ["python", *host_argv[1:]]
    elif first in {"pytest", "pytest.exe"}:
        mapped = [
            "python",
            "-m",
            "pytest",
            *host_argv[1:],
        ]
    elif first in {"pip", "pip.exe", "pip3", "pip3.exe"}:
        mapped = [
            "python",
            "-m",
            "pip",
            *host_argv[1:],
        ]
    elif first in NODE_EXECUTABLES:
        # Caller should reject before run; keep name.
        mapped = list(host_argv)
        mapped[0] = Path(host_argv[0]).stem
        if mapped[0].casefold().endswith(".cmd"):
            mapped[0] = mapped[0][:-4]
    else:
        mapped = list(host_argv)
        mapped[0] = Path(host_argv[0]).name

    result: list[str] = []
    for index, arg in enumerate(mapped):
        if index == 0:
            result.append(arg)
            continue

        candidate = Path(arg)
        if candidate.is_absolute():
            try:
                rel = candidate.resolve().relative_to(
                    root
                )
            except ValueError as exc:
                raise TaskCommandSandboxRuntimeError(
                    "Sandbox argv proje disi absolute "
                    f"path iceremez: {arg}"
                ) from exc
            result.append(
                f"{CONTAINER_PROJECT_ROOT}/"
                f"{rel.as_posix()}"
            )
            continue

        result.append(arg.replace("\\", "/"))

    return result


def container_workdir(
    *,
    project_root: Path,
    workdir: Path,
) -> str:
    root = project_root.resolve()
    cwd = workdir.resolve()
    if cwd == root:
        return CONTAINER_PROJECT_ROOT
    rel = cwd.relative_to(root).as_posix()
    return f"{CONTAINER_PROJECT_ROOT}/{rel}"


def build_docker_run_argv(
    *,
    project_root: Path,
    workdir: Path,
    container_argv: list[str],
    network_policy: NetworkPolicy,
    container_name: str,
    image_name: str = DEFAULT_TASK_COMMAND_IMAGE,
    launcher_path: Path | None = None,
) -> list[str]:
    launcher = (
        launcher_path
        if launcher_path is not None
        else launcher_host_path()
    ).resolve()

    if not launcher.is_file():
        raise TaskCommandSandboxRuntimeError(
            f"Trusted launcher bulunamadi: {launcher}"
        )

    abs_project = str(project_root.resolve())
    network = (
        "none"
        if network_policy
        == NetworkPolicy.NETWORK_NONE
        else "bridge"
    )

    docker_argv = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        container_name,
        "--network",
        network,
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        SANDBOX_PIDS_LIMIT,
        "--memory",
        SANDBOX_MEMORY,
        "--cpus",
        SANDBOX_CPUS,
        # RW project mount — NO /app/data tmpfs
        # (unlike WRITE DockerSandbox).
        "-v",
        f"{abs_project}:{CONTAINER_PROJECT_ROOT}",
        "-v",
        (
            f"{launcher}:"
            f"{LAUNCHER_CONTAINER_PATH}:ro"
        ),
        "-w",
        container_workdir(
            project_root=project_root,
            workdir=workdir,
        ),
        image_name,
        "python",
        LAUNCHER_CONTAINER_PATH,
    ]

    # container_argv is delivered via stdin JSON,
    # not appended to docker argv (keeps secrets
    # and command structured).
    _ = container_argv
    return docker_argv


def build_stdin_payload(
    *,
    container_argv: list[str],
    request_env: dict[str, str],
) -> dict[str, Any]:
    return {
        "argv": list(container_argv),
        "env": dict(request_env),
    }


def _force_remove_container(
    container_name: str,
    *,
    docker_env: dict[str, str],
) -> None:
    try:
        subprocess.run(
            [
                "docker",
                "rm",
                "-f",
                container_name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            shell=False,
            check=False,
            timeout=30,
            env=docker_env,
        )
    except Exception:
        # Cleanup must not replace the primary result.
        return


def run_in_task_command_sandbox(
    *,
    project_root: Path,
    workdir: Path,
    host_argv: list[str],
    request_env: dict[str, str],
    network_policy: NetworkPolicy,
    command_id: str,
    timeout_seconds: int,
    image_name: str = DEFAULT_TASK_COMMAND_IMAGE,
    host_environ: dict[str, str] | None = None,
) -> TaskCommandSandboxResult:
    """Run argv inside Docker via trusted launcher + stdin."""
    exe_name = Path(host_argv[0]).name
    if requires_node_runtime(exe_name):
        raise TaskCommandSandboxRuntimeError(
            "Node/npm runtime bu terminal sandbox "
            "image'inda desteklenmiyor; host fallback yok."
        )

    container_argv = map_argv_for_container(
        host_argv=host_argv,
        project_root=project_root,
        workdir=workdir,
    )
    short_id = command_id.replace("-", "")[:12]
    container_name = f"ai-factory-taskcmd-{short_id}"

    docker_argv = build_docker_run_argv(
        project_root=project_root,
        workdir=workdir,
        container_argv=container_argv,
        network_policy=network_policy,
        container_name=container_name,
        image_name=image_name,
    )

    # Guardrails: never introduce a shell wrapper.
    if "sh" in docker_argv and "-c" in docker_argv:
        raise TaskCommandSandboxRuntimeError(
            "Sandbox docker argv shell wrapper iceremez."
        )

    payload = build_stdin_payload(
        container_argv=container_argv,
        request_env=request_env,
    )
    stdin_text = json.dumps(
        payload,
        ensure_ascii=False,
    )
    docker_env = build_docker_cli_env(host_environ)

    try:
        completed = subprocess.run(
            docker_argv,
            input=stdin_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=timeout_seconds,
            env=docker_env,
        )
    except FileNotFoundError as exc:
        raise TaskCommandSandboxRuntimeError(
            "Docker is not installed or not found "
            "in system PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        _force_remove_container(
            container_name,
            docker_env=docker_env,
        )
        raw_stdout = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else ""
        )
        raw_stderr = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else ""
        )
        return TaskCommandSandboxResult(
            exit_code=None,
            stdout=raw_stdout or "",
            stderr=raw_stderr or "",
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
