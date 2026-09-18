import sqlite3

import pytest

import factory.task_route_store as store


@pytest.fixture
def isolated_store(
    tmp_path,
    monkeypatch,
):
    database_path = (
        tmp_path / "task-routes.db"
    )

    def get_test_connection():
        return sqlite3.connect(
            database_path
        )

    monkeypatch.setattr(
        store,
        "get_connection",
        get_test_connection,
    )

    return store


def test_save_and_get_read_route(
    isolated_store,
):
    isolated_store.save_task_route(
        "TASK-1001",
        "read",
        "Salt-okuma gorevi.",
    )

    result = (
        isolated_store.get_task_route(
            "TASK-1001"
        )
    )

    assert result is not None
    assert result["task_id"] == "TASK-1001"
    assert result["kind"] == "read"
    assert result["reason"] == (
        "Salt-okuma gorevi."
    )


def test_save_and_get_write_route(
    isolated_store,
):
    isolated_store.save_task_route(
        "TASK-1002",
        "write",
        "Kod degisikligi gorevi.",
    )

    result = (
        isolated_store.get_task_route(
            "TASK-1002"
        )
    )

    assert result is not None
    assert result["kind"] == "write"


def test_route_can_be_updated(
    isolated_store,
):
    isolated_store.save_task_route(
        "TASK-1003",
        "read",
        "Ilk karar.",
    )

    isolated_store.save_task_route(
        "TASK-1003",
        "write",
        "Yeni karar.",
    )

    result = (
        isolated_store.get_task_route(
            "TASK-1003"
        )
    )

    assert result is not None
    assert result["kind"] == "write"
    assert result["reason"] == (
        "Yeni karar."
    )


def test_invalid_kind_is_rejected(
    isolated_store,
):
    with pytest.raises(ValueError):
        isolated_store.save_task_route(
            "TASK-1004",
            "unknown",
        )


def test_delete_route(
    isolated_store,
):
    isolated_store.save_task_route(
        "TASK-1005",
        "read",
    )

    isolated_store.delete_task_route(
        "TASK-1005"
    )

    assert (
        isolated_store.get_task_route(
            "TASK-1005"
        )
        is None
    )
