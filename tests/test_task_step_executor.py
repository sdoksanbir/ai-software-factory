import pytest

from factory.task_plan_store import (
    get_task_plan,
    save_task_plan,
)
from factory.task_step_executor import (
    StepExecutionError,
    execute_task_plan,
)


def _steps():
    return [
        {
            "title": "Inspect",
            "instruction": "Inspect repository.",
            "kind": "read",
        },
        {
            "title": "Implement",
            "instruction": "Implement change.",
            "kind": "write",
        },
        {
            "title": "Verify",
            "instruction": "Verify result.",
            "kind": "verify",
        },
    ]


def test_all_steps_use_same_worktree(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-3001",
        _steps(),
        db_path=db_path,
    )

    calls = []

    def handler(step, worktree_path):
        calls.append(
            (
                step["kind"],
                worktree_path,
            )
        )
        return step["kind"]

    result = execute_task_plan(
        "TASK-3001",
        "C:/shared-worktree",
        read_handler=handler,
        write_handler=handler,
        verify_handler=handler,
        db_path=db_path,
    )

    assert result["status"] == "completed"

    assert calls == [
        ("read", "C:/shared-worktree"),
        ("write", "C:/shared-worktree"),
        ("verify", "C:/shared-worktree"),
    ]


def test_step_results_are_persisted(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-3002",
        _steps(),
        db_path=db_path,
    )

    def handler(step, worktree_path):
        return (
            f"done-{step['kind']}"
        )

    execute_task_plan(
        "TASK-3002",
        "worktree",
        read_handler=handler,
        write_handler=handler,
        verify_handler=handler,
        db_path=db_path,
    )

    loaded = get_task_plan(
        "TASK-3002",
        db_path=db_path,
    )

    assert [
        step["result"]
        for step in loaded["steps"]
    ] == [
        "done-read",
        "done-write",
        "done-verify",
    ]

    assert all(
        step["status"] == "completed"
        for step in loaded["steps"]
    )


def test_failure_is_persisted(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-3003",
        _steps(),
        db_path=db_path,
    )

    def read_handler(step, worktree_path):
        return "read-ok"

    def write_handler(step, worktree_path):
        raise RuntimeError(
            "write failed"
        )

    def verify_handler(step, worktree_path):
        raise AssertionError(
            "verify must not run"
        )

    with pytest.raises(
        StepExecutionError
    ):
        execute_task_plan(
            "TASK-3003",
            "worktree",
            read_handler=read_handler,
            write_handler=write_handler,
            verify_handler=verify_handler,
            db_path=db_path,
        )

    loaded = get_task_plan(
        "TASK-3003",
        db_path=db_path,
    )

    assert loaded["status"] == "failed"

    assert (
        loaded["steps"][0]["status"]
        == "completed"
    )

    assert (
        loaded["steps"][1]["status"]
        == "failed"
    )

    assert (
        loaded["steps"][1]["attempt"]
        == 1
    )

    assert (
        loaded["steps"][1]["error"]
        == "write failed"
    )

    assert (
        loaded["steps"][2]["status"]
        == "pending"
    )


def test_retry_resumes_from_failed_step(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-3004",
        _steps(),
        db_path=db_path,
    )

    calls = []

    fail_once = {
        "value": True,
    }

    def read_handler(step, worktree_path):
        calls.append("read")
        return "read-ok"

    def write_handler(step, worktree_path):
        calls.append("write")

        if fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError(
                "temporary failure"
            )

        return "write-ok"

    def verify_handler(
        step,
        worktree_path,
    ):
        calls.append("verify")
        return "verify-ok"

    with pytest.raises(
        StepExecutionError
    ):
        execute_task_plan(
            "TASK-3004",
            "worktree",
            read_handler=read_handler,
            write_handler=write_handler,
            verify_handler=verify_handler,
            db_path=db_path,
        )

    assert calls == [
        "read",
        "write",
    ]

    result = execute_task_plan(
        "TASK-3004",
        "worktree",
        read_handler=read_handler,
        write_handler=write_handler,
        verify_handler=verify_handler,
        db_path=db_path,
    )

    assert calls == [
        "read",
        "write",
        "write",
        "verify",
    ]

    assert result["status"] == "completed"

    assert (
        result["steps"][0]["attempt"]
        == 1
    )

    assert (
        result["steps"][1]["attempt"]
        == 2
    )

    assert (
        result["steps"][2]["attempt"]
        == 1
    )


def test_completed_steps_are_skipped(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-3005",
        _steps(),
        db_path=db_path,
    )

    calls = []

    def handler(step, worktree_path):
        calls.append(step["kind"])
        return "ok"

    execute_task_plan(
        "TASK-3005",
        "worktree",
        read_handler=handler,
        write_handler=handler,
        verify_handler=handler,
        db_path=db_path,
    )

    calls.clear()

    execute_task_plan(
        "TASK-3005",
        "worktree",
        read_handler=handler,
        write_handler=handler,
        verify_handler=handler,
        db_path=db_path,
    )

    assert calls == []


def test_max_attempts_blocks_retry(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-3006",
        [
            {
                "title": "Write",
                "instruction": "Change file.",
                "kind": "write",
                "status": "failed",
                "attempt": 2,
            }
        ],
        db_path=db_path,
    )

    called = []

    def handler(step, worktree_path):
        called.append(True)
        return "unexpected"

    with pytest.raises(
        StepExecutionError
    ):
        execute_task_plan(
            "TASK-3006",
            "worktree",
            read_handler=handler,
            write_handler=handler,
            verify_handler=handler,
            max_step_attempts=2,
            db_path=db_path,
        )

    assert called == []


def test_unknown_plan_rejected(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    def handler(step, worktree_path):
        return "ok"

    with pytest.raises(KeyError):
        execute_task_plan(
            "TASK-3999",
            "worktree",
            read_handler=handler,
            write_handler=handler,
            verify_handler=handler,
            db_path=db_path,
        )
