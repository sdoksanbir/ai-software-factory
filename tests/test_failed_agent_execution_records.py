from factory.agent_execution_store import (
    list_agent_executions,
)
from factory.task_plan_store import (
    get_task_plan,
    save_task_plan,
)
from factory.task_step_executor import (
    AgentStepExecutionError,
    StepExecutionError,
    execute_task_plan,
)


def test_failed_agent_step_creates_failed_execution(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-FAIL-EX-1",
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
        raise AgentStepExecutionError(
            "provider unavailable",
            agent_name="ollama-agent",
            provider_name="ollama",
            model_name=(
                "qwen2.5-coder:14b"
            ),
            capabilities=[
                "read_repository",
                "write_code",
            ],
        )

    try:
        execute_task_plan(
            "TASK-FAIL-EX-1",
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=write_handler,
            verify_handler=lambda *_: None,
            db_path=db_path,
        )
    except StepExecutionError as exc:
        assert (
            "provider unavailable"
            in str(exc)
        )
    else:
        raise AssertionError(
            "Expected StepExecutionError"
        )

    executions = list_agent_executions(
        "TASK-FAIL-EX-1",
        db_path=db_path,
    )

    assert len(executions) == 1

    execution = executions[0]

    assert execution["status"] == "failed"
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
    assert execution["capabilities"] == [
        "read_repository",
        "write_code",
    ]
    assert (
        "provider unavailable"
        in execution["error"]
    )
    assert execution["duration_ms"] >= 0

    plan = get_task_plan(
        "TASK-FAIL-EX-1",
        db_path=db_path,
    )

    assert plan is not None
    assert plan["status"] == "failed"
    assert (
        plan["steps"][0]["status"]
        == "failed"
    )


def test_non_agent_failure_does_not_create_execution(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-FAIL-EX-2",
        [
            {
                "title": "Verify",
                "instruction": "Run tests",
                "kind": "verify",
            }
        ],
        db_path=db_path,
    )

    def verify_handler(
        step,
        worktree_path,
    ):
        raise RuntimeError(
            "pytest failed"
        )

    try:
        execute_task_plan(
            "TASK-FAIL-EX-2",
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=lambda *_: None,
            verify_handler=verify_handler,
            db_path=db_path,
        )
    except StepExecutionError:
        pass
    else:
        raise AssertionError(
            "Expected StepExecutionError"
        )

    assert list_agent_executions(
        "TASK-FAIL-EX-2",
        db_path=db_path,
    ) == []
