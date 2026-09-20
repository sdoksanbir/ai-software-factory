from pathlib import Path
from typing import Any

from factory.agent_checkpoint_store import (
    get_agent_checkpoint,
)
from factory.database import DEFAULT_DB_PATH
from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)


HANDOFF_CONTEXT_SCHEMA = "handoff_context.v1"
MAX_CHECKPOINT_LINEAGE = 8


def _checkpoint_payload(
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    payload = checkpoint.get("payload")

    if isinstance(payload, dict):
        return dict(payload)

    return {}


def _normalize_files(
    value: Any,
) -> list[str]:
    if not isinstance(
        value,
        (
            list,
            tuple,
            set,
            frozenset,
        ),
    ):
        return []

    files = {
        str(item).strip()
        for item in value
        if str(item).strip()
    }

    return sorted(
        files,
        key=str.casefold,
    )


def _build_artifacts(
    payload: dict[str, Any],
) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}

    files = _normalize_files(
        payload.get("files")
    )

    if files:
        artifacts["files"] = files

    model = payload.get("model")

    if model not in (
        None,
        "",
    ):
        artifacts["model"] = model

    # These fields are optional today but are
    # deliberately part of the context contract
    # for reviewer/verifier handoffs.
    for key in (
        "diff",
        "test_result",
        "test_output",
        "verification",
    ):
        value = payload.get(key)

        if value not in (
            None,
            "",
            [],
            {},
        ):
            artifacts[key] = value

    return artifacts


def _lineage_item(
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    payload = _checkpoint_payload(
        checkpoint
    )

    return {
        "checkpoint_id": checkpoint.get(
            "checkpoint_id"
        ),
        "step_index": checkpoint.get(
            "step_index"
        ),
        "agent_name": checkpoint.get(
            "agent_name"
        ),
        "provider_name": checkpoint.get(
            "provider_name"
        ),
        "status": checkpoint.get(
            "status"
        ),
        "summary": checkpoint.get(
            "summary"
        ),
        "source_checkpoint_id": (
            payload.get(
                "source_checkpoint_id"
            )
        ),
    }


def _build_checkpoint_lineage(
    checkpoint: dict[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
]:
    lineage: list[
        dict[str, Any]
    ] = []

    seen: set[str] = set()

    current: dict[str, Any] | None = (
        checkpoint
    )

    cycle_detected = False
    truncated = False
    missing_checkpoint_id = None

    for _ in range(
        MAX_CHECKPOINT_LINEAGE
    ):
        if current is None:
            break

        checkpoint_id = str(
            current.get(
                "checkpoint_id",
                "",
            )
            or ""
        ).strip()

        if not checkpoint_id:
            break

        if checkpoint_id in seen:
            cycle_detected = True
            break

        seen.add(checkpoint_id)

        lineage.append(
            _lineage_item(current)
        )

        payload = _checkpoint_payload(
            current
        )

        source_checkpoint_id = str(
            payload.get(
                "source_checkpoint_id",
                "",
            )
            or ""
        ).strip()

        if not source_checkpoint_id:
            break

        if source_checkpoint_id in seen:
            cycle_detected = True
            break

        current = get_agent_checkpoint(
            source_checkpoint_id,
            db_path=db_path,
        )

        if current is None:
            missing_checkpoint_id = (
                source_checkpoint_id
            )
            break

    else:
        # The loop exhausted its safety bound.
        last_payload = (
            _checkpoint_payload(current)
            if current is not None
            else {}
        )

        if last_payload.get(
            "source_checkpoint_id"
        ):
            truncated = True

    lineage_state = {
        "complete": not (
            cycle_detected
            or truncated
            or missing_checkpoint_id
        ),
        "cycle_detected": cycle_detected,
        "truncated": truncated,
        "missing_checkpoint_id": (
            missing_checkpoint_id
        ),
    }

    return (
        lineage,
        lineage_state,
    )


def build_handoff_context(
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
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    payload = _checkpoint_payload(
        checkpoint
    )

    lineage, lineage_state = (
        _build_checkpoint_lineage(
            checkpoint,
            db_path=db_path,
        )
    )

    capability_names = sorted(
        capability.value
        for capability
        in required_capabilities
    )

    # Keep the original top-level fields for
    # backward compatibility with existing
    # handoff consumers.
    return {
        "schema": HANDOFF_CONTEXT_SCHEMA,
        "task_id": checkpoint["task_id"],
        "step_index": checkpoint[
            "step_index"
        ],
        "source_checkpoint_id": (
            checkpoint["checkpoint_id"]
        ),
        "source_agent": checkpoint[
            "agent_name"
        ],
        "source_provider": checkpoint[
            "provider_name"
        ],
        "summary": checkpoint.get(
            "summary"
        ),
        "payload": payload,

        # Stable structured context for future
        # multi-agent consumers.
        "task": {
            "task_id": checkpoint[
                "task_id"
            ],
            "step_index": checkpoint[
                "step_index"
            ],
        },
        "source": {
            "checkpoint_id": (
                checkpoint[
                    "checkpoint_id"
                ]
            ),
            "agent_name": checkpoint[
                "agent_name"
            ],
            "provider_name": checkpoint[
                "provider_name"
            ],
            "status": checkpoint.get(
                "status"
            ),
        },
        "target": {
            "agent_name": (
                target_agent.name
            ),
            "provider_name": (
                target_agent.provider_name
            ),
        },
        "handoff": {
            "reason": str(
                reason
            ).strip(),
            "required_capabilities": (
                capability_names
            ),
        },
        "artifacts": _build_artifacts(
            payload
        ),
        "checkpoint_lineage": lineage,
        "lineage_state": lineage_state,
    }
