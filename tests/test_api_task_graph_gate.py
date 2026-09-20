from types import SimpleNamespace

import api.app as app_module


def _fake_task():
    return SimpleNamespace(
        task_id="TASK-1002",
        prompt="test task",
        status="queued",
        state="queued",
    )


def test_api_runner_stops_blocked_graph_task(
    monkeypatch,
):
    task_id = "TASK-1002"

    old_tasks = dict(
        app_module.TASKS
    )

    app_module.TASKS.clear()
    app_module.TASKS[
        task_id
    ] = _fake_task()

    updates = []
    logs = []

    monkeypatch.setattr(
        app_module,
        "evaluate_task_execution_gate",
        lambda *_args, **_kwargs: {
            "task_id": task_id,
            "allowed": False,
            "state": "blocked",
            "graph_ids": ["GRAPH-1"],
            "blocked_graphs": ["GRAPH-1"],
            "failed_graphs": [],
            "pending_dependencies": [
                "TASK-1001"
            ],
            "failed_dependencies": [],
        },
    )

    monkeypatch.setattr(
        app_module,
        "update_task_runtime",
        lambda task_id, **kwargs: (
            updates.append(
                (
                    task_id,
                    kwargs,
                )
            )
        ),
    )

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda task_id, message: (
            logs.append(
                (
                    task_id,
                    message,
                )
            )
        ),
    )

    def fail_if_routed(*_args, **_kwargs):
        raise AssertionError(
            "Task Router must not run "
            "for blocked graph task"
        )

    monkeypatch.setattr(
        app_module,
        "route_task",
        fail_if_routed,
    )

    try:
        result = (
            app_module.run_task_for_api(
                task_id
            )
        )

        assert result is None

        assert updates == [
            (
                task_id,
                {
                    "status": "queued",
                    "state": "blocked",
                },
            )
        ]

        assert logs

        assert (
            "TASK-1001"
            in logs[0][1]
        )

    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(
            old_tasks
        )


def test_api_runner_stops_failure_blocked_task(
    monkeypatch,
):
    task_id = "TASK-1002"

    old_tasks = dict(
        app_module.TASKS
    )

    app_module.TASKS.clear()
    app_module.TASKS[
        task_id
    ] = _fake_task()

    updates = []
    logs = []

    monkeypatch.setattr(
        app_module,
        "evaluate_task_execution_gate",
        lambda *_args, **_kwargs: {
            "task_id": task_id,
            "allowed": False,
            "state": "failed",
            "graph_ids": ["GRAPH-1"],
            "blocked_graphs": [],
            "failed_graphs": ["GRAPH-1"],
            "pending_dependencies": [],
            "failed_dependencies": [
                "TASK-1001"
            ],
        },
    )

    monkeypatch.setattr(
        app_module,
        "update_task_runtime",
        lambda task_id, **kwargs: (
            updates.append(
                (
                    task_id,
                    kwargs,
                )
            )
        ),
    )

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda task_id, message: (
            logs.append(
                (
                    task_id,
                    message,
                )
            )
        ),
    )

    def fail_if_routed(*_args, **_kwargs):
        raise AssertionError(
            "Task Router must not run "
            "after dependency failure"
        )

    monkeypatch.setattr(
        app_module,
        "route_task",
        fail_if_routed,
    )

    try:
        result = (
            app_module.run_task_for_api(
                task_id
            )
        )

        assert result is None

        assert updates == [
            (
                task_id,
                {
                    "status": "failed",
                    "state": "failed",
                },
            )
        ]

        assert logs

        assert (
            "TASK-1001"
            in logs[0][1]
        )

    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(
            old_tasks
        )
