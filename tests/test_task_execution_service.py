from types import SimpleNamespace

import api.app as app_module
from factory.task_execution_service import (
    TaskExecutionDeps,
    TaskExecutionService,
)


def _task(
    *,
    task_id="TASK-4001",
    prompt="implement feature",
    max_attempts=2,
):
    return SimpleNamespace(
        task_id=task_id,
        prompt=prompt,
        max_attempts=max_attempts,
        status="queued",
        state="queued",
        task_kind=None,
        model=None,
        attempt=0,
        test_result=None,
    )


def _allowed_gate(task_id):
    return {
        "task_id": task_id,
        "allowed": True,
        "state": "allowed",
        "graph_ids": [],
        "blocked_graphs": [],
        "failed_graphs": [],
        "pending_dependencies": [],
        "failed_dependencies": [],
    }


def _deps(
    *,
    task,
    tasks=None,
    logs=None,
    updates=None,
    cleanups=None,
    orchestrator=None,
    gate=None,
    release=None,
):
    tasks = tasks if tasks is not None else {
        task.task_id: task,
    }
    logs = logs if logs is not None else []
    updates = updates if updates is not None else []
    cleanups = cleanups if cleanups is not None else []

    if orchestrator is None:
        def _forbid_run_task(*a, **k):
            raise AssertionError(
                "Orchestrator.run_task "
                "must not be called"
            )

        orchestrator = SimpleNamespace(
            project_path="/repo",
            model_client=object(),
            git_manager=SimpleNamespace(
                repo_root="/repo",
            ),
            run_task=_forbid_run_task,
        )

    if gate is None:
        gate = lambda tid, _states: (
            _allowed_gate(tid)
        )

    if release is None:
        release = lambda _tid: []

    return TaskExecutionDeps(
        get_task=lambda tid: tasks.get(
            tid
        ),
        iter_tasks=lambda: tasks.items(),
        append_log=lambda tid, message: (
            logs.append((tid, message))
        ),
        update_runtime=(
            lambda tid, **kwargs: (
                updates.append(
                    (tid, kwargs)
                )
            )
        ),
        evaluate_gate=gate,
        build_orchestrator=lambda _task: (
            orchestrator
        ),
        approval_handler=(
            lambda *args, **kwargs: (
                "ready_for_approval"
            )
        ),
        progress_handler=(
            lambda *args, **kwargs: None
        ),
        cleanup_failed=(
            lambda orch, tid: (
                cleanups.append(
                    (orch, tid)
                )
            )
        ),
        release_dependents=release,
    ), logs, updates, cleanups, orchestrator


def _mock_execute_isolation(
    monkeypatch,
    *,
    worktree_path="/wt/execute-TASK",
    branch="execute/TASK",
):
    from factory.execute_worktree import (
        ExecuteWorktreeSession,
    )
    from factory.tools.git_ops import (
        GitWorkingTreeGuard,
    )

    prepare_calls = []
    cleanup_calls = []

    def fake_prepare(git_manager, task_id):
        prepare_calls.append(
            (git_manager, task_id)
        )
        return ExecuteWorktreeSession(
            task_id=task_id,
            branch=branch,
            path=worktree_path,
            repository_root="/repo",
            before_guard=GitWorkingTreeGuard(
                head_sha="abc",
                entries=(),
            ),
        )

    def fake_cleanup(
        git_manager,
        *,
        path,
        branch,
        task_id=None,
        remove_marker_on_success=True,
        **kwargs,
    ):
        cleanup_calls.append(
            {
                "git_manager": git_manager,
                "path": path,
                "branch": branch,
                "task_id": task_id,
            }
        )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "prepare_execute_worktree",
        fake_prepare,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "cleanup_execute_worktree",
        fake_cleanup,
    )
    return prepare_calls, cleanup_calls


def test_write_dispatches_to_execute_write_task(
    monkeypatch,
):
    task = _task(
        prompt="write a helper module",
    )
    deps, logs, updates, cleanups, orch = (
        _deps(task=task)
    )

    write_calls = []

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: (
            SimpleNamespace(
                kind="write",
                reason="write path",
                intent="implement",
                target="code",
                framework=None,
                confidence=0.9,
                source="test",
            )
        ),
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "save_task_route",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "get_task_model_preference",
        lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_model",
        lambda prompt: SimpleNamespace(
            model="fake-model",
            profile="test",
            reason="test",
            code_score=1,
        ),
    )

    def fake_write(**kwargs):
        write_calls.append(kwargs)
        assert not hasattr(
            kwargs["orchestrator"],
            "_run_task_called",
        )
        return (
            "ready_for_approval",
            {
                "planner_mode": "single_step",
                "steps": [],
            },
        )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "execute_write_task",
        fake_write,
    )

    result = TaskExecutionService(
        deps
    ).run(task.task_id)

    assert result == "ready_for_approval"
    assert len(write_calls) == 1
    assert write_calls[0]["task_id"] == (
        task.task_id
    )
    assert write_calls[0][
        "orchestrator"
    ] is orch
    assert cleanups == []
    assert any(
        "Planner modu: single_step"
        in message
        for _tid, message in logs
    )


