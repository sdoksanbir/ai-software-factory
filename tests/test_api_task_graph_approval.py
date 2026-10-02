from types import SimpleNamespace
import os

from fastapi import BackgroundTasks

import api.app as app_module


class FakeGitManager:
    def __init__(self, *, task_id="task-1001"):
        self.calls = []
        self._merged = False
        self.target_before = "target-before"
        self.task_head = "task-head"
        self.target_after = "target-after"
        self.repo_root = os.path.abspath(r"C:\repos\edusen")
        self.worktree_root = os.path.abspath(r"C:\AI-Worktrees")
        self.owned_task_id = task_id.lower()
        self.registered_branch = f"agent/{self.owned_task_id}"

    @property
    def owned_worktree_path(self):
        return os.path.abspath(
            os.path.join(
                self.worktree_root,
                os.path.basename(self.repo_root),
                self.owned_task_id,
            )
        )

    def _run_git_command(self, args, cwd=None):
        self.calls.append(("_run_git_command", tuple(args), cwd))
        if list(args[:3]) == ["worktree", "list", "--porcelain"]:
            return (
                f"worktree {self.repo_root}\n"
                "HEAD main-head\n"
                "branch refs/heads/main\n"
                "\n"
                f"worktree {self.owned_worktree_path}\n"
                "HEAD task-head\n"
                f"branch refs/heads/{self.registered_branch}\n"
            )
        raise RuntimeError(f"unexpected git command: {args}")

    def get_status(self, path):
        self.calls.append(
            ("get_status", path)
        )
        return ""

    def get_repository_status(self):
        self.calls.append(
            ("get_repository_status",)
        )
        return ""

    def get_repository_head(self):
        self.calls.append(
            ("get_repository_head",)
        )
        if self._merged:
            return self.target_after
        return self.target_before

    def get_branch_head(self, branch):
        self.calls.append(
            ("get_branch_head", branch)
        )
        return self.task_head

    def is_ancestor(
        self,
        maybe_ancestor,
        maybe_descendant,
    ):
        self.calls.append(
            (
                "is_ancestor",
                maybe_ancestor,
                maybe_descendant,
            )
        )
        if maybe_ancestor == maybe_descendant:
            return True
        return (
            maybe_ancestor == self.task_head
            and maybe_descendant
            == self.target_after
            and self._merged
        )

    def merge_branch(self, branch):
        self.calls.append(
            ("merge_branch", branch)
        )
        self._merged = True
        return self.target_after

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

    parent = app_module.TaskCreateResponse(
        task_id=parent_id,
        status="waiting_approval",
        prompt="parent",
        max_attempts=2,
        state="ready_for_approval",
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
    git_manager = FakeGitManager(task_id=parent_id)

    wt_result = SimpleNamespace(
        path=git_manager.owned_worktree_path,
        branch=git_manager.registered_branch,
    )

    app_module.TASK_CONTEXTS[
        parent_id
    ] = {
        "state_machine": state_machine,
        "wt_result": wt_result,
    }

    orchestrator = SimpleNamespace(
        git_manager=git_manager,
    )

    monkeypatch.setattr(
        app_module,
        "build_orchestrator_for_task",
        lambda _task: orchestrator,
    )

    persisted = []

    def fake_persist_task(task, **kwargs):
        persisted.append(
            (
                task.task_id,
                task.status,
                task.state,
            )
        )

    monkeypatch.setattr(
        app_module,
        "persist_task",
        fake_persist_task,
    )

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(
        app_module,
        "capture_approved_task_memory",
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
        assert persisted == [
            (
                parent_id,
                "approved",
                "approved",
            )
        ]

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
            git_manager.owned_worktree_path,
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
