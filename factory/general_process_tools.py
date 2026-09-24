from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import shutil
import subprocess
import sys

from factory.general_filesystem_tools import (
    UnsafeProjectPathError,
    build_filesystem_tool_registry,
)
from factory.tool_registry import (
    ToolRegistry,
)


DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 300
MAX_ARG_COUNT = 64
MAX_ARG_LENGTH = 2000
MAX_CAPTURE_CHARS = 100_000

SAFE_PATH_EXECUTABLES = {
    "python",
    "python.exe",
    "python3",
    "python3.exe",
    "py",
    "py.exe",
    "pytest",
    "pytest.exe",
    "pip",
    "pip.exe",
    "pip3",
    "pip3.exe",
    "node",
    "node.exe",
    "npm",
    "npm.cmd",
    "npx",
    "npx.cmd",
    "git",
    "git.exe",
    "uv",
    "uv.exe",
}

PYTHON_EVAL_FLAGS = {
    "-c",
}

NODE_EVAL_FLAGS = {
    "-e",
    "--eval",
    "-p",
    "--print",
}

GIT_DESTRUCTIVE_SUBCOMMANDS = {
    "clean",
}

GIT_DESTRUCTIVE_FLAGS = {
    "--hard",
}


class ProcessToolError(RuntimeError):
    pass


class UnsafeExecutableError(
    ProcessToolError
):
    pass


class UnsafeProcessArgumentsError(
    ProcessToolError
):
    pass


def _project_root(
    project_path: str,
) -> Path:
    root = Path(
        project_path
    ).expanduser().resolve()

    if not root.exists():
        raise ProcessToolError(
            f"Proje yolu bulunamadi: {root}"
        )

    if not root.is_dir():
        raise ProcessToolError(
            f"Proje yolu klasor degil: {root}"
        )

    return root


def _resolve_cwd(
    root: Path,
    cwd: str | None,
) -> Path:
    value = (
        (cwd or ".").strip()
        or "."
    )

    candidate_input = Path(
        value
    )

    if candidate_input.is_absolute():
        candidate = (
            candidate_input
            .expanduser()
            .resolve()
        )
    else:
        candidate = (
            root
            / candidate_input
        ).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeProjectPathError(
            "Process cwd proje kokunun disina cikamaz: "
            f"{value}"
        ) from exc

    if not candidate.exists():
        raise ProcessToolError(
            f"Process cwd bulunamadi: {value}"
        )

    if not candidate.is_dir():
        raise ProcessToolError(
            f"Process cwd klasor degil: {value}"
        )

    return candidate


def _is_project_venv_executable(
    root: Path,
    executable: Path,
) -> bool:
    try:
        relative = executable.relative_to(
            root
        )
    except ValueError:
        return False

    parts = {
        part.casefold()
        for part in relative.parts
    }

    return bool(
        {
            "venv",
            ".venv",
        }
        & parts
    )


def _resolve_executable(
    root: Path,
    raw: str,
) -> str:
    value = raw.strip()

    if not value:
        raise UnsafeExecutableError(
            "Executable bos olamaz."
        )

    if "\x00" in value:
        raise UnsafeExecutableError(
            "Executable NUL karakteri iceremez."
        )

    candidate = Path(
        value
    )

    if candidate.is_absolute():
        resolved = (
            candidate
            .expanduser()
            .resolve()
        )

        current_python = Path(
            sys.executable
        ).resolve()

        if resolved == current_python:
            return str(resolved)

        if (
            resolved.exists()
            and resolved.is_file()
            and _is_project_venv_executable(
                root,
                resolved,
            )
        ):
            return str(resolved)

        raise UnsafeExecutableError(
            "Absolute executable yalnizca mevcut Python "
            "yorumlayicisi veya proje venv'i icinden olabilir."
        )

    if (
        "/" in value
        or "\\" in value
    ):
        resolved = (
            root
            / candidate
        ).resolve()

        try:
            resolved.relative_to(
                root
            )
        except ValueError as exc:
            raise UnsafeExecutableError(
                "Executable proje kokunun disina cikamaz."
            ) from exc

        if not _is_project_venv_executable(
            root,
            resolved,
        ):
            raise UnsafeExecutableError(
                "Proje icindeki executable yalnizca "
                "venv/.venv altindan calistirilabilir."
            )

        if not resolved.exists():
            raise UnsafeExecutableError(
                f"Executable bulunamadi: {value}"
            )

        return str(resolved)

    lowered = value.casefold()

    if lowered not in SAFE_PATH_EXECUTABLES:
        raise UnsafeExecutableError(
            f"Executable izinli degil: {value}"
        )

    located = shutil.which(
        value
    )

    if located is None:
        raise UnsafeExecutableError(
            f"Executable PATH icinde bulunamadi: {value}"
        )

    return located


