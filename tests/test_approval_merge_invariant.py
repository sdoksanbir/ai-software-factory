"""Approval must not claim merge success without Git proof."""

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

import api.app as app_module
from factory.tools.git_ops import (
    GitLocalChangesSnapshot,
    GitOperationError,
    GitWorkingTreeGuard,
    GitWorktreeManager,
    UnsafeRollbackError,
)


SUCCESS_LOG = (
    "Görev onaylandı ve ana dala birleştirildi."
)
NO_CHANGE_DETAIL = (
    "Birleştirilecek yeni Git değişikliği bulunamadı."
)
TASK_NOT_FOUND_DETAIL = "Görev bulunamadı."
INVALID_APPROVAL_STATE_DETAIL = (
    "Görev şu anda onaylanabilir durumda değil."
)
APPROVAL_CONTEXT_UNAVAILABLE_DETAIL = (
    "Onay için gerekli görev bağlamı geri yüklenemedi."
)
PROJECT_UNAVAILABLE_DETAIL = (
    "Görevin bağlı olduğu proje kullanılamıyor."
)
LOCAL_CHANGES_PRESERVE_FAILED_DETAIL = (
    "Yerel değişiklikler güvenli şekilde korunamadığı için onay "
    "işlemi durduruldu."
)
LOCAL_CHANGES_STILL_DIRTY_DETAIL = (
    "Yerel değişiklikler güvenli şekilde ayrılamadığı için onay "
    "işlemi durduruldu."
)
MERGE_FAILED_DETAIL = (
    "Görev değişiklikleri ana dala birleştirilemedi. "
    "Görev kayıtlarını kontrol edin."
)
POST_MERGE_VERIFICATION_FAILED_DETAIL = (
    "Birleştirme tamamlandı ancak sonuç güvenli şekilde "
    "doğrulanamadı. Görev kayıtlarını kontrol edin."
)
RECOVERY_FAILED_DETAIL = (
    "Onay sırasında çakışma oluştu ve otomatik kurtarma "
    "tamamlanamadı. Görev kayıtlarını kontrol edin."
)
APPROVAL_PERSISTENCE_FAILED_DETAIL = (
    "Birleştirme tamamlandı ancak onay durumu kaydedilemedi. "
    "Görev kayıtlarını kontrol edin."
)

SECRET_PATH = r"C:\secret\repo\.git"
SECRET_BRANCH = "secret-branch"
SECRET_STDERR = "SECRET_MARKER"
SECRET_DB_PATH = r"C:\secret\factory.db"
SECRET_ROLLBACK_PATH = "SECRET_ROLLBACK_PATH"
INTERNAL_PROJECT_ID = "INTERNAL-PROJECT-ID"
SECRET_USER_REPO = r"C:\Users\secret\repo"

LEAKAGE_SENTINELS = (
    SECRET_PATH,
    SECRET_BRANCH,
    SECRET_STDERR,
    SECRET_DB_PATH,
    SECRET_ROLLBACK_PATH,
    INTERNAL_PROJECT_ID,
    SECRET_USER_REPO,
)


