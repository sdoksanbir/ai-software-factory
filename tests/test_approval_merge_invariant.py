"""Approval must not claim merge success without Git proof."""

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

import api.app as app_module
from factory.tools.git_ops import (
    GitOperationError,
    GitWorktreeManager,
)


SUCCESS_LOG = (
    "Görev onaylandı ve ana dala birleştirildi."
)
NO_CHANGE_DETAIL = (
    "Birleştirilecek yeni Git değişikliği bulunamadı."
)


class RecordingGitManager:
    def __init__(
        self,
        *,
        target_before="target-before",
        task_head="task-head",
        target_after="target-after",
        dirty="",
        missing_branch=False,
        fail_merge=False,
        fail_ancestry=False,
        raise_ancestry_error=False,
        fail_cleanup=False,
        already_in_target=False,
    ):
        self.target_before = target_before
        self.task_head = task_head
        self.target_after = target_after
        self.dirty = dirty
        self.missing_branch = missing_branch
        self.fail_merge = fail_merge
        self.fail_ancestry = fail_ancestry
        self.raise_ancestry_error = raise_ancestry_error
        self.fail_cleanup = fail_cleanup
        self.already_in_target = already_in_target

        self.calls = []
        self.merged = False
        self.committed = False
        self.cleaned_worktree = False
        self.deleted_branch = False
        self.abort_called = False

    def get_status(self, path):
        self.calls.append(("get_status", path))
        return self.dirty

    def commit_all(self, path, message):
        self.calls.append(("commit_all", path, message))
        self.committed = True
        # After committing dirty work, tip may diverge.
        if (
            self.task_head == self.target_before
            or self.already_in_target
        ):
            self.task_head = "committed-task-head"
            self.already_in_target = False
        return self.task_head

    def get_repository_head(self):
        self.calls.append(("get_repository_head",))
        if self.merged:
            return self.target_after
        return self.target_before

    def get_branch_head(self, branch):
        self.calls.append(("get_branch_head", branch))
        if self.missing_branch:
            raise GitOperationError(
                f"Branch does not exist: {branch}"
            )
        return self.task_head

    def is_ancestor(self, maybe_ancestor, maybe_descendant):
        self.calls.append(
            ("is_ancestor", maybe_ancestor, maybe_descendant)
        )
        # Equal commits are ancestors of themselves.
        if maybe_ancestor == maybe_descendant:
            return True

        # Pre-merge: task tip already contained in target.
        if (
            not self.merged
            and maybe_ancestor == self.task_head
            and maybe_descendant == self.target_before
            and self.already_in_target
        ):
            return True

        # Post-merge inspection error (after merge_branch succeeded).
        if self.merged and self.raise_ancestry_error:
            raise GitOperationError(
                "ancestry infrastructure failed"
            )

        if self.fail_ancestry:
            return False

        # Post-merge verification path.
        return (
            self.merged
            and maybe_ancestor == self.task_head
            and maybe_descendant == self.target_after
        )

    def merge_branch(self, branch):
        self.calls.append(("merge_branch", branch))
        if self.fail_merge:
            raise RuntimeError("merge conflict")
        self.merged = True
        return self.target_after

    def remove_worktree(self, path, *args, **kwargs):
        self.calls.append(("remove_worktree", path))
        if self.fail_cleanup:
            raise RuntimeError("cleanup failed")
        self.cleaned_worktree = True

    def delete_branch(self, branch, *args, **kwargs):
        self.calls.append(("delete_branch", branch))
        if self.fail_cleanup:
            raise RuntimeError("cleanup failed")
        self.deleted_branch = True

    def abort_merge(self):
        self.calls.append(("abort_merge",))
        self.abort_called = True


class FakeStateMachine:
    def __init__(self):
        self.transitions = []

    def transition(self, status):
        self.transitions.append(status)


