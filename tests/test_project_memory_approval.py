from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

import api.app as app_module


class FakeStateMachine:
    def __init__(self):
        self.transitions = []

    def transition(self, status):
        self.transitions.append(status)


class FakeGitManager:
    def __init__(
        self,
        *,
        fail_merge=False,
    ):
        self.fail_merge = fail_merge
        self.merged = False
        self.committed = False
        self.cleaned = False
        self._target_before = "target-before"
        self._task_head = "task-head"
        self._target_after = "merge-hash"

    def get_status(self, path):
        return "M factory/example.py"

    def commit_all(
        self,
        path,
        message,
    ):
        self.committed = True
        return "commit-hash"

    def get_repository_head(self):
        if self.merged:
            return self._target_after
        return self._target_before

    def get_branch_head(self, branch):
        return self._task_head

    def is_ancestor(
        self,
        maybe_ancestor,
        maybe_descendant,
    ):
        if maybe_ancestor == maybe_descendant:
            return True
        return (
            self.merged
            and maybe_ancestor == self._task_head
            and maybe_descendant
            == self._target_after
        )

    def merge_branch(
        self,
        branch,
    ):
        if self.fail_merge:
            raise RuntimeError(
                "merge failed"
            )

        self.merged = True
        return self._target_after

    def remove_worktree(
        self,
        path,
        *args,
        **kwargs,
    ):
        self.cleaned = True

    def delete_branch(
        self,
        branch,
        *args,
        **kwargs,
    ):
        return None

    def abort_merge(self):
        return None


def _task():
    return app_module.TaskCreateResponse(
        task_id="TASK-2451",
        status="waiting_approval",
        prompt="Implement memory.",
        max_attempts=2,
        project_id="PROJECT-2451",
        state="ready_for_approval",
        model=None,
        attempt=1,
        test_result="passed",
        started_at=None,
        task_kind=None,
    )


def _prepare(
    monkeypatch,
    *,
    fail_merge=False,
):
    task_id = "TASK-2451"
    task = _task()

    git_manager = FakeGitManager(
        fail_merge=fail_merge
    )

    state_machine = FakeStateMachine()

    app_module.TASKS[
        task_id
    ] = task

    app_module.TASK_CONTEXTS[
        task_id
    ] = {
        "state_machine": state_machine,
        "wt_result": SimpleNamespace(
            path="C:/worktree/TASK-2451",
            branch="agent/task-2451",
        ),
        "diff_output": "diff",
    }

    monkeypatch.setattr(
        app_module,
        "build_orchestrator_for_task",
        lambda _task: SimpleNamespace(
            git_manager=git_manager
        ),
    )

    monkeypatch.setattr(
        app_module,
        "release_runnable_graph_dependents",
        lambda _task_id: [],
    )

    logs = []

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda task_id, message: (
            logs.append(message)
        ),
    )

    monkeypatch.setattr(
        app_module,
        "persist_task",
        lambda *_args, **_kwargs: None,
    )

    return (
        task,
        git_manager,
        state_machine,
        logs,
    )


def test_approval_captures_memory_only_after_merge(
    monkeypatch,
):
    (
        task,
        git_manager,
        _state_machine,
        _logs,
    ) = _prepare(
        monkeypatch
    )

    captured = []

    def capture(task_id):
        assert git_manager.merged is True
        assert task.state == "approved"

        captured.append(
            task_id
        )

    monkeypatch.setattr(
        app_module,
        "capture_approved_task_memory",
        capture,
    )

    app_module.approve_task(
        "TASK-2451",
        BackgroundTasks(),
    )

    assert captured == [
        "TASK-2451"
    ]

    assert task.state == "approved"


def test_failed_merge_does_not_capture_memory(
    monkeypatch,
):
    (
        task,
        _git_manager,
        _state_machine,
        _logs,
    ) = _prepare(
        monkeypatch,
        fail_merge=True,
    )

    captured = []

    monkeypatch.setattr(
        app_module,
        "capture_approved_task_memory",
        lambda task_id: (
            captured.append(task_id)
        ),
    )

    with pytest.raises(
        HTTPException,
    ) as exc_info:
        app_module.approve_task(
            "TASK-2451",
            BackgroundTasks(),
        )

    assert (
        exc_info.value.status_code
        == 409
    )

    assert captured == []

    assert (
        task.state
        == "ready_for_approval"
    )


def test_memory_failure_does_not_undo_approval(
    monkeypatch,
):
    (
        task,
        git_manager,
        _state_machine,
        logs,
    ) = _prepare(
        monkeypatch
    )

    def fail_capture(task_id):
        raise RuntimeError(
            "memory db unavailable"
        )

    monkeypatch.setattr(
        app_module,
        "capture_approved_task_memory",
        fail_capture,
    )

    app_module.approve_task(
        "TASK-2451",
        BackgroundTasks(),
    )

    assert git_manager.merged is True
    assert task.state == "approved"

    assert any(
        "memory capture failed"
        in message.lower()
        for message in logs
    )