def _assert_no_http_leakage(detail: str, *extra_forbidden: str) -> None:
    text = str(detail)
    for marker in (*LEAKAGE_SENTINELS, *extra_forbidden):
        assert marker not in text, (
            f"HTTP detail leaked technical marker {marker!r}: {text!r}"
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
        merge_error=None,
        fail_ancestry=False,
        raise_ancestry_error=False,
        ancestry_error=None,
        fail_cleanup=False,
        already_in_target=False,
        main_dirty="",
        fail_preserve=False,
        preserve_error=None,
        fail_restore=False,
        fail_drop_snapshot=False,
        fail_reset=False,
        reset_error=None,
    ):
        self.target_before = target_before
        self.task_head = task_head
        self.target_after = target_after
        self.dirty = dirty
        self.missing_branch = missing_branch
        self.fail_merge = fail_merge
        self.merge_error = merge_error or RuntimeError("merge conflict")
        self.fail_ancestry = fail_ancestry
        self.raise_ancestry_error = raise_ancestry_error
        self.ancestry_error = ancestry_error or GitOperationError(
            "ancestry infrastructure failed"
        )
        self.fail_cleanup = fail_cleanup
        self.already_in_target = already_in_target
        self.main_dirty = main_dirty
        self.fail_preserve = fail_preserve
        self.preserve_error = preserve_error or GitOperationError(
            "stash push failed"
        )
        self.fail_restore = fail_restore
        self.fail_drop_snapshot = fail_drop_snapshot
        self.fail_reset = fail_reset
        self.reset_error = reset_error or GitOperationError(
            "unexpected HEAD"
        )

        self.calls = []
        self.merged = False
        self.committed = False
        self.cleaned_worktree = False
        self.deleted_branch = False
        self.abort_called = False
        self.preserved_snapshot = None
        self.restored_snapshot = False
        self.dropped_snapshot = False
        self.reset_to = None

    def get_status(self, path):
        self.calls.append(("get_status", path))
        return self.dirty

    def get_repository_status(self):
        self.calls.append(("get_repository_status",))
        if self.preserved_snapshot is not None and not self.restored_snapshot:
            return ""
        return self.main_dirty

    def preserve_local_changes(self, label):
        self.calls.append(("preserve_local_changes", label))
        if self.fail_preserve:
            raise self.preserve_error
        self.preserved_snapshot = GitLocalChangesSnapshot(
            commit_sha="snapshot-sha-1",
            label=label,
        )
        return self.preserved_snapshot

    def restore_local_changes(self, snapshot, *, restore_index=True):
        self.calls.append(
            ("restore_local_changes", snapshot.commit_sha, restore_index)
        )
        if self.fail_restore:
            raise GitOperationError("stash apply conflict")
        self.restored_snapshot = True

    def drop_local_changes_snapshot(self, snapshot):
        self.calls.append(
            ("drop_local_changes_snapshot", snapshot.commit_sha)
        )
        if self.fail_drop_snapshot:
            raise GitOperationError("stash drop failed")
        self.dropped_snapshot = True

    def reset_repository_to(
        self,
        commit_sha,
        *,
        expected_current_head,
        owned_paths=None,
        expected_guard=None,
        snapshot=None,
    ):
        self.calls.append(
            (
                "reset_repository_to",
                commit_sha,
                expected_current_head,
                frozenset(owned_paths or ()),
                expected_guard,
            )
        )
        if self.fail_reset:
            raise self.reset_error
        if self.get_repository_head() != expected_current_head:
            raise GitOperationError("unexpected HEAD")
        self.reset_to = commit_sha
        self.merged = False
        self.target_after = commit_sha

    def capture_working_tree_guard(self):
        self.calls.append(("capture_working_tree_guard",))
        return GitWorkingTreeGuard(
            head_sha=self.get_repository_head(),
            entries=(),
        )

    def list_snapshot_owned_paths(self, snapshot):
        self.calls.append(
            ("list_snapshot_owned_paths", snapshot.commit_sha)
        )
        return {"shared.txt"}

    def list_commit_range_paths(self, old_sha, new_sha):
        self.calls.append(
            ("list_commit_range_paths", old_sha, new_sha)
        )
        return {"task-file.txt"}

    def list_dirty_paths(self):
        self.calls.append(("list_dirty_paths",))
        return set()

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
            raise self.ancestry_error

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
            raise self.merge_error
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
    persist_error=None,
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
            raise persist_error or RuntimeError("sqlite persist failed")
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
        assert exc_info.value.detail == MERGE_FAILED_DETAIL
        _assert_no_http_leakage(
            exc_info.value.detail,
            "Branch does not exist",
            "agent/task-3873",
        )
        assert any(
            "Approval merge failed:" in message
            and "Branch does not exist" in message
            for message in logs
        )
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
        assert exc_info.value.detail == MERGE_FAILED_DETAIL
        _assert_no_http_leakage(exc_info.value.detail, "merge conflict")
        assert any(
            "Approval merge failed:" in message
            and "merge conflict" in message
            for message in logs
        )
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
        assert detail == POST_MERGE_VERIFICATION_FAILED_DETAIL
        _assert_no_http_leakage(detail, "task-head", "target-after")
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
        assert detail == POST_MERGE_VERIFICATION_FAILED_DETAIL
        _assert_no_http_leakage(
            detail,
            "ancestry infrastructure failed",
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
        assert any(
            "Post-merge verification failed after merge command completed"
            in message
            and "ancestry infrastructure failed" in message
            for message in logs
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
        assert detail == APPROVAL_PERSISTENCE_FAILED_DETAIL
        _assert_no_http_leakage(detail, "sqlite persist failed")
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
            and "sqlite persist failed" in message
            for message in logs
        )
    finally:
        restore()


def test_wrong_approval_state_user_safe_detail(monkeypatch):
    git_manager = RecordingGitManager()
    task, _sm, logs, restore, _ = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-WRONG-STATE",
    )
    task.state = "running"
    task.status = "running"

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-WRONG-STATE",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert (
            exc_info.value.detail
            == INVALID_APPROVAL_STATE_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "ready_for_approval",
            "running",
            "Task state is",
        )
        assert any(
            "expected 'ready_for_approval'" in message
            and "running" in message
            for message in logs
        )
        assert git_manager.merged is False
    finally:
        restore()


def test_missing_approval_context_user_safe_detail(monkeypatch):
    git_manager = RecordingGitManager()
    task, _sm, logs, restore, _ = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-NO-CONTEXT",
    )
    monkeypatch.setattr(
        app_module,
        "hydrate_runtime_from_database",
        lambda: None,
    )
    app_module.TASK_CONTEXTS.pop("TASK-NO-CONTEXT", None)

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-NO-CONTEXT",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert (
            exc_info.value.detail
            == APPROVAL_CONTEXT_UNAVAILABLE_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "SQLite",
            "runtime context",
            "TASK-NO-CONTEXT",
        )
        assert any(
            "SQLite" in message and "TASK-NO-CONTEXT" in message
            for message in logs
        )
        assert task.state == "ready_for_approval"
        assert git_manager.merged is False
    finally:
        restore()


def test_orchestrator_project_failure_hides_project_id(monkeypatch):
    git_manager = RecordingGitManager()
    task, _sm, logs, restore, _ = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-NO-PROJECT",
    )

    def boom(_task):
        raise KeyError(
            f"Project not found: {INTERNAL_PROJECT_ID}"
        )

    monkeypatch.setattr(
        app_module,
        "build_orchestrator_for_task",
        boom,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-NO-PROJECT",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert (
            exc_info.value.detail
            == PROJECT_UNAVAILABLE_DETAIL
        )
        _assert_no_http_leakage(exc_info.value.detail)
        assert INTERNAL_PROJECT_ID not in str(
            exc_info.value.detail
        )
        assert any(
            "Approval orchestrator unavailable:" in message
            and INTERNAL_PROJECT_ID in message
            for message in logs
        )
        assert git_manager.merged is False
    finally:
        restore()


def test_task_not_found_user_safe_detail(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "hydrate_runtime_from_database",
        lambda: None,
    )
    old_tasks = dict(app_module.TASKS)
    old_contexts = dict(app_module.TASK_CONTEXTS)
    app_module.TASKS.clear()
    app_module.TASK_CONTEXTS.clear()

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-MISSING",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == TASK_NOT_FOUND_DETAIL
        _assert_no_http_leakage(
            exc_info.value.detail,
            "TASK-MISSING",
            "SQLite",
        )
    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(old_tasks)
        app_module.TASK_CONTEXTS.clear()
        app_module.TASK_CONTEXTS.update(old_contexts)


