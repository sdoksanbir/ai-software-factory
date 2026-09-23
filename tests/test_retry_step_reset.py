from factory.task_plan_store import (
    save_task_plan,
    get_task_plan,
    reset_retryable_task_steps,
    update_task_step,
)


def test_reset_retryable_task_steps_preserves_completed_and_skipped(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-RETRY-1",
        [
            {
                "title": "done",
                "instruction": "done",
                "kind": "write",
            },
            {
                "title": "failed",
                "instruction": "failed",
                "kind": "write",
            },
            {
                "title": "running",
                "instruction": "running",
                "kind": "verify",
            },
            {
                "title": "skipped",
                "instruction": "skipped",
                "kind": "read",
            },
        ],
        db_path=db_path,
    )

    update_task_step(
        "TASK-RETRY-1",
        1,
        status="completed",
        attempt=1,
        result="ok",
        db_path=db_path,
    )
    update_task_step(
        "TASK-RETRY-1",
        2,
        status="failed",
        attempt=3,
        error="provider offline",
        db_path=db_path,
    )
    update_task_step(
        "TASK-RETRY-1",
        3,
        status="running",
        attempt=2,
        error="interrupted",
        db_path=db_path,
    )
    update_task_step(
        "TASK-RETRY-1",
        4,
        status="skipped",
        attempt=0,
        db_path=db_path,
    )

    reset_count = reset_retryable_task_steps(
        "TASK-RETRY-1",
        db_path=db_path,
    )

    assert reset_count == 2

    plan = get_task_plan(
        "TASK-RETRY-1",
        db_path=db_path,
    )
    assert plan is not None

    steps = {
        int(step["step_index"]): step
        for step in plan["steps"]
    }

    assert steps[1]["status"] == "completed"
    assert steps[1]["attempt"] == 1
    assert steps[1]["result"] == "ok"

    assert steps[2]["status"] == "pending"
    assert steps[2]["attempt"] == 0
    assert steps[2]["error"] == ""

    assert steps[3]["status"] == "pending"
    assert steps[3]["attempt"] == 0
    assert steps[3]["error"] == ""

    assert steps[4]["status"] == "skipped"
    assert steps[4]["attempt"] == 0

    assert plan["status"] == "pending"


def test_reset_retryable_task_steps_missing_plan_is_noop(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    assert (
        reset_retryable_task_steps(
            "TASK-NOT-FOUND",
            db_path=db_path,
        )
        == 0
    )
