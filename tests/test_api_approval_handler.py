from types import SimpleNamespace

import api.app as app_module


def _prepare_approval_task(
    monkeypatch,
    *,
    task_id,
    test_result,
):
    task = SimpleNamespace(
        task_id=task_id,
        status="running",
        state="running",
        prompt="Write something",
        max_attempts=2,
        project_id=None,
        model=None,
        attempt=1,
        test_result=test_result,
        started_at=None,
        task_kind="write",
    )

    app_module.TASKS[task_id] = task

    monkeypatch.setattr(
        app_module,
        "db_save_task_diff",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        app_module,
        "persist_task",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda *args, **kwargs: None,
    )

    return task


def test_api_approval_handler_preserves_not_required(
    monkeypatch,
):
    task_id = "TASK-3901"
    task = _prepare_approval_task(
        monkeypatch,
        task_id=task_id,
        test_result="not_required",
    )

    result = app_module.api_approval_handler(
        task_id,
        state_machine=object(),
        wt_result=SimpleNamespace(
            path="fake-worktree",
            branch="agent/task-3901",
        ),
        diff_output="DIFF",
    )

    assert result == "ready_for_approval"
    assert task.status == (
        "waiting_approval"
    )
    assert task.state == (
        "ready_for_approval"
    )
    assert task.test_result == (
        "not_required"
    )


def test_api_approval_handler_preserves_passed(
    monkeypatch,
):
    task_id = "TASK-3902"
    task = _prepare_approval_task(
        monkeypatch,
        task_id=task_id,
        test_result="passed",
    )

    result = app_module.api_approval_handler(
        task_id,
        state_machine=object(),
        wt_result=SimpleNamespace(
            path="fake-worktree",
            branch="agent/task-3902",
        ),
        diff_output="DIFF",
    )

    assert result == "ready_for_approval"
    assert task.status == (
        "waiting_approval"
    )
    assert task.state == (
        "ready_for_approval"
    )
    assert task.test_result == "passed"
