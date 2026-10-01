from types import SimpleNamespace

from factory.task_execution_dispatcher import (
    execute_write_task,
)


class FakeOrchestrator:
    def __init__(self):
        self.model_client = object()
        self.legacy_calls = []

    def run_task(self, prompt, **kwargs):
        self.legacy_calls.append(
            (prompt, kwargs)
        )
        return "legacy-result"


def _model_route():
    return SimpleNamespace(
        model="fake-model",
        profile="test",
        reason="test",
        code_score=1,
    )


def test_single_step_uses_agent_pipeline(
    monkeypatch,
):
    orchestrator = FakeOrchestrator()

    saved = []

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "build_task_plan",
        lambda *args, **kwargs: {
            "summary": "Simple",
            "planner_mode": "single_step",
            "steps": [
                {
                    "title": "Write",
                    "instruction": "Write file",
                    "kind": "write",
                    "status": "pending",
                    "attempt": 0,
                }
            ],
        },
    )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "save_task_plan",
        lambda *args, **kwargs: (
            saved.append((args, kwargs))
        ),
    )

    multi_calls = []

    def fake_multi(**kwargs):
        multi_calls.append(kwargs)
        return "ready_for_approval"

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "run_multi_step_task",
        fake_multi,
    )

    result, plan = execute_write_task(
        orchestrator=orchestrator,
        prompt="Simple write",
        task_id="TASK-3201",
        max_attempts=2,
        model_route=_model_route(),
    )

    assert result == "ready_for_approval"
    assert len(multi_calls) == 1
    assert orchestrator.legacy_calls == []
    assert [
        step["kind"]
        for step in plan["steps"]
    ] == [
        "write",
        "verify",
    ]
    assert saved
    assert saved[-1][0][1][-1]["kind"] == "verify"


def test_multi_step_uses_new_runner(
    monkeypatch,
):
    orchestrator = FakeOrchestrator()

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "build_task_plan",
        lambda *args, **kwargs: {
            "summary": "Complex",
            "planner_mode": "multi_step",
            "steps": [
                {
                    "title": "Read",
                    "instruction": "Inspect",
                    "kind": "read",
                    "status": "pending",
                    "attempt": 0,
                },
                {
                    "title": "Write",
                    "instruction": "Implement",
                    "kind": "write",
                    "status": "pending",
                    "attempt": 0,
                },
                {
                    "title": "Verify",
                    "instruction": "Verify",
                    "kind": "verify",
                    "status": "pending",
                    "attempt": 0,
                },
            ],
        },
    )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "save_task_plan",
        lambda *args, **kwargs: None,
    )

    captured = {}

    def fake_multi(**kwargs):
        captured.update(kwargs)
        return "ready_for_approval"

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "run_multi_step_task",
        fake_multi,
    )

    result, plan = execute_write_task(
        orchestrator=orchestrator,
        prompt="Complex write",
        task_id="TASK-3202",
        max_attempts=3,
        model_route=_model_route(),
    )

    assert result == (
        "ready_for_approval"
    )

    assert plan["planner_mode"] == (
        "multi_step"
    )

    assert (
        orchestrator.legacy_calls
        == []
    )

    assert captured["task_id"] == (
        "TASK-3202"
    )

    assert captured["max_attempts"] == 3
    assert captured["model_name"] == (
        "fake-model"
    )


def test_plan_is_persisted(
    monkeypatch,
):
    orchestrator = FakeOrchestrator()

    plan = {
        "summary": "Persist me",
        "planner_mode": "single_step",
        "steps": [
            {
                "title": "Write",
                "instruction": "Implement",
                "kind": "write",
                "status": "pending",
                "attempt": 0,
            }
        ],
    }

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "build_task_plan",
        lambda *args, **kwargs: plan,
    )

    captured = {}

    def fake_save(
        task_id,
        steps,
        **kwargs,
    ):
        captured["task_id"] = task_id
        captured["steps"] = steps
        captured["summary"] = (
            kwargs["summary"]
        )
        captured["planner_mode"] = (
            kwargs.get("planner_mode")
        )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "save_task_plan",
        fake_save,
    )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "run_multi_step_task",
        lambda **kwargs: "ready_for_approval",
    )

    execute_write_task(
        orchestrator=orchestrator,
        prompt="Write",
        task_id="TASK-3203",
        max_attempts=2,
        model_route=_model_route(),
    )

    assert captured["task_id"] == (
        "TASK-3203"
    )

    assert captured["steps"] == (
        plan["steps"]
    )

    assert captured["summary"] == (
        "Persist me"
    )

    assert captured["planner_mode"] == (
        "single_step"
    )



