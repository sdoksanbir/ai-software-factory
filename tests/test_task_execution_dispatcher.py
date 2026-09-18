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


def test_single_step_uses_legacy_runner(
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

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "run_multi_step_task",
        lambda **kwargs: (
            multi_calls.append(kwargs)
        ),
    )

    result, plan = execute_write_task(
        orchestrator=orchestrator,
        prompt="Simple write",
        task_id="TASK-3201",
        max_attempts=2,
        model_route=_model_route(),
    )

    assert result == "legacy-result"
    assert plan["planner_mode"] == (
        "single_step"
    )

    assert len(
        orchestrator.legacy_calls
    ) == 1

    assert multi_calls == []
    assert len(saved) == 1


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

    monkeypatch.setattr(
        "factory.task_execution_dispatcher."
        "save_task_plan",
        fake_save,
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
