"""EXECUTE ownership marker + hard-crash recovery regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import sys
import time

import psutil
import pytest

from factory.execute_recovery import (
    ActiveExecuteSessionError,
    RecoveryAction,
    UnownedExecuteArtifactsError,
    current_owner_identity,
    derive_execute_path_plan,
    ensure_execute_session_ready,
    is_owner_process_alive,
    marker_path_for,
    read_execute_owner_marker,
    recover_execute_session,
    recover_stale_execute_markers,
    write_execute_owner_marker,
)
from factory.execute_worktree import (
    cleanup_execute_worktree,
    prepare_execute_worktree,
)
from factory.tools.git_ops import (
    BranchAlreadyExistsError,
    GitWorktreeManager,
    WorktreeAlreadyExistsError,
)


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
    # Ensure main exists on platforms that default to master.
    branch = _git_out(repo, "branch", "--show-current")
    if branch != "main":
        _git(repo, "branch", "-M", "main")
    manager = GitWorktreeManager(str(repo), str(wt_root))
    return repo, wt_root, manager


def _branches(repo: Path, pattern: str) -> str:
    return _git_out(repo, "branch", "--list", pattern)


def _worktree_porcelain(repo: Path) -> str:
    return _git_out(repo, "worktree", "list", "--porcelain")


def _write_dead_marker(
    manager: GitWorktreeManager,
    task_id: str,
    *,
    owner_pid: int = 1,
    owner_ct: float = 1.0,
):
    plan = derive_execute_path_plan(manager, task_id)
    return write_execute_owner_marker(
        plan,
        owner_pid=owner_pid,
        owner_process_create_time=owner_ct,
    )


def test_normal_cleanup_removes_marker(tmp_path):
    _repo, wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-OK")
    plan = derive_execute_path_plan(manager, "TASK-OK")
    marker = marker_path_for(
        plan.worktree_root,
        plan.repo_namespace,
        plan.task_id,
    )
    assert Path(marker).is_file()

    cleanup_execute_worktree(
        manager,
        path=session.path,
        branch=session.branch,
        task_id=session.task_id,
    )

    assert not Path(marker).is_file()
    assert not Path(session.path).exists()
    assert "execute/TASK-OK" not in _branches(
        Path(manager.repo_root),
        "execute/*",
    )


def test_hard_crash_dead_owner_targeted_recovery(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-CRASH")
    plan = derive_execute_path_plan(manager, "TASK-CRASH")
    marker = marker_path_for(
        plan.worktree_root,
        plan.repo_namespace,
        plan.task_id,
    )

    # Simulate crash: leave artifacts, rewrite marker as dead owner.
    assert Path(session.path).exists()
    assert Path(marker).is_file()
    _write_dead_marker(manager, "TASK-CRASH")

    result = recover_execute_session(manager, "TASK-CRASH")
    assert result.action == RecoveryAction.RECOVERED
    assert not Path(session.path).exists()
    assert not Path(marker).is_file()
    assert "execute/TASK-CRASH" not in _branches(
        repo,
        "execute/*",
    )
    assert "execute-TASK-CRASH" not in _worktree_porcelain(repo)


def test_live_owner_recovery_preserves_artifacts(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-LIVE")
    plan = derive_execute_path_plan(manager, "TASK-LIVE")
    marker = marker_path_for(
        plan.worktree_root,
        plan.repo_namespace,
        plan.task_id,
    )

    with pytest.raises(ActiveExecuteSessionError):
        recover_execute_session(manager, "TASK-LIVE")

    assert Path(session.path).exists()
    assert Path(marker).is_file()
    assert "execute/TASK-LIVE" in _branches(repo, "execute/*")

    cleanup_execute_worktree(
        manager,
        path=session.path,
        branch=session.branch,
        task_id="TASK-LIVE",
    )


def test_pid_reuse_different_create_time_is_dead(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-REUSE")
    pid, _ct = current_owner_identity()
    # Same PID, impossible create_time → treated as reused/dead.
    _write_dead_marker(
        manager,
        "TASK-REUSE",
        owner_pid=pid,
        owner_ct=1.0,
    )
    assert not is_owner_process_alive(pid, 1.0)

    result = recover_execute_session(manager, "TASK-REUSE")
    assert result.action == RecoveryAction.RECOVERED
    assert not Path(session.path).exists()


def test_branch_only_with_dead_marker(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-BR")
    plan = derive_execute_path_plan(manager, "TASK-BR")

    manager.remove_worktree(session.path, force=True)
    # Directory gone; prune registration only.
    _git(repo, "worktree", "prune")
    assert manager._branch_exists(plan.branch)
    assert not Path(session.path).exists()
    _write_dead_marker(manager, "TASK-BR")

    result = recover_execute_session(manager, "TASK-BR")
    assert result.action == RecoveryAction.RECOVERED
    assert not manager._branch_exists(plan.branch)


def test_registration_without_directory_with_dead_marker(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-REG")
    plan = derive_execute_path_plan(manager, "TASK-REG")

    # Remove directory without git remove → prunable registration.
    import shutil

    shutil.rmtree(session.path)
    assert "prunable" in _worktree_porcelain(repo).casefold() or (
        plan.worktree_path.replace("\\", "/")
        in _worktree_porcelain(repo).replace("\\", "/")
    )
    _write_dead_marker(manager, "TASK-REG")

    result = recover_execute_session(manager, "TASK-REG")
    assert result.action == RecoveryAction.RECOVERED
    assert not manager._branch_exists(plan.branch)
    assert plan.worktree_path.replace("\\", "/") not in (
        _worktree_porcelain(repo).replace("\\", "/")
    )


def test_marker_only_cleanup(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    plan = derive_execute_path_plan(manager, "TASK-MARK")
    _write_dead_marker(manager, "TASK-MARK")
    marker = marker_path_for(
        plan.worktree_root,
        plan.repo_namespace,
        plan.task_id,
    )
    assert Path(marker).is_file()

    result = recover_execute_session(manager, "TASK-MARK")
    assert result.action == RecoveryAction.MARKER_ONLY
    assert not Path(marker).is_file()


def test_user_execute_my_test_branch_never_deleted(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    _git(repo, "branch", "execute/my-test")

    result = recover_execute_session(manager, "TASK-NOPE")
    assert result.action == RecoveryAction.NONE
    assert "execute/my-test" in _branches(repo, "execute/*")


def test_execute_task_branch_without_marker_not_auto_deleted(
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)
    _git(repo, "branch", "execute/TASK-X")

    result = recover_execute_session(manager, "TASK-X")
    assert result.action == RecoveryAction.UNOWNED_ARTIFACTS
    assert "execute/TASK-X" in _branches(repo, "execute/*")

    with pytest.raises(UnownedExecuteArtifactsError):
        ensure_execute_session_ready(manager, "TASK-X")


def test_agent_write_branch_untouched_by_execute_recovery(
    tmp_path,
):
    repo, wt_root, manager = _make_repo(tmp_path)
    write_wt = wt_root / "edusen" / "TASK-WRITE"
    write_wt.parent.mkdir(parents=True, exist_ok=True)
    _git(
        repo,
        "worktree",
        "add",
        "-b",
        "agent/TASK-WRITE",
        str(write_wt),
    )

    session = prepare_execute_worktree(manager, "TASK-EX")
    _write_dead_marker(manager, "TASK-EX")
    recover_execute_session(manager, "TASK-EX")

    assert manager._branch_exists("agent/TASK-WRITE")
    assert write_wt.exists()
    assert not Path(session.path).exists()


def test_different_task_not_affected(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    keep = prepare_execute_worktree(manager, "TASK-Y")
    crash = prepare_execute_worktree(manager, "TASK-X")
    _write_dead_marker(manager, "TASK-X")

    recover_execute_session(manager, "TASK-X")

    assert Path(keep.path).exists()
    assert manager._branch_exists("execute/TASK-Y")
    assert not Path(crash.path).exists()

    cleanup_execute_worktree(
        manager,
        path=keep.path,
        branch=keep.branch,
        task_id="TASK-Y",
    )


def test_malformed_marker_fail_closed(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    _git(repo, "branch", "execute/TASK-BAD")
    plan = derive_execute_path_plan(manager, "TASK-BAD")
    marker = Path(
        marker_path_for(
            plan.worktree_root,
            plan.repo_namespace,
            plan.task_id,
        )
    )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{not-json", encoding="utf-8")

    result = recover_execute_session(manager, "TASK-BAD")
    assert result.action == RecoveryAction.SKIPPED_INVALID
    assert "execute/TASK-BAD" in _branches(repo, "execute/*")
    assert marker.is_file()


def test_marker_path_escape_rejected(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    plan = derive_execute_path_plan(manager, "TASK-ESC")
    marker = Path(
        marker_path_for(
            plan.worktree_root,
            plan.repo_namespace,
            plan.task_id,
        )
    )
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "task_id": "TASK-ESC",
        "canonical_repo_root": plan.canonical_repo_root,
        "expected_branch": plan.branch,
        "expected_worktree_path": str(
            tmp_path / "outside" / "escape"
        ),
        "owner_pid": 1,
        "owner_process_create_time": 1.0,
        "created_at": "2020-01-01T00:00:00+00:00",
        "session_id": "abc",
    }
    marker.write_text(json.dumps(payload), encoding="utf-8")

    result = recover_execute_session(manager, "TASK-ESC")
    assert result.action == RecoveryAction.SKIPPED_INVALID


def test_startup_running_execute_dead_marker_marks_failed(
    tmp_path,
):
    repo, wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-RUN")
    _write_dead_marker(manager, "TASK-RUN")

    task = SimpleNamespace(
        task_id="TASK-RUN",
        state="running",
        status="running",
        project_id="proj-1",
        task_kind="execute",
    )
    logs: list[tuple[str, str]] = []
    interrupted: list[str] = []

    results = recover_stale_execute_markers(
        worktree_root=str(wt_root),
        get_task=lambda tid: task if tid == "TASK-RUN" else None,
        get_task_kind=lambda tid: "execute",
        get_project_path=lambda t: str(repo),
        mark_interrupted=lambda tid: interrupted.append(tid),
        append_log=lambda tid, msg: logs.append((tid, msg)),
    )

    assert any(
        r.action == RecoveryAction.RECOVERED for r in results
    )
    assert interrupted == ["TASK-RUN"]
    assert any(
        "interrupted" in msg.casefold() for _tid, msg in logs
    )
    assert not Path(session.path).exists()


def test_startup_live_owner_keeps_running(tmp_path):
    _repo, wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-ALIVE")

    task = SimpleNamespace(
        task_id="TASK-ALIVE",
        state="running",
        status="running",
        project_id="proj-1",
        task_kind="execute",
    )
    interrupted: list[str] = []

    results = recover_stale_execute_markers(
        worktree_root=str(wt_root),
        get_task=lambda tid: task if tid == "TASK-ALIVE" else None,
        get_task_kind=lambda tid: "execute",
        get_project_path=lambda t: str(_repo),
        mark_interrupted=lambda tid: interrupted.append(tid),
        append_log=lambda *_a: None,
    )

    assert any(r.action == RecoveryAction.ACTIVE for r in results)
    assert interrupted == []
    assert Path(session.path).exists()

    cleanup_execute_worktree(
        manager,
        path=session.path,
        branch=session.branch,
        task_id="TASK-ALIVE",
    )


def test_terminal_task_dead_marker_cleanup_keeps_state(tmp_path):
    repo, wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-DONE")
    _write_dead_marker(manager, "TASK-DONE")

    task = SimpleNamespace(
        task_id="TASK-DONE",
        state="failed",
        status="failed",
        project_id="proj-1",
        task_kind="execute",
    )
    interrupted: list[str] = []

    recover_stale_execute_markers(
        worktree_root=str(wt_root),
        get_task=lambda tid: task if tid == "TASK-DONE" else None,
        get_task_kind=lambda tid: "execute",
        get_project_path=lambda t: str(repo),
        mark_interrupted=lambda tid: interrupted.append(tid),
        append_log=lambda *_a: None,
    )

    assert interrupted == []
    assert task.state == "failed"
    assert not Path(session.path).exists()


def test_prepare_recovers_dead_marker_then_creates(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    stale = prepare_execute_worktree(manager, "TASK-PREP")
    _write_dead_marker(manager, "TASK-PREP")

    # Crash leftovers present; prepare must recover then recreate.
    session = prepare_execute_worktree(manager, "TASK-PREP")
    assert Path(session.path).exists()
    assert session.path == stale.path
    assert manager._branch_exists("execute/TASK-PREP")

    cleanup_execute_worktree(
        manager,
        path=session.path,
        branch=session.branch,
        task_id="TASK-PREP",
    )
    assert "execute/TASK-PREP" not in _branches(repo, "execute/*")


def test_prepare_rejects_live_marker(tmp_path):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-BUSY")

    with pytest.raises(ActiveExecuteSessionError):
        prepare_execute_worktree(manager, "TASK-BUSY")

    cleanup_execute_worktree(
        manager,
        path=session.path,
        branch=session.branch,
        task_id="TASK-BUSY",
    )


def test_worktree_already_exists_not_swallowed(tmp_path):
    repo, wt_root, manager = _make_repo(tmp_path)
    task_id = "TASK-DUP"
    created = manager.create_execute_worktree(task_id)

    # Directory removed; registration remains → must raise
    # WorktreeAlreadyExistsError (not swallowed into branch check).
    import shutil

    shutil.rmtree(created.path)
    porcelain = _worktree_porcelain(repo)
    assert created.path.replace("\\", "/") in porcelain.replace(
        "\\",
        "/",
    )

    with pytest.raises(WorktreeAlreadyExistsError):
        manager.create_execute_worktree(task_id)

    # Cleanup leftovers for the fixture.
    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(created.branch, force=True)


def test_write_create_worktree_already_exists_not_swallowed(
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)
    created = manager.create_worktree("TASK-W")
    import shutil

    shutil.rmtree(created.path)

    with pytest.raises(WorktreeAlreadyExistsError):
        manager.create_worktree("TASK-W")

    manager.remove_worktree(created.path, force=True)
    manager.delete_branch(created.branch, force=True)


def test_multi_backend_live_child_then_dead(tmp_path):
    """Real child process owns the marker; recovery must respect lease."""
    repo, wt_root, manager = _make_repo(tmp_path)
    task_id = "TASK-CHILD"
    plan = derive_execute_path_plan(manager, task_id)

    # Parent creates the execute worktree/branch artifacts.
    created = manager.create_execute_worktree(task_id)

    child_code = r"""
