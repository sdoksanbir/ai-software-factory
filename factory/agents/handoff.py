import json
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any

from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
    get_agent_checkpoint,
    list_agent_checkpoints,
)
from factory.agent_execution_store import (
    complete_agent_execution,
    create_agent_execution,
    fail_agent_execution,
    list_agent_executions,
)
from factory.agent_handoff_store import (
    create_agent_handoff,
    get_agent_handoff,
    update_agent_handoff,
)
from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.contracts import (
    AgentProvider,
    AgentRequest,
    AgentResult,
)
from factory.agents.execution_router import (
    AgentExecutionRouter,
)
from factory.agents.handoff_decision import (
    decide_handoff_target,
)
from factory.agents.handoff_context import (
    build_handoff_context,
)
from factory.agents.router import (
    AgentRouter,
)


@dataclass(frozen=True)
class ExecutedAgentHandoff:
    handoff: dict[str, Any]
    source_checkpoint: dict[str, Any]
    target_checkpoint: dict[str, Any]
    result: AgentResult


@dataclass(frozen=True)
class PreparedAgentHandoff:
    handoff: dict[str, Any]
    source_checkpoint: dict[str, Any]
    target_agent: AgentDescriptor
    target_provider: AgentProvider
    runtime: AgentExecutionRouter
    required_capabilities: frozenset[
        AgentCapability
    ]
    context: dict[str, Any]


def _build_handoff_context(
    checkpoint: dict[str, Any],
    *,
    reason: str,
    required_capabilities: set[
        AgentCapability
    ]
    | frozenset[
        AgentCapability
    ],
    target_agent: AgentDescriptor,
    db_path=None,
) -> dict[str, Any]:
    context_kwargs = {}

    if db_path is not None:
        context_kwargs["db_path"] = db_path

    return build_handoff_context(
        checkpoint,
        reason=reason,
        required_capabilities=(
            required_capabilities
        ),
        target_agent=target_agent,
        **context_kwargs,
    )


def prepare_agent_handoff(
    source_checkpoint_id: str,
    *,
    required_capabilities: set[
        AgentCapability
    ]
    | frozenset[
        AgentCapability
    ],
    reason: str,
    runtime: AgentExecutionRouter,
    preferred_provider: str | None = None,
    db_path=None,
) -> PreparedAgentHandoff:
    checkpoint_kwargs = {}

    if db_path is not None:
        checkpoint_kwargs["db_path"] = (
            db_path
        )

    checkpoint = get_agent_checkpoint(
        source_checkpoint_id,
        **checkpoint_kwargs,
    )

    if checkpoint is None:
        raise KeyError(
            "Unknown source checkpoint: "
            f"{source_checkpoint_id}"
        )

    decision = decide_handoff_target(
        source_agent=(
            checkpoint["agent_name"]
        ),
        required_capabilities=(
            required_capabilities
        ),
        reason=reason,
        router=runtime.agent_router,
        preferred_provider=(
            preferred_provider
        ),
    )

    target_agent = decision.target_agent

    target_provider = (
        runtime
        .provider_registry
        .get(
            target_agent.provider_name
        )
    )

    handoff_kwargs = {}

    if db_path is not None:
        handoff_kwargs["db_path"] = (
            db_path
        )

    handoff = create_agent_handoff(
        source_checkpoint_id=(
            source_checkpoint_id
        ),
        target_agent=target_agent.name,
        reason=reason,
        **handoff_kwargs,
    )

    return PreparedAgentHandoff(
        handoff=handoff,
        source_checkpoint=checkpoint,
        target_agent=target_agent,
        target_provider=target_provider,
        runtime=runtime,
        required_capabilities=frozenset(
            required_capabilities
        ),
        context=_build_handoff_context(
            checkpoint,
            reason=decision.reason,
            required_capabilities=(
                decision
                .required_capabilities
            ),
            target_agent=target_agent,
            db_path=db_path,
        ),
    )