def test_preserve_failure_hides_secret_path_and_stderr(monkeypatch):
    secret_exc = GitOperationError(
        f"{SECRET_PATH} git stash stderr {SECRET_STDERR}"
    )
    git_manager = RecordingGitManager(
        main_dirty=" D admin.html",
        fail_preserve=True,
        preserve_error=secret_exc,
    )
    task, state_machine, logs, restore, _ = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-PRESERVE-SECRET",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-PRESERVE-SECRET",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert (
            exc_info.value.detail
            == LOCAL_CHANGES_PRESERVE_FAILED_DETAIL
        )
        _assert_no_http_leakage(exc_info.value.detail)
        assert any(
            "Approval preserve local changes failed:" in message
            and SECRET_PATH in message
            and SECRET_STDERR in message
            for message in logs
        )
        assert git_manager.merged is False
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_preserve_still_dirty_user_safe_detail(monkeypatch):
    git_manager = RecordingGitManager(main_dirty=" M README.md")

    def remaining_dirty_status():
        git_manager.calls.append(("get_repository_status",))
        if git_manager.preserved_snapshot is None:
            return " M README.md"
        return " M leftover.txt"

    git_manager.get_repository_status = remaining_dirty_status
    task, state_machine, logs, restore, _ = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-STILL-DIRTY",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-STILL-DIRTY",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert (
            exc_info.value.detail
            == LOCAL_CHANGES_STILL_DIRTY_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "main repository",
            "leftover.txt",
        )
        assert git_manager.merged is False
        assert git_manager.restored_snapshot is True
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_merge_failure_hides_git_command_and_path(monkeypatch):
    merge_exc = RuntimeError(
        "Git command failed "
        f"('git merge {SECRET_BRANCH}'): {SECRET_USER_REPO}"
    )
    git_manager = RecordingGitManager(
        fail_merge=True,
        merge_error=merge_exc,
    )
    task, state_machine, logs, restore, _ = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-MERGE-SECRET",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-MERGE-SECRET",
                BackgroundTasks(),
            )

        detail = str(exc_info.value.detail)
        assert exc_info.value.status_code == 409
        assert detail == MERGE_FAILED_DETAIL
        _assert_no_http_leakage(
            detail,
            "git merge",
            r"C:\Users",
            SECRET_BRANCH,
        )
        assert any(
            "Approval merge failed:" in message
            and SECRET_BRANCH in message
            and SECRET_USER_REPO in message
            for message in logs
        )
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert git_manager.abort_called is True
        assert git_manager.cleaned_worktree is False
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_post_merge_verification_hides_sha_and_path(monkeypatch):
    ancestry_exc = GitOperationError(
        f"ancestry failed for sha SECRETSHA123 at {SECRET_PATH}"
    )
    git_manager = RecordingGitManager(
        raise_ancestry_error=True,
        ancestry_error=ancestry_exc,
    )
    task, state_machine, logs, restore, persisted = (
        _prepare_approval(
            monkeypatch,
            git_manager=git_manager,
            task_id="TASK-VERIFY-SECRET",
        )
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-VERIFY-SECRET",
                BackgroundTasks(),
            )

        detail = str(exc_info.value.detail)
        assert exc_info.value.status_code == 409
        assert detail == POST_MERGE_VERIFICATION_FAILED_DETAIL
        _assert_no_http_leakage(
            detail,
            "SECRETSHA123",
            SECRET_PATH,
        )
        assert any(
            "Post-merge verification failed after merge command completed"
            in message
            and "SECRETSHA123" in message
            and SECRET_PATH in message
            for message in logs
        )
        assert persisted == []
        assert task.state == "ready_for_approval"
        assert git_manager.cleaned_worktree is False
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_rollback_recovery_failure_hides_secret_path(monkeypatch):
    git_manager = RecordingGitManager(
        main_dirty=" M shared.txt",
        fail_restore=True,
        fail_reset=True,
        reset_error=GitOperationError(
            f"reset failed at {SECRET_ROLLBACK_PATH}"
        ),
    )
    task, state_machine, logs, restore, persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-RECOVERY-SECRET",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-RECOVERY-SECRET",
                BackgroundTasks(),
            )

        detail = str(exc_info.value.detail)
        assert exc_info.value.status_code == 409
        assert detail == RECOVERY_FAILED_DETAIL
        _assert_no_http_leakage(detail)
        assert SECRET_ROLLBACK_PATH not in detail
        assert any(
            "Transactional approval rollback failed" in message
            and SECRET_ROLLBACK_PATH in message
            for message in logs
        )
        assert persisted == []
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert git_manager.cleaned_worktree is False
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_db_persistence_failure_hides_sqlite_path(monkeypatch):
    import sqlite3

    persist_exc = sqlite3.OperationalError(
        f"unable to open database {SECRET_DB_PATH}"
    )
    git_manager = RecordingGitManager()
    task, state_machine, logs, restore, persisted = (
        _prepare_approval(
            monkeypatch,
            git_manager=git_manager,
            fail_persist=True,
            persist_error=persist_exc,
            task_id="TASK-DB-SECRET",
        )
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-DB-SECRET",
                BackgroundTasks(),
            )

        detail = str(exc_info.value.detail)
        assert exc_info.value.status_code == 409
        assert detail == APPROVAL_PERSISTENCE_FAILED_DETAIL
        _assert_no_http_leakage(
            detail,
            "factory.db",
            r"C:\secret",
            "OperationalError",
        )
        assert any(
            "Approval persistence failed after verified merge"
            in message
            and SECRET_DB_PATH in message
            for message in logs
        )
        assert persisted == []
        assert git_manager.merged is True
        assert git_manager.abort_called is False
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
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


LOCAL_CONFLICT_DETAIL = (
    "yerel kullanıcı değişiklikleri ile task değişiklikleri çakışıyor."
)
CONCURRENT_CHANGE_DETAIL = (
    "Approval sırasında repository'de yeni kullanıcı değişiklikleri "
    "algılandı; otomatik rollback veri kaybı riski nedeniyle durduruldu."
)


def _porcelain(repo):
    return _git(repo, "status", "--porcelain").stdout


def _prepare_real_approval_repo(tmp_path, task_id="task-3530"):
    """Create main repo + task worktree ready for dirty-main approval tests."""
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "admin.html").write_text("<html>admin</html>\n", encoding="utf-8")
    _git(repo, "add", "README.md", "admin.html")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    wt = manager.create_worktree(task_id)

    static_dir = wt_root / "repo" / task_id / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "index.html").write_text(
        "<html>task</html>\n",
        encoding="utf-8",
    )
    task_head = manager.commit_all(
        wt.path,
        f"{task_id}: add static/index.html",
    )

    return repo, wt_root, manager, wt, task_head