def _normalize_argv(
    raw: Any,
) -> list[str]:
    if not isinstance(
        raw,
        (list, tuple),
    ):
        raise UnsafeProcessArgumentsError(
            "argv liste olmali."
        )

    if not raw:
        raise UnsafeProcessArgumentsError(
            "argv bos olamaz."
        )

    if len(raw) > MAX_ARG_COUNT:
        raise UnsafeProcessArgumentsError(
            "argv cok fazla arguman iceriyor."
        )

    argv: list[str] = []

    for item in raw:
        if not isinstance(
            item,
            str,
        ):
            raise UnsafeProcessArgumentsError(
                "argv elemanlari string olmali."
            )

        if "\x00" in item:
            raise UnsafeProcessArgumentsError(
                "argv NUL karakteri iceremez."
            )

        if len(item) > MAX_ARG_LENGTH:
            raise UnsafeProcessArgumentsError(
                "argv elemani cok uzun."
            )

        argv.append(
            item
        )

    return argv


def _validate_command_policy(
    executable: str,
    args: list[str],
) -> None:
    name = Path(
        executable
    ).name.casefold()

    lowered_args = [
        arg.casefold()
        for arg in args
    ]

    if (
        name.startswith("python")
        or name in {
            "py",
            "py.exe",
        }
    ):
        if any(
            arg in PYTHON_EVAL_FLAGS
            for arg in lowered_args
        ):
            raise UnsafeProcessArgumentsError(
                "Python inline eval (-c) run_process "
                "uzerinden izinli degil."
            )

    if name in {
        "node",
        "node.exe",
    }:
        if any(
            arg in NODE_EVAL_FLAGS
            for arg in lowered_args
        ):
            raise UnsafeProcessArgumentsError(
                "Node inline eval run_process "
                "uzerinden izinli degil."
            )

    if name in {
        "git",
        "git.exe",
    }:
        if lowered_args:
            if (
                lowered_args[0]
                in GIT_DESTRUCTIVE_SUBCOMMANDS
            ):
                raise UnsafeProcessArgumentsError(
                    "Destructive git komutu run_process "
                    "uzerinden izinli degil."
                )

        if any(
            arg in GIT_DESTRUCTIVE_FLAGS
            for arg in lowered_args
        ):
            raise UnsafeProcessArgumentsError(
                "Destructive git flag run_process "
                "uzerinden izinli degil."
            )


def _truncate(
    value: str,
) -> tuple[str, bool]:
    if len(value) <= MAX_CAPTURE_CHARS:
        return value, False

    return (
        value[
            :MAX_CAPTURE_CHARS
        ],
        True,
    )


def _run_process_handler(
    root: Path,
):
    def handler(
        arguments: dict[str, Any],
        cwd: str | None,
    ) -> dict[str, Any]:
        argv = _normalize_argv(
            arguments["argv"]
        )

        executable = _resolve_executable(
            root,
            argv[0],
        )

        args = argv[1:]

        _validate_command_policy(
            executable,
            args,
        )

        workdir = _resolve_cwd(
            root,
            cwd,
        )

        timeout = int(
            arguments.get(
                "timeout_seconds",
                DEFAULT_TIMEOUT_SECONDS,
            )
        )

        if (
            timeout < 1
            or timeout > MAX_TIMEOUT_SECONDS
        ):
            raise UnsafeProcessArgumentsError(
                "timeout_seconds 1 ile "
                f"{MAX_TIMEOUT_SECONDS} arasinda olmali."
            )

        command = [
            executable,
            *args,
        ]

        try:
            completed = subprocess.run(
                command,
                cwd=str(workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                check=False,
                timeout=timeout,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout
                if isinstance(
                    exc.stdout,
                    str,
                )
                else ""
            )
            stderr = (
                exc.stderr
                if isinstance(
                    exc.stderr,
                    str,
                )
                else ""
            )

            stdout, stdout_truncated = (
                _truncate(stdout)
            )
            stderr, stderr_truncated = (
                _truncate(stderr)
            )

            return {
                "success": False,
                "timed_out": True,
                "exit_code": None,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": (
                    stdout_truncated
                ),
                "stderr_truncated": (
                    stderr_truncated
                ),
                "cwd": (
                    workdir
                    .relative_to(root)
                    .as_posix()
                    if workdir != root
                    else "."
                ),
            }

        stdout, stdout_truncated = (
            _truncate(
                completed.stdout
                or ""
            )
        )
        stderr, stderr_truncated = (
            _truncate(
                completed.stderr
                or ""
            )
        )

        return {
            "success": (
                completed.returncode
                == 0
            ),
            "timed_out": False,
            "exit_code": (
                completed.returncode
            ),
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": (
                stdout_truncated
            ),
            "stderr_truncated": (
                stderr_truncated
            ),
            "cwd": (
                workdir
                .relative_to(root)
                .as_posix()
                if workdir != root
                else "."
            ),
        }

    return handler


def build_project_tool_registry(
    project_path: str,
) -> ToolRegistry:
    root = _project_root(
        project_path
    )

    registry = (
        build_filesystem_tool_registry(
            str(root)
        )
    )

    registry.bind_handler(
        "run_process",
        _run_process_handler(root),
    )

    return registry
