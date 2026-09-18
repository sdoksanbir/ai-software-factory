from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "factory.db"
)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_model_preferences (
            task_id TEXT PRIMARY KEY,
            requested_model TEXT
        )
        """
    )

    connection.commit()

    return connection


def set_task_model_preference(
    task_id: str,
    requested_model: str | None,
) -> None:
    value = (
        requested_model.strip()
        if requested_model
        else None
    )

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO task_model_preferences (
                task_id,
                requested_model
            )
            VALUES (?, ?)
            ON CONFLICT(task_id)
            DO UPDATE SET
                requested_model =
                    excluded.requested_model
            """,
            (
                task_id,
                value,
            ),
        )

        connection.commit()


def get_task_model_preference(
    task_id: str,
) -> str | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT requested_model
            FROM task_model_preferences
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

    if row is None:
        return None

    value = row["requested_model"]

    if not value:
        return None

    return str(value)
