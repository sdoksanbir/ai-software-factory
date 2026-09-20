from pathlib import Path
from typing import Any

from factory.agent_checkpoint_store import (
    list_agent_checkpoints,
)
from factory.agent_execution_store import (
    list_agent_executions,
)
from factory.agent_handoff_store import (
    list_agent_handoffs,
)
from factory.database import DEFAULT_DB_PATH


AGENT_CHAIN_TELEMETRY_SCHEMA = (
    "agent_chain_telemetry.v1"
)


def _role_from_agent_name(
    agent_name: str,
) -> str:
    normalized = str(
        agent_name or ""
    ).strip().lower()

    for role in (
        "analyst",
        "coder",
        "reviewer",
        "verifier",
    ):
        if (
            normalized == role
            or normalized.endswith(
                "-" + role
            )
        ):
            return role

    return "agent"


def _checkpoint_payload(
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    payload = checkpoint.get(
        "payload"
    )

    if isinstance(payload, dict):
        return payload

    return {}


def _lineage_depth(
    checkpoint_id: str,
    checkpoint_map: dict[
        str,
        dict[str, Any],
    ],
    *,
    seen: frozenset[str] = frozenset(),
) -> int:
    if checkpoint_id in seen:
        return 0

    checkpoint = checkpoint_map.get(
        checkpoint_id
    )

    if checkpoint is None:
        return 0

    source_id = str(
        _checkpoint_payload(
            checkpoint
        ).get(
            "source_checkpoint_id",
            "",
        )
        or ""
    ).strip()

    if not source_id:
        return 0

    if source_id not in checkpoint_map:
        return 1

    return (
        1
        + _lineage_depth(
            source_id,
            checkpoint_map,
            seen=seen
            | {
                checkpoint_id,
            },
        )
    )


def build_agent_chain_telemetry(
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    checkpoints = list_agent_checkpoints(
        task_id,
        db_path=db_path,
    )

    executions = list_agent_executions(
        task_id,
        db_path=db_path,
    )

    handoffs = list_agent_handoffs(
        task_id,
        db_path=db_path,
    )

    checkpoint_map = {
        str(
            checkpoint[
                "checkpoint_id"
            ]
        ): checkpoint
        for checkpoint in checkpoints
    }

    execution_ids_by_checkpoint: dict[
        str,
        list[str],
    ] = {}

    for execution in executions:
        checkpoint_id = str(
            execution.get(
                "result_checkpoint_id",
                "",
            )
            or ""
        ).strip()

        if not checkpoint_id:
            continue

        execution_ids_by_checkpoint.setdefault(
            checkpoint_id,
            [],
        ).append(
            str(
                execution[
                    "execution_id"
                ]
            )
        )

    chain = []

    orphan_sources = set()

    for checkpoint in checkpoints:
        checkpoint_id = str(
            checkpoint[
                "checkpoint_id"
            ]
        )

        payload = _checkpoint_payload(
            checkpoint
        )

        source_id = str(
            payload.get(
                "source_checkpoint_id",
                "",
            )
            or ""
        ).strip()

        if (
            source_id
            and source_id
            not in checkpoint_map
        ):
            orphan_sources.add(
                source_id
            )

        chain.append(
            {
                "checkpoint_id": (
                    checkpoint_id
                ),
                "source_checkpoint_id": (
                    source_id or None
                ),
                "handoff_id": (
                    payload.get(
                        "handoff_id"
                    )
                ),
                "step_index": (
                    checkpoint.get(
                        "step_index"
                    )
                ),
                "agent_name": (
                    checkpoint.get(
                        "agent_name"
                    )
                ),
                "provider_name": (
                    checkpoint.get(
                        "provider_name"
                    )
                ),
                "role": (
                    _role_from_agent_name(
                        str(
                            checkpoint.get(
                                "agent_name",
                                "",
                            )
                        )
                    )
                ),
                "status": (
                    checkpoint.get(
                        "status"
                    )
                ),
                "execution_ids": (
                    execution_ids_by_checkpoint
                    .get(
                        checkpoint_id,
                        [],
                    )
                ),
                "fallback_used": bool(
                    payload.get(
                        "fallback_used",
                        False,
                    )
                ),
                "depth": (
                    _lineage_depth(
                        checkpoint_id,
                        checkpoint_map,
                    )
                ),
            }
        )

    chain.sort(
        key=lambda item: (
            item["depth"],
            item["step_index"]
            if item["step_index"]
            is not None
            else -1,
            item["checkpoint_id"],
        )
    )

    fallback_attempts = []

    for execution in executions:
        metadata = execution.get(
            "metadata"
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

        provider_attempt = metadata.get(
            "provider_attempt"
        )

        fallback = bool(
            metadata.get(
                "fallback",
                False,
            )
        )

        if (
            fallback
            or (
                isinstance(
                    provider_attempt,
                    int,
                )
                and provider_attempt > 1
            )
        ):
            fallback_attempts.append(
                {
                    "execution_id": (
                        execution.get(
                            "execution_id"
                        )
                    ),
                    "handoff_id": (
                        execution.get(
                            "handoff_id"
                        )
                    ),
                    "agent_name": (
                        execution.get(
                            "agent_name"
                        )
                    ),
                    "provider_name": (
                        execution.get(
                            "provider_name"
                        )
                    ),
                    "status": (
                        execution.get(
                            "status"
                        )
                    ),
                    "provider_attempt": (
                        provider_attempt
                    ),
                }
            )

    normalized_handoffs = [
        {
            "handoff_id": (
                handoff.get(
                    "handoff_id"
                )
            ),
            "source_checkpoint_id": (
                handoff.get(
                    "source_checkpoint_id"
                )
            ),
            "source_agent": (
                handoff.get(
                    "source_agent"
                )
            ),
            "target_agent": (
                handoff.get(
                    "target_agent"
                )
            ),
            "reason": (
                handoff.get(
                    "reason"
                )
            ),
            "status": (
                handoff.get(
                    "status"
                )
            ),
        }
        for handoff in handoffs
    ]

    completed_handoffs = sum(
        1
        for handoff in handoffs
        if handoff.get(
            "status"
        )
        == "completed"
    )

    failed_executions = sum(
        1
        for execution in executions
        if execution.get(
            "status"
        )
        == "failed"
    )

    return {
        "schema": (
            AGENT_CHAIN_TELEMETRY_SCHEMA
        ),
        "task_id": task_id,
        "summary": {
            "execution_count": len(
                executions
            ),
            "checkpoint_count": len(
                checkpoints
            ),
            "handoff_count": len(
                handoffs
            ),
            "completed_handoff_count": (
                completed_handoffs
            ),
            "failed_execution_count": (
                failed_executions
            ),
            "fallback_attempt_count": (
                len(
                    fallback_attempts
                )
            ),
            "lineage_orphan_count": (
                len(
                    orphan_sources
                )
            ),
            "lineage_ok": (
                len(
                    orphan_sources
                )
                == 0
            ),
        },
        "chain": chain,
        "handoffs": normalized_handoffs,
        "fallback_attempts": (
            fallback_attempts
        ),
    }