def _prepare_approval(
    monkeypatch,
    *,
    git_manager,
    task_id="TASK-3873",
    task_kind="write",
    fail_persist=False,
):
    task = app_module.TaskCreateResponse(
        task_id=task_id,
        status="waiting_approval",
        prompt="bana statik bir HTML tasarım prototipi yap",
        max_attempts=2,
        project_id="PROJECT-4309",
        state="ready_for_approval",
        model=None,
        attempt=1,
        test_result="passed",
        started_at=None,
        task_kind=task_kind,
    )

    state_machine = FakeStateMachine()
    wt_result = SimpleNamespace(
        path=r"C:\AI-Worktrees\edusen\task-3873",
        branch="agent/task-3873",
    )

    old_tasks = dict(app_module.TASKS)
    old_contexts = dict(app_module.TASK_CONTEXTS)

    app_module.TASKS[task_id] = task
    app_module.TASK_CONTEXTS[task_id] = {
        "state_machine": state_machine,
        "wt_result": wt_result,
        "diff_output": "",
    }

    logs = []
    persisted = []

    monkeypatch.setattr(
        app_module,
        "build_orchestrator_for_task",
        lambda _task: SimpleNamespace(git_manager=git_manager),
    )

    def fake_persist_task(staged_task, **kwargs):
        if fail_persist:
            raise RuntimeError("sqlite persist failed")
        persisted.append(
            (
                staged_task.task_id,
                staged_task.status,
                staged_task.state,
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
        lambda _task_id, message: logs.append(message),
    )
    monkeypatch.setattr(
        app_module,
        "capture_approved_task_memory",
        lambda _task_id: None,
    )
    monkeypatch.setattr(
        app_module,
        "release_runnable_graph_dependents",
        lambda _task_id: [],
    )

    def restore():
        app_module.TASKS.clear()
        app_module.TASKS.update(old_tasks)
        app_module.TASK_CONTEXTS.clear()
        app_module.TASK_CONTEXTS.update(old_contexts)

    return task, state_machine, logs, restore, persisted


def test_no_change_branch_rejects_approval(monkeypatch):
    git_manager = RecordingGitManager(
        target_before="same-sha",
        task_head="same-sha",
    )
    task, state_machine, logs, restore, _persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-3873",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == NO_CHANGE_DETAIL
        assert task.state == "ready_for_approval"
        assert task.status == "waiting_approval"
        assert SUCCESS_LOG not in logs
        assert git_manager.merged is False
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
        assert ("merge_branch", "agent/task-3873") not in (
            git_manager.calls
        )
        assert (
            "is_ancestor",
            "same-sha",
            "same-sha",
        ) in git_manager.calls
    finally:
        restore()


def test_behind_target_branch_rejects_as_no_change(monkeypatch):
    """Task tip already in target history (behind) must not false-approve."""
    git_manager = RecordingGitManager(
        target_before="target-C",
        task_head="task-B",
        already_in_target=True,
    )
    task, state_machine, logs, restore, _persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-3873",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == NO_CHANGE_DETAIL
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert git_manager.merged is False
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
        assert ("merge_branch", "agent/task-3873") not in (
            git_manager.calls
        )
        assert (
            "is_ancestor",
            "task-B",
            "target-C",
        ) in git_manager.calls
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_valid_branch_ahead_approves_and_cleans(monkeypatch):
    git_manager = RecordingGitManager(
        target_before="target-before",
        task_head="task-head",
        target_after="target-after",
    )
    task, state_machine, logs, restore, _persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
    )

    try:
        result = app_module.approve_task(
            "TASK-3873",
            BackgroundTasks(),
        )

        assert result is task
        assert task.state == "approved"
        assert task.status == "approved"
        assert SUCCESS_LOG in logs
        assert git_manager.merged is True
        assert git_manager.cleaned_worktree is True
        assert git_manager.deleted_branch is True
        assert (
            app_module.TaskStatus.APPROVED
            in state_machine.transitions
        )
        assert (
            "is_ancestor",
            "task-head",
            "target-after",
        ) in git_manager.calls
    finally:
        restore()


