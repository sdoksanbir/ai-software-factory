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


def _completed_plan_with_verify():
    return {
        "status": "completed",
        "steps": [
            {
                "kind": "write",
                "status": "completed",
            },
            {
                "kind": "verify",
                "status": "completed",
            },
        ],
    }


def _completed_plan_without_verify():
    return {
        "status": "completed",
        "steps": [
            {
                "kind": "write",
                "status": "completed",
            },
        ],
    }


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

        return _completed_plan_with_verify()

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

        return _completed_plan_with_verify()

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
        lambda *args, **kwargs: (
            _completed_plan_with_verify()
        ),
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


def test_success_skips_fake_patch_test_states(
    tmp_path,
    monkeypatch,
):
    orchestrator = FakeOrchestrator(
        tmp_path
    )

    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "execute_task_plan",
        lambda *args, **kwargs: (
            _completed_plan_with_verify()
        ),
    )

    seen = []

    def approval_handler(
        task_id,
        state_machine,
        wt_result,
        diff_output,
    ):
        seen.append(
            state_machine.task.status
        )
        return "ready_for_approval"

    original_transition = None

    transitions = []

    def install_spy(sm):
        nonlocal original_transition
        original_transition = sm.transition

        def spy(to_status):
            transitions.append(to_status)
            return original_transition(
                to_status
            )

        sm.transition = spy
        return sm

    real_sm_cls = None

    import factory.multi_step_task_runner as runner

    real_sm_cls = runner.TaskStateMachine

    class SpyStateMachine(real_sm_cls):
        def __init__(self, task):
            super().__init__(task)
            install_spy(self)

    monkeypatch.setattr(
        runner,
        "TaskStateMachine",
        SpyStateMachine,
    )

    result = run_multi_step_task(
        orchestrator=orchestrator,
        prompt="Complex write task",
        task_id="TASK-3105",
        approval_handler=approval_handler,
    )

    assert result == "ready_for_approval"
    assert seen == [
        TaskStatus.READY_FOR_APPROVAL
    ]

    fake_states = {
        TaskStatus.CONTEXT_BUILDING,
        TaskStatus.CONTEXT_READY,
        TaskStatus.PATCH_VALIDATING,
        TaskStatus.PATCH_READY,
        TaskStatus.PATCH_APPLIED,
        TaskStatus.TESTING,
        TaskStatus.TEST_PASSED,
    }

    assert fake_states.isdisjoint(
        set(transitions)
    )

    assert transitions == [
        TaskStatus.WORKTREE_CREATING,
        TaskStatus.WORKTREE_READY,
        TaskStatus.MODEL_RUNNING,
        TaskStatus.MODEL_COMPLETED,
        TaskStatus.READY_FOR_APPROVAL,
    ]


def test_no_verify_does_not_claim_passed(
    tmp_path,
    monkeypatch,
):
    orchestrator = FakeOrchestrator(
        tmp_path
    )

    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "execute_task_plan",
        lambda *args, **kwargs: (
            _completed_plan_without_verify()
        ),
    )

    events = []

    run_multi_step_task(
        orchestrator=orchestrator,
        prompt="Write without verify",
        task_id="TASK-3106",
        approval_handler=(
            lambda *args: (
                "ready_for_approval"
            )
        ),
        progress_handler=(
            lambda task_id, **kwargs: (
                events.append(kwargs)
            )
        ),
    )

    completion_events = [
        item
        for item in events
        if "test_result" in item
        and item.get("message", "").startswith(
            "Multi-step gorev tamamlandi"
        )
    ]

    assert completion_events
    assert completion_events[-1][
        "test_result"
    ] == "not_required"

    assert not any(
        item.get("test_result")
        == "passed"
        for item in events
    )


def test_failure_reports_failed_not_passed(
    tmp_path,
    monkeypatch,
):
    orchestrator = FakeOrchestrator(
        tmp_path
    )

    def fake_execute(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "execute_task_plan",
        fake_execute,
    )

    events = []
    final_state = {}

    def capture_transition(sm):
        original = sm.transition

        def wrapped(to_status):
            final_state["status"] = to_status
            return original(to_status)

        sm.transition = wrapped

    import factory.multi_step_task_runner as runner

    real_sm_cls = runner.TaskStateMachine

    class SpyStateMachine(real_sm_cls):
        def __init__(self, task):
            super().__init__(task)
            capture_transition(self)

    monkeypatch.setattr(
        runner,
        "TaskStateMachine",
        SpyStateMachine,
    )

    result = run_multi_step_task(
        orchestrator=orchestrator,
        prompt="Failing plan",
        task_id="TASK-3107",
        approval_handler=(
            lambda *args: "unexpected"
        ),
        progress_handler=(
            lambda task_id, **kwargs: (
                events.append(kwargs)
            )
        ),
    )

    assert result is None
    assert final_state["status"] == (
        TaskStatus.FAILED
    )
    assert any(
        item.get("test_result")
        == "failed"
        for item in events
    )
    assert not any(
        item.get("test_result")
        == "passed"
        for item in events
    )


def test_resume_worktree_skips_create(
    tmp_path,
    monkeypatch,
):
    worktree = tmp_path / "existing"
    worktree.mkdir()

    orchestrator = FakeOrchestrator(
        tmp_path
    )

    captured = {}

    def fake_execute(
        task_id,
        worktree_path,
        **kwargs,
    ):
        captured["worktree_path"] = (
            worktree_path
        )
        return _completed_plan_with_verify()

    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "execute_task_plan",
        fake_execute,
    )

    result = run_multi_step_task(
        orchestrator=orchestrator,
        prompt="Resume task",
        task_id="TASK-3108",
        approval_handler=(
            lambda *args: (
                "ready_for_approval"
            )
        ),
        resume_worktree_path=str(
            worktree
        ),
        resume_branch="agent/task-3108",
    )

    assert result == "ready_for_approval"
    assert (
        orchestrator.git_manager.created
        == []
    )
    assert captured["worktree_path"] == (
        str(worktree)
    )
