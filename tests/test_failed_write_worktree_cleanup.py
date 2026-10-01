"""Failed WRITE worktree cleanup vs multi-step resume."""

from types import SimpleNamespace

import api.app as app_module
from factory.task_plan_store import (
    get_task_plan,
    save_task_plan,
)


class _FakeGitManager:
    def __init__(self):
        self.calls = []

    def remove_worktree(self, path, force=False):
        self.calls.append(
            ("remove_worktree", path, force)
        )

    def delete_branch(self, name, force=False):
        self.calls.append(
            ("delete_branch", name, force)
        )


def _make_orchestrator(tmp_path, task_id):
    project_path = tmp_path / "repo"
    worktree_root = tmp_path / "worktrees"
    project_path.mkdir()
    worktree_root.mkdir()

    worktree_path = (
        worktree_root
        / project_path.name
        / task_id.lower()
    )
    worktree_path.mkdir(parents=True)
    (worktree_path / ".git").write_text(
        "gitdir: fake",
        encoding="utf-8",
    )

    git_manager = _FakeGitManager()

    orchestrator = SimpleNamespace(
        project_path=str(project_path),
        worktree_root=str(worktree_root),
        git_manager=git_manager,
    )

    return orchestrator, worktree_path, git_manager


def test_cleanup_single_step_failed_removes_worktree(
    tmp_path,
    monkeypatch,
):
    # TASK-1790 / TASK-2552 regression
    task_id = "TASK-1790"
    orchestrator, worktree_path, git_manager = (
        _make_orchestrator(tmp_path, task_id)
    )
    db_path = tmp_path / "factory.db"

    save_task_plan(
        task_id,
        [
            {
                "title": "Write",
                "instruction": "Write",
                "kind": "write",
                "status": "failed",
                "attempt": 1,
            },
            {
                "title": "Verify",
                "instruction": "Verify",
                "kind": "verify",
                "status": "pending",
            },
        ],
        summary="Tek adimli gorev",
        status="failed",
        planner_mode="single_step",
        db_path=db_path,
    )

    monkeypatch.setattr(
        app_module,
        "get_task_plan",
        lambda tid: get_task_plan(
            tid,
            db_path=db_path,
        ),
    )

    logs = []

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda tid, message: logs.append(message),
    )

    app_module.cleanup_failed_task_for_api(
        orchestrator,
        task_id,
    )

    assert (
        "remove_worktree",
        str(worktree_path),
        True,
    ) in git_manager.calls

    assert (
        "delete_branch",
        f"agent/{task_id.lower()}",
        True,
    ) in git_manager.calls

    assert not any(
        "Multi-step worktree retry"
        in message
        for message in logs
    )


def test_cleanup_completed_single_step_noop_gate(
    tmp_path,
    monkeypatch,
):
    # TASK-7503 regression: plan completed, final
    # no-op gate failed — do not keep worktree.
    task_id = "TASK-7503"
    orchestrator, worktree_path, git_manager = (
        _make_orchestrator(tmp_path, task_id)
    )
    db_path = tmp_path / "factory.db"

    save_task_plan(
        task_id,
        [
            {
                "title": "Write",
                "instruction": "Write",
                "kind": "write",
                "status": "completed",
            },
            {
                "title": "Verify",
                "instruction": "Verify",
                "kind": "verify",
                "status": "completed",
            },
        ],
        summary="Tek adimli gorev",
        status="completed",
        planner_mode="single_step",
        db_path=db_path,
    )

    monkeypatch.setattr(
        app_module,
        "get_task_plan",
        lambda tid: get_task_plan(
            tid,
            db_path=db_path,
        ),
    )

    logs = []

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda tid, message: logs.append(message),
    )

    app_module.cleanup_failed_task_for_api(
        orchestrator,
        task_id,
    )

    assert (
        "remove_worktree",
        str(worktree_path),
        True,
    ) in git_manager.calls

    assert (
        "delete_branch",
        f"agent/{task_id.lower()}",
        True,
    ) in git_manager.calls

    assert not any(
        "Multi-step worktree retry"
        in message
        for message in logs
    )


