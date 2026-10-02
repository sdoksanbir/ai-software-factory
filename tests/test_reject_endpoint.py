"""Reject endpoint: persist-first decision, best-effort cleanup."""

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.app as app_module
from factory.tools.git_ops import GitOperationError


SUCCESS_LOG = "Görev reddedildi."
TASK_NOT_FOUND_DETAIL = "Görev bulunamadı."
INVALID_REJECTION_STATE_DETAIL = (
    "Görev şu anda reddedilebilir durumda değil."
)
REJECTION_CONTEXT_UNAVAILABLE_DETAIL = (
    "Reddetme için gerekli görev bağlamı geri yüklenemedi."
)
PROJECT_UNAVAILABLE_DETAIL = (
    "Görevin bağlı olduğu proje kullanılamıyor."
)
REJECTION_PERSISTENCE_FAILED_DETAIL = (
    "Reddetme durumu kaydedilemedi. "
    "Görev kayıtlarını kontrol edin."
)

SECRET_PATH = r"C:\SECRET_PATH"
SECRET_STDERR = "SECRET_STDERR"
SECRET_BRANCH = "SECRET_BRANCH"
SECRET_DB_PATH = r"C:\SECRET_DB_PATH"
SECRET_SQL_ERROR = "SECRET_SQL_ERROR"
INTERNAL_PROJECT_ID = "INTERNAL-PROJECT-ID"
INTERNAL_STATE_MACHINE_SECRET = (
    "INTERNAL_STATE_MACHINE_SECRET"
)

LEAKAGE_SENTINELS = (
    SECRET_PATH,
    SECRET_STDERR,
    SECRET_BRANCH,
    SECRET_DB_PATH,
    SECRET_SQL_ERROR,
    INTERNAL_PROJECT_ID,
    INTERNAL_STATE_MACHINE_SECRET,
)


def _cleanup_calls(git_manager):
    return [
        call
        for call in git_manager.calls
        if call and call[0] in (
            "remove_worktree",
            "delete_branch",
        )
    ]


def _assert_no_http_leakage(
    detail: str,
    *extra_forbidden: str,
) -> None:
    text = str(detail)
    for marker in (*LEAKAGE_SENTINELS, *extra_forbidden):
        assert marker not in text, (
            f"HTTP detail leaked technical marker "
            f"{marker!r}: {text!r}"
        )


class RecordingGitManager:
    def __init__(
        self,
        *,
        fail_remove_worktree=False,
        remove_error=None,
        fail_delete_branch=False,
        delete_error=None,
        worktree_exists=True,
        branch_exists=True,
        repo_root=r"C:\repos\demo",
        worktree_root=r"C:\AI-Worktrees",
        owned_task_id="task-reject",
        registered_branch=None,
        omit_worktree_registration=False,
    ):
        self.calls = []
        self.fail_remove_worktree = fail_remove_worktree
        self.remove_error = remove_error
        self.fail_delete_branch = fail_delete_branch
        self.delete_error = delete_error
        self.worktree_exists = worktree_exists
        self.branch_exists = branch_exists
        self.cleaned_worktree = False
        self.deleted_branch = False
        self.repo_root = os.path.abspath(repo_root)
        self.worktree_root = os.path.abspath(worktree_root)
        self.owned_task_id = owned_task_id
        self.registered_branch = (
            registered_branch
            if registered_branch is not None
            else f"agent/{owned_task_id}"
        )
        self.omit_worktree_registration = omit_worktree_registration
        self._explicit_registered_branch = (
            registered_branch is not None
        )

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
            if self.omit_worktree_registration:
                return (
                    f"worktree {self.repo_root}\n"
                    "HEAD main-head\n"
                    "branch refs/heads/main\n"
                )
            return (
                f"worktree {self.repo_root}\n"
                "HEAD main-head\n"
                "branch refs/heads/main\n"
                "\n"
                f"worktree {self.owned_worktree_path}\n"
                "HEAD task-head\n"
                f"branch refs/heads/{self.registered_branch}\n"
            )
        raise GitOperationError(f"unexpected git command: {args}")

    def remove_worktree(self, path, *args, **kwargs):
        self.calls.append(
            ("remove_worktree", path, kwargs.get("force"))
        )
        if not self.worktree_exists:
            raise self.remove_error or GitOperationError(
                f"Git command failed ("
                f"'git worktree remove --force {path}'"
                f"): is not a working tree"
            )
        if self.fail_remove_worktree:
            raise self.remove_error or RuntimeError(
                "cleanup failed"
            )
        self.worktree_exists = False
        self.cleaned_worktree = True

    def delete_branch(self, branch, *args, **kwargs):
        self.calls.append(
            ("delete_branch", branch, kwargs.get("force"))
        )
        if not self.branch_exists:
            # Real delete_branch is missing-ok.
            return
        if self.fail_delete_branch:
            raise self.delete_error or RuntimeError(
                "cleanup failed"
            )
        self.branch_exists = False
        self.deleted_branch = True


