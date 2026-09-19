from pathlib import Path
from typing import Any
from uuid import uuid4

from factory.agent_checkpoint_store import (
    get_agent_checkpoint,
    init_agent_checkpoint_store,
    update_agent_checkpoint,
)
from factory.database import (
    DEFAULT_DB_PATH,
    get_connection,
)


HANDOFF_STATUSES = {
    "pending",
    "accepted",
    "completed",
    "failed",
    "cancelled",
}


def _require_text(
    value: Any,
    field_name: str,
) -> str:
    normalized = str(
        value or ""
    ).strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must not be blank"
        )

    return normalized


def _require_status(
    status: str,
) -> str:
    normalized = _require_text(
        status,
        "handoff status",
    ).lower()

    if normalized not in HANDOFF_STATUSES:
        raise ValueError(
            "Invalid handoff status: "
            f"{normalized}"
        )

    return normalized


def init_agent_handoff_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    init_agent_checkpoint_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS
                agent_handoffs (
                    handoff_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_index INTEGER,
                    source_checkpoint_id TEXT NOT NULL,
                    source_agent TEXT NOT NULL,
                    target_agent TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL
                        DEFAULT 'pending',
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                );

            CREATE INDEX IF NOT EXISTS
                idx_agent_handoffs_task
            ON agent_handoffs (
                task_id,
                step_index,
                created_at
            );

            CREATE INDEX IF NOT EXISTS
                idx_agent_handoffs_checkpoint
            ON agent_handoffs (
                source_checkpoint_id
            );
            """
        )

        connection.commit()

    finally:
        connection.close()


def create_agent_handoff(
    *,
    source_checkpoint_id: str,
    target_agent: str,
    reason: str,
    status: str = "pending",
    handoff_id: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    source_checkpoint_id = _require_text(
        source_checkpoint_id,
        "source_checkpoint_id",
    )

    target_agent = _require_text(
        target_agent,
        "target_agent",
    )

    reason = _require_text(
        reason,
        "reason",
    )

    status = _require_status(
        status
    )

    checkpoint = get_agent_checkpoint(
        source_checkpoint_id,
        db_path=db_path,
    )

    if checkpoint is None:
        raise KeyError(
            "Unknown source checkpoint: "
            f"{source_checkpoint_id}"
        )

    source_agent = _require_text(
        checkpoint["agent_name"],
        "source_agent",
    )

    if (
        target_agent.strip().lower()
        == source_agent.strip().lower()
    ):
        raise ValueError(
            "target_agent must differ from "
            "source_agent"
        )

    handoff_id = _require_text(
        handoff_id
        or f"HOF-{uuid4().hex[:12]}",
        "handoff_id",
    )

    init_agent_handoff_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        connection.execute(
            """
            INSERT INTO agent_handoffs (
                handoff_id,
                task_id,
                step_index,
                source_checkpoint_id,
                source_agent,
                target_agent,
                reason,
                status
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                handoff_id,
                checkpoint["task_id"],
                checkpoint["step_index"],
                source_checkpoint_id,
                source_agent,
                target_agent,
                reason,
                status,
            ),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    if status in {
        "pending",
        "accepted",
        "completed",
    }:
        update_agent_checkpoint(
            source_checkpoint_id,
            status="handed_off",
            db_path=db_path,
        )

    handoff = get_agent_handoff(
        handoff_id,
        db_path=db_path,
    )

    if handoff is None:
        raise RuntimeError(
            "Handoff could not be loaded "
            "after create"
        )

    return handoff


def get_agent_handoff(
    handoff_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    handoff_id = _require_text(
        handoff_id,
        "handoff_id",
    )

    init_agent_handoff_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT *
            FROM agent_handoffs
            WHERE handoff_id = ?
            """,
            (handoff_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def list_agent_handoffs(
    task_id: str,
    *,
    step_index: int | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    task_id = _require_text(
        task_id,
        "task_id",
    )

    if (
        step_index is not None
        and step_index < 1
    ):
        raise ValueError(
            "step_index must be >= 1"
        )

    init_agent_handoff_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        if step_index is None:
            rows = connection.execute(
                """
                SELECT *
                FROM agent_handoffs
                WHERE task_id = ?
                ORDER BY created_at ASC,
                         handoff_id ASC
                """,
                (task_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM agent_handoffs
                WHERE task_id = ?
                  AND step_index = ?
                ORDER BY created_at ASC,
                         handoff_id ASC
                """,
                (
                    task_id,
                    step_index,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def update_agent_handoff(
    handoff_id: str,
    *,
    status: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    handoff_id = _require_text(
        handoff_id,
        "handoff_id",
    )

    status = _require_status(
        status
    )

    init_agent_handoff_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        cursor = connection.execute(
            """
            UPDATE agent_handoffs
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE handoff_id = ?
            """,
            (
                status,
                handoff_id,
            ),
        )

        if cursor.rowcount == 0:
            raise KeyError(
                "Unknown handoff: "
                f"{handoff_id}"
            )

        connection.commit()

    finally:
        connection.close()
