"""Reject endpoint: user-safe HTTP details, technical logs only."""

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
REJECTION_FAILED_DETAIL = (
    "Reddetme işlemi tamamlanamadı. "
    "Görev kayıtlarını kontrol edin."
)

SECRET_PATH = r"C:\SECRET_PATH"
SECRET_STDERR = "SECRET_STDERR"
SECRET_BRANCH = "SECRET_BRANCH"
INTERNAL_PROJECT_ID = "INTERNAL-PROJECT-ID"
INTERNAL_STATE_MACHINE_SECRET = (
    "INTERNAL_STATE_MACHINE_SECRET"
)

LEAKAGE_SENTINELS = (
    SECRET_PATH,
    SECRET_STDERR,
    SECRET_BRANCH,
    INTERNAL_PROJECT_ID,
    INTERNAL_STATE_MACHINE_SECRET,
)


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
    ):
        self.calls = []
        self.fail_remove_worktree = fail_remove_worktree
        self.remove_error = remove_error
        self.fail_delete_branch = fail_delete_branch
        self.delete_error = delete_error
        self.cleaned_worktree = False
        self.deleted_branch = False

    def remove_worktree(self, path, *args, **kwargs):
        self.calls.append(
            ("remove_worktree", path, kwargs.get("force"))
        )
        if self.fail_remove_worktree:
            raise self.remove_error or RuntimeError(
                "cleanup failed"
            )
        self.cleaned_worktree = True

    def delete_branch(self, branch, *args, **kwargs):
        self.calls.append(
            ("delete_branch", branch, kwargs.get("force"))
        )
        if self.fail_delete_branch:
            raise self.delete_error or RuntimeError(
                "cleanup failed"
            )
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

    wt_result = SimpleNamespace(
        path=r"C:\AI-Worktrees\demo\task-reject",
        branch="agent/task-reject",
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
        lambda _task: SimpleNamespace(
            git_manager=git_manager
        ),
    )

    def fake_persist_task(staged_task, **kwargs):
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
        assert git_manager.calls == [
            ("remove_worktree", wt_result.path, True),
            ("delete_branch", wt_result.branch, True),
        ]
        assert ("TASK-REJECT-OK", "rejected", "rejected") in (
            persisted
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
    task, _sm, _wt, logs, restore, _ = _prepare_reject(
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
    task, _sm, _wt, logs, restore, _ = _prepare_reject(
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
    task, _sm, _wt, logs, restore, _ = _prepare_reject(
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


def test_worktree_remove_failure_scrubbed(monkeypatch):
    secret_exc = GitOperationError(
        "Git command failed ("
        f"'git worktree remove --force {SECRET_PATH}'"
        f"): {SECRET_STDERR}"
    )
    git_manager = RecordingGitManager(
        fail_remove_worktree=True,
        remove_error=secret_exc,
    )
    task, state_machine, _wt, logs, restore, _ = (
        _prepare_reject(
            monkeypatch,
            git_manager=git_manager,
            task_id="TASK-WT-FAIL",
        )
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.reject_task("TASK-WT-FAIL")

        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail == REJECTION_FAILED_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "git worktree",
            "Rejection failed",
        )
        assert any(
            "Task rejection failed:" in message
            and SECRET_PATH in message
            and SECRET_STDERR in message
            for message in logs
        )
        assert task.state == "ready_for_approval"
        assert app_module.TaskStatus.REJECTED not in (
            state_machine.transitions
        )
        assert SUCCESS_LOG not in logs
    finally:
        restore()


def test_branch_delete_failure_scrubbed(monkeypatch):
    secret_exc = GitOperationError(
        "Git command failed ("
        f"'git branch -D {SECRET_BRANCH}'"
        f"): {SECRET_STDERR}"
    )
    git_manager = RecordingGitManager(
        fail_delete_branch=True,
        delete_error=secret_exc,
    )
    task, state_machine, _wt, logs, restore, _ = (
        _prepare_reject(
            monkeypatch,
            git_manager=git_manager,
            task_id="TASK-BRANCH-FAIL",
        )
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.reject_task("TASK-BRANCH-FAIL")

        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail == REJECTION_FAILED_DETAIL
        )
        _assert_no_http_leakage(
            exc_info.value.detail,
            "git branch",
            "Rejection failed",
        )
        assert any(
            "Task rejection failed:" in message
            and SECRET_BRANCH in message
            for message in logs
        )
        assert git_manager.cleaned_worktree is True
        assert git_manager.deleted_branch is False
        assert task.state == "ready_for_approval"
        assert app_module.TaskStatus.REJECTED not in (
            state_machine.transitions
        )
    finally:
        restore()


def test_state_machine_failure_scrubbed(monkeypatch):
    git_manager = RecordingGitManager()
    state_machine = FakeStateMachine(
        fail_transition=True,
        error=RuntimeError(INTERNAL_STATE_MACHINE_SECRET),
    )
    task, _sm, _wt, logs, restore, _ = _prepare_reject(
        monkeypatch,
        git_manager=git_manager,
        task_id="TASK-SM-FAIL",
        state_machine=state_machine,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.reject_task("TASK-SM-FAIL")

        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail == REJECTION_FAILED_DETAIL
        )
        _assert_no_http_leakage(exc_info.value.detail)
        assert any(
            "Task rejection failed:" in message
            and INTERNAL_STATE_MACHINE_SECRET in message
            for message in logs
        )
        assert git_manager.cleaned_worktree is True
        assert git_manager.deleted_branch is True
        assert task.state == "ready_for_approval"
        assert SUCCESS_LOG not in logs
    finally:
        restore()


def test_status_code_regression(monkeypatch):
    """missing→404, wrong/context/project→409, cleanup→500."""
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
    task, _sm, _wt, _logs, restore, _ = _prepare_reject(
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
                git_manager=RecordingGitManager(
                    fail_remove_worktree=True,
                    remove_error=GitOperationError("boom"),
                )
            ),
        )
        with pytest.raises(HTTPException) as cleanup:
            app_module.reject_task("TASK-STATUS-CODES")
        assert cleanup.value.status_code == 500
    finally:
        restore()