class FakeStateMachine:
    def __init__(self, *, fail_transition=False, error=None):
        self.transitions = []
        self.fail_transition = fail_transition
        self.error = error

    def transition(self, status):
        if self.fail_transition:
            raise self.error or RuntimeError(
                "state machine failed"
            )
        self.transitions.append(status)


def _prepare_reject(
    monkeypatch,
    *,
    git_manager,
    task_id="TASK-REJECT",
    state_machine=None,
    fail_persist=False,
    persist_error=None,
    wt_path=None,
    wt_branch=None,
):
    task = app_module.TaskCreateResponse(
        task_id=task_id,
        status="waiting_approval",
        prompt="reject hardening fixture",
        max_attempts=2,
        project_id="PROJECT-REJECT",
        state="ready_for_approval",
        model=None,
        attempt=1,
        test_result="passed",
        started_at=None,
        task_kind="write",
    )

    if state_machine is None:
        state_machine = FakeStateMachine()

    clean_id = task_id.lower()
    if hasattr(git_manager, "owned_task_id"):
        git_manager.owned_task_id = clean_id
        if not getattr(
            git_manager,
            "_explicit_registered_branch",
            False,
        ):
            git_manager.registered_branch = f"agent/{clean_id}"
    expected_path = (
        git_manager.owned_worktree_path
        if hasattr(git_manager, "owned_worktree_path")
        else os.path.abspath(
            os.path.join(
                r"C:\AI-Worktrees",
                "demo",
                clean_id,
            )
        )
    )
    expected_branch = f"agent/{clean_id}"
    wt_result = SimpleNamespace(
        path=wt_path if wt_path is not None else expected_path,
        branch=(
            wt_branch
            if wt_branch is not None
            else expected_branch
        ),
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
    persist_order = []

    monkeypatch.setattr(
        app_module,
        "build_orchestrator_for_task",
        lambda _task: SimpleNamespace(
            git_manager=git_manager
        ),
    )

    def fake_persist_task(staged_task, **kwargs):
        persist_order.append(
            (
                "persist",
                staged_task.task_id,
                staged_task.status,
                staged_task.state,
                app_module.TASKS[task_id].state,
            )
        )
        if fail_persist:
            raise persist_error or RuntimeError(
                "persist failed"
            )
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

    def restore():
        app_module.TASKS.clear()
        app_module.TASKS.update(old_tasks)
        app_module.TASK_CONTEXTS.clear()
        app_module.TASK_CONTEXTS.update(old_contexts)

    return (
        task,
        state_machine,
        wt_result,
        logs,
        restore,
        persisted,
        persist_order,
    )


def test_success_reject(monkeypatch):
    git_manager = RecordingGitManager()
    (
        task,
        state_machine,
        wt_result,
        logs,
        restore,
        persisted,
        persist_order,
    ) = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-REJECT-OK",
    )

    try:
        result = app_module.reject_task("TASK-REJECT-OK")

        assert result.task_id == "TASK-REJECT-OK"
        assert result.state == "rejected"
        assert result.status == "rejected"
        assert task.state == "rejected"
        assert task.status == "rejected"
        assert "TASK-REJECT-OK" not in app_module.TASK_CONTEXTS
        assert SUCCESS_LOG in logs
        assert app_module.TaskStatus.REJECTED in (
            state_machine.transitions
        )
        assert git_manager.cleaned_worktree is True
        assert git_manager.deleted_branch is True
        assert _cleanup_calls(git_manager) == [
            ("remove_worktree", wt_result.path, True),
            ("delete_branch", wt_result.branch, True),
        ]
        assert ("TASK-REJECT-OK", "rejected", "rejected") in (
            persisted
        )
        assert persist_order[0][0] == "persist"
        assert persist_order[0][4] == "ready_for_approval"
    finally:
        restore()