def _build_handoff_fallback_runtime(
    prepared: PreparedAgentHandoff,
) -> AgentExecutionRouter:
    source_name = str(
        prepared.source_checkpoint[
            "agent_name"
        ]
    ).strip().casefold()

    target_name = (
        prepared.target_agent.name
        .strip()
        .casefold()
    )

    agents = [
        prepared.target_agent
    ]

    for agent in (
        prepared.runtime
        .agent_router
        .agents()
    ):
        agent_name = (
            agent.name
            .strip()
            .casefold()
        )

        if agent_name == source_name:
            continue

        if agent_name == target_name:
            continue

        agents.append(agent)

    return AgentExecutionRouter(
        agent_router=AgentRouter(
            agents
        ),
        provider_registry=(
            prepared.runtime
            .provider_registry
        ),
    )


def _find_handoff_target_checkpoint(
    prepared: PreparedAgentHandoff,
    *,
    handoff_id: str,
    db_path=None,
) -> dict[str, Any] | None:
    kwargs = {}

    if db_path is not None:
        kwargs["db_path"] = db_path

    checkpoints = list_agent_checkpoints(
        prepared.source_checkpoint[
            "task_id"
        ],
        step_index=(
            prepared.source_checkpoint[
                "step_index"
            ]
        ),
        **kwargs,
    )

    source_checkpoint_id = str(
        prepared.source_checkpoint[
            "checkpoint_id"
        ]
    )

    matches = []

    for checkpoint in checkpoints:
        if (
            checkpoint.get("status")
            != "completed"
        ):
            continue

        payload = checkpoint.get(
            "payload"
        )

        if not isinstance(
            payload,
            dict,
        ):
            continue

        if (
            str(
                payload.get(
                    "handoff_id",
                    "",
                )
            )
            != handoff_id
        ):
            continue

        if (
            str(
                payload.get(
                    "source_checkpoint_id",
                    "",
                )
            )
            != source_checkpoint_id
        ):
            continue

        matches.append(
            checkpoint
        )

    if len(matches) > 1:
        raise RuntimeError(
            "Duplicate completed target "
            "checkpoints detected for handoff "
            f"{handoff_id}"
        )

    if not matches:
        return None

    return matches[0]


def _result_from_handoff_checkpoint(
    checkpoint: dict[str, Any],
) -> AgentResult:
    payload = checkpoint.get(
        "payload"
    )

    if not isinstance(
        payload,
        dict,
    ):
        payload = {}

    metadata = payload.get(
        "result_metadata"
    )

    if not isinstance(
        metadata,
        dict,
    ):
        metadata = {}

    model = payload.get(
        "model"
    )

    if model is not None:
        model = str(model)

    return AgentResult(
        content=str(
            checkpoint.get(
                "summary",
                "",
            )
            or ""
        ),
        provider=str(
            checkpoint.get(
                "provider_name",
                "",
            )
            or ""
        ),
        model=model,
        metadata=dict(
            metadata
        ),
    )


def _list_handoff_executions(
    prepared: PreparedAgentHandoff,
    *,
    handoff_id: str,
    db_path=None,
) -> list[dict[str, Any]]:
    kwargs = {}

    if db_path is not None:
        kwargs["db_path"] = db_path

    executions = list_agent_executions(
        prepared.source_checkpoint[
            "task_id"
        ],
        **kwargs,
    )

    return [
        execution
        for execution in executions
        if str(
            execution.get(
                "handoff_id",
                "",
            )
            or ""
        )
        == handoff_id
    ]


