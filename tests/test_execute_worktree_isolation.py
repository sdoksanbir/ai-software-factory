"""Regression: EXECUTE disposable worktree isolation.

Main repository must never be mutated by EXECUTE materialization
or by commands that run inside the isolated worktree.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from factory.execute_worktree import (
    ExecuteConcurrencyError,
    ExecuteConflictError,
    cleanup_execute_worktree,
    prepare_execute_worktree,
)
from factory.task_execution_service import (
    TaskExecutionDeps,
    TaskExecutionService,
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


def _snapshot_main(repo: Path) -> dict:
    head = _git_out(repo, "rev-parse", "HEAD")
    status = _git_out(repo, "status", "--porcelain")
    tracked = {}
    for rel in _git_out(
        repo,
        "ls-files",
        "-z",
    ).split("\0"):
        if not rel:
            continue
        tracked[rel] = (repo / rel).read_bytes()
    staged = _git(
        repo,
        "diff",
        "--cached",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-renames",
        "HEAD",
        "--",
    ).stdout
    unstaged = _git(
        repo,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-renames",
        "--",
    ).stdout
    untracked = {}
    raw = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    for part in raw.split(b"\0"):
        if not part:
            continue
        rel = part.decode("utf-8", errors="surrogateescape")
        untracked[rel] = (repo / rel).read_bytes()
    return {
        "head": head,
        "status": status,
        "tracked": tracked,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
    }


def _make_repo(tmp_path: Path) -> tuple[Path, Path, GitWorktreeManager]:
    repo = tmp_path / "edusen"
    wt_root = tmp_path / "AI-Worktrees"
    repo.mkdir()
    wt_root.mkdir()
    _init_git_repo(repo)

    (repo / "source.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (repo / "script.py").write_text(
        "from pathlib import Path\n"
        "Path('generated.txt').write_text('hi', encoding='utf-8')\n",
        encoding="utf-8",
    )
    _git(repo, "add", "source.py", "script.py")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "main")

    manager = GitWorktreeManager(str(repo), str(wt_root))
    return repo, wt_root, manager


def test_prepare_clean_main_generated_txt_stays_isolated(
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)

    session = prepare_execute_worktree(
        manager,
        "TASK-GEN",
    )
    try:
        assert Path(session.path).is_dir()
        assert session.branch == "execute/TASK-GEN"
        assert "execute-TASK-GEN" in session.path

        # Simulate EXECUTE command writing generated.txt
        generated = Path(session.path) / "generated.txt"
        generated.write_text("hi", encoding="utf-8")
        assert generated.exists()
        assert not (repo / "generated.txt").exists()
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )

    after = _snapshot_main(repo)
    assert after == before
    assert not (repo / "generated.txt").exists()
    assert not Path(session.path).exists()
    assert not manager._branch_exists(session.branch)


def test_tracked_modify_and_delete_do_not_touch_main(
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)

    session = prepare_execute_worktree(
        manager,
        "TASK-MUT",
    )
    try:
        wt = Path(session.path)
        (wt / "source.py").write_text(
            "VALUE = 999\n",
            encoding="utf-8",
        )
        (wt / "script.py").unlink()
        assert (repo / "source.py").read_text(
            encoding="utf-8"
        ) == "VALUE = 1\n"
        assert (repo / "script.py").is_file()
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )

    after = _snapshot_main(repo)
    assert after == before


def test_preexisting_dirty_main_is_materialized(
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)

    (repo / "source.py").write_text(
        "VALUE = dirty\n",
        encoding="utf-8",
    )
    (repo / "local-data.txt").write_text(
        "local\n",
        encoding="utf-8",
    )
    before = _snapshot_main(repo)
    assert "M source.py" in before["status"] or (
        " M source.py" in before["status"]
    )
    assert "?? local-data.txt" in before["status"]

    session = prepare_execute_worktree(
        manager,
        "TASK-DIRTY",
    )
    try:
        wt = Path(session.path)
        assert (wt / "source.py").read_text(
            encoding="utf-8"
        ) == "VALUE = dirty\n"
        assert (wt / "local-data.txt").read_text(
            encoding="utf-8"
        ) == "local\n"
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )

    after = _snapshot_main(repo)
    assert after == before


def test_staged_plus_unstaged_materialization(
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)

    (repo / "source.py").write_text(
        "VALUE = staged\n",
        encoding="utf-8",
    )
    _git(repo, "add", "source.py")
    (repo / "source.py").write_text(
        "VALUE = unstaged\n",
        encoding="utf-8",
    )
    before = _snapshot_main(repo)

    session = prepare_execute_worktree(
        manager,
        "TASK-STAGE",
    )
    try:
        wt = Path(session.path)
        assert (wt / "source.py").read_text(
            encoding="utf-8"
        ) == "VALUE = unstaged\n"
        # Staged blob in index should still be staged content.
        staged_blob = subprocess.run(
            ["git", "show", ":source.py"],
            cwd=wt,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
        assert staged_blob == "VALUE = staged\n"
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )

    after = _snapshot_main(repo)
    assert after == before


def test_concurrency_during_materialization_fails_closed(
    tmp_path,
    monkeypatch,
):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)

    def mutate_main():
        (repo / "race.txt").write_text(
            "race\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "factory.execute_worktree."
        "_post_materialize_before_guard_recheck",
        mutate_main,
    )

    with pytest.raises(ExecuteConcurrencyError) as exc:
        prepare_execute_worktree(
            manager,
            "TASK-RACE",
        )

    assert "retry" in str(exc.value).casefold()
    after = _snapshot_main(repo)
    # User edit preserved; no reset/clean of race.txt.
    assert (repo / "race.txt").read_text(
        encoding="utf-8"
    ) == "race\n"
    assert after["head"] == before["head"]
    assert not manager._branch_exists(
        "execute/TASK-RACE"
    )
    expected_path = (
        Path(manager.worktree_root)
        / "edusen"
        / "execute-TASK-RACE"
    )
    assert not expected_path.exists()


def test_unmerged_main_fails_closed(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)

    _git(repo, "checkout", "-b", "side")
    (repo / "source.py").write_text(
        "VALUE = side\n",
        encoding="utf-8",
    )
    _git(repo, "add", "source.py")
    _git(repo, "commit", "-m", "side")
    _git(repo, "checkout", "main")
    (repo / "source.py").write_text(
        "VALUE = main\n",
        encoding="utf-8",
    )
    _git(repo, "add", "source.py")
    _git(repo, "commit", "-m", "main conflict")

    merge = subprocess.run(
        ["git", "merge", "side"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0

    before_head = _git_out(repo, "rev-parse", "HEAD")
    before_status = _git_out(
        repo,
        "status",
        "--porcelain",
    )

    with pytest.raises(ExecuteConflictError) as exc:
        prepare_execute_worktree(
            manager,
            "TASK-CONFLICT",
        )

    assert "unresolved" in str(exc.value).casefold()
    assert _git_out(repo, "rev-parse", "HEAD") == (
        before_head
    )
    assert _git_out(
        repo,
        "status",
        "--porcelain",
    ) == before_status


def test_git_add_commit_inside_execute_stays_isolated(
    tmp_path,
):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)

    session = prepare_execute_worktree(
        manager,
        "TASK-GIT",
    )
    try:
        wt = Path(session.path)
        (wt / "extra.txt").write_text(
            "x\n",
            encoding="utf-8",
        )
        _git(wt, "add", "extra.txt")
        _git(wt, "commit", "-m", "execute commit")
        execute_head = _git_out(wt, "rev-parse", "HEAD")
        assert execute_head != before["head"]
        assert _git_out(
            repo,
            "rev-parse",
            "HEAD",
        ) == before["head"]
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )

    after = _snapshot_main(repo)
    assert after == before
    assert not manager._branch_exists(
        "execute/TASK-GIT"
    )


def test_pytest_cache_does_not_leak_to_main(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)

    session = prepare_execute_worktree(
        manager,
        "TASK-CACHE",
    )
    try:
        cache = (
            Path(session.path)
            / ".pytest_cache"
            / "v"
            / "cache"
        )
        cache.mkdir(parents=True)
        (cache / "nodeids").write_text(
            "[]\n",
            encoding="utf-8",
        )
        assert not (
            repo / ".pytest_cache"
        ).exists()
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )

    after = _snapshot_main(repo)
    assert after == before
    assert not (repo / ".pytest_cache").exists()


def test_service_passes_worktree_to_terminal_and_cleans(
    tmp_path,
    monkeypatch,
):
    repo, wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)

    task = SimpleNamespace(
        task_id="TASK-SVC",
        prompt="run script",
        max_attempts=2,
        status="queued",
        state="queued",
        task_kind=None,
        model=None,
        attempt=0,
        test_result=None,
    )

    orch = SimpleNamespace(
        project_path=str(repo),
        worktree_root=str(wt_root),
        model_client=object(),
        git_manager=manager,
    )

    logs = []
    updates = []
    terminal_paths = []

    def fake_terminal(**kwargs):
        terminal_paths.append(kwargs["project_path"])
        path = Path(kwargs["project_path"])
        assert path != Path(repo)
        (path / "generated.txt").write_text(
            "from-execute\n",
            encoding="utf-8",
        )
        # Host-safe style check: worktree is the cwd root.
        assert (path / "source.py").is_file()
        return SimpleNamespace(
            status="completed",
            summary="ok",
            reason="ok",
            steps_used=1,
            commands_executed=1,
            successful_commands=1,
            failed_commands=0,
            rejected_commands=0,
            last_observation=None,
        )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: SimpleNamespace(
            kind="execute",
            reason="execute",
            intent="run_tests",
            target=None,
            framework=None,
            confidence=1.0,
            source="test",
        ),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "save_task_route",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "get_task_model_preference",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_model",
        lambda prompt: SimpleNamespace(
            model="m",
            profile="p",
            reason="r",
            code_score=1,
        ),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "run_agent_terminal_loop",
        fake_terminal,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "save_task_read_result",
        lambda *a, **k: None,
    )

    deps = TaskExecutionDeps(
        get_task=lambda tid: task,
        iter_tasks=lambda: [(task.task_id, task)],
        append_log=lambda tid, message: logs.append(
            (tid, message)
        ),
        update_runtime=lambda tid, **kwargs: updates.append(
            (tid, kwargs)
        ),
        evaluate_gate=lambda tid, _s: {
            "task_id": tid,
            "allowed": True,
            "state": "allowed",
            "graph_ids": [],
            "blocked_graphs": [],
            "failed_graphs": [],
            "pending_dependencies": [],
            "failed_dependencies": [],
        },
        build_orchestrator=lambda _t: orch,
        approval_handler=lambda *a, **k: None,
        progress_handler=lambda *a, **k: None,
        cleanup_failed=lambda *a, **k: None,
        release_dependents=lambda _tid: [],
    )

    TaskExecutionService(deps).run(task.task_id)

    assert len(terminal_paths) == 1
    assert "execute-TASK-SVC" in terminal_paths[0]
    assert not (repo / "generated.txt").exists()
    assert not Path(terminal_paths[0]).exists()
    assert not manager._branch_exists(
        "execute/TASK-SVC"
    )
    after = _snapshot_main(repo)
    assert after == before
    assert any(
        "were not applied to the main project"
        in message
        for _tid, message in logs
    )


def test_service_cleans_up_when_terminal_raises(
    tmp_path,
    monkeypatch,
):
    repo, wt_root, manager = _make_repo(tmp_path)
    before = _snapshot_main(repo)

    task = SimpleNamespace(
        task_id="TASK-FAIL",
        prompt="boom",
        max_attempts=2,
        status="queued",
        state="queued",
        task_kind=None,
        model=None,
        attempt=0,
        test_result=None,
    )
    orch = SimpleNamespace(
        project_path=str(repo),
        worktree_root=str(wt_root),
        model_client=object(),
        git_manager=manager,
    )
    seen = {}

    def boom(**kwargs):
        seen["path"] = kwargs["project_path"]
        raise RuntimeError("terminal exploded")

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: SimpleNamespace(
            kind="execute",
            reason="execute",
            intent="run_tests",
            target=None,
            framework=None,
            confidence=1.0,
            source="test",
        ),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "save_task_route",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "get_task_model_preference",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_model",
        lambda prompt: SimpleNamespace(
            model="m",
            profile="p",
            reason="r",
            code_score=1,
        ),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "run_agent_terminal_loop",
        boom,
    )

    logs = []
    updates = []
    deps = TaskExecutionDeps(
        get_task=lambda tid: task,
        iter_tasks=lambda: [(task.task_id, task)],
        append_log=lambda tid, message: logs.append(
            (tid, message)
        ),
        update_runtime=lambda tid, **kwargs: updates.append(
            (tid, kwargs)
        ),
        evaluate_gate=lambda tid, _s: {
            "task_id": tid,
            "allowed": True,
            "state": "allowed",
            "graph_ids": [],
            "blocked_graphs": [],
            "failed_graphs": [],
            "pending_dependencies": [],
            "failed_dependencies": [],
        },
        build_orchestrator=lambda _t: orch,
        approval_handler=lambda *a, **k: None,
        progress_handler=lambda *a, **k: None,
        cleanup_failed=lambda *a, **k: None,
        release_dependents=lambda _tid: [],
    )

    TaskExecutionService(deps).run(task.task_id)

    assert "path" in seen
    assert not Path(seen["path"]).exists()
    assert not manager._branch_exists(
        "execute/TASK-FAIL"
    )
    after = _snapshot_main(repo)
    assert after == before
    assert (
        task.task_id,
        {"status": "failed", "state": "failed"},
    ) in updates


def test_read_route_does_not_create_execute_worktree(
    tmp_path,
    monkeypatch,
):
    repo, wt_root, manager = _make_repo(tmp_path)
    prepare_calls = []

    task = SimpleNamespace(
        task_id="TASK-READ",
        prompt="explain source.py",
        max_attempts=2,
        status="queued",
        state="queued",
        task_kind=None,
        model=None,
        attempt=0,
        test_result=None,
        related_task_id=None,
    )
    orch = SimpleNamespace(
        project_path=str(repo),
        worktree_root=str(wt_root),
        model_client=object(),
        git_manager=manager,
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "prepare_execute_worktree",
        lambda *a, **k: prepare_calls.append(True),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: SimpleNamespace(
            kind="read",
            reason="read",
            intent="explain_or_inspect",
            target=None,
            framework=None,
            confidence=1.0,
            source="test",
        ),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "save_task_route",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "get_task_model_preference",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_model",
        lambda prompt: SimpleNamespace(
            model="m",
            profile="p",
            reason="r",
            code_score=0,
        ),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "run_read_task",
        lambda **kwargs: "ok",
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "save_task_read_result",
        lambda *a, **k: None,
    )

    deps = TaskExecutionDeps(
        get_task=lambda tid: task,
        iter_tasks=lambda: [(task.task_id, task)],
        append_log=lambda *a, **k: None,
        update_runtime=lambda *a, **k: None,
        evaluate_gate=lambda tid, _s: {
            "task_id": tid,
            "allowed": True,
            "state": "allowed",
            "graph_ids": [],
            "blocked_graphs": [],
            "failed_graphs": [],
            "pending_dependencies": [],
            "failed_dependencies": [],
        },
        build_orchestrator=lambda _t: orch,
        approval_handler=lambda *a, **k: None,
        progress_handler=lambda *a, **k: None,
        cleanup_failed=lambda *a, **k: None,
        release_dependents=lambda _tid: [],
    )

    TaskExecutionService(deps).run(task.task_id)
    assert prepare_calls == []


def test_write_route_still_uses_execute_write_task(
    monkeypatch,
    tmp_path,
):
    repo, wt_root, manager = _make_repo(tmp_path)
    write_calls = []
    prepare_calls = []

    task = SimpleNamespace(
        task_id="TASK-WRITE",
        prompt="implement feature",
        max_attempts=2,
        status="queued",
        state="queued",
        task_kind=None,
        model=None,
        attempt=0,
        test_result=None,
    )
    orch = SimpleNamespace(
        project_path=str(repo),
        worktree_root=str(wt_root),
        model_client=object(),
        git_manager=manager,
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "prepare_execute_worktree",
        lambda *a, **k: prepare_calls.append(True),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: SimpleNamespace(
            kind="write",
            reason="write",
            intent="code_change",
            target=None,
            framework=None,
            confidence=1.0,
            source="test",
        ),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "save_task_route",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "get_task_model_preference",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_model",
        lambda prompt: SimpleNamespace(
            model="m",
            profile="p",
            reason="r",
            code_score=1,
        ),
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "execute_write_task",
        lambda **kwargs: (
            write_calls.append(kwargs),
            (
                "ready_for_approval",
                {"planner_mode": "single_step"},
            ),
        )[1],
    )

    deps = TaskExecutionDeps(
        get_task=lambda tid: task,
        iter_tasks=lambda: [(task.task_id, task)],
        append_log=lambda *a, **k: None,
        update_runtime=lambda *a, **k: None,
        evaluate_gate=lambda tid, _s: {
            "task_id": tid,
            "allowed": True,
            "state": "allowed",
            "graph_ids": [],
            "blocked_graphs": [],
            "failed_graphs": [],
            "pending_dependencies": [],
            "failed_dependencies": [],
        },
        build_orchestrator=lambda _t: orch,
        approval_handler=lambda *a, **k: (
            "ready_for_approval"
        ),
        progress_handler=lambda *a, **k: None,
        cleanup_failed=lambda *a, **k: None,
        release_dependents=lambda _tid: [],
    )

    result = TaskExecutionService(deps).run(
        task.task_id
    )
    assert result == "ready_for_approval"
    assert prepare_calls == []
    assert len(write_calls) == 1


def test_docker_mount_root_is_execute_worktree(
    tmp_path,
):
    """PROJECT_CODE_SANDBOX receives execute worktree as project_root."""
    from factory.task_command_sandbox import (
        build_docker_run_argv,
    )
    from factory.task_command_models import (
        NetworkPolicy,
    )

    repo, _wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(
        manager,
        "TASK-DOCKER",
    )
    try:
        docker_argv = build_docker_run_argv(
            project_root=Path(session.path),
            workdir=Path(session.path),
            container_argv=["python", "script.py"],
            network_policy=NetworkPolicy.NETWORK_NONE,
            container_name="ai-factory-taskcmd-test",
        )
        volume = f"{Path(session.path).resolve()}:/app"
        assert volume in docker_argv
        main_volume = f"{Path(repo).resolve()}:/app"
        assert main_volume not in docker_argv
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )


def test_host_safe_cwd_is_execute_worktree(tmp_path):
    from factory.task_command_runner import (
        resolve_command_cwd,
    )

    repo, _wt_root, manager = _make_repo(tmp_path)
    session = prepare_execute_worktree(
        manager,
        "TASK-HOST",
    )
    try:
        cwd = resolve_command_cwd(
            Path(session.path),
            None,
        )
        assert cwd == Path(session.path).resolve()
        assert cwd != Path(repo).resolve()
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )


def test_execute_branch_not_merged_to_main(tmp_path):
    repo, _wt_root, manager = _make_repo(tmp_path)
    before_head = _git_out(repo, "rev-parse", "HEAD")

    session = prepare_execute_worktree(
        manager,
        "TASK-NOMERGE",
    )
    try:
        wt = Path(session.path)
        (wt / "only-execute.txt").write_text(
            "x\n",
            encoding="utf-8",
        )
        _git(wt, "add", "only-execute.txt")
        _git(wt, "commit", "-m", "isolated")
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )

    assert _git_out(repo, "rev-parse", "HEAD") == (
        before_head
    )
    assert not (repo / "only-execute.txt").exists()
    branches = _git_out(repo, "branch")
    assert "execute/TASK-NOMERGE" not in branches


def _repo_wide_snapshot(repo: Path) -> dict:
    config = (repo / '.git' / 'config').read_text(encoding='utf-8')
    return {
        'head': _git_out(repo, 'rev-parse', 'HEAD'),
        'status': _git_out(repo, 'status', '--porcelain'),
        'branches': _git_out(repo, 'branch'),
        'tags': _git_out(repo, 'tag'),
        'stash': _git_out(repo, 'stash', 'list'),
        'config': config,
        'worktrees': _git_out(repo, 'worktree', 'list'),
        'remotes': _git_out(repo, 'remote', '-v'),
    }


def test_execute_policy_rejects_git_mutations_before_subprocess(
    tmp_path,
):
    from factory.task_command_models import TaskCommandRequest
    from factory.task_command_runner import (
        GIT_MUTATION_REJECTED_MESSAGE,
        run_task_command,
    )
    from factory.agent_terminal_models import (
        build_execute_terminal_policy,
    )

    repo, _wt_root, manager = _make_repo(tmp_path)
    (repo / 'user.txt').write_text('keep\n', encoding='utf-8')
    _git(repo, 'add', 'user.txt')
    _git(repo, 'stash', 'push', '-m', 'user-preexisting')

    policy = build_execute_terminal_policy()
    assert policy.allow_mutating is True
    assert policy.allow_git_mutation is False

    session = prepare_execute_worktree(manager, 'TASK-GITLOCK')
    before = _repo_wide_snapshot(repo)
    # Temporary execute branch is expected while session lives.
    assert 'execute/TASK-GITLOCK' in before['branches']

    mutating = [
        ['git', 'branch', 'leaked-branch'],
        ['git', 'tag', 'leaked-tag'],
        ['git', 'stash', 'push', '-m', 'execute-leak'],
        ['git', 'config', '--local', 'test.execute', 'leaked'],
        ['git', 'remote', 'add', 'leaked', 'https://example.com/r.git'],
        ['git', 'update-ref', 'refs/heads/leaked-ref', 'HEAD'],
        ['git', 'add', '.'],
        ['git', 'commit', '-m', 'should-not-run'],
        ['git', 'checkout', 'main'],
        ['git', 'switch', 'main'],
        ['git', 'reset'],
        ['git', 'restore', 'source.py'],
    ]

    try:
        for argv in mutating:
            result = run_task_command(
                project_path=session.path,
                request=TaskCommandRequest(
                    task_id='TASK-GITLOCK',
                    argv=argv,
                    allow_mutating=policy.allow_mutating,
                    allow_git_mutation=policy.allow_git_mutation,
                ),
                persist=False,
            )
            assert result.status == 'rejected', argv
            assert GIT_MUTATION_REJECTED_MESSAGE in result.stderr

        # SAFE git still works under execute policy.
        safe = run_task_command(
            project_path=session.path,
            request=TaskCommandRequest(
                task_id='TASK-GITLOCK',
                argv=['git', 'branch', '--show-current'],
                allow_mutating=True,
                allow_git_mutation=False,
            ),
            persist=False,
        )
        assert safe.status == 'succeeded'
        assert 'execute/TASK-GITLOCK' in safe.stdout

        after = _repo_wide_snapshot(repo)
        assert after['head'] == before['head']
        assert after['status'] == before['status']
        assert after['tags'] == before['tags']
        assert after['stash'] == before['stash']
        assert after['config'] == before['config']
        assert after['remotes'] == before['remotes']
        assert 'leaked-branch' not in after['branches']
        assert 'leaked-tag' not in after['tags']
        assert 'leaked-ref' not in _git_out(repo, 'show-ref')
        assert 'test.execute' not in after['config']
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )

    final = _repo_wide_snapshot(repo)
    assert 'execute/TASK-GITLOCK' not in final['branches']
    assert 'leaked-branch' not in final['branches']
    assert final['tags'] == ''
    assert 'user-preexisting' in final['stash']
    assert 'execute-leak' not in final['stash']
    assert 'test.execute' not in final['config']


def test_execute_policy_still_allows_python_filesystem_mutation(
    tmp_path,
):
    from factory.task_command_models import TaskCommandRequest
    from factory.task_command_runner import run_task_command
    from factory.agent_terminal_models import (
        build_execute_terminal_policy,
    )

    repo, _wt_root, manager = _make_repo(tmp_path)
    policy = build_execute_terminal_policy()
    session = prepare_execute_worktree(manager, 'TASK-FS')
    before = _snapshot_main(repo)
    try:
        result = run_task_command(
            project_path=session.path,
            request=TaskCommandRequest(
                task_id='TASK-FS',
                argv=['python', 'script.py'],
                allow_mutating=policy.allow_mutating,
                allow_git_mutation=policy.allow_git_mutation,
            ),
            persist=False,
        )
        # May succeed or fail if Docker unavailable; must not be
        # rejected by git-mutation gate.
        assert result.status != 'rejected'
        if result.status == 'succeeded':
            assert (Path(session.path) / 'generated.txt').exists()
        assert not (repo / 'generated.txt').exists()
    finally:
        cleanup_execute_worktree(
            manager,
            path=session.path,
            branch=session.branch,
        )
    assert _snapshot_main(repo) == before
    assert not (repo / 'generated.txt').exists()
