"""Production guarded task command runner.

Independent of experimental general_agent_* / general_process_tools.
Does not import experimental modules. Not wired into TaskExecutionService.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

from factory.task_command_models import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_ARG_COUNT,
    MAX_ARG_LENGTH,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    CommandStatus,
    PermissionLevel,
    TaskCommandError,
    TaskCommandPathError,
    TaskCommandPolicyError,
    TaskCommandRequest,
    TaskCommandResult,
    TaskCommandValidationError,
    collect_secret_values,
    redact_text,
    resolve_secret_env_keys,
    truncate_capture,
)
from factory.task_command_store import (
    save_task_command,
)


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

DANGEROUS_EXECUTABLES = {
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "cmd",
    "cmd.exe",
    "bash",
    "bash.exe",
    "sh",
    "sh.exe",
    "zsh",
    "csh",
    "fish",
    "rm",
    "rm.exe",
    "del",
    "del.exe",
    "rmdir",
    "rd",
    "format",
    "format.exe",
    "diskpart",
    "diskpart.exe",
    "shutdown",
    "shutdown.exe",
    "mkfs",
    "dd",
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

GIT_SAFE_SUBCOMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "rev-parse",
    "remote",
    "tag",
    "describe",
    "ls-files",
    "version",
    "--version",
    "help",
}

GIT_MUTATING_SUBCOMMANDS = {
    "add",
    "commit",
    "checkout",
    "switch",
    "restore",
    "stash",
    "fetch",
    "pull",
    "push",
    "merge",
    "rebase",
    "init",
    "clone",
    "mv",
    "rm",
}

GIT_DANGEROUS_SUBCOMMANDS = {
    "clean",
}

GIT_DANGEROUS_FLAGS = {
    "--hard",
    "-fd",
    "-fdx",
    "-fx",
    "-dff",
}

DJANGO_SAFE_MANAGE_COMMANDS = {
    "check",
    "test",
    "showmigrations",
    "diffsettings",
    "version",
    "help",
}

DJANGO_DANGEROUS_MANAGE_COMMANDS = {
    "shell",
    "dbshell",
    "flush",
}

DJANGO_MUTATING_MANAGE_COMMANDS = {
    "migrate",
    "makemigrations",
    "createsuperuser",
    "collectstatic",
    "loaddata",
    "dumpdata",
    "startapp",
    "startproject",
}

# Minimal host env allowlist for child processes.
# Do not copy the full host environment.
PROCESS_ENV_ALLOWLIST = {
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
    "LANG",
    "LC_ALL",
    "VIRTUAL_ENV",
}

NPM_SAFE_ARGS = {
    "--version",
    "-v",
    "version",
    "view",
    "list",
    "ls",
    "outdated",
    "pack",
    "ping",
    "help",
}

NPM_MUTATING_ARGS = {
    "install",
    "ci",
    "uninstall",
    "update",
    "run",
    "exec",
    "publish",
    "link",
    "unlink",
    "dedupe",
}


def _utcnow_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _project_root(project_path: str | Path) -> Path:
    root = Path(project_path).expanduser().resolve()

    if not root.exists():
        raise TaskCommandPathError(
            f"Proje yolu bulunamadi: {root}"
        )

    if not root.is_dir():
        raise TaskCommandPathError(
            f"Proje yolu klasor degil: {root}"
        )

    return root


def resolve_command_cwd(
    project_root: Path,
    cwd: str | None,
) -> Path:
    """Resolve cwd and enforce project-root jail."""
    value = (cwd or ".").strip() or "."
    candidate_input = Path(value)

    if candidate_input.is_absolute():
        candidate = (
            candidate_input
            .expanduser()
            .resolve()
        )
    else:
        candidate = (
            project_root / candidate_input
        ).resolve()

    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise TaskCommandPathError(
            "Process cwd proje kokunun disina cikamaz: "
            f"{value}"
        ) from exc

    if not candidate.exists():
        raise TaskCommandPathError(
            f"Process cwd bulunamadi: {value}"
        )

    if not candidate.is_dir():
        raise TaskCommandPathError(
            f"Process cwd klasor degil: {value}"
        )

    return candidate


def _normalize_argv(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        raise TaskCommandValidationError(
            "argv liste olmali."
        )

    if not raw:
        raise TaskCommandValidationError(
            "argv bos olamaz."
        )

    if len(raw) > MAX_ARG_COUNT:
        raise TaskCommandValidationError(
            "argv cok fazla arguman iceriyor."
        )

    argv: list[str] = []

    for item in raw:
        if not isinstance(item, str):
            raise TaskCommandValidationError(
                "argv elemanlari string olmali."
            )

        if "\x00" in item:
            raise TaskCommandValidationError(
                "argv NUL karakteri iceremez."
            )

        if len(item) > MAX_ARG_LENGTH:
            raise TaskCommandValidationError(
                "argv elemani cok uzun."
            )

        argv.append(item)

    return argv


def _validate_timeout(timeout_seconds: int) -> int:
    try:
        timeout = int(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise TaskCommandValidationError(
            "timeout_seconds tamsayi olmali."
        ) from exc

    if (
        timeout < MIN_TIMEOUT_SECONDS
        or timeout > MAX_TIMEOUT_SECONDS
    ):
        raise TaskCommandValidationError(
            "timeout_seconds "
            f"{MIN_TIMEOUT_SECONDS} ile "
            f"{MAX_TIMEOUT_SECONDS} arasinda olmali."
        )

    return timeout


def _is_project_venv_executable(
    root: Path,
    executable: Path,
) -> bool:
    try:
        relative = executable.relative_to(root)
    except ValueError:
        return False

    parts = {
        part.casefold()
        for part in relative.parts
    }

    return bool(
        {"venv", ".venv"} & parts
    )


def resolve_command_executable(
    root: Path,
    raw: str,
) -> str:
    value = raw.strip()

    if not value:
        raise TaskCommandPolicyError(
            "Executable bos olamaz."
        )

    if "\x00" in value:
        raise TaskCommandPolicyError(
            "Executable NUL karakteri iceremez."
        )

    candidate = Path(value)
    lowered_name = candidate.name.casefold()

    if lowered_name in DANGEROUS_EXECUTABLES:
        raise TaskCommandPolicyError(
            f"DANGEROUS executable reddedildi: {value}"
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

        name = resolved.name.casefold()

        if (
            name in SAFE_PATH_EXECUTABLES
            and resolved.exists()
            and resolved.is_file()
        ):
            aliases = {
                name,
                Path(name).stem.casefold(),
            }

            for alias in aliases:
                located = shutil.which(alias)

                if located is None:
                    continue

                if (
                    Path(located)
                    .expanduser()
                    .resolve()
                    == resolved
                ):
                    return str(resolved)

        raise TaskCommandPolicyError(
            "Absolute executable yalnizca mevcut Python "
            "yorumlayicisi, proje venv'i veya PATH'teki "
            "izinli runtime olabilir."
        )

    if "/" in value or "\\" in value:
        resolved = (root / candidate).resolve()

        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise TaskCommandPolicyError(
                "Executable proje kokunun disina cikamaz."
            ) from exc

        if not _is_project_venv_executable(
            root,
            resolved,
        ):
            raise TaskCommandPolicyError(
                "Proje icindeki executable yalnizca "
                "venv/.venv altindan calistirilabilir."
            )

        if not resolved.exists():
            raise TaskCommandPolicyError(
                f"Executable bulunamadi: {value}"
            )

        return str(resolved)

    lowered = value.casefold()

    if lowered in DANGEROUS_EXECUTABLES:
        raise TaskCommandPolicyError(
            f"DANGEROUS executable reddedildi: {value}"
        )

    if lowered not in SAFE_PATH_EXECUTABLES:
        raise TaskCommandPolicyError(
            f"Executable izinli degil: {value}"
        )

    located = shutil.which(value)

    if located is None:
        raise TaskCommandPolicyError(
            f"Executable PATH icinde bulunamadi: {value}"
        )

    return located


def _executable_basename(executable: str) -> str:
    return Path(executable).name.casefold()


def _is_python_executable(name: str) -> bool:
    return (
        name.startswith("python")
        or name in {"py", "py.exe"}
    )


def _is_pip_executable(name: str) -> bool:
    return name.startswith("pip")


def _is_npm_family(name: str) -> bool:
    return name in {
        "npm",
        "npm.cmd",
        "npx",
        "npx.cmd",
    }


def _django_manage_command(
    args: list[str],
) -> str | None:
    if not args:
        return None

    first = Path(args[0]).name.casefold()

    if first != "manage.py":
        return None

    for arg in args[1:]:
        if arg.startswith("-"):
            continue

        return arg.casefold()

    return None


def classify_permission_level(
    executable: str,
    args: list[str],
) -> PermissionLevel:
    """Classify argv into SAFE / MUTATING / DANGEROUS."""
    name = _executable_basename(executable)
    lowered_args = [arg.casefold() for arg in args]

    if name in DANGEROUS_EXECUTABLES:
        return PermissionLevel.DANGEROUS

    if _is_python_executable(name):
        if any(
            arg in PYTHON_EVAL_FLAGS
            for arg in lowered_args
        ):
            return PermissionLevel.DANGEROUS

        # python -m pip ...
        if (
            len(lowered_args) >= 2
            and lowered_args[0] == "-m"
            and lowered_args[1] == "pip"
        ):
            pip_args = lowered_args[2:]

            if any(
                token in pip_args
                for token in (
                    "install",
                    "uninstall",
                    "download",
                )
            ):
                return PermissionLevel.EXECUTE_MUTATING

            return PermissionLevel.EXECUTE_SAFE

        # python -m django ...
        if (
            len(lowered_args) >= 2
            and lowered_args[0] == "-m"
            and lowered_args[1] == "django"
        ):
            django_args = lowered_args[2:]

            if any(
                token in django_args
                for token in (
                    "startproject",
                    "startapp",
                )
            ):
                return PermissionLevel.EXECUTE_MUTATING

            if any(
                token in django_args
                for token in (
                    "--version",
                    "help",
                )
            ):
                return PermissionLevel.EXECUTE_SAFE

            return PermissionLevel.EXECUTE_MUTATING

        manage_cmd = _django_manage_command(args)

        if manage_cmd is not None:
            if manage_cmd in DJANGO_DANGEROUS_MANAGE_COMMANDS:
                return PermissionLevel.DANGEROUS

            if manage_cmd in DJANGO_SAFE_MANAGE_COMMANDS:
                return PermissionLevel.EXECUTE_SAFE

            if manage_cmd in DJANGO_MUTATING_MANAGE_COMMANDS:
                return PermissionLevel.EXECUTE_MUTATING

            # Unknown manage.py subcommand: mutating by default.
            return PermissionLevel.EXECUTE_MUTATING

        if any(
            arg in {"--version", "-V"}
            for arg in args
        ) and len(args) == 1:
            return PermissionLevel.EXECUTE_SAFE

        # Running a project script / module is mutating.
        return PermissionLevel.EXECUTE_MUTATING

    if name in {"pytest", "pytest.exe"}:
        return PermissionLevel.EXECUTE_SAFE

    if _is_pip_executable(name):
        if any(
            token in lowered_args
            for token in (
                "install",
                "uninstall",
                "download",
            )
        ):
            return PermissionLevel.EXECUTE_MUTATING

        return PermissionLevel.EXECUTE_SAFE

    if name in {"node", "node.exe"}:
        if any(
            arg in NODE_EVAL_FLAGS
            for arg in lowered_args
        ):
            return PermissionLevel.DANGEROUS

        if any(
            arg in {"--version", "-v"}
            for arg in lowered_args
        ):
            return PermissionLevel.EXECUTE_SAFE

        return PermissionLevel.EXECUTE_MUTATING

    if _is_npm_family(name):
        if not lowered_args:
            return PermissionLevel.EXECUTE_SAFE

        head = lowered_args[0]

        if head in NPM_SAFE_ARGS:
            return PermissionLevel.EXECUTE_SAFE

        if head in NPM_MUTATING_ARGS:
            return PermissionLevel.EXECUTE_MUTATING

        return PermissionLevel.EXECUTE_MUTATING

    if name in {"git", "git.exe"}:
        if not lowered_args:
            return PermissionLevel.EXECUTE_SAFE

        sub = lowered_args[0]

        if any(
            flag in lowered_args
            for flag in GIT_DANGEROUS_FLAGS
        ):
            return PermissionLevel.DANGEROUS

        if sub in GIT_DANGEROUS_SUBCOMMANDS:
            return PermissionLevel.DANGEROUS

        if sub == "reset" and any(
            flag in lowered_args
            for flag in ("--hard", "--merge")
        ):
            return PermissionLevel.DANGEROUS

        if sub in GIT_SAFE_SUBCOMMANDS:
            return PermissionLevel.EXECUTE_SAFE

        if sub in GIT_MUTATING_SUBCOMMANDS:
            return PermissionLevel.EXECUTE_MUTATING

        return PermissionLevel.EXECUTE_MUTATING

    if name in {"uv", "uv.exe"}:
        if any(
            token in lowered_args
            for token in ("pip", "add", "remove", "sync")
        ):
            return PermissionLevel.EXECUTE_MUTATING

        return PermissionLevel.EXECUTE_SAFE

    return PermissionLevel.DANGEROUS


def assert_command_allowed(
    permission_level: PermissionLevel,
    *,
    allow_mutating: bool = False,
) -> None:
    if permission_level == PermissionLevel.DANGEROUS:
        raise TaskCommandPolicyError(
            "DANGEROUS komut reddedildi."
        )

    if (
        permission_level
        == PermissionLevel.EXECUTE_MUTATING
        and not allow_mutating
    ):
        raise TaskCommandPolicyError(
            "EXECUTE_MUTATING komut icin "
            "allow_mutating=True gerekli."
        )


def build_process_env(
    request_env: dict[str, str] | None = None,
    *,
    host_environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a minimal child env — never copy the full host env."""
    host = (
        host_environ
        if host_environ is not None
        else dict(os.environ)
    )

    # Case-insensitive host lookup (Windows).
    host_by_fold = {
        key.casefold(): (key, value)
        for key, value in host.items()
    }

    process_env: dict[str, str] = {}

    for allowed in PROCESS_ENV_ALLOWLIST:
        hit = host_by_fold.get(
            allowed.casefold()
        )

        if hit is None:
            continue

        original_key, value = hit
        process_env[original_key] = value

    if request_env:
        process_env.update(request_env)

    return process_env


