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
    ExecutionBoundary,
    NetworkPolicy,
    PermissionLevel,
    TaskCommandError,
    TaskCommandPathError,
    TaskCommandPolicyError,
    TaskCommandRequest,
    TaskCommandResult,
    TaskCommandSandboxRuntimeError,
    TaskCommandValidationError,
    collect_secret_values,
    redact_argv,
    redact_text,
    resolve_secret_env_keys,
    truncate_capture,
)
from factory.task_command_dependency_environment import (
    ensure_dependency_environment,
    prepare_package_install_argv,
    trusted_pip_install_env,
    uses_python_dependency_environment,
)
from factory.task_command_sandbox import (
    run_in_task_command_sandbox,
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

# Narrow HOST_SAFE git templates (read-only).
# Subcommand alone is insufficient — each entry is
# validated by a per-subcommand arg allowlist/template.
GIT_HOST_SAFE_SUBCOMMANDS = {
    "status",
    "rev-parse",
    "branch",
    "ls-files",
}

# Exact flags only (fail closed on unknown).
GIT_HOST_SAFE_STATUS_FLAGS = {
    "--short",
    "--porcelain",
    "--porcelain=v1",
}

GIT_HOST_SAFE_BRANCH_FLAGS = {
    "--list",
    "--show-current",
}

GIT_HOST_SAFE_REV_PARSE_FLAGS = {
    "--is-inside-work-tree",
    "--show-toplevel",
    "--show-prefix",
    "--git-dir",
    "--absolute-git-dir",
    "--is-bare-repository",
    "--abbrev-ref",
    "--short",
    "--verify",
    "--quiet",
    "--symbolic-full-name",
}

GIT_HOST_SAFE_LS_FILES_FLAGS = {
    "--cached",
    "--others",
    "--ignored",
    "--exclude-standard",
    "--modified",
    "--deleted",
    "--stage",
    "-c",
    "-o",
    "-i",
    "-m",
    "-d",
    "-s",
    "-z",
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
        return classify_git_permission_level(args)

    if name in {"uv", "uv.exe"}:
        if any(
            token in lowered_args
            for token in ("pip", "add", "remove", "sync")
        ):
            return PermissionLevel.EXECUTE_MUTATING

        return PermissionLevel.EXECUTE_SAFE

    return PermissionLevel.DANGEROUS


def _find_git_subcommand(
    args: list[str],
) -> tuple[str | None, list[str]]:
    """Locate git subcommand after common globals."""
    index = 0
    while index < len(args):
        lowered = args[index].casefold()

        if lowered in {"--no-pager", "--paginate"}:
            index += 1
            continue

        if lowered == "-c":
            index += 2
            continue

        if lowered.startswith("-c") and lowered != "-c":
            index += 1
            continue

        if lowered.startswith("-"):
            index += 1
            continue

        break

    if index >= len(args):
        return None, []

    return args[index].casefold(), list(args[index + 1 :])


def _git_delete_force_flags(
    sub_args: list[str],
) -> bool:
    lowered = [arg.casefold() for arg in sub_args]
    if "-d" in lowered or "-D".casefold() in lowered:
        return True
    if "--delete" in lowered:
        return True
    return False


def _git_permission_is_dangerous(
    sub: str | None,
    sub_args: list[str],
    full_args: list[str],
) -> bool:
    lowered_full = [arg.casefold() for arg in full_args]

    if any(
        flag in lowered_full
        for flag in GIT_DANGEROUS_FLAGS
    ):
        return True

    if sub in GIT_DANGEROUS_SUBCOMMANDS:
        return True

    if sub == "reset" and any(
        flag in lowered_full
        for flag in ("--hard", "--merge")
    ):
        return True

    if sub == "branch" and _git_delete_force_flags(
        sub_args
    ):
        return True

    if sub == "tag" and _git_delete_force_flags(
        sub_args
    ):
        return True

    return False


# Narrow read-only flags for diff/log/show EXECUTE_SAFE.
# Unknown / exec / write surfaces → not SAFE (MUTATING).
GIT_READ_ONLY_DIFF_LOG_SHOW_FLAGS = {
    "--stat",
    "--name-only",
    "--name-status",
    "--cached",
    "--staged",
    "--quiet",
    "--numstat",
    "--shortstat",
    "--compact-summary",
    "--color",
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--oneline",
    "--decorate",
    "--all",
    "--graph",
    "--reverse",
    "--summary",
}


def _git_diff_log_show_read_only_args(
    sub_args: list[str],
) -> bool:
    allowed = {
        flag.casefold()
        for flag in GIT_READ_ONLY_DIFF_LOG_SHOW_FLAGS
    }
    for arg in sub_args:
        if not _is_safe_git_token(arg):
            return False
        lowered = arg.casefold()
        if lowered.startswith("-"):
            if lowered in {
                "--ext-diff",
                "--textconv",
                "--exec",
            } or lowered.startswith("--output"):
                return False
            if lowered.startswith("--max-count="):
                continue
            if lowered.startswith("--unified="):
                continue
            if (
                len(lowered) > 2
                and lowered.startswith("-u")
                and lowered[2:].isdigit()
            ):
                continue
            if lowered not in allowed:
                return False
            continue
        if not _is_safe_git_ref_or_path(arg):
            return False
    return True


def _git_remote_read_only_args(
    sub_args: list[str],
) -> bool:
    if not sub_args:
        return True

    for arg in sub_args:
        if not _is_safe_git_token(arg):
            return False

    head = sub_args[0].casefold()
    if head in {"-v", "--verbose"}:
        return len(sub_args) == 1

    if head == "show":
        if len(sub_args) == 1:
            return True
        if len(sub_args) == 2:
            return _is_safe_git_ref_or_path(
                sub_args[1]
            )
        return False

    if head == "get-url":
        if len(sub_args) == 2:
            return _is_safe_git_ref_or_path(
                sub_args[1]
            )
        return False

    return False


def _git_tag_read_only_args(
    sub_args: list[str],
) -> bool:
    """Bare list / --list only — creating tags is mutating."""
    if not sub_args:
        return True

    for arg in sub_args:
        if not _is_safe_git_token(arg):
            return False

    head = sub_args[0].casefold()
    if head in {"-l", "--list"}:
        if len(sub_args) == 1:
            return True
        if len(sub_args) == 2:
            return _is_safe_git_ref_or_path(
                sub_args[1]
            )
        return False

    return False


def is_git_execute_safe_argv(
    args: list[str],
) -> bool:
    """Verified read-only git templates for EXECUTE_SAFE.

    Reuses the same HOST_SAFE read-only templates where
    applicable, plus narrow read-only forms for
    diff/log/show/remote/tag/version that may still run
    in PROJECT_CODE_SANDBOX. Does not consult
    ExecutionBoundary.
    """
    if not args:
        return True

    if is_host_safe_git_argv(args):
        return True

    remaining, sub = _parse_host_safe_git_head(args)
    if sub is None:
        return False

    if sub in {"version", "--version", "help"}:
        return len(remaining) == 1

    if sub in {"diff", "log", "show"}:
        return _git_diff_log_show_read_only_args(
            remaining[1:]
        )

    if sub == "remote":
        return _git_remote_read_only_args(
            remaining[1:]
        )

    if sub == "tag":
        return _git_tag_read_only_args(
            remaining[1:]
        )

    if sub == "describe":
        # Only bare describe or a single safe ref.
        rest = remaining[1:]
        if not rest:
            return True
        if len(rest) == 1:
            return _is_safe_git_ref_or_path(rest[0])
        return False

    return False


def classify_git_permission_level(
    args: list[str],
) -> PermissionLevel:
    """Argv-aware git permission — fail closed on unknown."""
    if not args:
        return PermissionLevel.EXECUTE_SAFE

    sub, sub_args = _find_git_subcommand(args)

    if _git_permission_is_dangerous(
        sub,
        sub_args,
        args,
    ):
        return PermissionLevel.DANGEROUS

    if is_git_execute_safe_argv(args):
        return PermissionLevel.EXECUTE_SAFE

    return PermissionLevel.EXECUTE_MUTATING


def _parse_host_safe_git_head(
    args: list[str],
) -> tuple[list[str], str | None]:
    """Parse HOST_SAFE git head — reject caller globals.

    Only optional ``--no-pager`` is tolerated (harden
    injects it anyway). ``-c`` / other globals are
    fail-closed because they can reopen exec surfaces.
    """
    index = 0
    while index < len(args):
        lowered = args[index].casefold()
        if lowered == "--no-pager":
            index += 1
            continue
        if lowered.startswith("-"):
            return [], None
        break

    if index >= len(args):
        return [], None

    return args[index:], args[index].casefold()


def _is_safe_git_token(token: str) -> bool:
    if not token:
        return False
    if token.startswith("!"):
        return False
    if "\n" in token or "\r" in token or "\x00" in token:
        return False
    return True


def _is_safe_git_ref_or_path(token: str) -> bool:
    if not _is_safe_git_token(token):
        return False
    if token.startswith("-"):
        return False
    return True


def _host_safe_git_status_args(
    sub_args: list[str],
) -> bool:
    allowed = {
        flag.casefold()
        for flag in GIT_HOST_SAFE_STATUS_FLAGS
    }
    for arg in sub_args:
        if not _is_safe_git_token(arg):
            return False
        if arg.casefold() not in allowed:
            return False
    return True


def _host_safe_git_branch_args(
    sub_args: list[str],
) -> bool:
    """Only bare list / --list / --show-current."""
    if not sub_args:
        return True

    for arg in sub_args:
        if not _is_safe_git_token(arg):
            return False

    head = sub_args[0].casefold()
    if head == "--show-current":
        return len(sub_args) == 1

    if head == "--list":
        if len(sub_args) == 1:
            return True
        if len(sub_args) == 2:
            return _is_safe_git_ref_or_path(
                sub_args[1]
            )
        return False

    # Positional branch names / -D / -m / etc.
    return False


def _host_safe_git_rev_parse_args(
    sub_args: list[str],
) -> bool:
    allowed = {
        flag.casefold()
        for flag in GIT_HOST_SAFE_REV_PARSE_FLAGS
    }
    for arg in sub_args:
        if not _is_safe_git_token(arg):
            return False
        lowered = arg.casefold()
        if lowered.startswith("-"):
            if lowered not in allowed:
                return False
            continue
        if not _is_safe_git_ref_or_path(arg):
            return False
    return True


def _host_safe_git_ls_files_args(
    sub_args: list[str],
) -> bool:
    allowed = {
        flag.casefold()
        for flag in GIT_HOST_SAFE_LS_FILES_FLAGS
    }
    for arg in sub_args:
        if not _is_safe_git_token(arg):
            return False
        lowered = arg.casefold()
        if lowered.startswith("-"):
            if lowered not in allowed:
                return False
            continue
        if not _is_safe_git_ref_or_path(arg):
            return False
    return True


def _host_safe_git_sub_args_allowed(
    sub: str,
    sub_args: list[str],
) -> bool:
    if sub == "status":
        return _host_safe_git_status_args(sub_args)
    if sub == "branch":
        return _host_safe_git_branch_args(sub_args)
    if sub == "rev-parse":
        return _host_safe_git_rev_parse_args(
            sub_args
        )
    if sub == "ls-files":
        return _host_safe_git_ls_files_args(
            sub_args
        )
    return False


def is_host_safe_python_version_argv(
    args: list[str],
) -> bool:
    if len(args) != 1:
        return False

    return args[0] in {"--version", "-V"}


def is_host_safe_git_argv(
    args: list[str],
) -> bool:
    """HOST_SAFE only for exact per-subcommand templates."""
    remaining, sub = _parse_host_safe_git_head(args)

    if sub is None:
        return False

    if sub not in GIT_HOST_SAFE_SUBCOMMANDS:
        return False

    return _host_safe_git_sub_args_allowed(
        sub,
        remaining[1:],
    )


def classify_execution_boundary(
    executable: str,
    args: list[str],
) -> ExecutionBoundary:
    """Classify where a non-dangerous command may run."""
    name = _executable_basename(executable)

    if _is_python_executable(name):
        if is_host_safe_python_version_argv(args):
            return ExecutionBoundary.HOST_SAFE

        return ExecutionBoundary.PROJECT_CODE_SANDBOX

    if name in {"git", "git.exe"}:
        if is_host_safe_git_argv(args):
            return ExecutionBoundary.HOST_SAFE

        return ExecutionBoundary.PROJECT_CODE_SANDBOX

    # Everything else that passed permission checks
    # (pytest, manage.py, npm, pip, scripts, ...) is
    # repository-controlled / package-manager code.
    return ExecutionBoundary.PROJECT_CODE_SANDBOX


def classify_network_policy(
    executable: str,
    args: list[str],
) -> NetworkPolicy:
    name = _executable_basename(executable)
    lowered = [arg.casefold() for arg in args]

    if _is_python_executable(name):
        if (
            len(lowered) >= 3
            and lowered[0] == "-m"
            and lowered[1] == "pip"
            and "install" in lowered[2:]
        ):
            return NetworkPolicy.NETWORK_PACKAGE_INSTALL

    if _is_pip_executable(name):
        if "install" in lowered:
            return NetworkPolicy.NETWORK_PACKAGE_INSTALL

    if _is_npm_family(name):
        if lowered and lowered[0] in {
            "install",
            "ci",
        }:
            return NetworkPolicy.NETWORK_PACKAGE_INSTALL

    return NetworkPolicy.NETWORK_NONE


def harden_host_safe_git_command(
    executable: str,
    args: list[str],
) -> list[str]:
    """Rebuild HOST_SAFE git from validated templates only.

    Caller globals / unknown flags are dropped by
    re-parsing through ``is_host_safe_git_argv`` —
    security options cannot be overridden by trailing
    caller args because only allowlisted tokens remain.
    """
    if not is_host_safe_git_argv(args):
        raise TaskCommandPolicyError(
            "HOST_SAFE git template degil."
        )

    remaining, sub = _parse_host_safe_git_head(args)
    if sub is None:
        raise TaskCommandPolicyError(
            "HOST_SAFE git template degil."
        )

    sub_args = remaining[1:]

    return [
        executable,
        "--no-pager",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=",
        sub,
        *sub_args,
    ]


def build_host_safe_process_env(
    request_env: dict[str, str] | None = None,
    *,
    host_environ: dict[str, str] | None = None,
    for_git: bool = False,
) -> dict[str, str]:
    """Minimal trusted host env for HOST_SAFE only.

    ``request_env`` is intentionally ignored in V1 —
    HOST_SAFE must not receive caller env overlays
    (blocks GIT_DIR / GIT_CONFIG_* / secret injection).
    """
    _ = request_env
    process_env = build_process_env(
        None,
        host_environ=host_environ,
    )

    # Never forward external-diff helper env.
    drop_keys = {
        key
        for key in list(process_env)
        if key.casefold()
        in {
            "git_external_diff",
            "git_pager",
            "pager",
            "git_trace",
        }
    }
    for key in drop_keys:
        process_env.pop(key, None)

    if for_git:
        process_env["GIT_CONFIG_NOSYSTEM"] = "1"
        process_env["GIT_CONFIG_GLOBAL"] = os.devnull
        process_env["GIT_CONFIG_SYSTEM"] = os.devnull
        process_env["GIT_TERMINAL_PROMPT"] = "0"

    return process_env


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
    """Run one guarded command and optionally persist history.

    Policy / path / validation rejections before process start are
    persisted as ``CommandStatus.REJECTED`` (no subprocess) and
    returned — not raised — so Terminal history stays complete.
    """
    project_root = _project_root(project_path)
    argv = _normalize_argv(request.argv)
    original_argv = list(argv)
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

    command_id = str(uuid4())
    started_at = _utcnow_iso()
    started_monotonic = time.monotonic()
    cwd_label = "."
    permission_level = PermissionLevel.DANGEROUS
    boundary = ExecutionBoundary.PROJECT_CODE_SANDBOX
    network_policy = NetworkPolicy.NETWORK_NONE
    secret_values: list[str] = []
    workdir: Path | None = None
    executable: str | None = None
    args: list[str] = []
    sandbox_args: list[str] = []

    def _persist_result(
        result: TaskCommandResult,
    ) -> TaskCommandResult:
        if persist:
            save_kwargs: dict[str, Any] = {
                "result": result,
            }
            if db_path is not None:
                save_kwargs["db_path"] = db_path
            save_task_command(**save_kwargs)
        return result

    def _persistable_argv(
        values: list[str] | None = None,
    ) -> list[str]:
        """Argv safe for persistence / observations."""
        secrets = values if values is not None else secret_values
        return redact_argv(original_argv, secrets)

    def _rejected(
        reason: str,
        *,
        level: PermissionLevel | None = None,
        argv_secret_values: list[str] | None = None,
    ) -> TaskCommandResult:
        finished_at = _utcnow_iso()
        duration_ms = int(
            (
                time.monotonic()
                - started_monotonic
            )
            * 1000
        )
        err, err_trunc = truncate_capture(reason)
        result = TaskCommandResult(
            command_id=command_id,
            task_id=request.task_id,
            argv=_persistable_argv(
                argv_secret_values
            ),
            cwd=cwd_label,
            permission_level=(
                level or permission_level
            ).value,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            exit_code=None,
            stdout="",
            stderr=err,
            status=CommandStatus.REJECTED.value,
            secret_env_keys=secret_keys,
            stdout_truncated=False,
            stderr_truncated=err_trunc,
            execution_boundary="",
            network_policy="",
        )
        return _persist_result(result)

    def _finish(
        *,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        status: str,
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
    ) -> TaskCommandResult:
        finished_at = _utcnow_iso()
        duration_ms = int(
            (
                time.monotonic()
                - started_monotonic
            )
            * 1000
        )
        out, out_trunc = truncate_capture(
            redact_text(stdout, secret_values)
        )
        err, err_trunc = truncate_capture(
            redact_text(stderr, secret_values)
        )
        result = TaskCommandResult(
            command_id=command_id,
            task_id=request.task_id,
            argv=_persistable_argv(),
            cwd=cwd_label,
            permission_level=permission_level.value,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            exit_code=exit_code,
            stdout=out,
            stderr=err,
            status=status,
            secret_env_keys=secret_keys,
            stdout_truncated=(
                stdout_truncated or out_trunc
            ),
            stderr_truncated=(
                stderr_truncated or err_trunc
            ),
            execution_boundary=boundary.value,
            network_policy=network_policy.value,
        )
        return _persist_result(result)

    # Secrets must never appear in argv.
    secret_values_for_argv_check = collect_secret_values(
        extra_env,
        secret_keys,
    )
    # Populate early so rejection paths can redact.
    secret_values = list(
        secret_values_for_argv_check
    )

    for arg in argv:
        for secret in secret_values_for_argv_check:
            if secret and secret in arg:
                return _rejected(
                    "Secret deger argv icinde bulunamaz; "
                    "env kullanin.",
                    argv_secret_values=(
                        secret_values_for_argv_check
                    ),
                )

    try:
        workdir = resolve_command_cwd(
            project_root,
            request.cwd,
        )
        cwd_label = _relative_cwd_label(
            project_root,
            workdir,
        )
        executable = resolve_command_executable(
            project_root,
            argv[0],
        )
        args = argv[1:]
        permission_level = classify_permission_level(
            executable,
            args,
        )
        assert_command_allowed(
            permission_level,
            allow_mutating=bool(
                request.allow_mutating
            ),
        )
        boundary = classify_execution_boundary(
            executable,
            args,
        )
        network_policy = classify_network_policy(
            executable,
            args,
        )

        is_package_install = (
            network_policy
            == NetworkPolicy.NETWORK_PACKAGE_INSTALL
        )
        sandbox_args = list(args)

        if is_package_install:
            if extra_env:
                raise TaskCommandPolicyError(
                    "NETWORK_PACKAGE_INSTALL komutunda "
                    "request.env V1'de bos olmali."
                )
            sandbox_args = prepare_package_install_argv(
                project_root=project_root,
                executable=executable,
                args=args,
            )

        secret_values = collect_secret_values(
            extra_env,
            secret_keys,
        )
    except (
        TaskCommandPolicyError,
        TaskCommandPathError,
        TaskCommandValidationError,
    ) as exc:
        return _rejected(str(exc))

    assert workdir is not None
    assert executable is not None

    if boundary == ExecutionBoundary.HOST_SAFE:
        if _executable_basename(executable) in {
            "git",
            "git.exe",
        }:
            command = harden_host_safe_git_command(
                executable,
                args,
            )
            process_env = build_host_safe_process_env(
                for_git=True,
            )
        else:
            command = [executable, *args]
            process_env = build_host_safe_process_env(
                for_git=False,
            )

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
            return _finish(
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
                status=CommandStatus.TIMED_OUT.value,
            )

        return _finish(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            status=(
                CommandStatus.SUCCEEDED.value
                if completed.returncode == 0
                else CommandStatus.FAILED.value
            ),
        )

    # PROJECT_CODE_SANDBOX
    dependency_volume_name: str | None = None
    sandbox_request_env = dict(extra_env)
    is_package_install = (
        network_policy
        == NetworkPolicy.NETWORK_PACKAGE_INSTALL
    )

    if uses_python_dependency_environment(executable):
        dependency_volume_name = (
            ensure_dependency_environment(
                project_root=project_root,
                task_id=request.task_id,
            )
        )
        if is_package_install:
            sandbox_request_env = (
                trusted_pip_install_env()
            )

    try:
        sandbox_result = run_in_task_command_sandbox(
            project_root=project_root,
            workdir=workdir,
            host_argv=[executable, *sandbox_args],
            request_env=sandbox_request_env,
            network_policy=network_policy,
            command_id=command_id,
            timeout_seconds=timeout,
            dependency_volume_name=(
                dependency_volume_name
            ),
        )
    except TaskCommandSandboxRuntimeError:
        raise
    except TaskCommandError:
        raise

    if sandbox_result.timed_out:
        return _finish(
            exit_code=None,
            stdout=sandbox_result.stdout,
            stderr=sandbox_result.stderr,
            status=CommandStatus.TIMED_OUT.value,
        )

    return _finish(
        exit_code=sandbox_result.exit_code,
        stdout=sandbox_result.stdout,
        stderr=sandbox_result.stderr,
        status=(
            CommandStatus.SUCCEEDED.value
            if sandbox_result.exit_code == 0
            else CommandStatus.FAILED.value
        ),
    )