def test_progress_reports_planner_mode(
    monkeypatch,
):
    orchestrator = FakeOrchestrator()

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "build_task_plan",
        lambda *args, **kwargs: {
            "summary": "Plan summary",
            "planner_mode": "single_step",
            "steps": [
                {
                    "title": "Write",
                    "instruction": "Write",
                    "kind": "write",
                    "status": "pending",
                    "attempt": 0,
                }
            ],
        },
    )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "save_task_plan",
        lambda *args, **kwargs: None,
    )

    events = []

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "run_multi_step_task",
        lambda **kwargs: "ready_for_approval",
    )

    execute_write_task(
        orchestrator=orchestrator,
        prompt="Write",
        task_id="TASK-3204",
        max_attempts=2,
        model_route=_model_route(),
        progress_handler=(
            lambda task_id, **kwargs:
            events.append(kwargs)
        ),
    )

    assert any(
        "Planner: single_step"
        in item.get("message", "")
        for item in events
    )


def test_failed_multi_step_resumes_existing_worktree(
    monkeypatch,
    tmp_path,
):
    from types import SimpleNamespace

    task_id = "TASK-RESUME-1"

    project_path = tmp_path / "repo"
    worktree_root = tmp_path / "worktrees"

    project_path.mkdir()
    worktree_root.mkdir()

    repo_name = project_path.name
    worktree_path = (
        worktree_root
        / repo_name
        / task_id.lower()
    )

    worktree_path.mkdir(parents=True)

    # Git worktree'lerde .git genellikle dosyadir.
    (worktree_path / ".git").write_text(
        "gitdir: fake",
        encoding="utf-8",
    )

    orchestrator = SimpleNamespace(
        project_path=str(project_path),
        worktree_root=str(worktree_root),
    )

    existing_steps = [
        {
            "step_index": 1,
            "title": "Read",
            "instruction": "Inspect",
            "kind": "read",
            "status": "completed",
            "attempt": 1,
            "result": "ok",
            "error": None,
        },
        {
            "step_index": 2,
            "title": "Verify",
            "instruction": "Verify",
            "kind": "verify",
            "status": "failed",
            "attempt": 1,
            "result": None,
            "error": "test failed",
        },
    ]

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "get_task_plan",
        lambda *_args, **_kwargs: {
            "task_id": task_id,
            "status": "failed",
            "summary": "Resume plan",
            "planner_mode": "multi_step",
            "steps": existing_steps,
        },
    )

    def fail_if_planner_runs(*args, **kwargs):
        raise AssertionError(
            "build_task_plan must not run during resume"
        )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "build_task_plan",
        fail_if_planner_runs,
    )

    def fail_if_plan_saved(*args, **kwargs):
        raise AssertionError(
            "save_task_plan must not overwrite resume plan"
        )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "save_task_plan",
        fail_if_plan_saved,
    )

    captured = {}

    def fake_multi_step(**kwargs):
        captured.update(kwargs)
        return "ready_for_approval"

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "run_multi_step_task",
        fake_multi_step,
    )

    result, plan = execute_write_task(
        orchestrator=orchestrator,
        prompt="Resume existing task",
        task_id=task_id,
        max_attempts=2,
        model_route=_model_route(),
    )

    assert result == "ready_for_approval"
    assert plan["planner_mode"] == "multi_step"
    assert plan["steps"] == existing_steps

    assert captured["resume_worktree_path"] == str(
        worktree_path
    )
    assert captured["resume_branch"] == (
        f"agent/{task_id.lower()}"
    )


def test_invalid_planner_mode_raises_without_legacy(
    monkeypatch,
):
    import pytest

    orchestrator = FakeOrchestrator()

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "build_task_plan",
        lambda *args, **kwargs: {
            "summary": "Broken",
            "planner_mode": "legacy_cli",
            "steps": [
                {
                    "title": "Write",
                    "instruction": "Write",
                    "kind": "write",
                    "status": "pending",
                    "attempt": 0,
                }
            ],
        },
    )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "save_task_plan",
        lambda *args, **kwargs: None,
    )

    multi_calls = []

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "run_multi_step_task",
        lambda **kwargs: (
            multi_calls.append(kwargs)
            or "should-not-run"
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "Unsupported planner mode: "
            "legacy_cli"
        ),
    ):
        execute_write_task(
            orchestrator=orchestrator,
            prompt="Invalid mode",
            task_id="TASK-3205",
            max_attempts=2,
            model_route=_model_route(),
        )

    assert orchestrator.legacy_calls == []
    assert multi_calls == []


