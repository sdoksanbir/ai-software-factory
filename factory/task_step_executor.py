from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Callable

from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
)
from factory.agent_execution_store import (
    complete_agent_execution,
    create_agent_execution,
    fail_agent_execution,
)
from factory.agents.step_capabilities import (
    capabilities_for_step,
)
from factory.database import DEFAULT_DB_PATH
from factory.task_plan_store import (
    get_task_plan,
    update_task_plan_status,
    update_task_step,
)


@dataclass(frozen=True)
class StepHandlerResult:
    output: str | None
    agent_name: str | None = None
    provider_name: str | None = None
    checkpoint_payload: dict[str, Any] = field(
        default_factory=dict
    )
    fallback_attempts: tuple[
        dict[str, Any],
        ...,
    ] = field(
        default_factory=tuple
    )


StepHandler = Callable[
    [dict[str, Any], str],
    str | None | StepHandlerResult,
]


class AgentStepExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        agent_name: str,
        provider_name: str,
        model_name: str | None = None,
        capabilities: list[str] | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.provider_name = provider_name
        self.model_name = model_name
        self.capabilities = list(
            capabilities or []
        )

        super().__init__(message)


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

        started_ns = perf_counter_ns()

        try:
            result = handler(
                step_payload,
                worktree_path,
            )

        except Exception as exc:
            duration_ms = max(
                0,
                (
                    perf_counter_ns()
                    - started_ns
                )
                // 1_000_000,
            )

            if isinstance(
                exc,
                AgentStepExecutionError,
            ):
                try:
                    execution = (
                        create_agent_execution(
                            task_id,
                            step_index=step_index,
                            agent_name=(
                                exc.agent_name
                            ),
                            provider_name=(
                                exc.provider_name
                            ),
                            model_name=(
                                exc.model_name
                            ),
                            capabilities=(
                                exc.capabilities
                            ),
                            metadata={
                                "attempt": (
                                    current_attempt
                                ),
                                "step_kind": kind,
                            },
                            db_path=db_path,
                        )
                    )

                    fail_agent_execution(
                        execution[
                            "execution_id"
                        ],
                        error=str(exc),
                        duration_ms=duration_ms,
                        metadata={
                            "attempt": (
                                current_attempt
                            ),
                            "step_kind": kind,
                        },
                        db_path=db_path,
                    )

                except Exception:
                    # Telemetry must not hide the
                    # original agent failure.
                    pass

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

        checkpoint_result = (
            result
            if isinstance(
                result,
                StepHandlerResult,
            )
            else None
        )

        output = (
            checkpoint_result.output
            if checkpoint_result is not None
            else result
        )

        try:
            agent_name = ""
            provider_name = ""

            if checkpoint_result is not None:
                agent_name = str(
                    checkpoint_result.agent_name
                    or ""
                ).strip()

                provider_name = str(
                    checkpoint_result.provider_name
                    or ""
                ).strip()

                if bool(agent_name) != bool(
                    provider_name
                ):
                    raise ValueError(
                        "checkpoint agent_name and "
                        "provider_name must be "
                        "supplied together"
                    )

            execution = None

            duration_ms = max(
                0,
                (
                    perf_counter_ns()
                    - started_ns
                )
                // 1_000_000,
            )

            if agent_name and provider_name:
                checkpoint_payload = {
                    "step_kind": kind,
                    "attempt": current_attempt,
                    **checkpoint_result
                    .checkpoint_payload,
                }

                capabilities = [
                    capability.value
                    for capability
                    in capabilities_for_step(
                        kind
                    )
                    if capability.value
                    != "run_tests"
                ]

                fallback_attempts = tuple(
                    checkpoint_result
                    .fallback_attempts
                )

                for (
                    provider_attempt,
                    fallback_attempt,
                ) in enumerate(
                    fallback_attempts,
                    start=1,
                ):
                    failure_agent_name = str(
                        fallback_attempt.get(
                            "agent_name",
                            "",
                        )
                    ).strip()

                    failure_provider_name = str(
                        fallback_attempt.get(
                            "provider_name",
                            "",
                        )
                    ).strip()

                    failure_error = str(
                        fallback_attempt.get(
                            "error",
                            "",
                        )
                    ).strip()

                    if not (
                        failure_agent_name
                        and failure_provider_name
                        and failure_error
                    ):
                        continue

                    failure_metadata = {
                        "attempt": current_attempt,
                        "step_kind": kind,
                        "fallback": True,
                        "provider_attempt": (
                            provider_attempt
                        ),
                        "error_type": str(
                            fallback_attempt.get(
                                "error_type",
                                "",
                            )
                        ).strip(),
                    }

                    failure_execution = (
                        create_agent_execution(
                            task_id,
                            step_index=step_index,
                            agent_name=(
                                failure_agent_name
                            ),
                            provider_name=(
                                failure_provider_name
                            ),
                            model_name=(
                                fallback_attempt.get(
                                    "model_name"
                                )
                                or checkpoint_payload.get(
                                    "model"
                                )
                            ),
                            capabilities=capabilities,
                            metadata=(
                                failure_metadata
                            ),
                            db_path=db_path,
                        )
                    )

                    fail_agent_execution(
                        failure_execution[
                            "execution_id"
                        ],
                        error=failure_error,
                        metadata=failure_metadata,
                        db_path=db_path,
                    )

                success_metadata = {
                    "attempt": current_attempt,
                    "step_kind": kind,
                    "fallback": bool(
                        fallback_attempts
                    ),
                    "provider_attempt": (
                        len(fallback_attempts)
                        + 1
                    ),
                    "fallback_count": len(
                        fallback_attempts
                    ),
                }

                execution = create_agent_execution(
                    task_id,
                    step_index=step_index,
                    agent_name=agent_name,
                    provider_name=provider_name,
                    model_name=(
                        checkpoint_payload.get(
                            "model"
                        )
                    ),
                    capabilities=capabilities,
                    metadata=success_metadata,
                    db_path=db_path,
                )

                try:
                    checkpoint = (
                        create_agent_checkpoint(
                            task_id,
                            step_index=step_index,
                            agent_name=agent_name,
                            provider_name=provider_name,
                            status="completed",
                            summary=(
                                None
                                if output is None
                                else str(output)
                            ),
                            payload=(
                                checkpoint_payload
                            ),
                            db_path=db_path,
                        )
                    )

                    complete_agent_execution(
                        execution[
                            "execution_id"
                        ],
                        result_checkpoint_id=(
                            checkpoint[
                                "checkpoint_id"
                            ]
                        ),
                        duration_ms=duration_ms,
                        metadata=(
                            success_metadata
                        ),
                        db_path=db_path,
                    )

                except Exception as exc:
                    fail_agent_execution(
                        execution[
                            "execution_id"
                        ],
                        error=str(exc),
                        duration_ms=duration_ms,
                        metadata={
                            "attempt": (
                                current_attempt
                            ),
                            "step_kind": kind,
                        },
                        db_path=db_path,
                    )
                    raise

            update_task_step(
                task_id,
                step_index,
                status="completed",
                attempt=current_attempt,
                result=(
                    ""
                    if output is None
                    else str(output)
                ),
                error="",
                db_path=db_path,
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