def test_worktree_cleanup_failure_still_rejects(
    monkeypatch,
):
    secret_exc = GitOperationError(
        "Git command failed ("
        f"'git worktree remove --force {SECRET_PATH}'"
        f"): {SECRET_STDERR}"
    )
    git_manager = RecordingGitManager(
        fail_remove_worktree=True,
        remove_error=secret_exc,
    )
    (
        task,
        state_machine,
        wt_result,
        logs,
        restore,
        persisted,
        _,
    ) = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-WT-FAIL",
    )

    try:
        result = app_module.reject_task("TASK-WT-FAIL")

        assert result.state == "rejected"
        assert task.state == "rejected"
        assert ("TASK-WT-FAIL", "rejected", "rejected") in (
            persisted
        )
        assert "TASK-WT-FAIL" not in app_module.TASK_CONTEXTS
        assert app_module.TaskStatus.REJECTED in (
            state_machine.transitions
        )
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is True
        assert _cleanup_calls(git_manager) == [
            ("remove_worktree", wt_result.path, True),
            ("delete_branch", wt_result.branch, True),
        ]
        assert any(
            "Reject cleanup warning: worktree cleanup failed:"
            in message
            and SECRET_PATH in message
            and SECRET_STDERR in message
            for message in logs
        )
        assert SUCCESS_LOG in logs
    finally:
        restore()


def test_branch_cleanup_failure_still_rejects(
    monkeypatch,
):
    secret_exc = GitOperationError(
        "Git command failed ("
        f"'git branch -D {SECRET_BRANCH}'"
        f"): {SECRET_STDERR}"
    )
    git_manager = RecordingGitManager(
        fail_delete_branch=True,
        delete_error=secret_exc,
    )
    (
        task,
        state_machine,
        wt_result,
        logs,
        restore,
        persisted,
        _,
    ) = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-BRANCH-FAIL",
    )

    try:
        result = app_module.reject_task("TASK-BRANCH-FAIL")

        assert result.state == "rejected"
        assert task.state == "rejected"
        assert ("TASK-BRANCH-FAIL", "rejected", "rejected") in (
            persisted
        )
        assert "TASK-BRANCH-FAIL" not in (
            app_module.TASK_CONTEXTS
        )
        assert git_manager.cleaned_worktree is True
        assert git_manager.deleted_branch is False
        assert git_manager.worktree_exists is False
        assert git_manager.branch_exists is True
        assert any(
            "Reject cleanup warning: branch cleanup failed:"
            in message
            and SECRET_BRANCH in message
            for message in logs
        )
        assert SUCCESS_LOG in logs
        assert app_module.TaskStatus.REJECTED in (
            state_machine.transitions
        )
    finally:
        restore()


def test_both_cleanup_failures_still_rejects(monkeypatch):
    git_manager = RecordingGitManager(
        fail_remove_worktree=True,
        remove_error=GitOperationError("wt boom"),
        fail_delete_branch=True,
        delete_error=GitOperationError("branch boom"),
    )
    (
        task,
        _sm,
        wt_result,
        logs,
        restore,
        persisted,
        _,
    ) = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-BOTH-CLEANUP-FAIL",
    )

    try:
        result = app_module.reject_task(
            "TASK-BOTH-CLEANUP-FAIL"
        )

        assert result.state == "rejected"
        assert task.state == "rejected"
        assert (
            "TASK-BOTH-CLEANUP-FAIL",
            "rejected",
            "rejected",
        ) in persisted
        assert _cleanup_calls(git_manager) == [
            ("remove_worktree", wt_result.path, True),
            ("delete_branch", wt_result.branch, True),
        ]
        assert any(
            "Reject cleanup warning: worktree cleanup failed:"
            in message
            for message in logs
        )
        assert any(
            "Reject cleanup warning: branch cleanup failed:"
            in message
            for message in logs
        )
        assert SUCCESS_LOG in logs
    finally:
        restore()


