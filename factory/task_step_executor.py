from pathlib import Path
from typing import Any, Callable

from factory.database import DEFAULT_DB_PATH
from factory.task_plan_store import (
    get_task_plan,
    update_task_plan_status,
    update_task_step,
)


StepHandler = Callable[
    [dict[str, Any], str],
    str | None,
]


class StepExecutionError(RuntimeError):
    def __init__(
        self,
        task_id: str,
        step_index: int,
        message: str,
    ):
        self.task_id = task_id
        self.step_index = step_index

        super().__init__(
            f"{task_id} step {step_index}: "
            f"{message}"
        )


def execute_task_plan(
    task_id: str,
    worktree_path: str,
    *,
    read_handler: StepHandler,
    write_handler: StepHandler,
    verify_handler: StepHandler,
    max_step_attempts: int = 2,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    if max_step_attempts < 1:
        raise ValueError(
            "max_step_attempts must be >= 1"
        )

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    if plan is None:
        raise KeyError(
            f"Unknown task plan: {task_id}"
        )

    handlers = {
        "read": read_handler,
        "write": write_handler,
        "verify": verify_handler,
    }

    update_task_plan_status(
        task_id,
        "running",
        db_path=db_path,
    )

    for step in plan["steps"]:
        step_index = int(
            step["step_index"]
        )

        status = str(
            step["status"]
        )

        if status in {
            "completed",
            "skipped",
        }:
            continue

        previous_attempt = int(
            step["attempt"] or 0
        )

        if (
            previous_attempt
            >= max_step_attempts
        ):
            update_task_plan_status(
                task_id,
                "failed",
                db_path=db_path,
            )

            raise StepExecutionError(
                task_id,
                step_index,
                (
                    "maximum step attempts "
                    "already reached"
                ),
            )

        kind = str(
            step["kind"]
        ).strip().lower()

        handler = handlers.get(kind)

        if handler is None:
            update_task_plan_status(
                task_id,
                "failed",
                db_path=db_path,
            )

            raise StepExecutionError(
                task_id,
                step_index,
                f"unsupported step kind: {kind}",
            )

        current_attempt = (
            previous_attempt + 1
        )

        update_task_step(
            task_id,
            step_index,
            status="running",
            attempt=current_attempt,
            error="",
            db_path=db_path,
        )

        step_payload = dict(step)
        step_payload["status"] = "running"
        step_payload["attempt"] = (
            current_attempt
        )

        try:
            result = handler(
                step_payload,
                worktree_path,
            )

        except Exception as exc:
            update_task_step(
                task_id,
                step_index,
                status="failed",
                attempt=current_attempt,
                error=str(exc),
                db_path=db_path,
            )

            update_task_plan_status(
                task_id,
                "failed",
                db_path=db_path,
            )

            raise StepExecutionError(
                task_id,
                step_index,
                str(exc),
            ) from exc

        update_task_step(
            task_id,
            step_index,
            status="completed",
            attempt=current_attempt,
            result=(
                ""
                if result is None
                else str(result)
            ),
            error="",
            db_path=db_path,
        )

    update_task_plan_status(
        task_id,
        "completed",
        db_path=db_path,
    )

    completed_plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    if completed_plan is None:
        raise RuntimeError(
            "Task plan disappeared "
            "after execution"
        )

    return completed_plan