def _wire_real_approve(
    monkeypatch,
    *,
    manager,
    wt,
    task_id="TASK-3530",
):
    task, state_machine, logs, restore, persisted = _prepare_approval(
        monkeypatch,
        git_manager=manager,
        task_id=task_id,
    )
    # Point context worktree at the real worktree path/branch.
    app_module.TASK_CONTEXTS[task_id]["wt_result"] = SimpleNamespace(
        path=wt.path,
        branch=wt.branch,
    )
    return task, state_machine, logs, restore, persisted


def test_task_3530_dirty_deleted_file_approves_and_preserves_deletion(
    monkeypatch,
    tmp_path,
):
    """TASK-3530: deleted admin.html must not block merge of static/index.html."""
    repo, _wt_root, manager, wt, task_head = _prepare_real_approval_repo(
        tmp_path
    )
    target_before = manager.get_repository_head()

    # User deletes a different tracked file on main.
    (repo / "admin.html").unlink()
    assert "admin.html" in _porcelain(repo)

    task, _sm, logs, restore, _persisted = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
    )

    try:
        result = app_module.approve_task(
            "TASK-3530",
            BackgroundTasks(),
        )

        assert result is task
        assert task.state == "approved"
        assert SUCCESS_LOG in logs
        assert manager.is_ancestor(
            task_head,
            manager.get_repository_head(),
        )
        assert (repo / "static" / "index.html").is_file()
        assert not (repo / "admin.html").exists()
        status = _porcelain(repo)
        assert "admin.html" in status
        assert "D" in status

        # Task file is in HEAD tree; user deletion stayed uncommitted.
        _git(repo, "cat-file", "-e", "HEAD:static/index.html")
        _git(repo, "cat-file", "-e", "HEAD:admin.html")
        assert not manager._branch_exists(wt.branch)
        assert manager.get_repository_head() != target_before
    finally:
        restore()


def test_dirty_modified_file_preserved_across_approval(
    monkeypatch,
    tmp_path,
):
    repo, _wt_root, manager, wt, task_head = _prepare_real_approval_repo(
        tmp_path,
        task_id="task-mod",
    )
    (repo / "README.md").write_text("user edit\n", encoding="utf-8")

    task, _sm, logs, restore, _ = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
        task_id="TASK-MOD",
    )

    try:
        result = app_module.approve_task("TASK-MOD", BackgroundTasks())
        assert result.state == "approved"
        assert SUCCESS_LOG in logs
        assert manager.is_ancestor(task_head, manager.get_repository_head())
        assert (repo / "README.md").read_text(encoding="utf-8") == "user edit\n"
        assert "README.md" in _porcelain(repo)
        assert (repo / "static" / "index.html").is_file()
    finally:
        restore()


def test_dirty_untracked_file_preserved_across_approval(
    monkeypatch,
    tmp_path,
):
    repo, _wt_root, manager, wt, task_head = _prepare_real_approval_repo(
        tmp_path,
        task_id="task-untracked",
    )
    (repo / "notes.local.txt").write_text("scratch\n", encoding="utf-8")

    task, _sm, logs, restore, _ = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
        task_id="TASK-UNTRACKED",
    )

    try:
        result = app_module.approve_task(
            "TASK-UNTRACKED",
            BackgroundTasks(),
        )
        assert result.state == "approved"
        assert SUCCESS_LOG in logs
        assert manager.is_ancestor(task_head, manager.get_repository_head())
        assert (repo / "notes.local.txt").read_text(encoding="utf-8") == (
            "scratch\n"
        )
        assert "notes.local.txt" in _porcelain(repo)
    finally:
        restore()


def test_dirty_staged_change_restored_as_staged(
    monkeypatch,
    tmp_path,
):
    repo, _wt_root, manager, wt, _task_head = _prepare_real_approval_repo(
        tmp_path,
        task_id="task-staged",
    )
    (repo / "README.md").write_text("staged edit\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    assert _porcelain(repo).strip().startswith("M")

    task, _sm, logs, restore, _ = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
        task_id="TASK-STAGED",
    )

    try:
        result = app_module.approve_task("TASK-STAGED", BackgroundTasks())
        assert result.state == "approved"
        assert SUCCESS_LOG in logs
        status = _porcelain(repo)
        assert "README.md" in status
        # Staged modification appears in first column as M
        assert status.splitlines()[0].startswith("M")
        assert (repo / "README.md").read_text(encoding="utf-8") == (
            "staged edit\n"
        )
    finally:
        restore()


def test_local_vs_task_same_file_conflict_rolls_back(
    monkeypatch,
    tmp_path,
):
    repo, wt_root, manager, wt, task_head = _prepare_real_approval_repo(
        tmp_path,
        task_id="task-conflict",
    )
    target_before = manager.get_repository_head()

    # Make task modify admin.html instead of adding a new file.
    # Rebuild: amend task branch content.
    wt_admin = wt_root / "repo" / "task-conflict" / "admin.html"
    wt_admin.write_text("<html>task admin</html>\n", encoding="utf-8")
    # Also keep static from helper — remove it for a cleaner conflict case
    static_path = wt_root / "repo" / "task-conflict" / "static" / "index.html"
    if static_path.exists():
        static_path.unlink()
        try:
            static_path.parent.rmdir()
        except OSError:
            pass
    task_head = manager.commit_all(
        wt.path,
        "task-conflict: change admin.html",
    )

    # User also modifies admin.html on main.
    (repo / "admin.html").write_text("<html>user admin</html>\n", encoding="utf-8")

    task, state_machine, logs, restore, persisted = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
        task_id="TASK-CONFLICT",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-CONFLICT",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert LOCAL_CONFLICT_DETAIL in str(exc_info.value.detail)
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert persisted == []
        assert manager.get_repository_head() == target_before
        assert (repo / "admin.html").read_text(encoding="utf-8") == (
            "<html>user admin</html>\n"
        )
        assert "admin.html" in _porcelain(repo)
        assert manager._branch_exists(wt.branch)
        assert (wt_root / "repo" / "task-conflict").exists()
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
        # Task tip must not be in main history after rollback.
        assert manager.is_ancestor(
            task_head,
            manager.get_repository_head(),
        ) is False
    finally:
        restore()