def execute_prepared_handoff(
    prepared: PreparedAgentHandoff,
    *,
    instruction: str,
    model_role: str = "fast_local",
    model_name: str | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
    retry_interrupted: bool = False,
    db_path=None,
) -> ExecutedAgentHandoff:
    instruction = str(
        instruction or ""
    ).strip()

    if not instruction:
        raise ValueError(
            "instruction must not be blank"
        )

    handoff_id = str(
        prepared.handoff["handoff_id"]
    )

    store_kwargs = {}

    if db_path is not None:
        store_kwargs["db_path"] = (
            db_path
        )

    stored_handoff = get_agent_handoff(
        handoff_id,
        **store_kwargs,
    )

    if stored_handoff is None:
        raise RuntimeError(
            "Handoff disappeared before execution"
        )

    existing_target = (
        _find_handoff_target_checkpoint(
            prepared,
            handoff_id=handoff_id,
            db_path=db_path,
        )
    )

    # Crash may happen after target checkpoint
    # creation but before handoff completion.
    # In that case the provider MUST NOT run again.
    if existing_target is not None:
        if (
            stored_handoff["status"]
            != "completed"
        ):
            update_agent_handoff(
                handoff_id,
                status="completed",
                **store_kwargs,
            )

        recovered_handoff = (
            get_agent_handoff(
                handoff_id,
                **store_kwargs,
            )
        )

        if recovered_handoff is None:
            raise RuntimeError(
                "Handoff disappeared during "
                "checkpoint recovery"
            )

        return ExecutedAgentHandoff(
            handoff=recovered_handoff,
            source_checkpoint=(
                prepared.source_checkpoint
            ),
            target_checkpoint=(
                existing_target
            ),
            result=(
                _result_from_handoff_checkpoint(
                    existing_target
                )
            ),
        )

    if (
        stored_handoff["status"]
        == "completed"
    ):
        raise RuntimeError(
            "Completed handoff has no completed "
            "target checkpoint: "
            f"{handoff_id}"
        )

    prior_executions = (
        _list_handoff_executions(
            prepared,
            handoff_id=handoff_id,
            db_path=db_path,
        )
    )

    running_executions = [
        execution
        for execution in prior_executions
        if str(
            execution.get(
                "status",
                "",
            )
        ).strip().lower()
        in {
            "running",
            "created",
            "pending",
        }
    ]

    # accepted + running + no checkpoint is
    # ambiguous: provider may have completed just
    # before the process crashed. Never repeat it
    # automatically.
    if running_executions:
        if not retry_interrupted:
            raise RuntimeError(
                "Interrupted handoff has no "
                "completed target checkpoint; "
                "explicit retry required"
            )

        for old_execution in (
            running_executions
        ):
            fail_agent_execution(
                old_execution[
                    "execution_id"
                ],
                error=(
                    "Interrupted handoff explicitly "
                    "retried"
                ),
                duration_ms=0,
                metadata={
                    "execution_type": (
                        "handoff"
                    ),
                    "handoff_id": (
                        handoff_id
                    ),
                    "recovery": (
                        "explicit_retry"
                    ),
                },
                **store_kwargs,
            )

    update_agent_handoff(
        handoff_id,
        status="accepted",
        **store_kwargs,
    )

    context_json = json.dumps(
        prepared.context,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        default=str,
    )

    request = AgentRequest(
        model_role=model_role,
        system_prompt=(
            "You are continuing work handed off "
            "from another software agent. "
            "Use the supplied checkpoint as prior "
            "work context. "
            "Do not claim work that is not present "
            "in the checkpoint. "
            "Complete only the requested handoff "
            "instruction."
        ),
        user_prompt=(
            "HANDOFF INSTRUCTION:\n"
            f"{instruction}\n\n"
            "SOURCE CHECKPOINT CONTEXT:\n"
            f"{context_json}"
        ),
        temperature=temperature,
        timeout=timeout,
        model_name=model_name,
        metadata={
            "handoff_id": handoff_id,
            "source_checkpoint_id": (
                prepared
                .source_checkpoint[
                    "checkpoint_id"
                ]
            ),
            "planned_target_agent": (
                prepared.target_agent.name
            ),
            "fallback_allowed": True,
        },
    )

    fallback_runtime = (
        _build_handoff_fallback_runtime(
            prepared
        )
    )

    task_id = str(
        prepared.source_checkpoint[
            "task_id"
        ]
    )

    step_index = (
        prepared.source_checkpoint[
            "step_index"
        ]
    )

    source_checkpoint_id = str(
        prepared.source_checkpoint[
            "checkpoint_id"
        ]
    )

    def create_execution(
        *,
        agent_name: str,
        provider_name: str,
        provider_attempt: int,
        fallback: bool,
    ):
        return create_agent_execution(
            task_id,
            step_index=step_index,
            handoff_id=handoff_id,
            source_checkpoint_id=(
                source_checkpoint_id
            ),
            agent_name=agent_name,
            provider_name=provider_name,
            model_name=model_name,
            capabilities=[
                capability.value
                for capability
                in prepared
                .required_capabilities
            ],
            metadata={
                "execution_type": "handoff",
                "provider_attempt": (
                    provider_attempt
                ),
                "fallback": fallback,
                "planned_target_agent": (
                    prepared
                    .target_agent
                    .name
                ),
            },
            **store_kwargs,
        )

    execution = None
    started_ns = perf_counter_ns()

    try:
        # Create the planned-target execution
        # before provider invocation so a crash
        # still leaves an observable attempt.
        execution = create_execution(
            agent_name=(
                prepared.target_agent.name
            ),
            provider_name=(
                prepared
                .target_provider
                .provider_name
            ),
            provider_attempt=1,
            fallback=False,
        )

        fallback_execution = (
            fallback_runtime
            .execute_with_fallback(
                request,
                prepared
                .required_capabilities,
                preferred_provider=(
                    prepared
                    .target_provider
                    .provider_name
                ),
            )
        )

        result = (
            fallback_execution.result
        )

        successful_route = (
            fallback_execution.route
        )

        failures = (
            fallback_execution.failures
        )

        # If fallback occurred, close the
        # initially-created execution as failed.
        if failures:
            first_failure = failures[0]

            fail_agent_execution(
                execution[
                    "execution_id"
                ],
                error=first_failure.error,
                duration_ms=0,
                metadata={
                    "execution_type": (
                        "handoff"
                    ),
                    "handoff_id": handoff_id,
                    "provider_attempt": 1,
                    "fallback": False,
                    "error_type": (
                        first_failure
                        .error_type
                    ),
                },
                **store_kwargs,
            )

            execution = None

            # Record any additional failed
            # fallback providers.
            for provider_attempt, failure in (
                enumerate(
                    failures[1:],
                    start=2,
                )
            ):
                failed_execution = (
                    create_execution(
                        agent_name=(
                            failure
                            .agent_name
                        ),
                        provider_name=(
                            failure
                            .provider_name
                        ),
                        provider_attempt=(
                            provider_attempt
                        ),
                        fallback=True,
                    )
                )

                fail_agent_execution(
                    failed_execution[
                        "execution_id"
                    ],
                    error=failure.error,
                    duration_ms=0,
                    metadata={
                        "execution_type": (
                            "handoff"
                        ),
                        "handoff_id": (
                            handoff_id
                        ),
                        "provider_attempt": (
                            provider_attempt
                        ),
                        "fallback": True,
                        "error_type": (
                            failure
                            .error_type
                        ),
                    },
                    **store_kwargs,
                )

            # The successful fallback gets its
            # own execution identity.
            execution = create_execution(
                agent_name=(
                    successful_route
                    .agent
                    .name
                ),
                provider_name=(
                    successful_route
                    .provider
                    .provider_name
                ),
                provider_attempt=(
                    len(failures) + 1
                ),
                fallback=True,
            )

        target_checkpoint = (
            create_agent_checkpoint(
                task_id,
                step_index=step_index,
                agent_name=(
                    successful_route
                    .agent
                    .name
                ),
                provider_name=(
                    successful_route
                    .provider
                    .provider_name
                ),
                status="completed",
                summary=result.content,
                payload={
                    "handoff_id": handoff_id,
                    "source_checkpoint_id": (
                        source_checkpoint_id
                    ),
                    "source_agent": (
                        prepared
                        .source_checkpoint[
                            "agent_name"
                        ]
                    ),
                    "source_provider": (
                        prepared
                        .source_checkpoint[
                            "provider_name"
                        ]
                    ),
                    "handoff_context_schema": (
                        prepared.context.get(
                            "schema"
                        )
                    ),
                    "required_capabilities": sorted(
                        capability.value
                        for capability
                        in prepared
                        .required_capabilities
                    ),
                    "planned_target_agent": (
                        prepared.target_agent.name
                    ),
                    "planned_target_provider": (
                        prepared
                        .target_provider
                        .provider_name
                    ),
                    "fallback_used": bool(
                        failures
                    ),
                    "fallback_attempts": [
                        {
                            "agent_name": (
                                failure
                                .agent_name
                            ),
                            "provider_name": (
                                failure
                                .provider_name
                            ),
                            "error": (
                                failure.error
                            ),
                            "error_type": (
                                failure
                                .error_type
                            ),
                        }
                        for failure in failures
                    ],
                    "model": result.model,
                    "result_metadata": dict(
                        result.metadata
                    ),
                },
                **store_kwargs,
            )
        )

        duration_ms = max(
            0,
            (
                perf_counter_ns()
                - started_ns
            )
            // 1_000_000,
        )

        result_metadata = dict(
            result.metadata
        )

        usage = result_metadata.get(
            "usage"
        )

        if not isinstance(
            usage,
            dict,
        ):
            usage = {}

        complete_agent_execution(
            execution["execution_id"],
            result_checkpoint_id=(
                target_checkpoint[
                    "checkpoint_id"
                ]
            ),
            model_name=(
                result.model
                or model_name
            ),
            duration_ms=duration_ms,
            prompt_tokens=usage.get(
                "prompt_tokens"
            ),
            completion_tokens=usage.get(
                "completion_tokens"
            ),
            cost=float(
                usage.get(
                    "cost",
                    0.0,
                )
                or 0.0
            ),
            metadata={
                "execution_type": "handoff",
                "handoff_id": handoff_id,
                "provider_attempt": (
                    len(failures) + 1
                ),
                "fallback": bool(
                    failures
                ),
                "fallback_attempts": [
                    {
                        "agent_name": (
                            failure
                            .agent_name
                        ),
                        "provider_name": (
                            failure
                            .provider_name
                        ),
                        "error": (
                            failure.error
                        ),
                        "error_type": (
                            failure
                            .error_type
                        ),
                    }
                    for failure in failures
                ],
            },
            **store_kwargs,
        )

        update_agent_handoff(
            handoff_id,
            status="completed",
            **store_kwargs,
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

        if execution is not None:
            try:
                fail_agent_execution(
                    execution[
                        "execution_id"
                    ],
                    error=str(exc),
                    duration_ms=duration_ms,
                    metadata={
                        "execution_type": (
                            "handoff"
                        ),
                        "handoff_id": (
                            handoff_id
                        ),
                    },
                    **store_kwargs,
                )
            except Exception:
                pass

        update_agent_handoff(
            handoff_id,
            status="failed",
            **store_kwargs,
        )

        raise

    handoff = get_agent_handoff(
        handoff_id,
        **store_kwargs,
    )

    if handoff is None:
        raise RuntimeError(
            "Handoff disappeared after execution"
        )

    return ExecutedAgentHandoff(
        handoff=handoff,
        source_checkpoint=(
            prepared.source_checkpoint
        ),
        target_checkpoint=(
            target_checkpoint
        ),
        result=result,
    )