def test_single_step_failed_does_not_resume_worktree(
    monkeypatch,
    tmp_path,
):
    # TASK-1790 / TASK-2552: automatic VERIFY
    # makes len(steps)==2, but planner_mode is
    # single_step so retry must rebuild.
    from types import SimpleNamespace

    task_id = "TASK-RESUME-SS-1"

    project_path = tmp_path / "repo"
    worktree_root = tmp_path / "worktrees"

    project_path.mkdir()
    worktree_root.mkdir()

    repo_name = project_path.name
    worktree_path = (
        worktree_root
        / repo_name
        / task_id.lower()
    )
    worktree_path.mkdir(parents=True)
    (worktree_path / ".git").write_text(
        "gitdir: fake",
        encoding="utf-8",
    )

    orchestrator = SimpleNamespace(
        project_path=str(project_path),
        worktree_root=str(worktree_root),
        model_client=object(),
    )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "get_task_plan",
        lambda *_args, **_kwargs: {
            "task_id": task_id,
            "status": "failed",
            "summary": "Tek adimli gorev",
            "planner_mode": "single_step",
            "steps": [
                {
                    "step_index": 1,
                    "title": "Write",
                    "instruction": "Write",
                    "kind": "write",
                    "status": "failed",
                    "attempt": 1,
                },
                {
                    "step_index": 2,
                    "title": "Verify",
                    "instruction": "Verify",
                    "kind": "verify",
                    "status": "pending",
                    "attempt": 0,
                },
            ],
        },
    )

    rebuilt = {
        "summary": "Tek adimli gorev",
        "planner_mode": "single_step",
        "steps": [
            {
                "title": "Write",
                "instruction": "Write",
                "kind": "write",
                "status": "pending",
                "attempt": 0,
            }
        ],
    }

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "build_task_plan",
        lambda *args, **kwargs: rebuilt,
    )

    saved = []

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "save_task_plan",
        lambda *args, **kwargs: (
            saved.append((args, kwargs))
        ),
    )

    captured = {}

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "run_multi_step_task",
        lambda **kwargs: (
            captured.update(kwargs)
            or "ready_for_approval"
        ),
    )

    events = []

    result, plan = execute_write_task(
        orchestrator=orchestrator,
        prompt="Retry single step",
        task_id=task_id,
        max_attempts=2,
        model_route=_model_route(),
        progress_handler=(
            lambda task_id, **kwargs:
            events.append(kwargs)
        ),
    )

    assert result == "ready_for_approval"
    assert plan["planner_mode"] == "single_step"
    assert captured["resume_worktree_path"] is None
    assert captured["resume_branch"] is None
    assert saved
    assert all(
        kwargs.get("planner_mode")
        == "single_step"
        for _args, kwargs in saved
    )
    assert not any(
        "multi-step plan resume"
        in item.get("message", "")
        for item in events
    )


def test_completed_multi_step_does_not_resume(
    monkeypatch,
    tmp_path,
):
    from types import SimpleNamespace

    task_id = "TASK-RESUME-DONE-1"

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

    orchestrator = SimpleNamespace(
        project_path=str(project_path),
        worktree_root=str(worktree_root),
        model_client=object(),
    )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "get_task_plan",
        lambda *_args, **_kwargs: {
            "task_id": task_id,
            "status": "completed",
            "summary": "Done plan",
            "planner_mode": "multi_step",
            "steps": [
                {
                    "step_index": 1,
                    "kind": "write",
                    "status": "completed",
                },
                {
                    "step_index": 2,
                    "kind": "verify",
                    "status": "completed",
                },
            ],
        },
    )

    rebuilt = {
        "summary": "Fresh plan",
        "planner_mode": "multi_step",
        "steps": [
            {
                "title": "Write",
                "instruction": "Write",
                "kind": "write",
                "status": "pending",
                "attempt": 0,
            },
            {
                "title": "Verify",
                "instruction": "Verify",
                "kind": "verify",
                "status": "pending",
                "attempt": 0,
            },
        ],
    }

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "build_task_plan",
        lambda *args, **kwargs: rebuilt,
    )

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "save_task_plan",
        lambda *args, **kwargs: None,
    )

    captured = {}

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "run_multi_step_task",
        lambda **kwargs: (
            captured.update(kwargs)
            or "ready_for_approval"
        ),
    )

    result, plan = execute_write_task(
        orchestrator=orchestrator,
        prompt="Retry completed",
        task_id=task_id,
        max_attempts=2,
        model_route=_model_route(),
    )

    assert result == "ready_for_approval"
    assert plan["summary"] == "Fresh plan"
    assert captured["resume_worktree_path"] is None
    assert captured["resume_branch"] is None