def test_state_machine_failure_still_rejects(monkeypatch):
    git_manager = RecordingGitManager()
    state_machine = FakeStateMachine(
        fail_transition=True,
        error=RuntimeError(INTERNAL_STATE_MACHINE_SECRET),
    )
    (
        task,
        _sm,
        _wt,
        logs,
        restore,
        persisted,
        _,
    ) = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-SM-FAIL",
        state_machine=state_machine,
    )

    try:
        result = app_module.reject_task("TASK-SM-FAIL")

        assert result.state == "rejected"
        assert task.state == "rejected"
        assert ("TASK-SM-FAIL", "rejected", "rejected") in (
            persisted
        )
        assert "TASK-SM-FAIL" not in app_module.TASK_CONTEXTS
        assert git_manager.cleaned_worktree is True
        assert git_manager.deleted_branch is True
        assert any(
            "Reject state-machine synchronization failed:"
            in message
            and INTERNAL_STATE_MACHINE_SECRET in message
            for message in logs
        )
        assert SUCCESS_LOG in logs
    finally:
        restore()


def test_db_persistence_failure_preserves_evidence(
    monkeypatch,
):
    persist_error = RuntimeError(
        f"sqlite write failed path={SECRET_DB_PATH} "
        f"err={SECRET_SQL_ERROR}"
    )
    git_manager = RecordingGitManager()
    (
        task,
        state_machine,
        _wt,
        logs,
        restore,
        persisted,
        _,
    ) = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-PERSIST-FAIL",
        fail_persist=True,
        persist_error=persist_error,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.reject_task("TASK-PERSIST-FAIL")

        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail
            == REJECTION_PERSISTENCE_FAILED_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "sqlite",
            "persistence",
            "Task rejection",
        )
        assert task.state == "ready_for_approval"
        assert task.status == "waiting_approval"
        assert "TASK-PERSIST-FAIL" in app_module.TASK_CONTEXTS
        assert persisted == []
        assert git_manager.calls == []
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
        assert state_machine.transitions == []
        assert SUCCESS_LOG not in logs
        assert any(
            "Task rejection persistence failed:" in message
            and SECRET_DB_PATH in message
            and SECRET_SQL_ERROR in message
            for message in logs
        )
    finally:
        restore()


def test_memory_publish_only_after_db_persist(monkeypatch):
    live_states_at_persist = []

    git_manager = RecordingGitManager()
    task, _sm, _wt, _logs, restore, _, _ = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-PUBLISH-ORDER",
    )

    def tracking_persist(staged_task, **kwargs):
        live_states_at_persist.append(
            app_module.TASKS["TASK-PUBLISH-ORDER"].state
        )
        assert staged_task.state == "rejected"
        assert staged_task.status == "rejected"
        assert (
            app_module.TASKS["TASK-PUBLISH-ORDER"].state
            == "ready_for_approval"
        )

    monkeypatch.setattr(
        app_module,
        "persist_task",
        tracking_persist,
    )

    try:
        app_module.reject_task("TASK-PUBLISH-ORDER")
        assert live_states_at_persist == [
            "ready_for_approval"
        ]
        assert task.state == "rejected"
    finally:
        restore()


def test_partial_cleanup_no_longer_sticks_in_queue(
    monkeypatch,
):
    """Former stuck bug: remove OK + branch fail left ready."""
    git_manager = RecordingGitManager(
        fail_delete_branch=True,
        delete_error=GitOperationError("branch locked"),
    )
    task, _sm, _wt, logs, restore, _, _ = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-NO-STUCK",
    )

    try:
        result = app_module.reject_task("TASK-NO-STUCK")
        assert result.state == "rejected"
        assert task.state == "rejected"

        with pytest.raises(HTTPException) as exc_info:
            app_module.reject_task("TASK-NO-STUCK")

        assert exc_info.value.status_code == 409
        assert (
            exc_info.value.detail
            == INVALID_REJECTION_STATE_DETAIL
        )
        assert any(
            "Reject cleanup warning: branch cleanup failed:"
            in message
            for message in logs
        )
    finally:
        restore()


