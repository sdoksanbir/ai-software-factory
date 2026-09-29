from __future__ import annotations

from factory.database import get_connection


VALID_TASK_KINDS = {
    "read",
    "write",
    "execute",
}

VALID_ROUTE_SOURCES = {
    "semantic",
    "deterministic_fallback",
}


def _ensure_table(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_routes (
            task_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            reason TEXT,
            source TEXT
        )
        """
    )

    # CREATE TABLE IF NOT EXISTS does not add
    # columns to older databases; migrate source.
    column_rows = connection.execute(
        "PRAGMA table_info(task_routes)"
    ).fetchall()

    column_names = {
        str(
            row["name"]
            if hasattr(row, "keys")
            else row[1]
        )
        for row in column_rows
    }

    if "source" not in column_names:
        connection.execute(
            """
            ALTER TABLE task_routes
            ADD COLUMN source TEXT
            """
        )

    connection.commit()


def save_task_route(
    task_id: str,
    kind: str,
    reason: str | None = None,
    *,
    source: str | None = None,
) -> None:
    normalized_kind = kind.strip().casefold()

    if normalized_kind not in VALID_TASK_KINDS:
        raise ValueError(
            f"Gecersiz task kind: {kind}"
        )

    normalized_source = None

    if source is not None:
        normalized_source = (
            str(source).strip().casefold()
        )

        if not normalized_source:
            normalized_source = None
        elif (
            normalized_source
            not in VALID_ROUTE_SOURCES
        ):
            raise ValueError(
                f"Gecersiz route source: {source}"
            )

    with get_connection() as connection:
        _ensure_table(connection)

        connection.execute(
            """
            INSERT INTO task_routes (
                task_id,
                kind,
                reason,
                source
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(task_id)
            DO UPDATE SET
                kind = excluded.kind,
                reason = excluded.reason,
                source = excluded.source
            """,
            (
                task_id,
                normalized_kind,
                reason,
                normalized_source,
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
                reason,
                source
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
        "source": row[3],
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
