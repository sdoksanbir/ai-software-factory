from types import SimpleNamespace

from fastapi import BackgroundTasks

import api.app as app_module


class FakeGitManager:
    def __init__(self):
        self.calls = []

    def get_status(self, path):
        self.calls.append(
            ("get_status", path)
        )
        return ""

    def merge_branch(self, branch):
        self.calls.append(
            ("merge_branch", branch)
        )

    def remove_worktree(self, path):
        self.calls.append(
            ("remove_worktree", path)
        )

    def delete_branch(self, branch):
        self.calls.append(
            ("delete_branch", branch)
        )


class FakeStateMachine:
    def __init__(self):
        self.transitions = []

    def transition(self, status):
        self.transitions.append(
            status
        )


def test_approve_releases_blocked_dependent(
    monkeypatch,
):
    parent_id = "TASK-1001"
    child_id = "TASK-1002"

    parent = SimpleNamespace(
        task_id=parent_id,
        state="ready_for_approval",
        status="ready_for_approval",
    )

    child = SimpleNamespace(
        task_id=child_id,
        state="blocked",
        status="queued",
    )

    old_tasks = dict(
        app_module.TASKS
    )

    old_contexts = dict(
        app_module.TASK_CONTEXTS
    )

    app_module.TASKS.clear()
    app_module.TASK_CONTEXTS.clear()

    app_module.TASKS[parent_id] = parent
    app_module.TASKS[child_id] = child

    state_machine = FakeStateMachine()

    wt_result = SimpleNamespace(
        path="fake-worktree",
        branch="agent/task-1001",
    )

    app_module.TASK_CONTEXTS[
        parent_id
    ] = {
        "state_machine": state_machine,
        "wt_result": wt_result,
    }

    git_manager = FakeGitManager()

    orchestrator = SimpleNamespace(
        git_manager=git_manager,
    )

    monkeypatch.setattr(
        app_module,
        "build_orchestrator_for_task",
        lambda _task: orchestrator,
    )

    runtime_updates = []

    def fake_update_task_runtime(
        task_id,
        **kwargs,
    ):
        runtime_updates.append(
            (
                task_id,
                kwargs,
            )
        )

        task = app_module.TASKS[
            task_id
        ]

        for key, value in (
            kwargs.items()
        ):
            setattr(
                task,
                key,
                value,
            )

        return task

    monkeypatch.setattr(
        app_module,
        "update_task_runtime",
        fake_update_task_runtime,
    )

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(
        app_module,
        "release_runnable_graph_dependents",
        lambda _task_id: [
            child_id
        ],
    )

    background_tasks = BackgroundTasks()

    try:
        result = app_module.approve_task(
            parent_id,
            background_tasks,
        )

        assert result is parent

        assert parent.state == "approved"
        assert parent.status == "approved"

        assert (
            app_module.TaskStatus.APPROVED
            in state_machine.transitions
        )

        assert (
            "merge_branch",
            "agent/task-1001",
        ) in git_manager.calls

        assert (
            "remove_worktree",
            "fake-worktree",
        ) in git_manager.calls

        assert (
            "delete_branch",
            "agent/task-1001",
        ) in git_manager.calls

        assert parent_id not in (
            app_module.TASK_CONTEXTS
        )

        assert len(
            background_tasks.tasks
        ) == 1

        queued = (
            background_tasks.tasks[0]
        )

        assert (
            queued.func
            is app_module.run_task_for_api
        )

        assert queued.args == (
            child_id,
        )

    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(
            old_tasks
        )

        app_module.TASK_CONTEXTS.clear()
        app_module.TASK_CONTEXTS.update(
            old_contexts
        )