def test_missing_task_branch_rejects_without_success(monkeypatch):
    git_manager = RecordingGitManager(missing_branch=True)
    task, state_machine, logs, restore, _persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-3873",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert "Branch does not exist" in str(exc_info.value.detail)
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
        assert git_manager.abort_called is True
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_merge_conflict_preserves_evidence(monkeypatch):
    git_manager = RecordingGitManager(fail_merge=True)
    task, state_machine, logs, restore, _persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-3873",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert "Approval merge failed" in str(exc_info.value.detail)
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
        assert git_manager.abort_called is True
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_post_merge_ancestry_failure_not_approved(monkeypatch):
    git_manager = RecordingGitManager(fail_ancestry=True)
    task, state_machine, logs, restore, persisted = (
        _prepare_approval(
            monkeypatch,
            git_manager=git_manager,
        )
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-3873",
                BackgroundTasks(),
            )

        detail = str(exc_info.value.detail)
        assert exc_info.value.status_code == 409
        assert (
            "Git merge completed but post-merge verification failed"
            in detail
        )
        assert "rolled back" not in detail
        assert "Approval merge failed" not in detail
        assert task.status == "waiting_approval"
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert persisted == []
        assert git_manager.merged is True
        assert git_manager.abort_called is False
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
        assert any(
            "Post-merge verification failed after merge command completed"
            in message
            for message in logs
        )
    finally:
        restore()


def test_post_merge_ancestry_inspection_error_preserves_evidence(
    monkeypatch,
):
    git_manager = RecordingGitManager(
        raise_ancestry_error=True,
    )
    task, state_machine, logs, restore, persisted = (
        _prepare_approval(
            monkeypatch,
            git_manager=git_manager,
        )
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-3873",
                BackgroundTasks(),
            )

        detail = str(exc_info.value.detail)
        assert exc_info.value.status_code == 409
        assert (
            "Git merge completed but post-merge verification failed"
            in detail
        )
        assert "rolled back" not in detail
        assert task.status == "waiting_approval"
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert persisted == []
        assert git_manager.merged is True
        assert git_manager.abort_called is False
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_task_3873_regression_no_false_success_log(monkeypatch):
    """WRITE with identical branch tip must never emit merge success log."""
    git_manager = RecordingGitManager(
        target_before="5e93e7d000000000000000000000000000000000",
        task_head="5e93e7d000000000000000000000000000000000",
    )
    task, _state_machine, logs, restore, _persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_kind="write",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-3873",
                BackgroundTasks(),
            )

        assert exc_info.value.detail == NO_CHANGE_DETAIL
        assert SUCCESS_LOG not in logs
        assert task.state != "approved"
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
    finally:
        restore()


def test_cleanup_failure_after_verified_merge_keeps_approved(
    monkeypatch,
):
    git_manager = RecordingGitManager(fail_cleanup=True)
    task, state_machine, logs, restore, _persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
    )

    try:
        result = app_module.approve_task(
            "TASK-3873",
            BackgroundTasks(),
        )

        assert result is task
        assert task.state == "approved"
        assert SUCCESS_LOG in logs
        assert any(
            "Approval cleanup warning" in message
            for message in logs
        )
        assert (
            app_module.TaskStatus.APPROVED
            in state_machine.transitions
        )
    finally:
        restore()


def test_db_persistence_failure_after_verified_merge(
    monkeypatch,
):
    git_manager = RecordingGitManager()
    task, state_machine, logs, restore, persisted = (
        _prepare_approval(
            monkeypatch,
            git_manager=git_manager,
            fail_persist=True,
        )
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-3873",
                BackgroundTasks(),
            )

        detail = str(exc_info.value.detail)
        assert exc_info.value.status_code == 409
        assert (
            "Git merge succeeded but approval state persistence failed"
            in detail
        )
        assert "merge was rolled back" not in detail
        assert "Approval merge failed" not in detail
        assert git_manager.merged is True
        assert git_manager.abort_called is False
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
        assert SUCCESS_LOG not in logs
        assert persisted == []
        assert task.status == "waiting_approval"
        assert task.state == "ready_for_approval"
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
        assert any(
            "Approval persistence failed after verified merge"
            in message
            for message in logs
        )
    finally:
        restore()


def test_state_machine_failure_after_db_approved_still_succeeds(
    monkeypatch,
):
    git_manager = RecordingGitManager()
    task, state_machine, logs, restore, persisted = (
        _prepare_approval(
            monkeypatch,
            git_manager=git_manager,
        )
    )

    def boom(_status):
        raise RuntimeError("transition exploded")

    state_machine.transition = boom

    try:
        result = app_module.approve_task(
            "TASK-3873",
            BackgroundTasks(),
        )

        assert result is task
        assert task.status == "approved"
        assert task.state == "approved"
        assert persisted == [
            ("TASK-3873", "approved", "approved")
        ]
        assert SUCCESS_LOG in logs
        assert any(
            "Approval state-machine synchronization warning"
            in message
            for message in logs
        )
        assert git_manager.merged is True
        assert git_manager.abort_called is False
        assert git_manager.cleaned_worktree is True
        assert git_manager.deleted_branch is True
    finally:
        restore()


