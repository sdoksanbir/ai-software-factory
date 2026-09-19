import pytest

from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
)
from factory.task_plan_store import (
    get_task_plan,
    save_task_plan,
)
from factory.task_step_executor import (
    StepExecutionError,
    execute_task_plan,
)


def test_running_write_with_completed_checkpoint_recovers(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-RECOVERY-1"

    save_task_plan(
        task_id,
        [
            {
                "title": "Write code",
                "instruction": "Create x.py",
                "kind": "write",
                "status": "running",
                "attempt": 1,
            }
        ],
        db_path=db_path,
    )

    create_agent_checkpoint(
        task_id,
        step_index=1,
        agent_name="ollama-agent",
        provider_name="ollama",
        status="completed",
        summary="x.py created",
        payload={
            "attempt": 1,
            "step_kind": "write",
            "model": "qwen2.5-coder:14b",
            "files": ["x.py"],
        },
        db_path=db_path,
    )

    calls = []

    def write_handler(*args):
        calls.append(True)
        raise AssertionError(
            "Recovered WRITE must not run again"
        )

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=write_handler,
        verify_handler=lambda *_: None,
        max_step_attempts=1,
        db_path=db_path,
    )

    assert calls == []
    assert plan["status"] == "completed"

    step = plan["steps"][0]

    assert step["status"] == "completed"
    assert step["attempt"] == 1
    assert step["result"] == "x.py created"
    assert step["error"] == ""


def test_interrupted_write_requires_explicit_retry(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-RECOVERY-2"

    save_task_plan(
        task_id,
        [
            {
                "title": "Write code",
                "instruction": "Create x.py",
                "kind": "write",
                "status": "running",
                "attempt": 1,
            }
        ],
        db_path=db_path,
    )

    calls = []

    def write_handler(*args):
        calls.append(True)
        return "WRITE_OK"

    with pytest.raises(
        StepExecutionError,
        match="explicit retry required",
    ):
        execute_task_plan(
            task_id,
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=write_handler,
            verify_handler=lambda *_: None,
            max_step_attempts=2,
            db_path=db_path,
        )

    # Recovery pass must not silently rerun WRITE.
    assert calls == []

    interrupted = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert interrupted is not None
    assert interrupted["status"] == "failed"
    assert (
        interrupted["steps"][0]["status"]
        == "failed"
    )
    assert (
        interrupted["steps"][0]["attempt"]
        == 1
    )

    # A later explicit retry is allowed and consumes
    # the next normal step attempt.
    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=write_handler,
        verify_handler=lambda *_: None,
        max_step_attempts=2,
        db_path=db_path,
    )

    assert calls == [True]
    assert plan["status"] == "completed"
    assert (
        plan["steps"][0]["status"]
        == "completed"
    )
    assert (
        plan["steps"][0]["attempt"]
        == 2
    )


def test_stale_checkpoint_does_not_skip_newer_attempt(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-RECOVERY-3"

    save_task_plan(
        task_id,
        [
            {
                "title": "Read repository",
                "instruction": "Inspect repository",
                "kind": "read",
                "status": "failed",
                "attempt": 2,
            }
        ],
        db_path=db_path,
    )

    create_agent_checkpoint(
        task_id,
        step_index=1,
        agent_name="ollama-agent",
        provider_name="ollama",
        status="completed",
        summary="old result",
        payload={
            "attempt": 1,
            "step_kind": "read",
        },
        db_path=db_path,
    )

    calls = []

    def read_handler(*args):
        calls.append(True)
        return "fresh result"

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=read_handler,
        write_handler=lambda *_: None,
        verify_handler=lambda *_: None,
        max_step_attempts=3,
        db_path=db_path,
    )

    assert calls == [True]
    assert (
        plan["steps"][0]["attempt"]
        == 3
    )
    assert (
        plan["steps"][0]["result"]
        == "fresh result"
    )