def test_approve_after_rejected_is_state_guarded(
    monkeypatch,
):
    git_manager = RecordingGitManager(
        fail_delete_branch=True,
        delete_error=GitOperationError("branch locked"),
    )
    task, _sm, _wt, _logs, restore, _, _ = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-APPROVE-AFTER",
    )

    merge_calls = []

    def boom_merge(*args, **kwargs):
        merge_calls.append(True)
        raise AssertionError("merge must not run")

    git_manager.merge_branch = boom_merge
    git_manager.get_status = boom_merge
    git_manager.get_repository_head = boom_merge
    git_manager.get_branch_head = boom_merge

    try:
        app_module.reject_task("TASK-APPROVE-AFTER")
        assert task.state == "rejected"

        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-APPROVE-AFTER",
                background_tasks=SimpleNamespace(
                    add_task=lambda *a, **k: None
                ),
            )

        assert exc_info.value.status_code == 409
        assert merge_calls == []
    finally:
        restore()


def test_worktree_already_absent_still_rejects(
    monkeypatch,
):
    git_manager = RecordingGitManager(worktree_exists=False)
    (
        task,
        _sm,
        wt_result,
        logs,
        restore,
        persisted,
        _,
    ) = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-WT-ABSENT",
    )

    try:
        result = app_module.reject_task("TASK-WT-ABSENT")

        assert result.state == "rejected"
        assert task.state == "rejected"
        assert ("TASK-WT-ABSENT", "rejected", "rejected") in (
            persisted
        )
        assert _cleanup_calls(git_manager) == [
            ("remove_worktree", wt_result.path, True),
            ("delete_branch", wt_result.branch, True),
        ]
        assert git_manager.deleted_branch is True
        assert any(
            "Reject cleanup warning: worktree cleanup failed:"
            in message
            for message in logs
        )
        assert SUCCESS_LOG in logs
    finally:
        restore()


def test_branch_already_absent_still_rejects(monkeypatch):
    git_manager = RecordingGitManager(branch_exists=False)
    (
        task,
        _sm,
        wt_result,
        logs,
        restore,
        persisted,
        _,
    ) = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-BRANCH-ABSENT",
    )

    try:
        result = app_module.reject_task("TASK-BRANCH-ABSENT")

        assert result.state == "rejected"
        assert task.state == "rejected"
        assert (
            "TASK-BRANCH-ABSENT",
            "rejected",
            "rejected",
        ) in persisted
        assert git_manager.cleaned_worktree is True
        assert _cleanup_calls(git_manager) == [
            ("remove_worktree", wt_result.path, True),
            ("delete_branch", wt_result.branch, True),
        ]
        assert SUCCESS_LOG in logs
        assert not any(
            "Reject cleanup warning: branch cleanup failed:"
            in message
            for message in logs
        )
    finally:
        restore()


def test_task_missing_user_safe_detail(monkeypatch):
    logs = []
    monkeypatch.setattr(
        app_module,
        "hydrate_runtime_from_database",
        lambda: None,
    )
    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda _task_id, message: logs.append(message),
    )
    old_tasks = dict(app_module.TASKS)
    old_contexts = dict(app_module.TASK_CONTEXTS)
    app_module.TASKS.clear()
    app_module.TASK_CONTEXTS.clear()

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.reject_task("TASK-SECRET")

        assert exc_info.value.status_code == 404
        assert (
            exc_info.value.detail == TASK_NOT_FOUND_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "TASK-SECRET",
            "SQLite",
            "recovery",
        )
        assert any(
            "Reject refused: task not found after SQLite"
            in message
            and "TASK-SECRET" in message
            for message in logs
        )
    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(old_tasks)
        app_module.TASK_CONTEXTS.clear()
        app_module.TASK_CONTEXTS.update(old_contexts)


