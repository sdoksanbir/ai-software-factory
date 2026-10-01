import subprocess
from types import SimpleNamespace

from factory.schemas import TaskStatus
from factory.multi_step_task_runner import (
    run_multi_step_task,
)
from factory.tools.git_ops import (
    GitWorktreeManager,
)


NO_CHANGE_MESSAGE = (
    "Görev tamamlandı ancak projede "
    "onaylanacak bir değişiklik oluşmadı."
)


class FakeGitManager:
    def __init__(
        self,
        worktree_path,
        *,
        diff="FINAL_DIFF",
    ):
        self.worktree_path = (
            str(worktree_path)
        )
        self.diff = diff
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
        return self.diff


class FakeOrchestrator:
    def __init__(
        self,
        worktree_path,
        *,
        diff="FINAL_DIFF",
        git_manager=None,
    ):
        self.project_path = (
            str(worktree_path)
        )
        self.git_manager = (
            git_manager
            if git_manager is not None
            else FakeGitManager(
                worktree_path,
                diff=diff,
            )
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


def _init_git_repo(path):
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _spy_transitions(monkeypatch):
    import factory.multi_step_task_runner as runner

    transitions = []
    real_sm_cls = runner.TaskStateMachine

    class SpyStateMachine(real_sm_cls):
        def __init__(self, task):
            super().__init__(task)
            original = self.transition

            def wrapped(to_status):
                transitions.append(to_status)
                return original(to_status)

            self.transition = wrapped

    monkeypatch.setattr(
        runner,
        "TaskStateMachine",
        SpyStateMachine,
    )
    return transitions


def _run_with_plan(
    *,
    orchestrator,
    monkeypatch,
    plan,
    task_id,
    prompt="Write task",
    approval_handler=None,
    progress_handler=None,
):
    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "execute_task_plan",
        lambda *args, **kwargs: plan,
    )

    approval_calls = []

    def tracking_handler(*args):
        approval_calls.append(args)
        return "ready_for_approval"

    handler = (
        approval_handler
        if approval_handler is not None
        else tracking_handler
    )

    events = []

    def default_progress(task_id, **kwargs):
        events.append(kwargs)

    progress = (
        progress_handler
        if progress_handler is not None
        else default_progress
    )

    result = run_multi_step_task(
        orchestrator=orchestrator,
        prompt=prompt,
        task_id=task_id,
        approval_handler=handler,
        progress_handler=progress,
    )

    return result, approval_calls, events


def test_empty_final_diff_skips_approval(
    tmp_path,
    monkeypatch,
):
    """Identical rewrite / empty net delta."""
    orchestrator = FakeOrchestrator(
        tmp_path,
        diff="",
    )
    transitions = _spy_transitions(
        monkeypatch
    )
    approval_called = []

    result, _, events = _run_with_plan(
        orchestrator=orchestrator,
        monkeypatch=monkeypatch,
        plan=_completed_plan_with_verify(),
        task_id="TASK-3870",
        approval_handler=(
            lambda *args: (
                approval_called.append(True)
                or "unexpected"
            )
        ),
    )

    assert result is None
    assert approval_called == []
    assert TaskStatus.READY_FOR_APPROVAL not in (
        transitions
    )
    assert transitions[-1] == TaskStatus.FAILED
    assert any(
        NO_CHANGE_MESSAGE in str(
            item.get("message", "")
        )
        for item in events
    )


