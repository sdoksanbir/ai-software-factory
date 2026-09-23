from pathlib import Path
from typing import Any

from factory.database import DEFAULT_DB_PATH, get_connection


PLAN_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
}

STEP_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
}

STEP_KINDS = {
    "read",
    "write",
    "verify",
}


def _require_text(
    value: Any,
    field_name: str,
) -> str:
    normalized = str(value or "").strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must not be blank"
        )

    return normalized


def _require_choice(
    value: str,
    allowed: set[str],
    field_name: str,
) -> str:
    normalized = _require_text(
        value,
        field_name,
    ).lower()

    if normalized not in allowed:
        raise ValueError(
            f"Invalid {field_name}: {normalized}"
        )

    return normalized


def init_task_plan_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(db_path)

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_plans (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                summary TEXT,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS task_steps (
                task_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                instruction TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt INTEGER NOT NULL DEFAULT 0,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (
                    task_id,
                    step_index
                )
            );

            CREATE INDEX IF NOT EXISTS
                idx_task_steps_task_id
            ON task_steps (
                task_id,
                step_index
            );
            """
        )

        connection.commit()

    finally:
        connection.close()


def save_task_plan(
    task_id: str,
    steps: list[dict[str, Any]],
    *,
    summary: str | None = None,
    status: str = "pending",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    task_id = _require_text(
        task_id,
        "task_id",
    )

    status = _require_choice(
        status,
        PLAN_STATUSES,
        "plan status",
    )

    if not steps:
        raise ValueError(
            "Task plan must contain at least one step"
        )

    normalized_steps = []

    for step_index, step in enumerate(
        steps,
        start=1,
    ):
        title = _require_text(
            step.get("title"),
            "step title",
        )

        instruction = _require_text(
            step.get("instruction"),
            "step instruction",
        )

        kind = _require_choice(
            step.get("kind", "write"),
            STEP_KINDS,
            "step kind",
        )

        step_status = _require_choice(
            step.get("status", "pending"),
            STEP_STATUSES,
            "step status",
        )

        attempt = int(
            step.get("attempt", 0)
        )

        if attempt < 0:
            raise ValueError(
                "step attempt must be >= 0"
            )

        normalized_steps.append(
            (
                task_id,
                step_index,
                title,
                instruction,
                kind,
                step_status,
                attempt,
                step.get("result"),
                step.get("error"),
            )
        )

    init_task_plan_store(db_path)

    connection = get_connection(db_path)

    try:
        connection.execute(
            """
            INSERT INTO task_plans (
                task_id,
                status,
                summary,
                updated_at
            )
            VALUES (
                ?, ?, ?, CURRENT_TIMESTAMP
            )
            ON CONFLICT(task_id) DO UPDATE SET
                status = excluded.status,
                summary = excluded.summary,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                task_id,
                status,
                summary,
            ),
        )

        connection.execute(
            """
            DELETE FROM task_steps
            WHERE task_id = ?
            """,
            (task_id,),
        )

        connection.executemany(
            """
            INSERT INTO task_steps (
                task_id,
                step_index,
                title,
                instruction,
                kind,
                status,
                attempt,
                result,
                error
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            normalized_steps,
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    result = get_task_plan(
        task_id,
        db_path=db_path,
    )

    if result is None:
        raise RuntimeError(
            "Task plan could not be loaded "
            "after save"
        )

    return result


def get_task_plan(
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    init_task_plan_store(db_path)

    connection = get_connection(db_path)

    try:
        plan_row = connection.execute(
            """
            SELECT *
            FROM task_plans
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

        if plan_row is None:
            return None

        step_rows = connection.execute(
            """
            SELECT *
            FROM task_steps
            WHERE task_id = ?
            ORDER BY step_index ASC
            """,
            (task_id,),
        ).fetchall()

        plan = dict(plan_row)
        plan["steps"] = [
            dict(row)
            for row in step_rows
        ]

        return plan

    finally:
        connection.close()


def update_task_plan_status(
    task_id: str,
    status: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    status = _require_choice(
        status,
        PLAN_STATUSES,
        "plan status",
    )

    init_task_plan_store(db_path)

    connection = get_connection(db_path)

    try:
        cursor = connection.execute(
            """
            UPDATE task_plans
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (
                status,
                task_id,
            ),
        )

        if cursor.rowcount == 0:
            raise KeyError(
                f"Unknown task plan: {task_id}"
            )

        connection.commit()

    finally:
        connection.close()


def update_task_step(
    task_id: str,
    step_index: int,
    *,
    status: str | None = None,
    attempt: int | None = None,
    result: str | None = None,
    error: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    if step_index < 1:
        raise ValueError(
            "step_index must be >= 1"
        )

    updates = []
    values: list[Any] = []

    if status is not None:
        status = _require_choice(
            status,
            STEP_STATUSES,
            "step status",
        )

        updates.append("status = ?")
        values.append(status)

    if attempt is not None:
        if attempt < 0:
            raise ValueError(
                "attempt must be >= 0"
            )

        updates.append("attempt = ?")
        values.append(attempt)

    if result is not None:
        updates.append("result = ?")
        values.append(result)

    if error is not None:
        updates.append("error = ?")
        values.append(error)

    if not updates:
        raise ValueError(
            "No step fields supplied for update"
        )

    updates.append(
        "updated_at = CURRENT_TIMESTAMP"
    )

    init_task_plan_store(db_path)

    connection = get_connection(db_path)

    try:
        values.extend(
            [
                task_id,
                step_index,
            ]
        )

        cursor = connection.execute(
            f"""
            UPDATE task_steps
            SET {", ".join(updates)}
            WHERE task_id = ?
              AND step_index = ?
            """,
            values,
        )

        if cursor.rowcount == 0:
            raise KeyError(
                "Unknown task step: "
                f"{task_id}#{step_index}"
            )

        connection.commit()

    finally:
        connection.close()

def reset_retryable_task_steps(
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    if plan is None:
        return 0

    reset_count = 0

    for step in plan.get("steps", []):
        step_status = str(
            step.get("status") or ""
        ).strip().lower()

        if step_status not in {
            "failed",
            "running",
        }:
            continue

        update_task_step(
            task_id,
            int(step["step_index"]),
            status="pending",
            attempt=0,
            error="",
            db_path=db_path,
        )

        reset_count += 1

    if reset_count > 0:
        update_task_plan_status(
            task_id,
            "pending",
            db_path=db_path,
        )

    return reset_count



def delete_task_plan(
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    init_task_plan_store(db_path)

    connection = get_connection(db_path)

    try:
        connection.execute(
            """
            DELETE FROM task_steps
            WHERE task_id = ?
            """,
            (task_id,),
        )

        connection.execute(
            """
            DELETE FROM task_plans
            WHERE task_id = ?
            """,
            (task_id,),
        )

        connection.commit()

    finally:
        connection.close()
