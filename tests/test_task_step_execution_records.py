from factory.agent_execution_store import (
    list_agent_executions,
)
from factory.task_plan_store import (
    save_task_plan,
)
from factory.task_step_executor import (
    StepHandlerResult,
    execute_task_plan,
)


def test_rich_step_creates_execution_record(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-EXE-STEP-1",
        [
            {
                "title": "Write code",
                "instruction": "Create x.py",
                "kind": "write",
            }
        ],
        db_path=db_path,
    )

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

    execute_task_plan(
        "TASK-EXE-STEP-1",
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=write_handler,
        verify_handler=lambda *_: None,
        db_path=db_path,
    )

    executions = list_agent_executions(
        "TASK-EXE-STEP-1",
        db_path=db_path,
    )

    assert len(executions) == 1

    execution = executions[0]

    assert execution["status"] == "completed"
    assert (
        execution["agent_name"]
        == "ollama-agent"
    )
    assert (
        execution["provider_name"]
        == "ollama"
    )
    assert (
        execution["model_name"]
        == "qwen2.5-coder:14b"
    )
    assert (
        execution["result_checkpoint_id"]
        is not None
    )
    assert execution["duration_ms"] >= 0

    assert sorted(
        execution["capabilities"]
    ) == [
        "read_repository",
        "write_code",
    ]


def test_legacy_step_does_not_create_agent_execution(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-EXE-STEP-2",
        [
            {
                "title": "Verify",
                "instruction": "Run tests",
                "kind": "verify",
            }
        ],
        db_path=db_path,
    )

    execute_task_plan(
        "TASK-EXE-STEP-2",
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=lambda *_: None,
        verify_handler=(
            lambda *_: "tests passed"
        ),
        db_path=db_path,
    )

    assert list_agent_executions(
        "TASK-EXE-STEP-2",
        db_path=db_path,
    ) == []