def test_wrong_state_user_safe_detail(monkeypatch):
    git_manager = RecordingGitManager()
    task, _sm, _wt, logs, restore, _, _ = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-WRONG-STATE",
    )
    task.state = "failed"
    task.status = "failed"

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.reject_task("TASK-WRONG-STATE")

        assert exc_info.value.status_code == 409
        assert (
            exc_info.value.detail
            == INVALID_REJECTION_STATE_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "failed",
            "ready_for_approval",
            "Task state is",
        )
        assert any(
            "expected 'ready_for_approval'" in message
            and "failed" in message
            for message in logs
        )
        assert git_manager.cleaned_worktree is False
        assert git_manager.deleted_branch is False
    finally:
        restore()


def test_context_missing_user_safe_detail(monkeypatch):
    git_manager = RecordingGitManager()
    task, _sm, _wt, logs, restore, _, _ = _prepare_reject(
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
            app_module.reject_task("TASK-NO-CONTEXT")

        assert exc_info.value.status_code == 409
        assert (
            exc_info.value.detail
            == REJECTION_CONTEXT_UNAVAILABLE_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "SQLite",
            "runtime context",
            "TASK-NO-CONTEXT",
        )
        assert any(
            "SQLite" in message
            and "TASK-NO-CONTEXT" in message
            for message in logs
        )
        assert task.state == "ready_for_approval"
        assert git_manager.cleaned_worktree is False
    finally:
        restore()


def test_orchestrator_project_failure_hides_project_id(
    monkeypatch,
):
    git_manager = RecordingGitManager()
    task, _sm, _wt, logs, restore, _, _ = _prepare_reject(
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
            app_module.reject_task("TASK-NO-PROJECT")

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
            "Reject orchestrator unavailable:" in message
            and INTERNAL_PROJECT_ID in message
            for message in logs
        )
        assert task.state == "ready_for_approval"
        assert git_manager.cleaned_worktree is False
    finally:
        restore()


def test_status_code_regression(monkeypatch):
    """Pre-durable→404/409/500; post-durable secondary→200."""
    logs = []
    monkeypatch.setattr(
        app_module,
        "hydrate_runtime_from_database",
        lambda: None,
    )
    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda _task_id, message: logs.append(message),
    )
    old_tasks = dict(app_module.TASKS)
    old_contexts = dict(app_module.TASK_CONTEXTS)
    app_module.TASKS.clear()
    app_module.TASK_CONTEXTS.clear()

    try:
        with pytest.raises(HTTPException) as missing:
            app_module.reject_task("TASK-STATUS-MISSING")
        assert missing.value.status_code == 404
    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(old_tasks)
        app_module.TASK_CONTEXTS.clear()
        app_module.TASK_CONTEXTS.update(old_contexts)

    git_manager = RecordingGitManager()
    task, _sm, _wt, _logs, restore, _, _ = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-STATUS-CODES",
    )
    try:
        task.state = "failed"
        with pytest.raises(HTTPException) as wrong:
            app_module.reject_task("TASK-STATUS-CODES")
        assert wrong.value.status_code == 409

        task.state = "ready_for_approval"
        app_module.TASK_CONTEXTS.pop(
            "TASK-STATUS-CODES",
            None,
        )
        with pytest.raises(HTTPException) as no_ctx:
            app_module.reject_task("TASK-STATUS-CODES")
        assert no_ctx.value.status_code == 409

        app_module.TASK_CONTEXTS["TASK-STATUS-CODES"] = {
            "state_machine": FakeStateMachine(),
            "wt_result": SimpleNamespace(
                path=r"C:\wt",
                branch="agent/x",
            ),
            "diff_output": "",
        }

        def boom(_task):
            raise KeyError("Project not found: x")

        monkeypatch.setattr(
            app_module,
            "build_orchestrator_for_task",
            boom,
        )
        with pytest.raises(HTTPException) as no_project:
            app_module.reject_task("TASK-STATUS-CODES")
        assert no_project.value.status_code == 409

        monkeypatch.setattr(
            app_module,
            "build_orchestrator_for_task",
            lambda _task: SimpleNamespace(
                git_manager=RecordingGitManager()
            ),
        )

        def boom_persist(staged_task, **kwargs):
            raise RuntimeError(
                f"{SECRET_DB_PATH}:{SECRET_SQL_ERROR}"
            )

        monkeypatch.setattr(
            app_module,
            "persist_task",
            boom_persist,
        )
        with pytest.raises(HTTPException) as persist_fail:
            app_module.reject_task("TASK-STATUS-CODES")
        assert persist_fail.value.status_code == 500
        assert (
            persist_fail.value.detail
            == REJECTION_PERSISTENCE_FAILED_DETAIL
        )
        _assert_no_http_leakage(persist_fail.value.detail)

        # Restore successful persist; secondary failures → 200.
        persisted = []

        def ok_persist(staged_task, **kwargs):
            persisted.append(staged_task.state)

        monkeypatch.setattr(
            app_module,
            "persist_task",
            ok_persist,
        )
        monkeypatch.setattr(
            app_module,
            "build_orchestrator_for_task",
            lambda _task: SimpleNamespace(
                git_manager=RecordingGitManager(
                    fail_remove_worktree=True,
                    fail_delete_branch=True,
                )
            ),
        )
        app_module.TASK_CONTEXTS["TASK-STATUS-CODES"] = {
            "state_machine": FakeStateMachine(
                fail_transition=True,
                error=RuntimeError("sm boom"),
            ),
            "wt_result": SimpleNamespace(
                path=r"C:\wt",
                branch="agent/x",
            ),
            "diff_output": "",
        }
        task.state = "ready_for_approval"
        task.status = "waiting_approval"

        result = app_module.reject_task("TASK-STATUS-CODES")
        assert result.state == "rejected"
        assert persisted == ["rejected"]
    finally:
        restore()


