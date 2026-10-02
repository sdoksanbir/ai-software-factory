"""WRITE approval/reject ownership hardening regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import subprocess

import pytest
from fastapi import BackgroundTasks, HTTPException

import api.app as app_module
from factory.database import (
    create_project,
    get_project,
    get_task_diff,
    init_database,
    list_task_logs,
    list_tasks,
    save_task_diff,
    upsert_task,
)
from factory.tools.git_ops import GitWorktreeManager
from factory.write_worktree_ownership import (
    WriteOwnershipError,
    derive_write_path_plan,
    has_symlink_or_junction_escape,
    paths_equal,
    verify_write_metadata_ownership,
    verify_write_worktree_ownership,
)


OWNERSHIP_FAILED_DETAIL = (
    "Görev worktree/branch sahipliği doğrulanamadığı için "
    "onay işlemi durduruldu."
)
SUCCESS_APPROVE_LOG = (
    "Görev onaylandı ve ana dala birleştirildi."
)
SUCCESS_REJECT_LOG = "Görev reddedildi."


def _init_git_repo(path: Path) -> None:
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


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _git_out(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _try_symlink(target: Path, link_path: Path, *, target_is_directory=False):
    try:
        os.symlink(
            str(target),
            str(link_path),
            target_is_directory=target_is_directory,
        )
    except OSError as exc:
        pytest.skip(f"symlink not permitted: {exc}")


def _make_repo(tmp_path: Path, name: str = "edusen"):
    repo = tmp_path / name
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)
    (repo / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "source.py")
    _git(repo, "commit", "-m", "init")
    branch = _git_out(repo, "branch", "--show-current")
    if branch != "main":
        _git(repo, "branch", "-M", "main")
    manager = GitWorktreeManager(str(repo), str(wt_root))
    return repo, wt_root, manager


def _snapshot_main(repo: Path) -> tuple[str, str]:
    return (
        _git_out(repo, "rev-parse", "HEAD"),
        _git_out(repo, "status", "--porcelain"),
    )


def _assert_main_unchanged(repo: Path, before: tuple[str, str]) -> None:
    assert _snapshot_main(repo) == before


def _create_write_worktree(manager: GitWorktreeManager, task_id: str):
    return manager.create_worktree(task_id.lower())


def _write_task_file(wt_path: str, name: str, content: str) -> None:
    target = Path(wt_path) / name
    target.write_text(content, encoding="utf-8")


class FakeStateMachine:
    def __init__(self):
        self.transitions = []

    def transition(self, status):
        self.transitions.append(status)


def _wire_api_task(
    monkeypatch,
    *,
    manager: GitWorktreeManager,
    task_id: str,
    wt_path: str,
    wt_branch: str,
    logs: list[str],
):
    task = app_module.TaskCreateResponse(
        task_id=task_id,
        status="waiting_approval",
        prompt="ownership hardening",
        max_attempts=2,
        project_id="PROJECT-OWN",
        state="ready_for_approval",
        model=None,
        attempt=1,
        test_result="passed",
        started_at=None,
        task_kind="write",
    )
    state_machine = FakeStateMachine()
    wt_result = SimpleNamespace(path=wt_path, branch=wt_branch)

    old_tasks = dict(app_module.TASKS)
    old_contexts = dict(app_module.TASK_CONTEXTS)
    old_logs = dict(app_module.TASK_LOGS)

    app_module.TASKS[task_id] = task
    app_module.TASK_CONTEXTS[task_id] = {
        "state_machine": state_machine,
        "wt_result": wt_result,
        "diff_output": "diff --git a/x b/x\n",
    }
    app_module.TASK_LOGS[task_id] = logs

    persisted = []

    monkeypatch.setattr(
        app_module,
        "build_orchestrator_for_task",
        lambda _task: SimpleNamespace(git_manager=manager),
    )

    def fake_persist_task(staged_task, **kwargs):
        persisted.append(
            (
                staged_task.task_id,
                staged_task.status,
                staged_task.state,
                kwargs.get("branch"),
                kwargs.get("worktree_path"),
            )
        )

    monkeypatch.setattr(app_module, "persist_task", fake_persist_task)
    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda tid, message: logs.append(message)
        if tid == task_id
        else None,
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
        app_module.TASK_LOGS.clear()
        app_module.TASK_LOGS.update(old_logs)

    return task, state_machine, restore, persisted


# ---------------------------------------------------------------------------
# G. Ownership helper unit tests
# ---------------------------------------------------------------------------


def test_helper_exact_task_id_convention(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-OWN-G1")
    plan = derive_write_path_plan(manager, "TASK-OWN-G1")

    assert plan.task_id == "task-own-g1"
    assert plan.branch == "agent/task-own-g1"
    assert paths_equal(plan.worktree_path, created.path)
    assert paths_equal(created.path, plan.worktree_path)

    verified = verify_write_worktree_ownership(
        task_id="TASK-OWN-G1",
        claimed_branch=created.branch,
        claimed_worktree_path=created.path,
        git_manager=manager,
    )
    assert verified == plan
    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)
    _assert_main_unchanged(repo, before)


def test_helper_wrong_branch(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    created = _create_write_worktree(manager, "TASK-OWN-G2")
    plan = derive_write_path_plan(manager, "TASK-OWN-G2")

    with pytest.raises(WriteOwnershipError, match="branch"):
        verify_write_metadata_ownership(
            task_id="TASK-OWN-G2",
            claimed_branch="agent/other-task",
            claimed_worktree_path=plan.worktree_path,
            git_manager=manager,
        )

    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)


def test_helper_wrong_path(tmp_path):
    _repo, wt_root, manager = _make_repo(tmp_path)
    created = _create_write_worktree(manager, "TASK-OWN-G3")
    plan = derive_write_path_plan(manager, "TASK-OWN-G3")
    wrong = str(wt_root / "edusen" / "foreign")

    with pytest.raises(WriteOwnershipError, match="worktree_path"):
        verify_write_metadata_ownership(
            task_id="TASK-OWN-G3",
            claimed_branch=plan.branch,
            claimed_worktree_path=wrong,
            git_manager=manager,
        )

    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)


def test_helper_path_outside_worktree_root(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    outside = tmp_path / "outside" / "escape"
    outside.mkdir(parents=True)

    with pytest.raises(WriteOwnershipError):
        verify_write_metadata_ownership(
            task_id="TASK-OWN-G4",
            claimed_branch="agent/task-own-g4",
            claimed_worktree_path=str(outside),
            git_manager=manager,
        )


def test_helper_repository_mismatch(tmp_path):
    """Worktree registered in repo A must not prove ownership for repo B."""
    shared_wt = tmp_path / "worktrees"
    shared_wt.mkdir()

    repo_a = tmp_path / "a" / "edusen"
    repo_a.mkdir(parents=True)
    _init_git_repo(repo_a)
    (repo_a / "f.txt").write_text("a\n", encoding="utf-8")
    _git(repo_a, "add", "f.txt")
    _git(repo_a, "commit", "-m", "init")
    _git(repo_a, "branch", "-M", "main")
    manager_a = GitWorktreeManager(str(repo_a), str(shared_wt))

    repo_b = tmp_path / "b" / "edusen"
    repo_b.mkdir(parents=True)
    _init_git_repo(repo_b)
    (repo_b / "f.txt").write_text("b\n", encoding="utf-8")
    _git(repo_b, "add", "f.txt")
    _git(repo_b, "commit", "-m", "init")
    _git(repo_b, "branch", "-M", "main")
    manager_b = GitWorktreeManager(str(repo_b), str(shared_wt))

    created = _create_write_worktree(manager_a, "TASK-OWN-G5")
    plan_b = derive_write_path_plan(manager_b, "TASK-OWN-G5")
    assert paths_equal(created.path, plan_b.worktree_path)

    with pytest.raises(WriteOwnershipError, match="not registered"):
        verify_write_worktree_ownership(
            task_id="TASK-OWN-G5",
            claimed_branch=plan_b.branch,
            claimed_worktree_path=plan_b.worktree_path,
            git_manager=manager_b,
        )

    manager_a.remove_worktree(created.path, force=True)
    manager_a.delete_branch(created.branch, force=True)


def test_helper_registered_worktree_branch_mismatch(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    plan = derive_write_path_plan(manager, "TASK-OWN-G6")
    Path(plan.worktree_path).parent.mkdir(parents=True, exist_ok=True)
    _git(
        Path(manager.repo_root),
        "worktree",
        "add",
        "-b",
        "wrong/branch",
        plan.worktree_path,
    )

    with pytest.raises(WriteOwnershipError, match="registered worktree branch"):
        verify_write_worktree_ownership(
            task_id="TASK-OWN-G6",
            claimed_branch=plan.branch,
            claimed_worktree_path=plan.worktree_path,
            git_manager=manager,
        )

    manager.remove_worktree(plan.worktree_path, force=True)
    manager.delete_branch("wrong/branch", force=True)


def test_helper_windows_path_normalization(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    created = _create_write_worktree(manager, "TASK-OWN-G7")
    plan = derive_write_path_plan(manager, "TASK-OWN-G7")

    mixed = plan.worktree_path.replace("\\", "/")
    if os.name == "nt":
        mixed = mixed.replace("/", "\\")
        # Alternate separator style still exact after normalization.
        alt = plan.worktree_path.replace("/", "\\")
        assert paths_equal(alt, plan.worktree_path)

    verified = verify_write_metadata_ownership(
        task_id="TASK-OWN-G7",
        claimed_branch=plan.branch,
        claimed_worktree_path=mixed,
        git_manager=manager,
    )
    assert paths_equal(verified.worktree_path, plan.worktree_path)

    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)


def test_helper_symlink_escape_fail_closed(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    plan = derive_write_path_plan(manager, "TASK-OWN-G8")
    real_target = tmp_path / "real-target"
    real_target.mkdir()
    (real_target / "secret.txt").write_text("keep", encoding="utf-8")
    parent = Path(plan.worktree_path).parent
    parent.mkdir(parents=True, exist_ok=True)
    _try_symlink(
        real_target,
        Path(plan.worktree_path),
        target_is_directory=True,
    )
    _git(Path(manager.repo_root), "branch", plan.branch)

    assert has_symlink_or_junction_escape(
        plan.worktree_path,
        plan.worktree_root,
    )

    with pytest.raises(WriteOwnershipError, match="symlink"):
        verify_write_worktree_ownership(
            task_id="TASK-OWN-G8",
            claimed_branch=plan.branch,
            claimed_worktree_path=plan.worktree_path,
            git_manager=manager,
            require_registered_association=False,
            require_no_symlink_escape=True,
        )

    assert (real_target / "secret.txt").read_text(encoding="utf-8") == "keep"
    manager.delete_branch(plan.branch, force=True)


# ---------------------------------------------------------------------------
# A / B / C / D / E / F — API ownership flows (real git where required)
# ---------------------------------------------------------------------------


def test_a_normal_approval_with_correct_ownership(monkeypatch, tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    created = _create_write_worktree(manager, "TASK-OWN-A")
    _write_task_file(created.path, "feature.py", "X = 1\n")
    task_head = manager.commit_all(
        created.path,
        "TASK-OWN-A: feature",
    )
    before = _snapshot_main(repo)
    logs: list[str] = []

    task, _sm, restore, persisted = _wire_api_task(
        monkeypatch,
        manager=manager,
        task_id="TASK-OWN-A",
        wt_path=created.path,
        wt_branch=created.branch,
        logs=logs,
    )

    try:
        result = app_module.approve_task(
            "TASK-OWN-A",
            BackgroundTasks(),
        )
        assert result.state == "approved"
        assert task.state == "approved"
        assert SUCCESS_APPROVE_LOG in logs
        assert ("TASK-OWN-A", "approved", "approved", None, None) in (
            persisted
        )
        assert manager.is_ancestor(
            task_head,
            manager.get_repository_head(),
        )
        assert not manager._branch_exists(created.branch)
        assert manager.get_repository_head() != before[0]
    finally:
        restore()


def test_b_approval_tampered_worktree_path_preserves_foreign(
    monkeypatch,
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)
    task_a = _create_write_worktree(manager, "TASK-OWN-B")
    _write_task_file(task_a.path, "a.py", "A = 1\n")
    manager.commit_all(task_a.path, "TASK-OWN-B: a")

    foreign = _create_write_worktree(manager, "TASK-FOREIGN-B")
    foreign_marker = Path(foreign.path) / "keep.py"
    foreign_marker.write_text("KEEP = 1\n", encoding="utf-8")
    foreign_head = manager.commit_all(
        foreign.path,
        "foreign commit",
    )
    foreign_status_before = manager.get_status(foreign.path)
    before = _snapshot_main(repo)
    logs: list[str] = []

    task, state_machine, restore, persisted = _wire_api_task(
        monkeypatch,
        manager=manager,
        task_id="TASK-OWN-B",
        wt_path=foreign.path,
        wt_branch=task_a.branch,
        logs=logs,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-OWN-B",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == OWNERSHIP_FAILED_DETAIL
        assert "symlink" not in str(exc_info.value.detail).casefold()
        assert foreign.path not in str(exc_info.value.detail)
        assert task.state == "ready_for_approval"
        assert task.status == "waiting_approval"
        assert SUCCESS_APPROVE_LOG not in logs
        assert persisted == []
        assert app_module.TaskStatus.APPROVED not in (
            state_machine.transitions
        )
        assert any(
            "WRITE ownership verification failed" in message
            for message in logs
        )
        assert Path(foreign.path).exists()
        assert foreign_marker.read_text(encoding="utf-8") == "KEEP = 1\n"
        assert manager._branch_exists(foreign.branch)
        assert manager.get_branch_head(foreign.branch) == foreign_head
        assert manager.get_status(foreign.path) == foreign_status_before
        assert Path(task_a.path).exists()
        assert manager._branch_exists(task_a.branch)
        _assert_main_unchanged(repo, before)
    finally:
        restore()
        if manager._branch_exists(task_a.branch):
            manager.remove_worktree(task_a.path, force=True)
            manager.delete_branch(task_a.branch, force=True)
        if manager._branch_exists(foreign.branch):
            manager.remove_worktree(foreign.path, force=True)
            manager.delete_branch(foreign.branch, force=True)


def test_c_approval_tampered_branch_does_not_merge_foreign(
    monkeypatch,
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)
    task_a = _create_write_worktree(manager, "TASK-OWN-C")
    _write_task_file(task_a.path, "a.py", "A = 1\n")
    manager.commit_all(task_a.path, "TASK-OWN-C: a")

    foreign = _create_write_worktree(manager, "TASK-FOREIGN-C")
    _write_task_file(foreign.path, "foreign.py", "F = 1\n")
    foreign_head = manager.commit_all(
        foreign.path,
        "foreign tip",
    )
    before = _snapshot_main(repo)
    logs: list[str] = []

    task, _sm, restore, persisted = _wire_api_task(
        monkeypatch,
        manager=manager,
        task_id="TASK-OWN-C",
        wt_path=task_a.path,
        wt_branch=foreign.branch,
        logs=logs,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                "TASK-OWN-C",
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == OWNERSHIP_FAILED_DETAIL
        assert task.state == "ready_for_approval"
        assert SUCCESS_APPROVE_LOG not in logs
        assert persisted == []
        assert manager._branch_exists(foreign.branch)
        assert manager.get_branch_head(foreign.branch) == foreign_head
        assert Path(foreign.path).exists()
        _assert_main_unchanged(repo, before)
    finally:
        restore()
        if manager._branch_exists(task_a.branch):
            manager.remove_worktree(task_a.path, force=True)
            manager.delete_branch(task_a.branch, force=True)
        if manager._branch_exists(foreign.branch):
            manager.remove_worktree(foreign.path, force=True)
            manager.delete_branch(foreign.branch, force=True)


def test_d_restart_hydration_tampered_metadata_blocks_approval(
    monkeypatch,
    tmp_path,
):
    """Tampered SQLite metadata must survive real hydrate then fail ownership."""
    repo, _wt_root, manager = _make_repo(tmp_path)
    # TaskSpec requires TASK-#### ids during hydrate reconstruction.
    task_id = "TASK-9001"
    foreign_id = "TASK-9002"
    task_a = _create_write_worktree(manager, task_id)
    _write_task_file(task_a.path, "a.py", "A = 1\n")
    manager.commit_all(task_a.path, f"{task_id}: a")

    foreign = _create_write_worktree(manager, foreign_id)
    foreign_marker = Path(foreign.path) / "keep.py"
    foreign_marker.write_text("KEEP\n", encoding="utf-8")
    foreign_head = manager.commit_all(foreign.path, "foreign")
    before = _snapshot_main(repo)

    project_id = "PROJECT-OWN-D"
    tampered_branch = foreign.branch
    tampered_path = foreign.path
    diff_output = "diff --git a/a.py b/a.py\n"

    db_path = tmp_path / "factory-own-d.db"
    init_database(db_path)
    create_project(
        project_id,
        name="ownership-hydrate",
        path=str(repo),
        db_path=db_path,
    )
    upsert_task(
        task_id,
        prompt="hydrate ownership",
        status="waiting_approval",
        max_attempts=2,
        state="ready_for_approval",
        attempt=1,
        test_result="passed",
        project_id=project_id,
        branch=tampered_branch,
        worktree_path=tampered_path,
        db_path=db_path,
    )
    save_task_diff(task_id, diff_output, db_path=db_path)

    destructive_calls: list[tuple] = []
    persisted: list[tuple] = []
    logs: list[str] = []

    def _track(name, fn):
        def wrapper(*args, **kwargs):
            destructive_calls.append((name, args, kwargs))
            return fn(*args, **kwargs)

        return wrapper

    manager.merge_branch = _track(
        "merge_branch",
        manager.merge_branch,
    )
    manager.commit_all = _track(
        "commit_all",
        manager.commit_all,
    )
    manager.remove_worktree = _track(
        "remove_worktree",
        manager.remove_worktree,
    )
    manager.delete_branch = _track(
        "delete_branch",
        manager.delete_branch,
    )

    monkeypatch.setattr(
        app_module,
        "init_database",
        lambda: init_database(db_path),
    )
    monkeypatch.setattr(
        app_module,
        "db_list_tasks",
        lambda: list_tasks(db_path),
    )
    monkeypatch.setattr(
        app_module,
        "db_list_task_logs",
        lambda tid: list_task_logs(tid, db_path),
    )
    monkeypatch.setattr(
        app_module,
        "db_get_task_diff",
        lambda tid: get_task_diff(tid, db_path),
    )
    monkeypatch.setattr(
        app_module,
        "db_get_project",
        lambda pid: get_project(pid, db_path),
    )
    monkeypatch.setattr(
        app_module,
        "db_append_task_log",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        app_module,
        "get_task_route",
        lambda _tid: {"kind": "write"},
    )
    monkeypatch.setattr(
        app_module,
        "build_orchestrator_for_task",
        lambda _task: SimpleNamespace(
            git_manager=manager,
            project_path=str(repo),
        ),
    )
    monkeypatch.setattr(
        app_module,
        "append_task_log",
        lambda _tid, message: logs.append(message),
    )

    def fake_persist_task(staged_task, **kwargs):
        persisted.append(
            (
                staged_task.task_id,
                staged_task.status,
                staged_task.state,
            )
        )
        raise AssertionError(
            "approved persistence must not run after ownership failure"
        )

    monkeypatch.setattr(
        app_module,
        "persist_task",
        fake_persist_task,
    )
    monkeypatch.setattr(
        app_module,
        "capture_approved_task_memory",
        lambda _task_id: (_ for _ in ()).throw(
            AssertionError("memory capture must not run")
        ),
    )
    monkeypatch.setattr(
        app_module,
        "release_runnable_graph_dependents",
        lambda _task_id: [],
    )

    old_tasks = dict(app_module.TASKS)
    old_contexts = dict(app_module.TASK_CONTEXTS)
    old_logs = dict(app_module.TASK_LOGS)
    old_diffs = dict(app_module.TASK_DIFFS)

    # Empty runtime cache — force real restart recovery from SQLite.
    app_module.TASKS.clear()
    app_module.TASK_CONTEXTS.clear()
    app_module.TASK_LOGS.clear()
    app_module.TASK_DIFFS.clear()

    try:
        # Real ensure_approval_runtime → hydrate_runtime_from_database.
        task, context = app_module.ensure_approval_runtime(task_id)

        assert task is not None
        assert task.state == "ready_for_approval"
        assert context is not None
        assert "wt_result" in context
        assert context["wt_result"].path == tampered_path
        assert context["wt_result"].branch == tampered_branch
        assert app_module.TASK_DIFFS.get(task_id) == diff_output
        assert task_id in app_module.TASK_CONTEXTS

        with pytest.raises(HTTPException) as exc_info:
            app_module.approve_task(
                task_id,
                BackgroundTasks(),
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == OWNERSHIP_FAILED_DETAIL
        assert foreign.path not in str(exc_info.value.detail)
        assert tampered_branch not in str(exc_info.value.detail)

        live = app_module.TASKS[task_id]
        assert live.state == "ready_for_approval"
        assert live.status == "waiting_approval"
        assert persisted == []
        assert SUCCESS_APPROVE_LOG not in logs
        assert any(
            "WRITE ownership verification failed" in message
            for message in logs
        )
        assert destructive_calls == []

        assert Path(foreign.path).exists()
        assert foreign_marker.read_text(encoding="utf-8") == "KEEP\n"
        assert manager._branch_exists(foreign.branch)
        assert manager.get_branch_head(foreign.branch) == foreign_head
        assert manager._branch_exists(task_a.branch)
        assert Path(task_a.path).exists()
        _assert_main_unchanged(repo, before)
    finally:
        try:
            if manager._branch_exists(task_a.branch):
                GitWorktreeManager.remove_worktree(
                    manager,
                    task_a.path,
                    force=True,
                )
                GitWorktreeManager.delete_branch(
                    manager,
                    task_a.branch,
                    force=True,
                )
            if manager._branch_exists(foreign.branch):
                GitWorktreeManager.remove_worktree(
                    manager,
                    foreign.path,
                    force=True,
                )
                GitWorktreeManager.delete_branch(
                    manager,
                    foreign.branch,
                    force=True,
                )
        finally:
            app_module.TASKS.clear()
            app_module.TASKS.update(old_tasks)
            app_module.TASK_CONTEXTS.clear()
            app_module.TASK_CONTEXTS.update(old_contexts)
            app_module.TASK_LOGS.clear()
            app_module.TASK_LOGS.update(old_logs)
            app_module.TASK_DIFFS.clear()
            app_module.TASK_DIFFS.update(old_diffs)

def test_e_reject_tampered_path_skips_cleanup_keeps_rejected(
    monkeypatch,
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)
    task_a = _create_write_worktree(manager, "TASK-OWN-E")
    _write_task_file(task_a.path, "a.py", "A = 1\n")
    manager.commit_all(task_a.path, "TASK-OWN-E: a")

    foreign = _create_write_worktree(manager, "TASK-FOREIGN-E")
    foreign_marker = Path(foreign.path) / "keep.py"
    foreign_marker.write_text("KEEP\n", encoding="utf-8")
    manager.commit_all(foreign.path, "foreign")
    before = _snapshot_main(repo)
    logs: list[str] = []

    task, _sm, restore, persisted = _wire_api_task(
        monkeypatch,
        manager=manager,
        task_id="TASK-OWN-E",
        wt_path=foreign.path,
        wt_branch=foreign.branch,
        logs=logs,
    )

    try:
        result = app_module.reject_task("TASK-OWN-E")

        assert result.state == "rejected"
        assert task.state == "rejected"
        assert ("TASK-OWN-E", "rejected", "rejected", None, None) in (
            persisted
        )
        assert SUCCESS_REJECT_LOG in logs
        assert any(
            "Reject cleanup skipped: WRITE ownership could not be verified"
            in message
            for message in logs
        )
        assert Path(foreign.path).exists()
        assert foreign_marker.read_text(encoding="utf-8") == "KEEP\n"
        assert manager._branch_exists(foreign.branch)
        assert Path(task_a.path).exists()
        assert manager._branch_exists(task_a.branch)
        _assert_main_unchanged(repo, before)
    finally:
        restore()
        if manager._branch_exists(task_a.branch):
            manager.remove_worktree(task_a.path, force=True)
            manager.delete_branch(task_a.branch, force=True)
        if manager._branch_exists(foreign.branch):
            manager.remove_worktree(foreign.path, force=True)
            manager.delete_branch(foreign.branch, force=True)


def test_f_normal_reject_cleans_owned_worktree(monkeypatch, tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    created = _create_write_worktree(manager, "TASK-OWN-F")
    _write_task_file(created.path, "a.py", "A = 1\n")
    manager.commit_all(created.path, "TASK-OWN-F: a")
    before = _snapshot_main(repo)
    logs: list[str] = []

    task, _sm, restore, persisted = _wire_api_task(
        monkeypatch,
        manager=manager,
        task_id="TASK-OWN-F",
        wt_path=created.path,
        wt_branch=created.branch,
        logs=logs,
    )

    try:
        result = app_module.reject_task("TASK-OWN-F")
        assert result.state == "rejected"
        assert task.state == "rejected"
        assert ("TASK-OWN-F", "rejected", "rejected", None, None) in (
            persisted
        )
        assert SUCCESS_REJECT_LOG in logs
        assert not Path(created.path).exists()
        assert not manager._branch_exists(created.branch)
        _assert_main_unchanged(repo, before)
    finally:
        restore()
