import pytest

from factory.agent_checkpoint_store import (
    list_agent_checkpoints,
)
from factory.task_plan_store import (
    get_task_plan,
    save_task_plan,
)
from factory.task_step_executor import (
    StepExecutionError,
    StepHandlerResult,
    execute_task_plan,
)


def _save_plan(
    db_path,
):
    save_task_plan(
        "TASK-CP-1",
        [
            {
                "title": "Write file",
                "instruction": "Create x.py",
                "kind": "write",
            }
        ],
        db_path=db_path,
    )


def test_executor_creates_checkpoint_for_rich_result(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    _save_plan(db_path)

    def write_handler(
        step,
        worktree_path,
    ):
        return StepHandlerResult(
            output="x.py created",
            agent_name="ollama-agent",
            provider_name="ollama",
            checkpoint_payload={
                "model": (
                    "qwen2.5-coder:14b"
                ),
                "files": [
                    "x.py",
                ],
            },
        )

    plan = execute_task_plan(
        "TASK-CP-1",
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=write_handler,
        verify_handler=lambda *_: None,
        db_path=db_path,
    )

    assert (
        plan["steps"][0]["result"]
        == "x.py created"
    )

    checkpoints = list_agent_checkpoints(
        "TASK-CP-1",
        db_path=db_path,
    )

    assert len(checkpoints) == 1

    checkpoint = checkpoints[0]

    assert (
        checkpoint["agent_name"]
        == "ollama-agent"
    )
    assert (
        checkpoint["provider_name"]
        == "ollama"
    )
    assert (
        checkpoint["status"]
        == "completed"
    )
    assert checkpoint["payload"] == {
        "attempt": 1,
        "files": [
            "x.py",
        ],
        "model": (
            "qwen2.5-coder:14b"
        ),
        "step_kind": "write",
    }


def test_executor_keeps_legacy_string_result(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    _save_plan(db_path)

    plan = execute_task_plan(
        "TASK-CP-1",
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=(
            lambda *_: "legacy result"
        ),
        verify_handler=lambda *_: None,
        db_path=db_path,
    )

    assert (
        plan["steps"][0]["result"]
        == "legacy result"
    )

    assert list_agent_checkpoints(
        "TASK-CP-1",
        db_path=db_path,
    ) == []


def test_checkpoint_identity_must_be_complete(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    _save_plan(db_path)

    def write_handler(
        step,
        worktree_path,
    ):
        return StepHandlerResult(
            output="result",
            agent_name="ollama-agent",
            provider_name=None,
        )

    with pytest.raises(
        StepExecutionError,
        match="supplied together",
    ):
        execute_task_plan(
            "TASK-CP-1",
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=write_handler,
            verify_handler=lambda *_: None,
            db_path=db_path,
        )

    plan = get_task_plan(
        "TASK-CP-1",
        db_path=db_path,
    )

    assert plan is not None
    assert plan["status"] == "failed"
    assert (
        plan["steps"][0]["status"]
        == "failed"
    )


def test_checkpoint_write_failure_marks_step_failed(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    _save_plan(db_path)

    def write_handler(
        step,
        worktree_path,
    ):
        return StepHandlerResult(
            output="result",
            agent_name="ollama-agent",
            provider_name="ollama",
        )

    def fail_checkpoint(*args, **kwargs):
        raise RuntimeError(
            "checkpoint storage failed"
        )

    monkeypatch.setattr(
        "factory.task_step_executor."
        "create_agent_checkpoint",
        fail_checkpoint,
    )

    with pytest.raises(
        StepExecutionError,
        match="checkpoint storage failed",
    ):
        execute_task_plan(
            "TASK-CP-1",
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=write_handler,
            verify_handler=lambda *_: None,
            db_path=db_path,
        )

    plan = get_task_plan(
        "TASK-CP-1",
        db_path=db_path,
    )

    assert plan is not None
    assert plan["status"] == "failed"
    assert (
        plan["steps"][0]["status"]
        == "failed"
    )