def test_persist_and_publish_rejected_helper_order(
    monkeypatch,
):
    task = app_module.TaskCreateResponse(
        task_id="TASK-HELPER-ORDER",
        status="waiting_approval",
        prompt="helper",
        max_attempts=2,
        project_id="PROJECT-HELPER",
        state="ready_for_approval",
        model=None,
        attempt=1,
        test_result="passed",
        started_at=None,
        task_kind="write",
    )
    old_tasks = dict(app_module.TASKS)
    app_module.TASKS["TASK-HELPER-ORDER"] = task

    seen = []

    def boom_persist(staged_task, **kwargs):
        seen.append(
            (
                staged_task.state,
                app_module.TASKS["TASK-HELPER-ORDER"].state,
            )
        )
        raise RuntimeError("db down")

    monkeypatch.setattr(
        app_module,
        "persist_task",
        boom_persist,
    )

    try:
        with pytest.raises(RuntimeError, match="db down"):
            app_module.persist_and_publish_rejected_task(
                "TASK-HELPER-ORDER"
            )

        assert seen == [
            ("rejected", "ready_for_approval")
        ]
        assert task.state == "ready_for_approval"
        assert task.status == "waiting_approval"
    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(old_tasks)


def test_persist_and_publish_rejected_helper_success(
    monkeypatch,
):
    task = app_module.TaskCreateResponse(
        task_id="TASK-HELPER-OK",
        status="waiting_approval",
        prompt="helper",
        max_attempts=2,
        project_id="PROJECT-HELPER",
        state="ready_for_approval",
        model=None,
        attempt=1,
        test_result="passed",
        started_at=None,
        task_kind="write",
    )
    old_tasks = dict(app_module.TASKS)
    app_module.TASKS["TASK-HELPER-OK"] = task
    order = []

    def ok_persist(staged_task, **kwargs):
        order.append(
            (
                "db",
                staged_task.state,
                app_module.TASKS["TASK-HELPER-OK"].state,
            )
        )

    monkeypatch.setattr(
        app_module,
        "persist_task",
        ok_persist,
    )

    try:
        result = app_module.persist_and_publish_rejected_task(
            "TASK-HELPER-OK"
        )
        order.append(
            ("publish", result.state, task.state)
        )
        assert order == [
            ("db", "rejected", "ready_for_approval"),
            ("publish", "rejected", "rejected"),
        ]
        assert result is task
    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(old_tasks)