def test_no_change_gate_does_not_touch_dirty_tree(
    monkeypatch,
    tmp_path,
):
    repo, _wt_root, manager, wt, _ = _prepare_real_approval_repo(
        tmp_path,
        task_id="task-nochange",
    )
    # Merge task first so tip is already in target history.
    manager.merge_branch(wt.branch)
    # Recreate a "ready" branch pointer at same tip for get_branch_head.
    # Worktree still exists; branch tip is ancestor of main.

    (repo / "admin.html").unlink()
    status_before = _porcelain(repo)
    stash_before = _git(repo, "stash", "list").stdout

    task, _sm, logs, restore, _ = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
        task_id="TASK-NOCHANGE",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-NOCHANGE",
                BackgroundTasks(),
            )

        assert exc_info.value.detail == NO_CHANGE_DETAIL
        assert SUCCESS_LOG not in logs
        assert _porcelain(repo) == status_before
        assert _git(repo, "stash", "list").stdout == stash_before
        assert not (repo / "admin.html").exists()
    finally:
        restore()


def test_preserve_failure_blocks_merge_without_touching_user_changes(
    monkeypatch,
):
    git_manager = RecordingGitManager(
        main_dirty=" D admin.html",
        fail_preserve=True,
    )
    task, state_machine, logs, restore, _ = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-PRESERVE-FAIL",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-PRESERVE-FAIL",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert (
            exc_info.value.detail
            == LOCAL_CHANGES_PRESERVE_FAILED_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "stash push failed",
        )
        assert any(
            "Approval preserve local changes failed:" in message
            and "stash push failed" in message
            for message in logs
        )
        assert ("merge_branch", "agent/task-3873") not in git_manager.calls
        # branch in context is still agent/task-3873 from helper
        assert git_manager.merged is False
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_merge_failure_restores_local_snapshot(monkeypatch):
    git_manager = RecordingGitManager(
        main_dirty=" M README.md",
        fail_merge=True,
    )
    task, _sm, logs, restore, _ = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-MERGE-FAIL-DIRTY",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-MERGE-FAIL-DIRTY",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert git_manager.abort_called is True
        assert git_manager.restored_snapshot is True
        assert git_manager.dropped_snapshot is True
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
    finally:
        restore()


def test_post_merge_ancestry_failure_restores_locals(monkeypatch):
    git_manager = RecordingGitManager(
        main_dirty=" D admin.html",
        fail_ancestry=True,
    )
    task, _sm, logs, restore, persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-ANCESTRY-DIRTY",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-ANCESTRY-DIRTY",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert git_manager.merged is True
        assert git_manager.abort_called is False
        assert git_manager.restored_snapshot is True
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
        assert SUCCESS_LOG not in logs
        assert persisted == []
        assert task.state == "ready_for_approval"
    finally:
        restore()


def test_snapshot_drop_failure_after_restore_still_approves(monkeypatch):
    git_manager = RecordingGitManager(
        main_dirty="?? notes.txt",
        fail_drop_snapshot=True,
    )
    task, state_machine, logs, restore, _ = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-DROP-FAIL",
    )

    try:
        result = app_module.approve_task(
            "TASK-DROP-FAIL",
            BackgroundTasks(),
        )

        assert result.state == "approved"
        assert SUCCESS_LOG in logs
        assert git_manager.restored_snapshot is True
        assert git_manager.reset_to is None
        assert any(
            "snapshot cleanup failed" in message
            for message in logs
        )
        assert (
            app_module.TaskStatus.APPROVED
            in state_machine.transitions
        )
    finally:
        restore()


def test_restore_conflict_rolls_back_via_recording_manager(monkeypatch):
    git_manager = RecordingGitManager(
        main_dirty=" M shared.txt",
        fail_restore=True,
    )
    # After rollback reset, restore is called again and should succeed.
    restore_calls = {"n": 0}
    original_restore = git_manager.restore_local_changes

    def conditional_restore(snapshot, *, restore_index=True):
        restore_calls["n"] += 1
        git_manager.calls.append(
            ("restore_local_changes", snapshot.commit_sha, restore_index)
        )
        if restore_calls["n"] == 1:
            raise GitOperationError("stash apply conflict")
        git_manager.restored_snapshot = True

    git_manager.restore_local_changes = conditional_restore

    task, state_machine, logs, restore, persisted = _prepare_approval(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-RESTORE-CONFLICT",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-RESTORE-CONFLICT",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert LOCAL_CONFLICT_DETAIL in str(exc_info.value.detail)
        assert git_manager.reset_to == "target-before"
        assert restore_calls["n"] == 2
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert persisted == []
        assert git_manager.cleaned_worktree is False
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
    finally:
        restore()

    assert original_restore  # keep reference used for clarity


def test_git_ops_preserve_restore_roundtrip_real_repo(tmp_path):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    # Pre-existing user stash must not be touched.
    (repo / "other.txt").write_text("other\n", encoding="utf-8")
    _git(repo, "stash", "push", "-u", "-m", "user-stash")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("u\n", encoding="utf-8")

    snapshot = manager.preserve_local_changes("factory-test-snap")
    assert isinstance(snapshot, GitLocalChangesSnapshot)
    assert snapshot.commit_sha
    assert manager.get_repository_status() == ""

    # User stash still present; factory snapshot is an additional entry.
    stash_list = _git(repo, "stash", "list").stdout
    assert "user-stash" in stash_list
    assert "factory-test-snap" in stash_list

    manager.restore_local_changes(snapshot, restore_index=True)
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "dirty\n"
    assert (repo / "untracked.txt").read_text(encoding="utf-8") == "u\n"

    manager.drop_local_changes_snapshot(snapshot)
    stash_after = _git(repo, "stash", "list").stdout
    assert "factory-test-snap" not in stash_after
    assert "user-stash" in stash_after


def test_clean_main_approval_unchanged(monkeypatch, tmp_path):
    """Clean main: existing happy-path behaviour still works end-to-end."""
    repo, _wt_root, manager, wt, task_head = _prepare_real_approval_repo(
        tmp_path,
        task_id="task-clean",
    )
    assert manager.get_repository_status() == ""

    task, _sm, logs, restore, _ = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
        task_id="TASK-CLEAN",
    )

    try:
        result = app_module.approve_task("TASK-CLEAN", BackgroundTasks())
        assert result.state == "approved"
        assert SUCCESS_LOG in logs
        assert manager.is_ancestor(task_head, manager.get_repository_head())
        assert (repo / "static" / "index.html").is_file()
        assert (repo / "admin.html").is_file()
        assert manager.get_repository_status() == ""
    finally:
        restore()


