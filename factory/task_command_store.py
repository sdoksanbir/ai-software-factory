"""SQLite persistence for guarded task command history.

Secrets: only secret env KEY names may be stored — never values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from factory.database import (
    DEFAULT_DB_PATH,
    get_connection,
)
from factory.task_command_models import (
    TaskCommandResult,
    normalize_secret_env_keys,
)


def init_task_command_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(db_path)

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_commands (
                command_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                argv_json TEXT NOT NULL,
                cwd TEXT NOT NULL,
                permission_level TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms INTEGER,
                exit_code INTEGER,
                stdout TEXT,
                stderr TEXT,
                status TEXT NOT NULL,
                secret_env_keys_json TEXT NOT NULL
                    DEFAULT '[]',
                stdout_truncated INTEGER NOT NULL
                    DEFAULT 0,
                stderr_truncated INTEGER NOT NULL
                    DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS
                idx_task_commands_task
            ON task_commands (
                task_id,
                started_at,
                command_id
            );
            """
        )

        connection.commit()

    finally:
        connection.close()


def _serialize_argv(argv: list[str]) -> str:
    return json.dumps(
        list(argv),
        ensure_ascii=False,
    )


def _deserialize_argv(raw: str | None) -> list[str]:
    if not raw:
        return []

    loaded = json.loads(raw)

    if not isinstance(loaded, list):
        return []

    return [
        str(item)
        for item in loaded
    ]


def _serialize_secret_keys(
    keys: list[str] | None,
) -> str:
    return json.dumps(
        normalize_secret_env_keys(keys),
        ensure_ascii=False,
    )


def _deserialize_secret_keys(
    raw: str | None,
) -> list[str]:
    if not raw:
        return []

    loaded = json.loads(raw)

    if not isinstance(loaded, list):
        return []

    return normalize_secret_env_keys(
        [str(item) for item in loaded]
    )


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "command_id": row["command_id"],
        "task_id": row["task_id"],
        "argv": _deserialize_argv(
            row["argv_json"]
        ),
        "cwd": row["cwd"],
        "permission_level": row[
            "permission_level"
        ],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_ms": row["duration_ms"],
        "exit_code": row["exit_code"],
        "stdout": row["stdout"] or "",
        "stderr": row["stderr"] or "",
        "status": row["status"],
        "secret_env_keys": (
            _deserialize_secret_keys(
                row["secret_env_keys_json"]
            )
        ),
        "stdout_truncated": bool(
            row["stdout_truncated"]
        ),
        "stderr_truncated": bool(
            row["stderr_truncated"]
        ),
    }


def save_task_command(
    result: TaskCommandResult,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    init_task_command_store(db_path)

    payload = {
        "command_id": result.command_id,
        "task_id": result.task_id,
        "argv": list(result.argv),
        "cwd": result.cwd,
        "permission_level": (
            result.permission_level
        ),
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_ms": result.duration_ms,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": result.status,
        "secret_env_keys": (
            normalize_secret_env_keys(
                result.secret_env_keys
            )
        ),
        "stdout_truncated": bool(
            result.stdout_truncated
        ),
        "stderr_truncated": bool(
            result.stderr_truncated
        ),
    }

    connection = get_connection(db_path)

    try:
        connection.execute(
            """
            INSERT INTO task_commands (
                command_id,
                task_id,
                argv_json,
                cwd,
                permission_level,
                started_at,
                finished_at,
                duration_ms,
                exit_code,
                stdout,
                stderr,
                status,
                secret_env_keys_json,
                stdout_truncated,
                stderr_truncated
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                payload["command_id"],
                payload["task_id"],
                _serialize_argv(
                    payload["argv"]
                ),
                payload["cwd"],
                payload["permission_level"],
                payload["started_at"],
                payload["finished_at"],
                payload["duration_ms"],
                payload["exit_code"],
                payload["stdout"],
                payload["stderr"],
                payload["status"],
                _serialize_secret_keys(
                    payload["secret_env_keys"]
                ),
                int(
                    payload["stdout_truncated"]
                ),
                int(
                    payload["stderr_truncated"]
                ),
            ),
        )

        connection.commit()

    finally:
        connection.close()

    return payload


def get_task_command(
    command_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    init_task_command_store(db_path)

    connection = get_connection(db_path)

    try:
        row = connection.execute(
            """
            SELECT *
            FROM task_commands
            WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_dict(row)

    finally:
        connection.close()


def list_task_commands(
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    init_task_command_store(db_path)

    connection = get_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM task_commands
            WHERE task_id = ?
            ORDER BY started_at ASC,
                     command_id ASC
            """,
            (task_id,),
        ).fetchall()

        return [
            _row_to_dict(row)
            for row in rows
        ]

    finally:
        connection.close()
