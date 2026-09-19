import pytest

from factory.agent_execution_store import (
    complete_agent_execution,
    create_agent_execution,
    fail_agent_execution,
    get_agent_execution,
    list_agent_executions,
)


def test_create_agent_execution(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    created = create_agent_execution(
        "TASK-EX-1",
        step_index=2,
        agent_name="ollama-agent",
        provider_name="ollama",
        model_name="qwen2.5-coder:14b",
        capabilities=[
            "read_repository",
            "write_code",
        ],
        metadata={
            "attempt": 1,
        },
        execution_id="EXE-1",
        db_path=db_path,
    )

    assert created["execution_id"] == "EXE-1"
    assert created["status"] == "running"
    assert created["task_id"] == "TASK-EX-1"
    assert created["step_index"] == 2
    assert created["capabilities"] == [
        "read_repository",
        "write_code",
    ]
    assert created["metadata"] == {
        "attempt": 1,
    }


def test_complete_agent_execution(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_execution(
        "TASK-EX-2",
        step_index=1,
        agent_name="ollama-agent",
        provider_name="ollama",
        execution_id="EXE-2",
        db_path=db_path,
    )

    complete_agent_execution(
        "EXE-2",
        result_checkpoint_id="CHK-RESULT",
        duration_ms=1250,
        prompt_tokens=100,
        completion_tokens=40,
        cost=0.0,
        metadata={
            "finished": True,
        },
        db_path=db_path,
    )

    loaded = get_agent_execution(
        "EXE-2",
        db_path=db_path,
    )

    assert loaded is not None
    assert loaded["status"] == "completed"
    assert (
        loaded["result_checkpoint_id"]
        == "CHK-RESULT"
    )
    assert loaded["duration_ms"] == 1250
    assert loaded["prompt_tokens"] == 100
    assert loaded["completion_tokens"] == 40
    assert loaded["metadata"] == {
        "finished": True,
    }


def test_fail_agent_execution(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_execution(
        "TASK-EX-3",
        step_index=3,
        agent_name="gemini-agent",
        provider_name="gemini_cli",
        execution_id="EXE-3",
        db_path=db_path,
    )

    fail_agent_execution(
        "EXE-3",
        error="provider failed",
        duration_ms=500,
        db_path=db_path,
    )

    loaded = get_agent_execution(
        "EXE-3",
        db_path=db_path,
    )

    assert loaded is not None
    assert loaded["status"] == "failed"
    assert loaded["error"] == "provider failed"
    assert loaded["duration_ms"] == 500


def test_list_agent_executions_by_step(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_execution(
        "TASK-EX-4",
        step_index=1,
        agent_name="reader",
        provider_name="ollama",
        execution_id="EXE-A",
        db_path=db_path,
    )

    create_agent_execution(
        "TASK-EX-4",
        step_index=2,
        agent_name="coder",
        provider_name="ollama",
        execution_id="EXE-B",
        db_path=db_path,
    )

    assert len(
        list_agent_executions(
            "TASK-EX-4",
            db_path=db_path,
        )
    ) == 2

    step_two = list_agent_executions(
        "TASK-EX-4",
        step_index=2,
        db_path=db_path,
    )

    assert [
        item["execution_id"]
        for item in step_two
    ] == [
        "EXE-B"
    ]


def test_agent_execution_validation(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    with pytest.raises(
        ValueError,
        match="step_index",
    ):
        create_agent_execution(
            "TASK-EX-5",
            step_index=0,
            agent_name="coder",
            provider_name="ollama",
            db_path=db_path,
        )

    with pytest.raises(
        ValueError,
        match="duration_ms",
    ):
        complete_agent_execution(
            "EXE-MISSING",
            duration_ms=-1,
            db_path=db_path,
        )
