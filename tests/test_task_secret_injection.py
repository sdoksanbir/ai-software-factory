"""Controller secret-injection policy tests."""

from __future__ import annotations

import pytest

from factory.task_secret_injection import (
    DJANGO_SUPERUSER_PASSWORD_ENV,
    MISSING_TASK_SECRET_MESSAGE,
    TaskSecretUnavailableError,
    is_django_createsuperuser_noinput,
    resolve_task_command_secret_env,
)
from factory.task_secret_store import (
    reset_task_secret_store_for_tests,
    set_task_secrets,
)


@pytest.fixture(autouse=True)
def _clean_store():
    reset_task_secret_store_for_tests()
    yield
    reset_task_secret_store_for_tests()


@pytest.mark.parametrize(
    "argv,expected",
    [
        (
            [
                "python",
                "manage.py",
                "createsuperuser",
                "--noinput",
                "--username",
                "admin",
            ],
            True,
        ),
        (
            [
                "python3",
                "manage.py",
                "createsuperuser",
                "--no-input",
            ],
            True,
        ),
        (
            [
                "python",
                "manage.py",
                "createsuperuser",
            ],
            False,
        ),
        (["python", "--version"], False),
        (
            ["python", "manage.py", "check"],
            False,
        ),
        (["git", "status"], False),
        (
            [
                "python",
                "script.py",
                "createsuperuser",
                "--noinput",
            ],
            False,
        ),
    ],
)
def test_createsuperuser_detection(argv, expected):
    assert (
        is_django_createsuperuser_noinput(argv)
        is expected
    )


def test_injects_only_for_approved_op():
    set_task_secrets(
        "TASK-1",
        {"user_password": "pw-value-42"},
    )

    env = resolve_task_command_secret_env(
        "TASK-1",
        [
            "python",
            "manage.py",
            "createsuperuser",
            "--noinput",
            "--username",
            "admin",
            "--email",
            "a@b.c",
        ],
        "edusen",
    )
    assert env == {
        DJANGO_SUPERUSER_PASSWORD_ENV: "pw-value-42",
    }

    assert (
        resolve_task_command_secret_env(
            "TASK-1",
            ["python", "--version"],
        )
        == {}
    )
    assert (
        resolve_task_command_secret_env(
            "TASK-1",
            ["python", "manage.py", "check"],
        )
        == {}
    )
    assert (
        resolve_task_command_secret_env(
            "TASK-1",
            ["git", "status"],
        )
        == {}
    )


def test_other_task_cannot_resolve_secret():
    set_task_secrets(
        "TASK-1",
        {"user_password": "only-here"},
    )
    assert (
        resolve_task_command_secret_env(
            "TASK-2",
            [
                "python",
                "manage.py",
                "createsuperuser",
                "--noinput",
            ],
        )
        == {}
    )


def test_missing_required_secret_raises():
    with pytest.raises(
        TaskSecretUnavailableError
    ) as exc:
        resolve_task_command_secret_env(
            "TASK-1",
            [
                "python",
                "manage.py",
                "createsuperuser",
                "--noinput",
            ],
            required_secret_names=[
                "user_password"
            ],
        )

    assert str(exc.value) == (
        MISSING_TASK_SECRET_MESSAGE
    )
    assert "only-here" not in str(exc.value)
