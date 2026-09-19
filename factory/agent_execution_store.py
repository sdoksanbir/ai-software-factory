import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from factory.database import (
    DEFAULT_DB_PATH,
    get_connection,
)


EXECUTION_STATUSES = {
    "running",
    "completed",
    "failed",
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
        "execution status",
    ).lower()

    if normalized not in EXECUTION_STATUSES:
        raise ValueError(
            "Invalid execution status: "
            f"{normalized}"
        )

    return normalized


def init_agent_execution_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(
        db_path
    )

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS
                agent_executions (
                    execution_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_index INTEGER,
                    handoff_id TEXT,
                    source_checkpoint_id TEXT,
                    result_checkpoint_id TEXT,
                    agent_name TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    model_name TEXT,
                    capabilities TEXT NOT NULL
                        DEFAULT '[]',
                    status TEXT NOT NULL
                        DEFAULT 'running',
                    duration_ms INTEGER,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    cost REAL NOT NULL
                        DEFAULT 0.0,
                    error TEXT,
                    metadata TEXT NOT NULL
                        DEFAULT '{}',
                    started_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                );

            CREATE INDEX IF NOT EXISTS
                idx_agent_executions_task
            ON agent_executions (
                task_id,
                step_index,
                started_at
            );

            CREATE INDEX IF NOT EXISTS
                idx_agent_executions_handoff
            ON agent_executions (
                handoff_id
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

    for field_name, fallback in (
        ("capabilities", []),
        ("metadata", {}),
    ):
        try:
            item[field_name] = json.loads(
                item.get(field_name)
                or json.dumps(fallback)
            )
        except Exception:
            item[field_name] = fallback

    return item


def create_agent_execution(
    task_id: str,
    *,
    step_index: int | None,
    agent_name: str,
    provider_name: str,
    model_name: str | None = None,
    capabilities: list[str] | None = None,
    handoff_id: str | None = None,
    source_checkpoint_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    execution_id: str | None = None,
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

    if (
        step_index is not None
        and step_index < 1
    ):
        raise ValueError(
            "step_index must be >= 1"
        )

    execution_id = _require_text(
        execution_id
        or f"EXE-{uuid4().hex[:12]}",
        "execution_id",
    )

    encoded_capabilities = json.dumps(
        capabilities or [],
        ensure_ascii=False,
        sort_keys=True,
    )

    encoded_metadata = json.dumps(
        metadata or {},
        ensure_ascii=False,
        sort_keys=True,
    )

    init_agent_execution_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        connection.execute(
            """
            INSERT INTO agent_executions (
                execution_id,
                task_id,
                step_index,
                handoff_id,
                source_checkpoint_id,
                agent_name,
                provider_name,
                model_name,
                capabilities,
                status,
                metadata
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                'running', ?
            )
            """,
            (
                execution_id,
                task_id,
                step_index,
                handoff_id,
                source_checkpoint_id,
                agent_name,
                provider_name,
                model_name,
                encoded_capabilities,
                encoded_metadata,
            ),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    execution = get_agent_execution(
        execution_id,
        db_path=db_path,
    )

    if execution is None:
        raise RuntimeError(
            "Agent execution could not be "
            "loaded after create"
        )

    return execution


def get_agent_execution(
    execution_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    execution_id = _require_text(
        execution_id,
        "execution_id",
    )

    init_agent_execution_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT *
            FROM agent_executions
            WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()

        if row is None:
            return None

        return _decode_row(
            row
        )

    finally:
        connection.close()


def list_agent_executions(
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

    init_agent_execution_store(
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
                FROM agent_executions
                WHERE task_id = ?
                ORDER BY started_at ASC,
                         execution_id ASC
                """,
                (task_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM agent_executions
                WHERE task_id = ?
                  AND step_index = ?
                ORDER BY started_at ASC,
                         execution_id ASC
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


def complete_agent_execution(
    execution_id: str,
    *,
    result_checkpoint_id: str | None = None,
    model_name: str | None = None,
    duration_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost: float = 0.0,
    metadata: dict[str, Any] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    if (
        duration_ms is not None
        and duration_ms < 0
    ):
        raise ValueError(
            "duration_ms must be >= 0"
        )

    init_agent_execution_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        cursor = connection.execute(
            """
            UPDATE agent_executions
            SET
                status = 'completed',
                result_checkpoint_id = ?,
                model_name = COALESCE(
                    ?,
                    model_name
                ),
                duration_ms = ?,
                prompt_tokens = ?,
                completion_tokens = ?,
                cost = ?,
                metadata = ?,
                error = NULL,
                completed_at = CURRENT_TIMESTAMP
            WHERE execution_id = ?
            """,
            (
                result_checkpoint_id,
                model_name,
                duration_ms,
                prompt_tokens,
                completion_tokens,
                float(cost),
                json.dumps(
                    metadata or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                execution_id,
            ),
        )

        if cursor.rowcount == 0:
            raise KeyError(
                "Unknown agent execution: "
                f"{execution_id}"
            )

        connection.commit()

    finally:
        connection.close()


def fail_agent_execution(
    execution_id: str,
    *,
    error: str,
    duration_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    error = _require_text(
        error,
        "error",
    )

    if (
        duration_ms is not None
        and duration_ms < 0
    ):
        raise ValueError(
            "duration_ms must be >= 0"
        )

    init_agent_execution_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        cursor = connection.execute(
            """
            UPDATE agent_executions
            SET
                status = 'failed',
                duration_ms = ?,
                error = ?,
                metadata = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE execution_id = ?
            """,
            (
                duration_ms,
                error,
                json.dumps(
                    metadata or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                execution_id,
            ),
        )

        if cursor.rowcount == 0:
            raise KeyError(
                "Unknown agent execution: "
                f"{execution_id}"
            )

        connection.commit()

    finally:
        connection.close()