def test_write_never_calls_orchestrator_run_task(
    monkeypatch,
):
    task = _task()
    run_task_calls = []

    orchestrator = SimpleNamespace(
        project_path="/repo",
        model_client=object(),
    )

    def run_task(*args, **kwargs):
        run_task_calls.append(
            (args, kwargs)
        )
        return "legacy"

    orchestrator.run_task = run_task

    deps, *_rest = _deps(
        task=task,
        orchestrator=orchestrator,
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: (
            SimpleNamespace(
                kind="write",
                reason="write",
                intent="implement",
                target="code",
                framework=None,
                confidence=1.0,
                source="test",
            )
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
        "execute_write_task",
        lambda **kwargs: (
            "ready_for_approval",
            {"planner_mode": "multi_step"},
        ),
    )

    TaskExecutionService(deps).run(
        task.task_id
    )

    assert run_task_calls == []


def test_read_dispatches_to_run_read_task(
    monkeypatch,
):
    task = _task(
        prompt="explain the router",
    )
    deps, logs, updates, cleanups, orch = (
        _deps(task=task)
    )
    read_calls = []

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: (
            SimpleNamespace(
                kind="read",
                reason="read path",
                intent="explain",
                target="code",
                framework=None,
                confidence=0.95,
                source="test",
            )
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
            model="reader",
            profile="p",
            reason="r",
            code_score=0,
        ),
    )

    def fake_read(**kwargs):
        read_calls.append(kwargs)
        return "READ RESULT"

    monkeypatch.setattr(
        "factory.task_execution_service."
        "run_read_task",
        fake_read,
    )
    monkeypatch.setattr(
        "factory.task_execution_service."
        "save_task_read_result",
        lambda *a, **k: None,
    )

    result = TaskExecutionService(
        deps
    ).run(task.task_id)

    assert result is None
    assert len(read_calls) == 1
    assert read_calls[0][
        "project_path"
    ] == orch.project_path
    assert (
        "status",
        "completed",
    ) in [
        (k, v)
        for _tid, kwargs in updates
        for k, v in kwargs.items()
    ]
    assert cleanups == []


