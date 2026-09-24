from __future__ import annotations

from typing import Any

from factory.general_agent_contracts import (
    GeneralTaskPlan,
    Permission,
    PlanStep,
    StepStatus,
)


_LEGACY_KIND_PERMISSION = {
    "read": Permission.READ,
    "write": Permission.WRITE,
    "verify": Permission.EXECUTE,
    "execute": Permission.EXECUTE,
}


_LEGACY_STATUS_MAP = {
    "pending": StepStatus.PENDING,
    "ready": StepStatus.READY,
    "running": StepStatus.RUNNING,
    "completed": StepStatus.SUCCEEDED,
    "success": StepStatus.SUCCEEDED,
    "failed": StepStatus.FAILED,
    "skipped": StepStatus.SKIPPED,
}


def from_legacy_plan(
    plan: dict[str, Any],
    *,
    goal: str,
) -> GeneralTaskPlan:
    legacy_steps = list(
        plan.get("steps") or []
    )

    if not legacy_steps:
        raise ValueError(
            "Legacy plan en az bir step icermeli."
        )

    steps: list[PlanStep] = []
    previous_id: str | None = None

    for index, item in enumerate(
        legacy_steps,
        start=1,
    ):
        kind = str(
            item.get("kind") or "read"
        ).strip().casefold()

        permission = (
            _LEGACY_KIND_PERMISSION.get(
                kind,
                Permission.READ,
            )
        )

        raw_status = str(
            item.get("status") or "pending"
        ).strip().casefold()

        status = _LEGACY_STATUS_MAP.get(
            raw_status,
            StepStatus.PENDING,
        )

        step_id = f"legacy-step-{index}"

        instruction = str(
            item.get("instruction")
            or item.get("title")
            or f"Legacy step {index}"
        ).strip()

        title = str(
            item.get("title")
            or instruction
        ).strip()

        depends_on = (
            [previous_id]
            if previous_id is not None
            else []
        )

        steps.append(
            PlanStep(
                step_id=step_id,
                title=title,
                description=instruction,
                permission=permission,
                tool=None,
                depends_on=depends_on,
                status=status,
                max_attempts=max(
                    1,
                    int(
                        item.get(
                            "max_attempts",
                            2,
                        )
                    ),
                ),
                attempt=max(
                    0,
                    int(
                        item.get(
                            "attempt",
                            0,
                        )
                    ),
                ),
            )
        )

        previous_id = step_id

    summary = str(
        plan.get("summary")
        or "Legacy task plan"
    ).strip()

    return GeneralTaskPlan(
        goal=goal,
        summary=summary,
        steps=steps,
        constraints=[
            (
                "Legacy plan adapter ile olusturuldu; "
                "tool secimi henuz yeni Tool Registry "
                "tarafindan yapilmadi."
            )
        ],
    )


def to_legacy_plan(
    plan: GeneralTaskPlan,
) -> dict[str, Any]:
    permission_kind = {
        Permission.READ: "read",
        Permission.WRITE: "write",
        Permission.EXECUTE: "execute",
        Permission.DESTRUCTIVE: "execute",
    }

    status_map = {
        StepStatus.PENDING: "pending",
        StepStatus.READY: "pending",
        StepStatus.RUNNING: "running",
        StepStatus.BLOCKED: "pending",
        StepStatus.SUCCEEDED: "completed",
        StepStatus.FAILED: "failed",
        StepStatus.SKIPPED: "skipped",
    }

    steps = []

    for step in plan.steps:
        steps.append(
            {
                "title": step.title,
                "instruction": step.description,
                "kind": permission_kind[
                    step.permission
                ],
                "status": status_map[
                    step.status
                ],
                "attempt": step.attempt,
            }
        )

    return {
        "summary": plan.summary,
        "planner_mode": (
            "multi_step"
            if len(steps) > 1
            else "single_step"
        ),
        "steps": steps,
    }
