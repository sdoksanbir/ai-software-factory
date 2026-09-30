"""Ephemeral task secret store tests."""

from __future__ import annotations

import pytest

from factory.task_secret_store import (
    TaskSecretStoreError,
    clear_task_secrets,
    get_task_secret,
    has_task_secret,
    list_task_secret_names,
    reset_task_secret_store_for_tests,
    scrub_prompt_with_secrets,
    set_task_secrets,
    validate_secret_items,
)


@pytest.fixture(autouse=True)
def _clean_store():
    reset_task_secret_store_for_tests()
    yield
    reset_task_secret_store_for_tests()


def test_set_get_list_and_scope():
    set_task_secrets(
        "TASK-1",
        {"user_password": "secret-a"},
    )
    set_task_secrets(
        "TASK-2",
        {"user_password": "secret-b"},
    )

    assert has_task_secret(
        "TASK-1",
        "user_password",
    )
    assert get_task_secret(
        "TASK-1",
        "user_password",
    ) == "secret-a"
    assert get_task_secret(
        "TASK-2",
        "user_password",
    ) == "secret-b"
    assert list_task_secret_names("TASK-1") == [
        "user_password"
    ]
    # Cross-task isolation.
    assert (
        get_task_secret(
            "TASK-1",
            "user_password",
        )
        != get_task_secret(
            "TASK-2",
            "user_password",
        )
    )


def test_no_list_all_values_api():
    set_task_secrets(
        "TASK-1",
        {"user_password": "hidden-value"},
    )
    names = list_task_secret_names("TASK-1")
    assert names == ["user_password"]
    assert "hidden-value" not in names


def test_repr_does_not_expose_values():
    from factory import task_secret_store as mod

    set_task_secrets(
        "TASK-1",
        {"user_password": "super-secret-xyz"},
    )
    text = repr(mod._STORE)
    assert "super-secret-xyz" not in text
    assert "user_password" in text


def test_validate_rejects_bad_names_and_dupes():
    with pytest.raises(TaskSecretStoreError):
        validate_secret_items(
            [{"name": "", "value": "x"}]
        )

    with pytest.raises(TaskSecretStoreError):
        validate_secret_items(
            [{"name": "Bad-Name", "value": "x"}]
        )

    with pytest.raises(TaskSecretStoreError):
        validate_secret_items(
            [
                {
                    "name": "user_password",
                    "value": "a",
                },
                {
                    "name": "user_password",
                    "value": "b",
                },
            ]
        )

    with pytest.raises(TaskSecretStoreError):
        validate_secret_items(
            [{"name": "user_password", "value": ""}]
        )


def test_scrub_prompt_exact_values_only():
    scrubbed = scrub_prompt_with_secrets(
        "kullanıcı adı admin şifre Abc123!",
        {"user_password": "Abc123!"},
    )
    assert "Abc123!" not in scrubbed
    assert "[SECRET:user_password]" in scrubbed
    assert "admin" in scrubbed


def test_restart_simulation_clears_store():
    set_task_secrets(
        "TASK-1",
        {"user_password": "temp"},
    )
    reset_task_secret_store_for_tests()
    assert list_task_secret_names("TASK-1") == []
    assert (
        get_task_secret(
            "TASK-1",
            "user_password",
        )
        is None
    )


def test_clear_task_secrets():
    set_task_secrets(
        "TASK-1",
        {"user_password": "x"},
    )
    clear_task_secrets("TASK-1")
    assert not has_task_secret(
        "TASK-1",
        "user_password",
    )
