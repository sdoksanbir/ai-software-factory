import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "factory.db"
)


def get_connection(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        path,
        timeout=10,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")

    return connection


def _column_names(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {
        row["name"]
        for row in rows
    }


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if column_name in _column_names(
        connection,
        table_name,
    ):
        return

    connection.execute(
        f"ALTER TABLE {table_name} "
        f"ADD COLUMN {column_name} {definition}"
    )


def init_database(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(db_path)

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                branch TEXT,
                worktree_path TEXT,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                attempt_no INTEGER,
                model_name TEXT,
                patch_applied BOOLEAN,
                test_success BOOLEAN,
                error_message TEXT,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS model_calls (
                call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                model_role TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cost REAL DEFAULT 0.0,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS task_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS task_diffs (
                task_id TEXT PRIMARY KEY,
                diff TEXT NOT NULL,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        task_columns = {
            "project_id": "TEXT",
            "max_attempts": "INTEGER NOT NULL DEFAULT 2",
            "state": "TEXT NOT NULL DEFAULT 'queued'",
            "model": "TEXT",
            "attempt": "INTEGER NOT NULL DEFAULT 0",
            "test_result": "TEXT",
            "started_at": "TEXT",
            "completed_at": "TEXT",
        }

        for column_name, definition in task_columns.items():
            _ensure_column(
                connection,
                "tasks",
                column_name,
                definition,
            )

        connection.commit()

    finally:
        connection.close()

def upsert_task(
    task_id: str,
    *,
    prompt: str,
    status: str,
    max_attempts: int,
    state: str,
    model: str | None = None,
    attempt: int = 0,
    test_result: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    project_id: str | None = None,
    branch: str | None = None,
    worktree_path: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(db_path)

    try:
        connection.execute(
            """
            INSERT INTO tasks (
                task_id,
                prompt,
                status,
                branch,
                worktree_path,
                project_id,
                max_attempts,
                state,
                model,
                attempt,
                test_result,
                started_at,
                completed_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(task_id) DO UPDATE SET
                prompt = excluded.prompt,
                status = excluded.status,
                branch = COALESCE(excluded.branch, tasks.branch),
                worktree_path = COALESCE(excluded.worktree_path, tasks.worktree_path),
                project_id = COALESCE(excluded.project_id, tasks.project_id),
                max_attempts = excluded.max_attempts,
                state = excluded.state,
                model = excluded.model,
                attempt = excluded.attempt,
                test_result = excluded.test_result,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                task_id,
                prompt,
                status,
                branch,
                worktree_path,
                project_id,
                max_attempts,
                state,
                model,
                attempt,
                test_result,
                started_at,
                completed_at,
            ),
        )

        connection.commit()

    finally:
        connection.close()


def get_task(
    task_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    connection = get_connection(db_path)

    try:
        row = connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def list_tasks(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    connection = get_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM tasks
            ORDER BY created_at DESC, task_id DESC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def append_task_log(
    task_id: str,
    message: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(db_path)

    try:
        connection.execute(
            """
            INSERT INTO task_logs (
                task_id,
                message
            )
            VALUES (?, ?)
            """,
            (
                task_id,
                message,
            ),
        )

        connection.commit()

    finally:
        connection.close()


def list_task_logs(
    task_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    connection = get_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT message
            FROM task_logs
            WHERE task_id = ?
            ORDER BY log_id
            """,
            (task_id,),
        ).fetchall()

        return [
            row["message"]
            for row in rows
        ]

    finally:
        connection.close()


def save_task_diff(
    task_id: str,
    diff_output: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(db_path)

    try:
        connection.execute(
            """
            INSERT INTO task_diffs (
                task_id,
                diff,
                updated_at
            )
            VALUES (
                ?, ?, CURRENT_TIMESTAMP
            )
            ON CONFLICT(task_id) DO UPDATE SET
                diff = excluded.diff,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                task_id,
                diff_output,
            ),
        )

        connection.commit()

    finally:
        connection.close()


def get_task_diff(
    task_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> str | None:
    connection = get_connection(db_path)

    try:
        row = connection.execute(
            """
            SELECT diff
            FROM task_diffs
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

        if row is None:
            return None

        return str(row["diff"])

    finally:
        connection.close()



def clear_task_logs(
    task_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(db_path)

    try:
        connection.execute(
            "DELETE FROM task_logs WHERE task_id = ?",
            (task_id,),
        )
        connection.commit()
    finally:
        connection.close()


def delete_task_diff(
    task_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(db_path)

    try:
        connection.execute(
            "DELETE FROM task_diffs WHERE task_id = ?",
            (task_id,),
        )
        connection.commit()
    finally:
        connection.close()


def create_project(
    project_id: str,
    *,
    name: str,
    path: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    connection = get_connection(db_path)

    try:
        connection.execute(
            """
            INSERT INTO projects (
                project_id,
                name,
                path,
                updated_at
            )
            VALUES (
                ?, ?, ?, CURRENT_TIMESTAMP
            )
            """,
            (
                project_id,
                name,
                path,
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT *
            FROM projects
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                f"Project could not be created: {project_id}"
            )

        return dict(row)

    finally:
        connection.close()


def get_project(
    project_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    connection = get_connection(db_path)

    try:
        row = connection.execute(
            """
            SELECT *
            FROM projects
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def get_project_by_path(
    project_path: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    connection = get_connection(db_path)

    try:
        row = connection.execute(
            """
            SELECT *
            FROM projects
            WHERE path = ?
            """,
            (project_path,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def list_projects(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    connection = get_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM projects
            ORDER BY created_at ASC, name ASC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def update_project(
    project_id: str,
    *,
    name: str,
    path: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    connection = get_connection(db_path)

    try:
        cursor = connection.execute(
            """
            UPDATE projects
            SET
                name = ?,
                path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE project_id = ?
            """,
            (
                name,
                path,
                project_id,
            ),
        )

        if cursor.rowcount == 0:
            connection.rollback()
            return None

        connection.commit()

        row = connection.execute(
            """
            SELECT *
            FROM projects
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def delete_project(
    project_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    connection = get_connection(db_path)

    try:
        cursor = connection.execute(
            """
            DELETE FROM projects
            WHERE project_id = ?
            """,
            (project_id,),
        )

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()

