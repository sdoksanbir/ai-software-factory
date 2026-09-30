"""Legacy SQLite upgrade for tasks.related_task_id."""

from __future__ import annotations

import sqlite3

from factory.database import (
    get_connection,
    get_task,
    init_database,
    upsert_task,
)


def test_legacy_tasks_table_gains_related_task_id(
    tmp_path,
):
    """Existing DBs without related_task_id upgrade safely."""
    db_path = tmp_path / "legacy.db"

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        connection.executescript(
            """
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                branch TEXT,
                worktree_path TEXT,
                project_id TEXT,
                max_attempts INTEGER NOT NULL
                    DEFAULT 2,
                state TEXT NOT NULL
                    DEFAULT 'queued',
                model TEXT,
                attempt INTEGER NOT NULL
                    DEFAULT 0,
                test_result TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        connection.execute(
            """
            INSERT INTO tasks (
                task_id,
                prompt,
                status,
                project_id,
                state
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "TASK-LEGACY-1",
                "legacy prompt",
                "failed",
                "PROJ-1",
                "failed",
            ),
        )
        connection.commit()

        columns_before = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(tasks)"
            ).fetchall()
        }
    finally:
        connection.close()

    assert "related_task_id" not in columns_before

    init_database(db_path)
    # Idempotent: second init must not fail.
    init_database(db_path)

    connection = get_connection(db_path)

    try:
        columns_after = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(tasks)"
            ).fetchall()
        }
        row = connection.execute(
            """
            SELECT task_id, prompt, status,
                   project_id, related_task_id
            FROM tasks
            WHERE task_id = ?
            """,
            ("TASK-LEGACY-1",),
        ).fetchone()
    finally:
        connection.close()

    assert "related_task_id" in columns_after
    assert row is not None
    assert row["task_id"] == "TASK-LEGACY-1"
    assert row["prompt"] == "legacy prompt"
    assert row["status"] == "failed"
    assert row["project_id"] == "PROJ-1"
    assert row["related_task_id"] is None

    upsert_task(
        "TASK-NEW-1",
        prompt="follow-up diagnosis",
        status="queued",
        max_attempts=2,
        state="queued",
        project_id="PROJ-1",
        related_task_id="TASK-LEGACY-1",
        db_path=db_path,
    )

    stored = get_task(
        "TASK-NEW-1",
        db_path=db_path,
    )
    assert stored is not None
    assert stored["related_task_id"] == (
        "TASK-LEGACY-1"
    )

    legacy = get_task(
        "TASK-LEGACY-1",
        db_path=db_path,
    )
    assert legacy is not None
    assert legacy["prompt"] == "legacy prompt"
    assert legacy["related_task_id"] is None