def test_task_3873_identical_admin_html_no_approval(
    tmp_path,
    monkeypatch,
):
    """TASK-3873: admin.html already matches → empty Git diff."""
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    admin_content = (
        "<!DOCTYPE html>\n"
        "<html><body>"
        "<h1>Admin</h1>"
        "</body></html>\n"
    )
    admin = repo / "admin.html"
    admin.write_text(
        admin_content,
        encoding="utf-8",
    )
    _git(repo, "add", "admin.html")
    _git(repo, "commit", "-m", "seed admin")
    _git(repo, "branch", "-M", "main")

    real_manager = GitWorktreeManager(
        str(repo),
        str(wt_root),
    )

    class RepoAsWorktreeGitManager:
        def __init__(self):
            self.created = []
            self.diff_calls = []

        def create_worktree(self, task_id):
            self.created.append(task_id)
            return SimpleNamespace(
                path=str(repo),
                branch=f"agent/{task_id}",
            )

        def get_diff(self, worktree_path):
            self.diff_calls.append(
                worktree_path
            )
            # Identical rewrite: rewrite same bytes.
            (repo / "admin.html").write_text(
                admin_content,
                encoding="utf-8",
            )
            return real_manager.get_diff(
                worktree_path
            )

    orchestrator = FakeOrchestrator(
        repo,
        git_manager=RepoAsWorktreeGitManager(),
    )
    transitions = _spy_transitions(
        monkeypatch
    )
    approval_called = []

    result, _, events = _run_with_plan(
        orchestrator=orchestrator,
        monkeypatch=monkeypatch,
        plan=_completed_plan_with_verify(),
        task_id="TASK-3873",
        prompt=(
            "bana statik bir HTML "
            "tasarım prototipi yap"
        ),
        approval_handler=(
            lambda *args: (
                approval_called.append(True)
                or "unexpected"
            )
        ),
    )

    assert result is None
    assert approval_called == []
    assert TaskStatus.READY_FOR_APPROVAL not in (
        transitions
    )
    assert any(
        NO_CHANGE_MESSAGE in str(
            item.get("message", "")
        )
        for item in events
    )


def test_nonempty_final_diff_reaches_approval(
    tmp_path,
    monkeypatch,
):
    """Real modify with non-empty final diff."""
    orchestrator = FakeOrchestrator(
        tmp_path,
        diff="diff --git a/x b/x\n+changed",
    )

    result, approval_calls, _ = _run_with_plan(
        orchestrator=orchestrator,
        monkeypatch=monkeypatch,
        plan=_completed_plan_with_verify(),
        task_id="TASK-3874",
    )

    assert result == "ready_for_approval"
    assert len(approval_calls) == 1
    assert approval_calls[0][3] == (
        "diff --git a/x b/x\n+changed"
    )


def test_new_file_final_diff_reaches_approval(
    tmp_path,
    monkeypatch,
):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    (repo / "README.md").write_text(
        "base\n",
        encoding="utf-8",
    )
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    real_manager = GitWorktreeManager(
        str(repo),
        str(wt_root),
    )

    class NewFileGitManager:
        def __init__(self):
            self.created = []

        def create_worktree(self, task_id):
            self.created.append(task_id)
            return SimpleNamespace(
                path=str(repo),
                branch=f"agent/{task_id}",
            )

        def get_diff(self, worktree_path):
            (repo / "created.html").write_text(
                "<p>new</p>\n",
                encoding="utf-8",
            )
            return real_manager.get_diff(
                worktree_path
            )

    orchestrator = FakeOrchestrator(
        repo,
        git_manager=NewFileGitManager(),
    )

    result, approval_calls, _ = _run_with_plan(
        orchestrator=orchestrator,
        monkeypatch=monkeypatch,
        plan=_completed_plan_with_verify(),
        task_id="TASK-3875",
    )

    assert result == "ready_for_approval"
    assert len(approval_calls) == 1
    assert "created.html" in approval_calls[0][3]


