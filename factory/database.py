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
