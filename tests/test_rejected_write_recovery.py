"""REJECTED WRITE stale worktree/branch startup recovery regressions."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess

import pytest

from factory.rejected_write_recovery import (
    RecoveryAction,
    derive_write_path_plan,
    recover_rejected_write_artifacts,
    recover_rejected_write_artifacts_on_startup,
)
from factory.tools.git_ops import GitWorktreeManager


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


def _make_repo(tmp_path: Path):
    repo = tmp_path / "edusen"
    wt_root = tmp_path / "worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)
    (repo / "source.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    _git(repo, "add", "source.py")
    _git(repo, "commit", "-m", "init")
    branch = _git_out(repo, "branch", "--show-current")
    if branch != "main":
        _git(repo, "branch", "-M", "main")
    manager = GitWorktreeManager(str(repo), str(wt_root))
    return repo, wt_root, manager


def _branches(repo: Path, pattern: str) -> str:
    return _git_out(repo, "branch", "--list", pattern)


def _worktree_porcelain(repo: Path) -> str:
    return _git_out(repo, "worktree", "list", "--porcelain")


def _snapshot_main(repo: Path) -> tuple[str, str]:
    head = _git_out(repo, "rev-parse", "HEAD")
    status = _git_out(repo, "status", "--porcelain")
    return head, status


def _assert_main_unchanged(
    repo: Path,
    before: tuple[str, str],
) -> None:
    assert _snapshot_main(repo) == before


def _create_write_worktree(
    manager: GitWorktreeManager,
    task_id: str,
):
    return manager.create_worktree(task_id.lower())


def _try_symlink(target: Path, link_path: Path, *, target_is_directory=False):
    try:
        os.symlink(
            str(target),
            str(link_path),
            target_is_directory=target_is_directory,
        )
    except OSError as exc:
        pytest.skip(f"symlink not permitted: {exc}")


def test_rejected_wt_and_branch_cleaned(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-BOTH")
    plan = derive_write_path_plan(manager, "TASK-BOTH")
    assert Path(created.path).exists()
    assert manager._branch_exists(plan.branch)

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-BOTH",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.RECOVERED
    assert not Path(created.path).exists()
    assert not manager._branch_exists(plan.branch)
    assert plan.branch not in _worktree_porcelain(repo)
    _assert_main_unchanged(repo, before)


def test_rejected_worktree_only(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-WT2")
    plan = derive_write_path_plan(manager, "TASK-WT2")
    # Leave exact physical path without registration or branch.
    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)
    Path(created.path).mkdir(parents=True)
    (Path(created.path) / "left.txt").write_text(
        "orphan",
        encoding="utf-8",
    )
    assert not manager._branch_exists(plan.branch)
    assert Path(created.path).exists()

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-WT2",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.RECOVERED
    assert not Path(created.path).exists()
    assert not manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)


def test_rejected_branch_only(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-BR")
    plan = derive_write_path_plan(manager, "TASK-BR")
    manager.remove_worktree(created.path, force=True)
    _git(repo, "worktree", "prune")
    assert manager._branch_exists(plan.branch)
    assert not Path(created.path).exists()

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-BR",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.RECOVERED
    assert not manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)


def test_both_absent_noop_success(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    plan = derive_write_path_plan(manager, "TASK-GONE")

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-GONE",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )
    assert result.action == RecoveryAction.NONE

    again = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-GONE",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )
    assert again.action == RecoveryAction.NONE
    _assert_main_unchanged(repo, before)


def test_idempotent_double_recovery(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-IDEM")
    plan = derive_write_path_plan(manager, "TASK-IDEM")

    first = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-IDEM",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )
    second = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-IDEM",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert first.action == RecoveryAction.RECOVERED
    assert second.action == RecoveryAction.NONE
    assert not Path(created.path).exists()
    assert not manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)


def test_ready_for_approval_preserved(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-RFA")
    plan = derive_write_path_plan(manager, "TASK-RFA")

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-RFA",
        state="ready_for_approval",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.SKIPPED
    assert Path(created.path).exists()
    assert manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)
    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)


def test_approved_skipped(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-APP")
    plan = derive_write_path_plan(manager, "TASK-APP")

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-APP",
        state="approved",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.SKIPPED
    assert Path(created.path).exists()
    assert manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)
    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)


def test_kind_not_write_skipped(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-READ")
    plan = derive_write_path_plan(manager, "TASK-READ")

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-READ",
        state="rejected",
        task_kind="read",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.SKIPPED
    assert Path(created.path).exists()
    assert manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)
    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)


def test_user_branch_without_db_task_preserved(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    _git(repo, "branch", "agent/my-test")
    assert "agent/my-test" in _branches(repo, "agent/*")

    # Startup-style: no DB row → nothing to recover for that branch.
    results = recover_rejected_write_artifacts_on_startup(
        worktree_root=str(manager.worktree_root),
        list_task_rows=lambda: [],
        get_task_kind=lambda _tid: None,
        get_project_path=lambda _row: str(repo),
    )

    assert results == []
    assert "agent/my-test" in _branches(repo, "agent/*")
    _assert_main_unchanged(repo, before)
    _git(repo, "branch", "-D", "agent/my-test")


def test_branch_mismatch_fail_closed(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-X")
    plan = derive_write_path_plan(manager, "TASK-X")
    _git(repo, "branch", "agent/user-special")

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-X",
        state="rejected",
        task_kind="write",
        stored_branch="agent/user-special",
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.SKIPPED
    assert Path(created.path).exists()
    assert manager._branch_exists(plan.branch)
    assert "agent/user-special" in _branches(repo, "agent/*")
    _assert_main_unchanged(repo, before)
    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)
    _git(repo, "branch", "-D", "agent/user-special")


def test_path_mismatch_fail_closed(tmp_path):
    repo, wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-PATH")
    plan = derive_write_path_plan(manager, "TASK-PATH")
    wrong_path = str(wt_root / "edusen" / "other-task")

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-PATH",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=wrong_path,
    )

    assert result.action == RecoveryAction.SKIPPED
    assert Path(created.path).exists()
    assert manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)
    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)


def test_path_outside_worktree_root_not_deleted(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    outside = tmp_path / "important"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("precious", encoding="utf-8")
    plan = derive_write_path_plan(manager, "TASK-OUT")

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-OUT",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=str(outside),
    )

    assert result.action == RecoveryAction.SKIPPED
    assert marker.read_text(encoding="utf-8") == "precious"
    _assert_main_unchanged(repo, before)


def test_symlink_path_not_deleted(tmp_path):
    repo, wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    plan = derive_write_path_plan(manager, "TASK-LINK")
    real_target = tmp_path / "real-target"
    real_target.mkdir()
    (real_target / "secret.txt").write_text(
        "keep",
        encoding="utf-8",
    )
    parent = Path(plan.worktree_path).parent
    parent.mkdir(parents=True, exist_ok=True)
    _try_symlink(
        real_target,
        Path(plan.worktree_path),
        target_is_directory=True,
    )
    _git(repo, "branch", plan.branch)

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-LINK",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.FAILED
    assert Path(plan.worktree_path).is_symlink()
    assert (real_target / "secret.txt").read_text(
        encoding="utf-8"
    ) == "keep"
    assert not manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)


def test_registration_without_physical_path(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-REG")
    plan = derive_write_path_plan(manager, "TASK-REG")
    user_wt = tmp_path / "user-wt"
    _git(
        repo,
        "worktree",
        "add",
        str(user_wt),
        "-b",
        "user/feature",
    )
    shutil.rmtree(created.path)
    porcelain = _worktree_porcelain(repo).replace("\\", "/")
    assert plan.worktree_path.replace("\\", "/") in porcelain or (
        "prunable" in porcelain.casefold()
    )

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-REG",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.RECOVERED
    assert not manager._branch_exists(plan.branch)
    assert Path(user_wt).exists()
    assert "user/feature" in _branches(repo, "user/*")
    _assert_main_unchanged(repo, before)
    _git(repo, "worktree", "remove", str(user_wt), "--force")
    _git(repo, "branch", "-D", "user/feature")


def test_orphan_physical_path_without_registration(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    plan = derive_write_path_plan(manager, "TASK-ORPH")
    Path(plan.worktree_path).mkdir(parents=True)
    (Path(plan.worktree_path) / "left.txt").write_text(
        "orphan",
        encoding="utf-8",
    )
    _git(repo, "branch", plan.branch)

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-ORPH",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.RECOVERED
    assert not Path(plan.worktree_path).exists()
    assert not manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)


def test_unrelated_user_worktree_preserved(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-OWN")
    plan = derive_write_path_plan(manager, "TASK-OWN")
    user_wt = tmp_path / "manual-wt"
    _git(
        repo,
        "worktree",
        "add",
        str(user_wt),
        "-b",
        "manual/branch",
    )

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-OWN",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.RECOVERED
    assert not Path(created.path).exists()
    assert Path(user_wt).exists()
    assert "manual/branch" in _branches(repo, "manual/*")
    _assert_main_unchanged(repo, before)
    _git(repo, "worktree", "remove", str(user_wt), "--force")
    _git(repo, "branch", "-D", "manual/branch")


def test_unrelated_prunable_not_globally_pruned(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-PRUNE")
    plan = derive_write_path_plan(manager, "TASK-PRUNE")
    user_wt = tmp_path / "user-prunable"
    _git(
        repo,
        "worktree",
        "add",
        str(user_wt),
        "-b",
        "user/prunable",
    )
    shutil.rmtree(user_wt)
    shutil.rmtree(created.path)
    porcelain = _worktree_porcelain(repo).casefold()
    assert "prunable" in porcelain

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-PRUNE",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert result.action == RecoveryAction.RECOVERED
    # User prunable registration must still be listed (not global prune).
    after = _worktree_porcelain(repo).replace("\\", "/")
    assert str(user_wt).replace("\\", "/") in after or (
        "prunable" in after.casefold()
    )
    assert "user/prunable" in _branches(repo, "user/*")
    _assert_main_unchanged(repo, before)
    _git(repo, "worktree", "prune")
    if manager._branch_exists("user/prunable"):
        manager.delete_branch("user/prunable", force=True)


def test_multiprocess_style_idempotency(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-MP")
    plan = derive_write_path_plan(manager, "TASK-MP")

    first = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-MP",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )
    second = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-MP",
        state="rejected",
        task_kind="write",
        stored_branch=plan.branch,
        stored_worktree_path=plan.worktree_path,
    )

    assert first.action == RecoveryAction.RECOVERED
    assert second.action == RecoveryAction.NONE
    assert not Path(created.path).exists()
    _assert_main_unchanged(repo, before)


def test_startup_row_driven_recovery(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-START")
    plan = derive_write_path_plan(manager, "TASK-START")
    logs: list[tuple[str, str]] = []

    rows = [
        {
            "task_id": "TASK-START",
            "state": "rejected",
            "status": "rejected",
            "branch": plan.branch,
            "worktree_path": plan.worktree_path,
            "project_id": "proj-1",
        }
    ]

    results = recover_rejected_write_artifacts_on_startup(
        worktree_root=str(manager.worktree_root),
        list_task_rows=lambda: rows,
        get_task_kind=lambda _tid: "write",
        get_project_path=lambda _row: str(repo),
        append_log=lambda tid, msg: logs.append((tid, msg)),
    )

    assert len(results) == 1
    assert results[0].action == RecoveryAction.RECOVERED
    assert not Path(created.path).exists()
    assert not manager._branch_exists(plan.branch)
    assert any("startup recovery cleaned" in msg for _, msg in logs)
    _assert_main_unchanged(repo, before)


def test_startup_skips_ready_for_approval_row(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)
    created = _create_write_worktree(manager, "TASK-HYD")
    plan = derive_write_path_plan(manager, "TASK-HYD")

    results = recover_rejected_write_artifacts_on_startup(
        worktree_root=str(manager.worktree_root),
        list_task_rows=lambda: [
            {
                "task_id": "TASK-HYD",
                "state": "ready_for_approval",
                "status": "waiting_approval",
                "branch": plan.branch,
                "worktree_path": plan.worktree_path,
                "project_id": "proj-1",
            }
        ],
        get_task_kind=lambda _tid: "write",
        get_project_path=lambda _row: str(repo),
    )

    assert results == []
    assert Path(created.path).exists()
    assert manager._branch_exists(plan.branch)
    _assert_main_unchanged(repo, before)
    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(plan.branch, force=True)


def test_db_metadata_not_required_to_clear_for_success(tmp_path):
    """Historical branch/worktree_path may remain; recovery still succeeds."""
    repo, _wt_root, manager = _make_repo(tmp_path)
    created = _create_write_worktree(manager, "TASK-META")
    plan = derive_write_path_plan(manager, "TASK-META")
    stored_branch = plan.branch
    stored_path = plan.worktree_path

    result = recover_rejected_write_artifacts(
        git_manager=manager,
        task_id="TASK-META",
        state="rejected",
        task_kind="write",
        stored_branch=stored_branch,
        stored_worktree_path=stored_path,
    )
    assert result.action == RecoveryAction.RECOVERED
    # Caller still holds historical metadata strings.
    assert stored_branch == plan.branch
    assert stored_path == plan.worktree_path
    assert not Path(created.path).exists()
