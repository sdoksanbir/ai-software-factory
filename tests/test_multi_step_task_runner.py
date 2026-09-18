from types import SimpleNamespace

from factory.schemas import TaskStatus
from factory.multi_step_task_runner import (
    run_multi_step_task,
)


class FakeGitManager:
    def __init__(self, worktree_path):
        self.worktree_path = (
            str(worktree_path)
        )
        self.created = []
        self.diff_calls = []

    def create_worktree(self, task_id):
        self.created.append(task_id)

        return SimpleNamespace(
            path=self.worktree_path,
            branch=f"agent/{task_id}",
        )

    def get_diff(self, worktree_path):
        self.diff_calls.append(
            worktree_path
        )
        return "FINAL_DIFF"


class FakeOrchestrator:
    def __init__(self, worktree_path):
        self.project_path = (
            str(worktree_path)
        )
        self.git_manager = FakeGitManager(
            worktree_path
        )
        self.model_client = object()
        self.sandbox = object()

    def _validate_explicit_file_scope(
        self,
        prompt,
        changed_paths,
    ):
        return None

    def _handle_cli_approval(
        self,
        task_id,
        state_machine,
        wt_result,
        diff_output,
    ):
        return "cli-approved"


def test_multi_step_uses_one_worktree(
    tmp_path,
    monkeypatch,
):
    orchestrator = FakeOrchestrator(
        tmp_path
    )

    captured = {}

    def fake_execute(
        task_id,
        worktree_path,
        **kwargs,
    ):
        captured["task_id"] = task_id
        captured["worktree_path"] = (
            worktree_path
        )

        return {
            "status": "completed",
        }

    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "execute_task_plan",
        fake_execute,
    )

    approval = {}

    def approval_handler(
        task_id,
        state_machine,
        wt_result,
        diff_output,
    ):
        approval["task_id"] = task_id
        approval["state"] = (
            state_machine.task.status
        )
        approval["path"] = wt_result.path
        approval["diff"] = diff_output

        return "ready_for_approval"

    result = run_multi_step_task(
        orchestrator=orchestrator,
        prompt="Complex write task",
        task_id="TASK-3101",
        approval_handler=approval_handler,
        model_name="fake-model",
    )

    assert result == (
        "ready_for_approval"
    )

    assert orchestrator.git_manager.created == [
        "task-3101"
    ]

    assert captured["worktree_path"] == (
        str(tmp_path)
    )

    assert approval["path"] == (
        str(tmp_path)
    )

    assert approval["diff"] == (
        "FINAL_DIFF"
    )

    assert approval["state"] == (
        TaskStatus.READY_FOR_APPROVAL
    )


def test_executor_gets_all_handlers(
    tmp_path,
    monkeypatch,
):
    orchestrator = FakeOrchestrator(
        tmp_path
    )

    captured = {}

    def fake_execute(
        task_id,
        worktree_path,
        **kwargs,
    ):
        captured.update(kwargs)

        return {
            "status": "completed",
        }

    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "execute_task_plan",
        fake_execute,
    )

    result = run_multi_step_task(
        orchestrator=orchestrator,
        prompt="Complex write task",
        task_id="TASK-3102",
        approval_handler=(
            lambda *args: (
                "ready_for_approval"
            )
        ),
        model_name="fake-model",
    )

    assert result == (
        "ready_for_approval"
    )

    assert callable(
        captured["read_handler"]
    )

    assert callable(
        captured["write_handler"]
    )

    assert callable(
        captured["verify_handler"]
    )


def test_failure_does_not_reach_approval(
    tmp_path,
    monkeypatch,
):
    orchestrator = FakeOrchestrator(
        tmp_path
    )

    def fake_execute(*args, **kwargs):
        raise RuntimeError(
            "step failed"
        )

    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "execute_task_plan",
        fake_execute,
    )

    approval_called = []

    def approval_handler(*args):
        approval_called.append(True)
        return "unexpected"

    result = run_multi_step_task(
        orchestrator=orchestrator,
        prompt="Complex write task",
        task_id="TASK-3103",
        approval_handler=approval_handler,
    )

    assert result is None
    assert approval_called == []


def test_progress_reports_attempt(
    tmp_path,
    monkeypatch,
):
    orchestrator = FakeOrchestrator(
        tmp_path
    )

    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "execute_task_plan",
        lambda *args, **kwargs: {
            "status": "completed",
        },
    )

    events = []

    def progress_handler(
        task_id,
        **kwargs,
    ):
        events.append(kwargs)

    run_multi_step_task(
        orchestrator=orchestrator,
        prompt="Complex write task",
        task_id="TASK-3104",
        approval_handler=(
            lambda *args: (
                "ready_for_approval"
            )
        ),
        progress_handler=(
            progress_handler
        ),
    )

    assert any(
        item.get("attempt") == 1
        for item in events
    )

    assert any(
        item.get("test_result")
        == "passed"
        for item in events
    )
