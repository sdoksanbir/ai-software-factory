import os
from typing import Any, Callable

from factory.task_planner import build_task_plan
from factory.task_plan_store import (
    get_task_plan,
    save_task_plan,
)
from factory.multi_step_task_runner import (
    run_multi_step_task,
)


def _get_expected_worktree(
    orchestrator: Any,
    task_id: str,
) -> tuple[str, str]:
    repo_name = os.path.basename(
        os.path.normpath(
            orchestrator.project_path
        )
    )

    worktree_path = os.path.join(
        orchestrator.worktree_root,
        repo_name,
        task_id.lower(),
    )

    branch_name = (
        f"agent/{task_id.lower()}"
    )

    return worktree_path, branch_name


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
    existing_plan = get_task_plan(
        task_id
    )

    existing_steps = (
        existing_plan.get("steps", [])
        if existing_plan
        else []
    )

    worktree_path = None
    branch_name = None
    resume_multi_step = False

    # Worktree bilgisi yalnizca gercekten
    # resume adayi olan eski multi-step
    # planlarda hesaplanir.
    if (
        existing_plan
        and len(existing_steps) > 1
    ):
        worktree_path, branch_name = (
            _get_expected_worktree(
                orchestrator,
                task_id,
            )
        )

        resume_multi_step = bool(
            os.path.isdir(worktree_path)
            and os.path.exists(
                os.path.join(
                    worktree_path,
                    ".git",
                )
            )
        )

    if resume_multi_step:
        plan = {
            "planner_mode": "multi_step",
            "summary": (
                existing_plan.get("summary")
            ),
            "steps": existing_steps,
        }

        if progress_handler is not None:
            progress_handler(
                task_id,
                message=(
                    "Planner: mevcut multi-step "
                    "plan resume ediliyor."
                ),
            )

    else:
        plan = build_task_plan(
            prompt,
            model_client=(
                orchestrator.model_client
            ),
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

    # SINGLE_STEP_AGENT_PIPELINE_V1
    # Basit WRITE gorevleri de agent pipeline'dan gecsin:
    # WRITE -> REVIEW handoff -> VERIFY -> APPROVAL.
    # Reviewer, TaskStepHandlers.write() tarafindan uretilen
    # quality-gate handoff ile gercekten calisir.
    if planner_mode == "single_step":
        steps = list(plan.get("steps", []))

        has_verify = any(
            str(step.get("kind", ""))
            .strip()
            .lower()
            == "verify"
            for step in steps
        )

        if not has_verify:
            steps.append(
                {
                    "title": "Dogrula",
                    "instruction": (
                        "Uygulanan degisikligi dogrula ve "
                        "ilgili testleri calistir."
                    ),
                    "kind": "verify",
                    "status": "pending",
                    "attempt": 0,
                }
            )

            plan["steps"] = steps

            save_task_plan(
                task_id,
                plan["steps"],
                summary=plan.get("summary"),
            )

    if (
        progress_handler is not None
        and not resume_multi_step
    ):
        progress_handler(
            task_id,
            message=(
                "Planner: "
                f"{planner_mode} - "
                f"{plan.get('summary', '')}"
            ),
        )

    if planner_mode in {"multi_step", "single_step"}:
        result = run_multi_step_task(
            orchestrator=orchestrator,
            prompt=prompt,
            task_id=task_id,
            max_attempts=max_attempts,
            approval_handler=approval_handler,
            progress_handler=progress_handler,
            model_name=model_route.model,
            resume_worktree_path=(
                worktree_path
                if resume_multi_step
                else None
            ),
            resume_branch=(
                branch_name
                if resume_multi_step
                else None
            ),
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
