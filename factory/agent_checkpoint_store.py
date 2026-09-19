import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from factory.database import (
    DEFAULT_DB_PATH,
    get_connection,
)


CHECKPOINT_STATUSES = {
    "created",
    "completed",
    "failed",
    "handed_off",
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
        "checkpoint status",
    ).lower()

    if normalized not in CHECKPOINT_STATUSES:
        raise ValueError(
            "Invalid checkpoint status: "
            f"{normalized}"
        )

    return normalized


def init_agent_checkpoint_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(
        db_path
    )

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS
                agent_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_index INTEGER,
                    agent_name TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    status TEXT NOT NULL
                        DEFAULT 'created',
                    summary TEXT,
                    payload TEXT NOT NULL
                        DEFAULT '{}',
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                );

            CREATE INDEX IF NOT EXISTS
                idx_agent_checkpoints_task
            ON agent_checkpoints (
                task_id,
                step_index,
                created_at
            );
            """
        )

        connection.commit()

    finally:
        connection.close()


def _decode_row(
    row: Any,
) -> dict[str, Any]:
    item = dict(row)

    raw_payload = item.get(
        "payload"
    )

    try:
        item["payload"] = json.loads(
            raw_payload or "{}"
        )
    except Exception:
        item["payload"] = {}

    return item


def create_agent_checkpoint(
    task_id: str,
    *,
    step_index: int | None,
    agent_name: str,
    provider_name: str,
    status: str = "created",
    summary: str | None = None,
    payload: dict[str, Any] | None = None,
    checkpoint_id: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    task_id = _require_text(
        task_id,
        "task_id",
    )

    agent_name = _require_text(
        agent_name,
        "agent_name",
    )

    provider_name = _require_text(
        provider_name,
        "provider_name",
    )

    status = _require_status(
        status
    )

    if (
        step_index is not None
        and step_index < 1
    ):
        raise ValueError(
            "step_index must be >= 1"
        )

    checkpoint_id = _require_text(
        checkpoint_id
        or f"CHK-{uuid4().hex[:12]}",
        "checkpoint_id",
    )

    encoded_payload = json.dumps(
        payload or {},
        ensure_ascii=False,
        sort_keys=True,
    )

    init_agent_checkpoint_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        connection.execute(
            """
            INSERT INTO agent_checkpoints (
                checkpoint_id,
                task_id,
                step_index,
                agent_name,
                provider_name,
                status,
                summary,
                payload
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                checkpoint_id,
                task_id,
                step_index,
                agent_name,
                provider_name,
                status,
                summary,
                encoded_payload,
            ),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    checkpoint = get_agent_checkpoint(
        checkpoint_id,
        db_path=db_path,
    )

    if checkpoint is None:
        raise RuntimeError(
            "Checkpoint could not be loaded "
            "after create"
        )

    return checkpoint


def get_agent_checkpoint(
    checkpoint_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    checkpoint_id = _require_text(
        checkpoint_id,
        "checkpoint_id",
    )

    init_agent_checkpoint_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT *
            FROM agent_checkpoints
            WHERE checkpoint_id = ?
            """,
            (checkpoint_id,),
        ).fetchone()

        if row is None:
            return None

        return _decode_row(
            row
        )

    finally:
        connection.close()


def list_agent_checkpoints(
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

    init_agent_checkpoint_store(
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
                FROM agent_checkpoints
                WHERE task_id = ?
                ORDER BY created_at ASC,
                         checkpoint_id ASC
                """,
                (task_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM agent_checkpoints
                WHERE task_id = ?
                  AND step_index = ?
                ORDER BY created_at ASC,
                         checkpoint_id ASC
                """,
                (
                    task_id,
                    step_index,
                ),
            ).fetchall()

        return [
            _decode_row(row)
            for row in rows
        ]

    finally:
        connection.close()


def update_agent_checkpoint(
    checkpoint_id: str,
    *,
    status: str | None = None,
    summary: str | None = None,
    payload: dict[str, Any] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    checkpoint_id = _require_text(
        checkpoint_id,
        "checkpoint_id",
    )

    updates = []
    values: list[Any] = []

    if status is not None:
        updates.append(
            "status = ?"
        )
        values.append(
            _require_status(status)
        )

    if summary is not None:
        updates.append(
            "summary = ?"
        )
        values.append(
            summary
        )

    if payload is not None:
        updates.append(
            "payload = ?"
        )
        values.append(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    if not updates:
        raise ValueError(
            "No checkpoint fields supplied "
            "for update"
        )

    updates.append(
        "updated_at = CURRENT_TIMESTAMP"
    )

    init_agent_checkpoint_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        values.append(
            checkpoint_id
        )

        cursor = connection.execute(
            f"""
            UPDATE agent_checkpoints
            SET {", ".join(updates)}
            WHERE checkpoint_id = ?
            """,
            values,
        )

        if cursor.rowcount == 0:
            raise KeyError(
                "Unknown checkpoint: "
                f"{checkpoint_id}"
            )

        connection.commit()

    finally:
        connection.close()