def test_preserve_post_stash_verify_failure_restores_working_tree(
    tmp_path,
    monkeypatch,
):
    """
    If stash push succeeds but post-stash verify fails, user changes must
    return to the working tree (atomic preserve UX) — not stay hidden.
    """
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))

    (repo / "tracked.txt").write_text("user-tracked\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")  # keep staged
    (repo / "tracked.txt").write_text(
        "user-tracked-unstaged\n",
        encoding="utf-8",
    )
    (repo / "untracked.txt").write_text("user-untracked\n", encoding="utf-8")

    monkeypatch.setattr(
        manager,
        "_verify_clean_after_preserve",
        lambda: "?? phantom-after-stash\n",
    )

    with pytest.raises(GitOperationError) as exc_info:
        manager.preserve_local_changes("factory-partial-preserve")

    assert "restored" in str(exc_info.value).lower()
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == (
        "user-tracked-unstaged\n"
    )
    assert (repo / "untracked.txt").read_text(encoding="utf-8") == (
        "user-untracked\n"
    )
    status = _porcelain(repo)
    assert "tracked.txt" in status
    assert "untracked.txt" in status
    # Staged index state should still show for tracked.txt (M in first col).
    assert any(
        line.startswith("M") and "tracked.txt" in line
        for line in status.splitlines()
    ) or any(
        line[0] in "MADRC" and "tracked.txt" in line
        for line in status.splitlines()
        if len(line) >= 2
    )
    stash_list = _git(repo, "stash", "list").stdout
    assert "factory-partial-preserve" not in stash_list


def test_rollback_refuses_late_untracked_concurrent_change(
    monkeypatch,
    tmp_path,
):
    """late-user-note.txt must never be deleted by approval rollback."""
    repo, wt_root, manager, wt, task_head = _prepare_real_approval_repo(
        tmp_path,
        task_id="task-late-untracked",
    )
    target_before = manager.get_repository_head()

    # Task modifies admin.html so restore of user edit conflicts.
    wt_admin = wt_root / "repo" / "task-late-untracked" / "admin.html"
    wt_admin.write_text("<html>task admin</html>\n", encoding="utf-8")
    static_path = (
        wt_root / "repo" / "task-late-untracked" / "static" / "index.html"
    )
    if static_path.exists():
        static_path.unlink()
        try:
            static_path.parent.rmdir()
        except OSError:
            pass
    task_head = manager.commit_all(
        wt.path,
        "task-late-untracked: change admin.html",
    )

    (repo / "admin.html").write_text(
        "<html>user admin</html>\n",
        encoding="utf-8",
    )

    original_restore = manager.restore_local_changes

    def restore_with_late_file(snapshot, *, restore_index=True):
        (repo / "late-user-note.txt").write_text(
            "do-not-delete\n",
            encoding="utf-8",
        )
        return original_restore(snapshot, restore_index=restore_index)

    manager.restore_local_changes = restore_with_late_file

    task, state_machine, logs, restore, persisted = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
        task_id="TASK-LATE-UNTRACKED",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-LATE-UNTRACKED",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert CONCURRENT_CHANGE_DETAIL in str(exc_info.value.detail)
        assert (repo / "late-user-note.txt").read_text(encoding="utf-8") == (
            "do-not-delete\n"
        )
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert persisted == []
        assert manager._branch_exists(wt.branch)
        assert (wt_root / "repo" / "task-late-untracked").exists()
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
        # Snapshot retained for recovery (not dropped).
        stash_list = _git(repo, "stash", "list").stdout
        assert "factory-approval-TASK-LATE-UNTRACKED" in stash_list or (
            "factory-approval" in stash_list
        )
        # Merge was not hard-reset away without safety — HEAD may still
        # include task tip; either way late file must survive.
        assert (repo / "late-user-note.txt").exists()
    finally:
        restore()

    assert target_before
    assert task_head


def test_rollback_refuses_late_tracked_concurrent_change(
    monkeypatch,
    tmp_path,
):
    """Late tracked edit outside owned paths must block destructive rollback."""
    repo, wt_root, manager, wt, task_head = _prepare_real_approval_repo(
        tmp_path,
        task_id="task-late-tracked",
    )

    wt_admin = wt_root / "repo" / "task-late-tracked" / "admin.html"
    wt_admin.write_text("<html>task admin</html>\n", encoding="utf-8")
    static_path = (
        wt_root / "repo" / "task-late-tracked" / "static" / "index.html"
    )
    if static_path.exists():
        static_path.unlink()
        try:
            static_path.parent.rmdir()
        except OSError:
            pass
    task_head = manager.commit_all(
        wt.path,
        "task-late-tracked: change admin.html",
    )

    (repo / "admin.html").write_text(
        "<html>user admin</html>\n",
        encoding="utf-8",
    )

    original_restore = manager.restore_local_changes

    def restore_with_late_tracked(snapshot, *, restore_index=True):
        # README is outside snapshot (admin.html) and merge (admin.html).
        (repo / "README.md").write_text(
            "late tracked edit\n",
            encoding="utf-8",
        )
        return original_restore(snapshot, restore_index=restore_index)

    manager.restore_local_changes = restore_with_late_tracked

    task, state_machine, logs, restore, persisted = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
        task_id="TASK-LATE-TRACKED",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-LATE-TRACKED",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert CONCURRENT_CHANGE_DETAIL in str(exc_info.value.detail)
        assert (repo / "README.md").read_text(encoding="utf-8") == (
            "late tracked edit\n"
        )
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert persisted == []
        assert manager._branch_exists(wt.branch)
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
        stash_list = _git(repo, "stash", "list").stdout
        assert "factory-approval" in stash_list
    finally:
        restore()

    assert task_head


