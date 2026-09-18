from typing import Any, Callable

from factory.task_planner import build_task_plan
from factory.task_plan_store import save_task_plan
from factory.multi_step_task_runner import (
    run_multi_step_task,
)


def execute_write_task(
    *,
    orchestrator: Any,
    prompt: str,
    task_id: str,
    max_attempts: int,
    model_route: Any,
    approval_handler: Callable | None = None,
    progress_handler: Callable | None = None,
) -> tuple[str | None, dict[str, Any]]:
    plan = build_task_plan(
        prompt,
        model_client=orchestrator.model_client,
        model_name=model_route.model,
    )

    save_task_plan(
        task_id,
        plan["steps"],
        summary=plan.get("summary"),
    )

    planner_mode = plan.get(
        "planner_mode",
        "single_step",
    )

    if progress_handler is not None:
        progress_handler(
            task_id,
            message=(
                "Planner: "
                f"{planner_mode} - "
                f"{plan.get('summary', '')}"
            ),
        )

    if planner_mode == "multi_step":
        result = run_multi_step_task(
            orchestrator=orchestrator,
            prompt=prompt,
            task_id=task_id,
            max_attempts=max_attempts,
            approval_handler=approval_handler,
            progress_handler=progress_handler,
            model_name=model_route.model,
        )

        return result, plan

    result = orchestrator.run_task(
        prompt,
        task_id=task_id,
        max_attempts=max_attempts,
        approval_handler=approval_handler,
        progress_handler=progress_handler,
        model_route=model_route,
    )

    return result, plan