def test_diverged_branch_accepts_approval(monkeypatch):
    """Diverged tips (not ancestors of each other) remain mergeable."""
    git_manager = RecordingGitManager(
        target_before="target-C",
        task_head="task-D",
        target_after="merge-CD",
        already_in_target=False,
    )
    task, state_machine, logs, restore, _persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
    )

    try:
        result = app_module.approve_task(
            "TASK-3873",
            BackgroundTasks(),
        )

        assert result is task
        assert task.state == "approved"
        assert SUCCESS_LOG in logs
        assert git_manager.merged is True
        assert (
            "is_ancestor",
            "task-D",
            "target-C",
        ) in git_manager.calls
        assert (
            "is_ancestor",
            "task-D",
            "merge-CD",
        ) in git_manager.calls
        assert (
            app_module.TaskStatus.APPROVED
            in state_machine.transitions
        )
    finally:
        restore()


def _init_git_repo(path):
    import subprocess

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
    import subprocess

    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_git_ops_ancestry_true_false_and_error(tmp_path):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    base_head = manager.get_repository_head()

    wt = manager.create_worktree("task-helper")
    assert manager.get_branch_head(wt.branch) == base_head
    assert manager.is_ancestor(base_head, base_head) is True

    (wt_root / "repo" / "task-helper" / "feature.txt").write_text(
        "feature\n",
        encoding="utf-8",
    )
    commit_hash = manager.commit_all(
        wt.path,
        "TASK-helper: change",
    )

    assert manager.is_ancestor(base_head, commit_hash) is True
    assert manager.is_ancestor(commit_hash, base_head) is False

    with pytest.raises(GitOperationError):
        manager.is_ancestor(
            "definitely-not-a-ref",
            base_head,
        )

    with pytest.raises(GitOperationError):
        manager.is_ancestor(
            base_head,
            "also-not-a-ref",
        )

    merge_hash = manager.merge_branch(wt.branch)
    assert manager.is_ancestor(commit_hash, merge_hash) is True

    # Behind-target: tip differs, but task commit is already in target.
    behind_branch = "agent/task-behind"
    manager._run_git_command(
        ["branch", behind_branch, commit_hash],
        cwd=manager.repo_root,
    )
    target_now = manager.get_repository_head()
    assert manager.get_branch_head(behind_branch) != target_now
    assert manager.is_ancestor(
        manager.get_branch_head(behind_branch),
        target_now,
    ) is True


def test_diverged_branch_real_git_merge_contains_task_tip(tmp_path):
    """
    target: A -- B -- C
    task:   A -- B -- D
    """
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    (repo / "shared.txt").write_text("A\n", encoding="utf-8")
    _git(repo, "add", "shared.txt")
    _git(repo, "commit", "-m", "A")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    wt = manager.create_worktree("task-diverged")

    # Advance main with unique commit C.
    (repo / "main-only.txt").write_text("C\n", encoding="utf-8")
    _git(repo, "add", "main-only.txt")
    _git(repo, "commit", "-m", "C")
    target_before = manager.get_repository_head()

    # Advance task branch with unique commit D.
    (wt_root / "repo" / "task-diverged" / "task-only.txt").write_text(
        "D\n",
        encoding="utf-8",
    )
    task_head = manager.commit_all(
        wt.path,
        "TASK-diverged: D",
    )

    assert task_head != target_before
    assert manager.is_ancestor(task_head, target_before) is False
    assert manager.is_ancestor(target_before, task_head) is False

    merge_hash = manager.merge_branch(wt.branch)
    assert manager.is_ancestor(task_head, merge_hash) is True
    assert (repo / "task-only.txt").read_text(encoding="utf-8") == "D\n"
    assert (repo / "main-only.txt").read_text(encoding="utf-8") == "C\n"