def test_cleanup_real_multi_step_preserves_worktree(
    tmp_path,
    monkeypatch,
):
    task_id = "TASK-MS-KEEP"
    orchestrator, worktree_path, git_manager = (
        _make_orchestrator(tmp_path, task_id)
    )
    db_path = tmp_path / "factory.db"

    save_task_plan(
        task_id,
        [
            {
                "title": "Write A",
                "instruction": "A",
                "kind": "write",
                "status": "completed",
            },
            {
                "title": "Write B",
                "instruction": "B",
                "kind": "write",
                "status": "failed",
                "attempt": 1,
            },
            {
                "title": "Verify",
                "instruction": "Verify",
                "kind": "verify",
                "status": "pending",
            },
        ],
        summary="Multi step",
        status="failed",
        planner_mode="multi_step",
        db_path=db_path,
    )

    monkeypatch.setattr(
        app_module,
        "get_task_plan",
        lambda tid: get_task_plan(
            tid,
            db_path=db_path,
        ),
    )

    logs = []

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda tid, message: logs.append(message),
    )

    app_module.cleanup_failed_task_for_api(
        orchestrator,
        task_id,
    )

    assert git_manager.calls == []
    assert any(
        "Multi-step worktree retry icin korundu."
        == message
        for message in logs
    )
    assert worktree_path.is_dir()


def test_cleanup_completed_multi_step_removes_worktree(
    tmp_path,
    monkeypatch,
):
    task_id = "TASK-MS-DONE"
    orchestrator, worktree_path, git_manager = (
        _make_orchestrator(tmp_path, task_id)
    )
    db_path = tmp_path / "factory.db"

    save_task_plan(
        task_id,
        [
            {
                "title": "Write",
                "instruction": "Write",
                "kind": "write",
                "status": "completed",
            },
            {
                "title": "Verify",
                "instruction": "Verify",
                "kind": "verify",
                "status": "completed",
            },
        ],
        summary="Multi done",
        status="completed",
        planner_mode="multi_step",
        db_path=db_path,
    )

    monkeypatch.setattr(
        app_module,
        "get_task_plan",
        lambda tid: get_task_plan(
            tid,
            db_path=db_path,
        ),
    )

    logs = []

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda tid, message: logs.append(message),
    )

    app_module.cleanup_failed_task_for_api(
        orchestrator,
        task_id,
    )

    assert (
        "remove_worktree",
        str(worktree_path),
        True,
    ) in git_manager.calls

    assert not any(
        "Multi-step worktree retry"
        in message
        for message in logs
    )


def test_cleanup_legacy_null_incomplete_preserves(
    tmp_path,
    monkeypatch,
):
    task_id = "TASK-LEGACY-KEEP"
    orchestrator, _worktree_path, git_manager = (
        _make_orchestrator(tmp_path, task_id)
    )
    db_path = tmp_path / "factory.db"

    # Omit planner_mode → NULL legacy row.
    save_task_plan(
        task_id,
        [
            {
                "title": "Write",
                "instruction": "Write",
                "kind": "write",
                "status": "failed",
            },
            {
                "title": "Verify",
                "instruction": "Verify",
                "kind": "verify",
                "status": "pending",
            },
        ],
        status="failed",
        db_path=db_path,
    )

    loaded = get_task_plan(
        task_id,
        db_path=db_path,
    )
    assert loaded["planner_mode"] is None

    monkeypatch.setattr(
        app_module,
        "get_task_plan",
        lambda tid: get_task_plan(
            tid,
            db_path=db_path,
        ),
    )

    logs = []

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda tid, message: logs.append(message),
    )

    app_module.cleanup_failed_task_for_api(
        orchestrator,
        task_id,
    )

    assert git_manager.calls == []
    assert any(
        "Multi-step worktree retry icin korundu."
        == message
        for message in logs
    )


def test_cleanup_legacy_null_completed_removes(
    tmp_path,
    monkeypatch,
):
    task_id = "TASK-LEGACY-DONE"
    orchestrator, worktree_path, git_manager = (
        _make_orchestrator(tmp_path, task_id)
    )
    db_path = tmp_path / "factory.db"

    save_task_plan(
        task_id,
        [
            {
                "title": "Write",
                "instruction": "Write",
                "kind": "write",
                "status": "completed",
            },
            {
                "title": "Verify",
                "instruction": "Verify",
                "kind": "verify",
                "status": "completed",
            },
        ],
        status="completed",
        db_path=db_path,
    )

    monkeypatch.setattr(
        app_module,
        "get_task_plan",
        lambda tid: get_task_plan(
            tid,
            db_path=db_path,
        ),
    )

    logs = []

    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda tid, message: logs.append(message),
    )

    app_module.cleanup_failed_task_for_api(
        orchestrator,
        task_id,
    )

    assert (
        "remove_worktree",
        str(worktree_path),
        True,
    ) in git_manager.calls
