from __future__ import annotations

from factory.database import get_connection


VALID_TASK_KINDS = {
    "read",
    "write",
}


def _ensure_table(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_routes (
            task_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            reason TEXT
        )
        """
    )

    connection.commit()


def save_task_route(
    task_id: str,
    kind: str,
    reason: str | None = None,
) -> None:
    normalized_kind = kind.strip().casefold()

    if normalized_kind not in VALID_TASK_KINDS:
        raise ValueError(
            f"Gecersiz task kind: {kind}"
        )

    with get_connection() as connection:
        _ensure_table(connection)

        connection.execute(
            """
            INSERT INTO task_routes (
                task_id,
                kind,
                reason
            )
            VALUES (?, ?, ?)
            ON CONFLICT(task_id)
            DO UPDATE SET
                kind = excluded.kind,
                reason = excluded.reason
            """,
            (
                task_id,
                normalized_kind,
                reason,
            ),
        )

        connection.commit()


def get_task_route(
    task_id: str,
) -> dict[str, str | None] | None:
    with get_connection() as connection:
        _ensure_table(connection)

        row = connection.execute(
            """
            SELECT
                task_id,
                kind,
                reason
            FROM task_routes
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "task_id": row[0],
        "kind": row[1],
        "reason": row[2],
    }


def delete_task_route(
    task_id: str,
) -> None:
    with get_connection() as connection:
        _ensure_table(connection)

        connection.execute(
            """
            DELETE FROM task_routes
            WHERE task_id = ?
            """,
            (task_id,),
        )

        connection.commit()