def test_delete_tracked_file_reaches_approval(
    tmp_path,
    monkeypatch,
):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    victim = repo / "victim.txt"
    victim.write_text(
        "delete me\n",
        encoding="utf-8",
    )
    _git(repo, "add", "victim.txt")
    _git(repo, "commit", "-m", "track victim")
    _git(repo, "branch", "-M", "main")

    real_manager = GitWorktreeManager(
        str(repo),
        str(wt_root),
    )

    class DeleteGitManager:
        def __init__(self):
            self.created = []

        def create_worktree(self, task_id):
            self.created.append(task_id)
            return SimpleNamespace(
                path=str(repo),
                branch=f"agent/{task_id}",
            )

        def get_diff(self, worktree_path):
            victim.unlink()
            return real_manager.get_diff(
                worktree_path
            )

    orchestrator = FakeOrchestrator(
        repo,
        git_manager=DeleteGitManager(),
    )

    result, approval_calls, _ = _run_with_plan(
        orchestrator=orchestrator,
        monkeypatch=monkeypatch,
        plan=_completed_plan_with_verify(),
        task_id="TASK-3876",
    )

    assert result == "ready_for_approval"
    assert len(approval_calls) == 1
    assert approval_calls[0][3].strip() != ""
    assert "victim.txt" in approval_calls[0][3]


def test_write_then_revert_empty_final_diff(
    tmp_path,
    monkeypatch,
):
    """Multi-step net cancel-out → no approval."""
    orchestrator = FakeOrchestrator(
        tmp_path,
        diff="   \n",
    )
    transitions = _spy_transitions(
        monkeypatch
    )
    approval_called = []

    plan = {
        "status": "completed",
        "steps": [
            {
                "kind": "write",
                "status": "completed",
            },
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

    result, _, events = _run_with_plan(
        orchestrator=orchestrator,
        monkeypatch=monkeypatch,
        plan=plan,
        task_id="TASK-3877",
        approval_handler=(
            lambda *args: (
                approval_called.append(True)
                or "unexpected"
            )
        ),
    )

    assert result is None
    assert approval_called == []
    assert TaskStatus.READY_FOR_APPROVAL not in (
        transitions
    )
    assert any(
        NO_CHANGE_MESSAGE in str(
            item.get("message", "")
        )
        for item in events
    )


def test_early_noop_later_change_reaches_approval(
    tmp_path,
    monkeypatch,
):
    """Only final net delta matters."""
    orchestrator = FakeOrchestrator(
        tmp_path,
        diff=(
            "diff --git a/b.txt b/b.txt\n"
            "+later change"
        ),
    )

    plan = {
        "status": "completed",
        "steps": [
            {
                "kind": "write",
                "status": "completed",
                "note": "noop",
            },
            {
                "kind": "write",
                "status": "completed",
                "note": "real",
            },
            {
                "kind": "verify",
                "status": "completed",
            },
        ],
    }

    result, approval_calls, _ = _run_with_plan(
        orchestrator=orchestrator,
        monkeypatch=monkeypatch,
        plan=plan,
        task_id="TASK-3878",
    )

    assert result == "ready_for_approval"
    assert len(approval_calls) == 1


def test_verify_passed_empty_diff_still_fails(
    tmp_path,
    monkeypatch,
):
    """Tests alone must not bypass Git-delta gate."""
    orchestrator = FakeOrchestrator(
        tmp_path,
        diff="",
    )
    transitions = _spy_transitions(
        monkeypatch
    )
    approval_called = []

    result, _, events = _run_with_plan(
        orchestrator=orchestrator,
        monkeypatch=monkeypatch,
        plan=_completed_plan_with_verify(),
        task_id="TASK-3879",
        approval_handler=(
            lambda *args: (
                approval_called.append(True)
                or "unexpected"
            )
        ),
    )

    assert result is None
    assert approval_called == []
    assert TaskStatus.READY_FOR_APPROVAL not in (
        transitions
    )
    assert transitions[-1] == TaskStatus.FAILED
    # Verify completed in the plan, but finalization
    # still fails on empty net delta.
    assert any(
        NO_CHANGE_MESSAGE in str(
            item.get("message", "")
        )
        for item in events
    )
    assert any(
        item.get("test_result") == "failed"
        for item in events
    )
