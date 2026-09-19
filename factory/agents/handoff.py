import json
from dataclasses import dataclass
from typing import Any

from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
    get_agent_checkpoint,
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
    context: dict[str, Any]


def _build_handoff_context(
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_id": checkpoint["task_id"],
        "step_index": checkpoint["step_index"],
        "source_checkpoint_id": (
            checkpoint["checkpoint_id"]
        ),
        "source_agent": checkpoint["agent_name"],
        "source_provider": (
            checkpoint["provider_name"]
        ),
        "summary": checkpoint.get(
            "summary"
        ),
        "payload": checkpoint.get(
            "payload"
        ) or {},
    }


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

    source_agent = str(
        checkpoint["agent_name"]
    ).strip()

    matches = (
        runtime
        .agent_router
        .matching_agents(
            required_capabilities,
            preferred_provider=(
                preferred_provider
            ),
        )
    )

    target_agent = next(
        (
            agent
            for agent in matches
            if agent.name != source_agent
        ),
        None,
    )

    if target_agent is None:
        required_names = ", ".join(
            sorted(
                capability.value
                for capability
                in required_capabilities
            )
        )

        raise LookupError(
            "No alternate agent supports "
            "required capabilities: "
            f"{required_names}"
        )

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
        context=_build_handoff_context(
            checkpoint
        ),
    )


def execute_prepared_handoff(
    prepared: PreparedAgentHandoff,
    *,
    instruction: str,
    model_role: str = "fast_local",
    model_name: str | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
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
            "target_agent": (
                prepared.target_agent.name
            ),
        },
    )

    try:
        result = (
            prepared
            .target_provider
            .complete(request)
        )

        target_checkpoint = (
            create_agent_checkpoint(
                prepared
                .source_checkpoint[
                    "task_id"
                ],
                step_index=(
                    prepared
                    .source_checkpoint[
                        "step_index"
                    ]
                ),
                agent_name=(
                    prepared.target_agent.name
                ),
                provider_name=(
                    prepared
                    .target_provider
                    .provider_name
                ),
                status="completed",
                summary=result.content,
                payload={
                    "handoff_id": handoff_id,
                    "source_checkpoint_id": (
                        prepared
                        .source_checkpoint[
                            "checkpoint_id"
                        ]
                    ),
                    "model": result.model,
                    "result_metadata": dict(
                        result.metadata
                    ),
                },
                **store_kwargs,
            )
        )

        update_agent_handoff(
            handoff_id,
            status="completed",
            **store_kwargs,
        )

    except Exception:
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
