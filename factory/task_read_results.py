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
        CREATE TABLE IF NOT EXISTS task_read_results (
            task_id TEXT PRIMARY KEY,
            result TEXT NOT NULL
        )
        """
    )

    connection.commit()

    return connection


def save_task_read_result(
    task_id: str,
    result: str,
) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO task_read_results (
                task_id,
                result
            )
            VALUES (?, ?)
            ON CONFLICT(task_id)
            DO UPDATE SET
                result = excluded.result
            """,
            (
                task_id,
                result,
            ),
        )

        connection.commit()


def get_task_read_result(
    task_id: str,
) -> str | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT result
            FROM task_read_results
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

    if row is None:
        return None

    return str(row["result"])
