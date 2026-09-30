"""Controller-owned command → secret-env mapping.

The model never chooses env keys or values.
Only approved operations receive injected secrets.
"""

from __future__ import annotations

from pathlib import Path

from factory.task_secret_store import (
    USER_PASSWORD_SECRET_NAME,
    get_task_secret,
)


DJANGO_SUPERUSER_PASSWORD_ENV = (
    "DJANGO_SUPERUSER_PASSWORD"
)

MISSING_TASK_SECRET_MESSAGE = (
    "Gerekli görev sırrı artık mevcut değil."
)


class TaskSecretUnavailableError(RuntimeError):
    """Approved op needs a secret that is missing."""

    def __init__(
        self,
        message: str = MISSING_TASK_SECRET_MESSAGE,
    ) -> None:
        super().__init__(message)


def _executable_basename(token: str) -> str:
    return Path(token).name.casefold()


def _is_python_executable(token: str) -> bool:
    name = _executable_basename(token)

    return (
        name.startswith("python")
        or name in {"py", "py.exe"}
    )


def is_django_createsuperuser_noinput(
    argv: list[str] | tuple[str, ...] | None,
) -> bool:
    """True for approved createsuperuser --noinput forms.

    Supported shapes:
    - python manage.py createsuperuser --noinput ...
    - python3 / py aliases for the interpreter
    """
    tokens = [
        str(item)
        for item in (argv or [])
        if str(item)
    ]

    if len(tokens) < 3:
        return False

    if not _is_python_executable(tokens[0]):
        return False

    script = Path(tokens[1]).name.casefold()

    if script != "manage.py":
        return False

    has_createsuperuser = False
    has_noinput = False

    for token in tokens[2:]:
        folded = token.casefold()

        if folded == "createsuperuser":
            has_createsuperuser = True
            continue

        if folded in {
            "--noinput",
            "--no-input",
        }:
            has_noinput = True

    return has_createsuperuser and has_noinput


def resolve_task_command_secret_env(
    task_id: str,
    argv: list[str] | tuple[str, ...] | None,
    cwd: str | None = None,
    *,
    required_secret_names: (
        list[str] | tuple[str, ...] | None
    ) = None,
) -> dict[str, str]:
    """Return approved secret env for one command.

    Unrelated commands always get {}.
    Model cannot choose env keys.
    ``cwd`` is reserved for future path-aware rules.
    """
    _ = cwd
    tid = str(task_id or "").strip()

    if not tid:
        return {}

    if not is_django_createsuperuser_noinput(argv):
        return {}

    required = {
        str(name).strip()
        for name in (required_secret_names or [])
        if str(name).strip()
    }

    value = get_task_secret(
        tid,
        USER_PASSWORD_SECRET_NAME,
    )

    if value is None:
        if USER_PASSWORD_SECRET_NAME in required:
            raise TaskSecretUnavailableError()

        return {}

    # Controller-owned mapping only.
    return {
        DJANGO_SUPERUSER_PASSWORD_ENV: value,
    }
