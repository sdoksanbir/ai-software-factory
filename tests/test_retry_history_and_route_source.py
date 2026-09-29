"""Full-task retry history + route source contract."""

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

import api.app as app_module
from factory.database import (
    init_database,
    list_task_logs,
)
from factory.task_plan_store import (
    get_task_plan,
    reset_retryable_task_steps,
    save_task_plan,
    update_task_step,
)
import factory.task_route_store as route_store


@pytest.fixture
def isolated_retry_env(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    init_database(db_path)

    from factory.database import (
        append_task_log as db_append,
    )

    def append_log(task_id, message):
        app_module.TASK_LOGS.setdefault(
            task_id,
            [],
        ).append(message)
        db_append(
            task_id,
            message,
            db_path=db_path,
        )

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        append_log,
    )
    monkeypatch.setattr(
        app_module,
        "get_task_plan",
        lambda tid: get_task_plan(
            tid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        app_module,
        "reset_retryable_task_steps",
        lambda tid: reset_retryable_task_steps(
            tid,
            db_path=db_path,
        ),
    )

    monkeypatch.setattr(
        app_module,
        "persist_task",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        app_module,
        "db_delete_task_diff",
        lambda *args, **kwargs: None,
    )

    old_tasks = dict(app_module.TASKS)
    old_logs = dict(app_module.TASK_LOGS)
    old_diffs = dict(app_module.TASK_DIFFS)
    old_contexts = dict(
        app_module.TASK_CONTEXTS
    )

    app_module.TASKS.clear()
    app_module.TASK_LOGS.clear()
    app_module.TASK_DIFFS.clear()
    app_module.TASK_CONTEXTS.clear()

    try:
        yield db_path
    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(old_tasks)
        app_module.TASK_LOGS.clear()
        app_module.TASK_LOGS.update(old_logs)
        app_module.TASK_DIFFS.clear()
        app_module.TASK_DIFFS.update(
            old_diffs
        )
        app_module.TASK_CONTEXTS.clear()
        app_module.TASK_CONTEXTS.update(
            old_contexts
        )


def _failed_task(task_id: str):
    return SimpleNamespace(
        task_id=task_id,
        status="failed",
        state="failed",
        prompt="retry me",
        max_attempts=2,
        project_id=None,
        model="fake-model",
        attempt=2,
        test_result="failed",
        started_at="2026-01-01T00:00:00+00:00",
        task_kind="write",
    )


def test_full_task_retry_preserves_failure_evidence_in_logs(
    isolated_retry_env,
):
    task_id = "TASK-RETRY-HIST-1"
    db_path = isolated_retry_env

    save_task_plan(
        task_id,
        [
            {
                "title": "done",
                "instruction": "done",
                "kind": "write",
            },
            {
                "title": "verify",
                "instruction": "verify",
                "kind": "verify",
            },
        ],
        db_path=db_path,
    )

    update_task_step(
        task_id,
        1,
        status="completed",
        attempt=1,
        result="ok",
        db_path=db_path,
    )
    update_task_step(
        task_id,
        2,
        status="failed",
        attempt=2,
        error="test_failed: pytest failed",
        db_path=db_path,
    )

    app_module.TASKS[task_id] = _failed_task(
        task_id
    )
    prior = "Onceki run logu korunsun."
    app_module.TASK_LOGS[task_id] = [prior]

    from factory.database import (
        append_task_log as db_append,
    )

    db_append(
        task_id,
        prior,
        db_path=db_path,
    )

    background = BackgroundTasks()
    queued = []

    def capture_task(fn, *args, **kwargs):
        queued.append((fn, args, kwargs))

    background.add_task = capture_task

    result = app_module.retry_task(
        task_id,
        background,
    )

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert plan is not None
    assert plan["steps"][0]["status"] == (
        "completed"
    )
    assert plan["steps"][0]["attempt"] == 1
    assert plan["steps"][1]["status"] == (
        "pending"
    )
    assert plan["steps"][1]["attempt"] == 0
    assert plan["steps"][1]["error"] == ""

    logs = app_module.TASK_LOGS[task_id]
    db_logs = list_task_logs(
        task_id,
        db_path=db_path,
    )

    assert "Onceki run logu korunsun." in logs
    assert "Onceki run logu korunsun." in (
        db_logs
    )

    assert any(
        "Retry baslatildi" in message
        for message in logs
    )
    assert any(
        "step=2" in message
        and "kind=verify" in message
        and "attempt=2" in message
        and "test_failed: pytest failed"
        in message
        for message in logs
    )

    assert result.state == "queued"
    assert result.status == "queued"
    assert result.attempt == 0
    assert result.test_result is None
    assert len(queued) == 1


def test_retry_does_not_clear_prior_logs(
    isolated_retry_env,
):
    task_id = "TASK-RETRY-HIST-2"
    db_path = isolated_retry_env

    save_task_plan(
        task_id,
        [
            {
                "title": "write",
                "instruction": "write",
                "kind": "write",
                "status": "failed",
                "attempt": 1,
            }
        ],
        db_path=db_path,
    )
    update_task_step(
        task_id,
        1,
        status="failed",
        attempt=1,
        error="execution_failed: boom",
        db_path=db_path,
    )

    app_module.TASKS[task_id] = _failed_task(
        task_id
    )

    prior = "Worker basarisiz oldu."
    app_module.TASK_LOGS[task_id] = [prior]

    from factory.database import (
        append_task_log as db_append,
    )

    db_append(
        task_id,
        prior,
        db_path=db_path,
    )

    background = BackgroundTasks()
    background.add_task = (
        lambda *args, **kwargs: None
    )

    app_module.retry_task(task_id, background)

    logs = app_module.TASK_LOGS[task_id]

    assert logs[0] == prior
    assert any(
        "Retry baslatildi" in message
        for message in logs
    )
    assert any(
        "Görev yeniden sıraya alındı."
        in message
        or "yeniden" in message.casefold()
        for message in logs
    )


def test_retry_keeps_completed_steps(
    isolated_retry_env,
):
    task_id = "TASK-RETRY-HIST-3"
    db_path = isolated_retry_env

    save_task_plan(
        task_id,
        [
            {
                "title": "done",
                "instruction": "done",
                "kind": "write",
            },
            {
                "title": "failed",
                "instruction": "failed",
                "kind": "verify",
            },
        ],
        db_path=db_path,
    )
    update_task_step(
        task_id,
        1,
        status="completed",
        attempt=1,
        result="ok",
        db_path=db_path,
    )
    update_task_step(
        task_id,
        2,
        status="failed",
        attempt=2,
        error="test_failed: pytest failed",
        db_path=db_path,
    )

    app_module.TASKS[task_id] = _failed_task(
        task_id
    )
    app_module.TASK_LOGS[task_id] = []

    background = BackgroundTasks()
    background.add_task = (
        lambda *args, **kwargs: None
    )

    app_module.retry_task(task_id, background)

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert plan["steps"][0]["status"] == (
        "completed"
    )
    assert plan["steps"][0]["attempt"] == 1
    assert plan["steps"][0]["result"] == "ok"
    assert plan["steps"][1]["status"] == (
        "pending"
    )
    assert plan["steps"][1]["attempt"] == 0


@pytest.fixture
def isolated_route_store(
    tmp_path,
    monkeypatch,
):
    import sqlite3

    database_path = (
        tmp_path / "task-routes.db"
    )

    monkeypatch.setattr(
        route_store,
        "get_connection",
        lambda: sqlite3.connect(
            database_path
        ),
    )

    return route_store


def test_route_source_semantic_accepted(
    isolated_route_store,
):
    isolated_route_store.save_task_route(
        "TASK-SRC-1",
        "write",
        "ok",
        source="semantic",
    )

    record = isolated_route_store.get_task_route(
        "TASK-SRC-1"
    )

    assert record["source"] == "semantic"


def test_route_source_deterministic_fallback_accepted(
    isolated_route_store,
):
    isolated_route_store.save_task_route(
        "TASK-SRC-2",
        "read",
        "fallback",
        source="deterministic_fallback",
    )

    record = isolated_route_store.get_task_route(
        "TASK-SRC-2"
    )

    assert record["source"] == (
        "deterministic_fallback"
    )


def test_route_source_none_accepted(
    isolated_route_store,
):
    isolated_route_store.save_task_route(
        "TASK-SRC-3",
        "execute",
        "legacy",
        source=None,
    )

    record = isolated_route_store.get_task_route(
        "TASK-SRC-3"
    )

    assert record["source"] is None


def test_route_source_unknown_rejected(
    isolated_route_store,
):
    with pytest.raises(ValueError):
        isolated_route_store.save_task_route(
            "TASK-SRC-4",
            "write",
            "bad",
            source="mystery_router",
        )