import json, os, sys, time
import psutil
from pathlib import Path

marker_path = Path(sys.argv[1])
payload_path = Path(sys.argv[2])
pid = os.getpid()
ct = psutil.Process(pid).create_time()
payload = json.loads(payload_path.read_text(encoding="utf-8"))
payload["owner_pid"] = pid
payload["owner_process_create_time"] = ct
marker_path.parent.mkdir(parents=True, exist_ok=True)
tmp = marker_path.with_suffix(".tmp")
tmp.write_text(json.dumps(payload), encoding="utf-8")
os.replace(tmp, marker_path)
# Signal ready
Path(sys.argv[3]).write_text("ready", encoding="utf-8")
while not Path(sys.argv[4]).exists():
    time.sleep(0.05)
"""
    marker = Path(
        marker_path_for(
            plan.worktree_root,
            plan.repo_namespace,
            plan.task_id,
        )
    )
    payload = {
        "version": 1,
        "task_id": task_id,
        "canonical_repo_root": plan.canonical_repo_root,
        "expected_branch": plan.branch,
        "expected_worktree_path": plan.worktree_path,
        "owner_pid": 0,
        "owner_process_create_time": 0.0,
        "created_at": "2020-01-01T00:00:00+00:00",
        "session_id": "child-session",
    }
    payload_file = tmp_path / "payload.json"
    ready_file = tmp_path / "ready.txt"
    stop_file = tmp_path / "stop.txt"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")

    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child_code,
            str(marker),
            str(payload_file),
            str(ready_file),
            str(stop_file),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={
            **os.environ,
            "PYTHONPATH": str(
                Path(__file__).resolve().parents[1]
            ),
        },
    )
    try:
        for _ in range(100):
            if ready_file.exists():
                break
            time.sleep(0.05)
        assert ready_file.exists(), "child did not write marker"

        # Live child → must not cleanup.
        with pytest.raises(ActiveExecuteSessionError):
            recover_execute_session(manager, task_id)
        assert Path(created.path).exists()
        assert marker.is_file()

        stop_file.write_text("stop", encoding="utf-8")
        child.wait(timeout=10)
        assert child.returncode == 0

        # Dead child → exact artifacts recovered.
        result = recover_execute_session(manager, task_id)
        assert result.action == RecoveryAction.RECOVERED
        assert not Path(created.path).exists()
        assert not marker.is_file()
        assert not manager._branch_exists(plan.branch)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_cleanup_failure_keeps_marker(tmp_path, monkeypatch):
    _repo, _wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(manager, "TASK-KEEP")
    plan = derive_execute_path_plan(manager, "TASK-KEEP")
    marker = Path(
        marker_path_for(
            plan.worktree_root,
            plan.repo_namespace,
            plan.task_id,
        )
    )
    assert marker.is_file()

    def boom(*_a, **_k):
        raise RuntimeError("remove blocked")

    monkeypatch.setattr(manager, "remove_worktree", boom)
    monkeypatch.setattr(manager, "delete_branch", boom)

    from factory.execute_worktree import ExecuteCleanupError

    with pytest.raises(ExecuteCleanupError):
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
            task_id="TASK-KEEP",
        )

    assert marker.is_file()

    # Finish with real cleanup after restoring methods via dead marker.
    _write_dead_marker(manager, "TASK-KEEP")
    # Manual force cleanup without going through broken monkeypatch:
    monkeypatch.undo()
    recover_execute_session(manager, "TASK-KEEP")