def _relative_cwd_label(
    project_root: Path,
    workdir: Path,
) -> str:
    if workdir == project_root:
        return "."

    return workdir.relative_to(
        project_root
    ).as_posix()


def _validate_env(
    env: dict[str, str] | None,
) -> dict[str, str]:
    if env is None:
        return {}

    if not isinstance(env, dict):
        raise TaskCommandValidationError(
            "env dict olmali."
        )

    normalized: dict[str, str] = {}

    for key, value in env.items():
        if not isinstance(key, str) or not isinstance(
            value,
            str,
        ):
            raise TaskCommandValidationError(
                "env anahtar ve degerleri string olmali."
            )

        if not key.strip():
            raise TaskCommandValidationError(
                "env anahtari bos olamaz."
            )

        if "\x00" in key or "\x00" in value:
            raise TaskCommandValidationError(
                "env NUL karakteri iceremez."
            )

        normalized[key] = value

    return normalized


def run_task_command(
    *,
    project_path: str | Path,
    request: TaskCommandRequest,
    db_path: str | Path | None = None,
    persist: bool = True,
) -> TaskCommandResult:
    """Run one guarded command and optionally persist history."""
    project_root = _project_root(project_path)
    argv = _normalize_argv(request.argv)
    timeout = _validate_timeout(
        request.timeout_seconds
        if request.timeout_seconds is not None
        else DEFAULT_TIMEOUT_SECONDS
    )
    extra_env = _validate_env(request.env)
    secret_keys = resolve_secret_env_keys(
        extra_env,
        request.secret_env_keys,
    )

    # Secrets must never appear in argv.
    secret_values_for_argv_check = collect_secret_values(
        extra_env,
        secret_keys,
    )

    for arg in argv:
        for secret in secret_values_for_argv_check:
            if secret and secret in arg:
                raise TaskCommandValidationError(
                    "Secret deger argv icinde bulunamaz; "
                    "env kullanin."
                )

    workdir = resolve_command_cwd(
        project_root,
        request.cwd,
    )
    executable = resolve_command_executable(
        project_root,
        argv[0],
    )
    command = [executable, *argv[1:]]

    permission_level = classify_permission_level(
        executable,
        argv[1:],
    )
    assert_command_allowed(
        permission_level,
        allow_mutating=bool(
            request.allow_mutating
        ),
    )

    process_env = build_process_env(extra_env)

    secret_values = collect_secret_values(
        extra_env,
        secret_keys,
    )

    command_id = str(uuid4())
    started_at = _utcnow_iso()
    started_monotonic = time.monotonic()

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
            env=process_env,
        )
    except subprocess.TimeoutExpired as exc:
        finished_at = _utcnow_iso()
        duration_ms = int(
            (
                time.monotonic()
                - started_monotonic
            )
            * 1000
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

        stdout, stdout_truncated = truncate_capture(
            redact_text(raw_stdout, secret_values)
        )
        stderr, stderr_truncated = truncate_capture(
            redact_text(raw_stderr, secret_values)
        )

        result = TaskCommandResult(
            command_id=command_id,
            task_id=request.task_id,
            argv=list(argv),
            cwd=_relative_cwd_label(
                project_root,
                workdir,
            ),
            permission_level=permission_level.value,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            status=CommandStatus.TIMED_OUT.value,
            secret_env_keys=secret_keys,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

        if persist:
            save_kwargs: dict[str, Any] = {
                "result": result,
            }

            if db_path is not None:
                save_kwargs["db_path"] = db_path

            save_task_command(**save_kwargs)

        return result

    finished_at = _utcnow_iso()
    duration_ms = int(
        (
            time.monotonic()
            - started_monotonic
        )
        * 1000
    )

    stdout, stdout_truncated = truncate_capture(
        redact_text(
            completed.stdout or "",
            secret_values,
        )
    )
    stderr, stderr_truncated = truncate_capture(
        redact_text(
            completed.stderr or "",
            secret_values,
        )
    )

    status = (
        CommandStatus.SUCCEEDED.value
        if completed.returncode == 0
        else CommandStatus.FAILED.value
    )

    result = TaskCommandResult(
        command_id=command_id,
        task_id=request.task_id,
        argv=list(argv),
        cwd=_relative_cwd_label(
            project_root,
            workdir,
        ),
        permission_level=permission_level.value,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        exit_code=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        status=status,
        secret_env_keys=secret_keys,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )

    if persist:
        save_kwargs = {
            "result": result,
        }

        if db_path is not None:
            save_kwargs["db_path"] = db_path

        save_task_command(**save_kwargs)

    return result