def test_reset_repository_to_never_runs_git_clean(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    head = manager.get_repository_head()
    guard = manager.capture_working_tree_guard()

    calls = []
    original = manager._run_git_command

    def tracking_run(args, cwd=None):
        calls.append(list(args))
        return original(args, cwd=cwd)

    monkeypatch.setattr(manager, "_run_git_command", tracking_run)

    # Clean tree ownership check with empty dirty set.
    manager.reset_repository_to(
        head,
        expected_current_head=head,
        owned_paths=set(),
        expected_guard=guard,
    )
    assert not any(
        args[:2] == ["clean", "-fd"] or (
            args and args[0] == "clean"
        )
        for args in calls
    )


def test_unsafe_rollback_error_on_unowned_dirty_path(tmp_path):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    head = manager.get_repository_head()
    (repo / "late.txt").write_text("nope\n", encoding="utf-8")
    guard = manager.capture_working_tree_guard()

    with pytest.raises(UnsafeRollbackError) as exc_info:
        manager.reset_repository_to(
            head,
            expected_current_head=head,
            owned_paths=set(),
            expected_guard=guard,
        )
    assert "late.txt" in str(exc_info.value)
    assert (repo / "late.txt").read_text(encoding="utf-8") == "nope\n"


def test_same_owned_path_late_edit_blocks_rollback(
    monkeypatch,
    tmp_path,
):
    """
    Owned path admin.html edited after restore conflict must refuse reset.
    Distinct from outside-owned-path concurrent tests.
    """
    repo, wt_root, manager, wt, task_head = _prepare_real_approval_repo(
        tmp_path,
        task_id="task-owned-race",
    )

    wt_admin = wt_root / "repo" / "task-owned-race" / "admin.html"
    wt_admin.write_text("<html>task admin</html>\n", encoding="utf-8")
    static_path = (
        wt_root / "repo" / "task-owned-race" / "static" / "index.html"
    )
    if static_path.exists():
        static_path.unlink()
        try:
            static_path.parent.rmdir()
        except OSError:
            pass
    task_head = manager.commit_all(
        wt.path,
        "task-owned-race: change admin.html",
    )

    (repo / "admin.html").write_text(
        "<html>user admin</html>\n",
        encoding="utf-8",
    )

    original_reset = manager.reset_repository_to
    reset_calls = {"n": 0}

    def reset_with_same_path_race(
        commit_sha,
        *,
        expected_current_head,
        owned_paths,
        expected_guard,
        snapshot=None,
    ):
        reset_calls["n"] += 1
        # Simulate concurrent editor write on the SAME owned path after
        # guard capture in _rollback, before destructive reset body.
        (repo / "admin.html").write_text(
            "late user edit\n",
            encoding="utf-8",
        )
        return original_reset(
            commit_sha,
            expected_current_head=expected_current_head,
            owned_paths=owned_paths,
            expected_guard=expected_guard,
            snapshot=snapshot,
        )

    manager.reset_repository_to = reset_with_same_path_race

    hard_reset_seen = {"value": False}
    original_run = manager._run_git_command

    def tracking_run(args, cwd=None):
        if args[:2] == ["reset", "--hard"]:
            hard_reset_seen["value"] = True
        return original_run(args, cwd=cwd)

    monkeypatch.setattr(manager, "_run_git_command", tracking_run)

    task, state_machine, logs, restore, persisted = _wire_real_approve(
        monkeypatch,
        manager=manager,
        wt=wt,
        task_id="TASK-OWNED-RACE",
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-OWNED-RACE",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert CONCURRENT_CHANGE_DETAIL in str(exc_info.value.detail)
        assert (repo / "admin.html").read_text(encoding="utf-8") == (
            "late user edit\n"
        )
        assert hard_reset_seen["value"] is False
        assert reset_calls["n"] == 1
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
        assert persisted == []
        assert manager._branch_exists(wt.branch)
        assert (wt_root / "repo" / "task-owned-race").exists()
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
        stash_list = _git(repo, "stash", "list").stdout
        assert "factory-approval" in stash_list
    finally:
        restore()

    assert task_head


def test_preserve_finds_factory_stash_despite_intervening_user_stash(
    tmp_path,
    monkeypatch,
):
    """Factory stash identity must not assume refs/stash is ours."""
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    # Pre-existing user stash.
    (repo / "prior.txt").write_text("prior\n", encoding="utf-8")
    _git(repo, "stash", "push", "-u", "-m", "user-prior-stash")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    (repo / "tracked.txt").write_text("factory-dirty\n", encoding="utf-8")

    label = "factory-approval-TASK-STASH-A-aabbccdd0011"

    def intervening_user_stash():
        (repo / "intervening.txt").write_text(
            "race\n",
            encoding="utf-8",
        )
        manager._run_git_command(
            [
                "stash",
                "push",
                "--include-untracked",
                "-m",
                "user-intervening-stash",
            ],
            cwd=manager.repo_root,
        )

    monkeypatch.setattr(
        manager,
        "_after_stash_push_hook",
        intervening_user_stash,
    )

    snapshot = manager.preserve_local_changes(label)
    top_sha = manager._run_git_command(
        ["rev-parse", "refs/stash"],
        cwd=manager.repo_root,
    )
    assert snapshot.commit_sha != top_sha
    assert snapshot.label == label

    stash_list = _git(repo, "stash", "list").stdout
    assert "user-prior-stash" in stash_list
    assert "user-intervening-stash" in stash_list
    assert label in stash_list

    # Dropping Factory snapshot must not remove intervening user stash.
    manager.drop_local_changes_snapshot(snapshot)
    stash_after = _git(repo, "stash", "list").stdout
    assert label not in stash_after
    assert "user-intervening-stash" in stash_after
    assert "user-prior-stash" in stash_after


def test_preserve_refuses_to_claim_existing_user_refs_stash(
    tmp_path,
    monkeypatch,
):
    """If stash push creates no Factory entry, do not claim refs/stash."""
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    (repo / "user.txt").write_text("user\n", encoding="utf-8")
    _git(repo, "stash", "push", "-u", "-m", "user-only-stash")
    user_stash_sha = _git(repo, "rev-parse", "refs/stash").stdout.strip()

    manager = GitWorktreeManager(str(repo), str(wt_root))
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("u\n", encoding="utf-8")

    label = "factory-approval-TASK-STASH-B-ccddeeff1122"
    original_run = manager._run_git_command

    def no_op_factory_push(args, cwd=None):
        # Simulate stash push that reports success but creates no entry.
        if len(args) >= 2 and args[0] == "stash" and args[1] == "push":
            return ""
        return original_run(args, cwd=cwd)

    monkeypatch.setattr(manager, "_run_git_command", no_op_factory_push)

    with pytest.raises(GitOperationError) as exc_info:
        manager.preserve_local_changes(label)

    assert "Factory stash not found" in str(exc_info.value) or (
        "identify Factory stash" in str(exc_info.value)
    )
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "dirty\n"
    assert (repo / "untracked.txt").read_text(encoding="utf-8") == "u\n"
    stash_list = _git(repo, "stash", "list").stdout
    assert "user-only-stash" in stash_list
    assert label not in stash_list
    assert _git(repo, "rev-parse", "refs/stash").stdout.strip() == (
        user_stash_sha
    )


def _try_symlink(target, link_path, *, target_is_directory=False):
    """Create a symlink or skip when the platform denies privilege."""
    import os

    try:
        os.symlink(
            str(target),
            str(link_path),
            target_is_directory=target_is_directory,
        )
    except OSError as exc:
        pytest.skip(f"symlink not permitted: {exc}")


def _stash_untracked_snapshot(manager, repo, *, label, rel_path, content):
    """Create a Factory snapshot that owns an untracked file, then restore it."""
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    snapshot = manager.preserve_local_changes(label)
    # Recreate exact blob bytes from the stash untracked parent.
    blob = manager._show_blob_bytes(f"{snapshot.commit_sha}^3:{rel_path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    return snapshot


def test_validated_repo_path_preserves_leaf_symlink(tmp_path):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)
    (repo / "real.txt").write_text("real\n", encoding="utf-8")
    _git(repo, "add", "real.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    _try_symlink(repo / "real.txt", repo / "link.txt")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    validated = manager._validated_repo_path("link.txt")
    assert validated.is_symlink()
    assert validated.name == "link.txt"
    assert validated.resolve() == (repo / "real.txt").resolve()


def test_remove_verified_untracked_regular_file_still_works(tmp_path):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)
    (repo / "tracked.txt").write_text("t\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    snapshot = _stash_untracked_snapshot(
        manager,
        repo,
        label="factory-cleanup-regular",
        rel_path="notes.local.txt",
        content="scratch\n",
    )
    assert (repo / "notes.local.txt").is_file()
    manager._remove_verified_snapshot_untracked(snapshot)
    assert not (repo / "notes.local.txt").exists()


def test_remove_verified_untracked_refuses_in_repo_symlink_leaf(tmp_path):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)
    (repo / "real.txt").write_text("keep-me\n", encoding="utf-8")
    _git(repo, "add", "real.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    # Snapshot a regular untracked file, then replace on-disk path with symlink
    # to the tracked target before cleanup.
    snapshot = _stash_untracked_snapshot(
        manager,
        repo,
        label="factory-cleanup-symlink",
        rel_path="alias.txt",
        content="alias-blob\n",
    )
    (repo / "alias.txt").unlink()
    _try_symlink(repo / "real.txt", repo / "alias.txt")

    with pytest.raises(UnsafeRollbackError) as exc_info:
        manager._remove_verified_snapshot_untracked(snapshot)

    assert "symlink" in str(exc_info.value).lower()
    assert (repo / "real.txt").read_text(encoding="utf-8") == "keep-me\n"
    assert (repo / "alias.txt").is_symlink()


def test_remove_verified_untracked_refuses_external_symlink_leaf(tmp_path):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    outside = tmp_path / "outside_secret.txt"
    repo.mkdir()
    wt_root.mkdir()
    outside.write_text("secret\n", encoding="utf-8")
    _init_git_repo(repo)
    (repo / "tracked.txt").write_text("t\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    snapshot = _stash_untracked_snapshot(
        manager,
        repo,
        label="factory-cleanup-ext-symlink",
        rel_path="escape.txt",
        content="escape-blob\n",
    )
    (repo / "escape.txt").unlink()
    _try_symlink(outside, repo / "escape.txt")

    with pytest.raises(UnsafeRollbackError):
        manager._remove_verified_snapshot_untracked(snapshot)

    assert outside.read_text(encoding="utf-8") == "secret\n"
    assert (repo / "escape.txt").is_symlink()


def test_validated_repo_path_rejects_parent_symlink_escape(tmp_path):
    repo = tmp_path / "repo"
    wt_root = tmp_path / "worktrees"
    outside_dir = tmp_path / "outside_dir"
    repo.mkdir()
    wt_root.mkdir()
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("secret\n", encoding="utf-8")
    _init_git_repo(repo)
    (repo / "tracked.txt").write_text("t\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    _try_symlink(outside_dir, repo / "linkdir", target_is_directory=True)

    manager = GitWorktreeManager(str(repo), str(wt_root))
    with pytest.raises(GitOperationError) as exc_info:
        manager._validated_repo_path("linkdir/secret.txt")

    assert "escape" in str(exc_info.value).lower() or (
        "Path escapes" in str(exc_info.value)
    )
    assert (outside_dir / "secret.txt").read_text(encoding="utf-8") == (
        "secret\n"
    )