def test_execute_dispatches_to_agent_terminal_loop(
    monkeypatch,
):
    task = _task(
        prompt="install requests package",
    )
    deps, logs, updates, cleanups, orch = (
        _deps(task=task)
    )
    terminal_calls = []
    legacy_calls = []
    prepare_calls, isolation_cleanups = (
        _mock_execute_isolation(
            monkeypatch,
            worktree_path="/wt/execute-TASK-4001",
            branch="execute/TASK-4001",
        )
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: (
            SimpleNamespace(
                kind="execute",
                reason="execute path",
                intent="package_install",
                target="requests",
                framework=None,
                confidence=0.99,
                source="test",
            )
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
            model="agent-model",
            profile="code",
            reason="selected for execute",
            code_score=1,
        ),
    )

    def fake_terminal(**kwargs):
        terminal_calls.append(kwargs)
        return SimpleNamespace(
            status="completed",
            summary="EXECUTE OK",
            reason="done",
            steps_used=2,
            commands_executed=1,
            successful_commands=1,
            failed_commands=0,
            rejected_commands=0,
            last_observation=None,
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

    # Legacy runner must not be imported/called.
    import factory.execute_task_runner as legacy

    monkeypatch.setattr(
        legacy,
        "run_execute_task",
        lambda **kwargs: legacy_calls.append(kwargs),
    )

    result = TaskExecutionService(
        deps
    ).run(task.task_id)

    assert result is None
    assert legacy_calls == []
    assert len(prepare_calls) == 1
    assert prepare_calls[0][1] == task.task_id
    assert len(terminal_calls) == 1
    call = terminal_calls[0]
    assert call["project_path"] == (
        "/wt/execute-TASK-4001"
    )
    assert call["project_path"] != (
        orch.project_path
    )
    assert call["task_id"] == task.task_id
    assert call["prompt"] == task.prompt
    assert call["model_route"].model == "agent-model"
    assert call["model_client"] is orch.model_client
    assert call["policy"].allow_mutating is True
    assert call["policy"].allow_git_mutation is False
    assert call["route_context"].intent == (
        "package_install"
    )
    assert len(isolation_cleanups) == 1
    assert isolation_cleanups[0]["path"] == (
        "/wt/execute-TASK-4001"
    )
    assert isolation_cleanups[0]["branch"] == (
        "execute/TASK-4001"
    )
    assert any(
        kwargs.get("model") == "agent-model"
        for _tid, kwargs in updates
    )
    assert any(
        "Agent Terminal Model: agent-model" in message
        for _tid, message in logs
    )
    assert any(
        message == "Agent Terminal baslatildi."
        for _tid, message in logs
    )
    assert any(
        "Agent Terminal tamamlandi:" in message
        for _tid, message in logs
    )
    assert any(
        "were not applied to the main project"
        in message
        for _tid, message in logs
    )
    assert (
        task.task_id,
        {
            "status": "completed",
            "state": "completed",
            "test_result": "not_required",
        },
    ) in updates


def test_execute_terminal_stalled_marks_failed(
    monkeypatch,
):
    task = _task(prompt="run checks")
    deps, logs, updates, cleanups, orch = (
        _deps(task=task)
    )
    _prepare, isolation_cleanups = (
        _mock_execute_isolation(monkeypatch)
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: (
            SimpleNamespace(
                kind="execute",
                reason="execute path",
                intent="check",
                target=None,
                framework=None,
                confidence=0.9,
                source="test",
            )
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
        lambda *a, **k: "manual-model",
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "run_agent_terminal_loop",
        lambda **kwargs: SimpleNamespace(
            status="stalled",
            summary="stuck",
            reason="stall_identical_command",
            steps_used=3,
            commands_executed=2,
            successful_commands=0,
            failed_commands=2,
            rejected_commands=0,
            last_observation=None,
        ),
    )

    result = TaskExecutionService(
        deps
    ).run(task.task_id)

    assert result is None
    assert any(
        kwargs.get("model") == "manual-model"
        for _tid, kwargs in updates
    )
    assert (
        task.task_id,
        {
            "status": "failed",
            "state": "failed",
        },
    ) in updates
    assert any(
        "Agent Terminal stalled: "
        "stall_identical_command" in message
        for _tid, message in logs
    )
    assert cleanups == []
    assert len(isolation_cleanups) == 1


def test_write_failure_cleans_up_and_marks_failed(
    monkeypatch,
):
    task = _task()
    deps, logs, updates, cleanups, orch = (
        _deps(task=task)
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: (
            SimpleNamespace(
                kind="write",
                reason="write",
                intent="implement",
                target="code",
                framework=None,
                confidence=1.0,
                source="test",
            )
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

    def boom(**kwargs):
        raise RuntimeError("write failed")

    monkeypatch.setattr(
        "factory.task_execution_service."
        "execute_write_task",
        boom,
    )

    result = TaskExecutionService(
        deps
    ).run(task.task_id)

    assert result is None
    assert cleanups == [
        (orch, task.task_id)
    ]
    assert (
        task.task_id,
        {
            "status": "failed",
            "state": "failed",
        },
    ) in updates


def test_graph_gate_blocked_skips_dispatch(
    monkeypatch,
):
    task = _task(task_id="TASK-4002")
    routed = []

    deps, logs, updates, cleanups, _orch = (
        _deps(
            task=task,
            gate=lambda tid, _states: {
                "task_id": tid,
                "allowed": False,
                "state": "blocked",
                "graph_ids": ["G1"],
                "blocked_graphs": ["G1"],
                "failed_graphs": [],
                "pending_dependencies": [
                    "TASK-4000"
                ],
                "failed_dependencies": [],
            },
        )
    )

    def fail_if_routed(*_args, **_kwargs):
        routed.append(True)
        raise AssertionError(
            "router must not run"
        )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        fail_if_routed,
    )

    result = TaskExecutionService(
        deps
    ).run(task.task_id)

    assert result is None
    assert routed == []
    assert updates == [
        (
            task.task_id,
            {
                "status": "queued",
                "state": "blocked",
            },
        )
    ]


def test_run_task_for_api_uses_service(
    monkeypatch,
):
    calls = []

    class FakeService:
        def __init__(self, deps):
            calls.append(("init", deps))

        def run(self, task_id):
            calls.append(("run", task_id))
            return "service-result"

    monkeypatch.setattr(
        app_module,
        "TaskExecutionService",
        FakeService,
    )

    result = app_module.run_task_for_api(
        "TASK-4099"
    )

    assert result == "service-result"
    assert calls[0][0] == "init"
    assert isinstance(
        calls[0][1],
        TaskExecutionDeps,
    )
    assert calls[1] == (
        "run",
        "TASK-4099",
    )
