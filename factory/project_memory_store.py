import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from factory.database import (
    DEFAULT_DB_PATH,
    get_connection,
    get_project,
    init_database,
)


MEMORY_KINDS = {
    "decision",
    "constraint",
    "convention",
    "lesson",
    "fact",
}

MEMORY_STATUSES = {
    "active",
    "superseded",
    "archived",
}


def _dedup_normalize(
    value: str,
) -> str:
    return " ".join(
        str(value or "")
        .casefold()
        .split()
    )


def _build_dedup_key(
    *,
    kind: str,
    title: str,
    content: str,
) -> str:
    payload = "\n".join(
        (
            _dedup_normalize(kind),
            _dedup_normalize(title),
            _dedup_normalize(content),
        )
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


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


def _normalize_kind(
    value: str,
) -> str:
    kind = _require_text(
        value,
        "memory kind",
    ).lower()

    if kind not in MEMORY_KINDS:
        raise ValueError(
            f"Invalid memory kind: {kind}"
        )

    return kind


def _normalize_status(
    value: str,
) -> str:
    status = _require_text(
        value,
        "memory status",
    ).lower()

    if status not in MEMORY_STATUSES:
        raise ValueError(
            f"Invalid memory status: {status}"
        )

    return status


def _normalize_tags(
    tags: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if tags is None:
        return []

    normalized = []

    for tag in tags:
        value = str(
            tag or ""
        ).strip().lower()

        if not value:
            continue

        if value not in normalized:
            normalized.append(value)

    return normalized


def _row_to_memory(
    row,
) -> dict[str, Any]:
    item = dict(row)

    raw_tags = item.pop(
        "tags_json",
        "[]",
    )

    try:
        tags = json.loads(
            raw_tags or "[]"
        )
    except json.JSONDecodeError:
        tags = []

    if not isinstance(tags, list):
        tags = []

    item["tags"] = [
        str(tag)
        for tag in tags
    ]

    return item


def init_project_memory_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    init_database(db_path)

    connection = get_connection(
        db_path
    )

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS
            project_memories (
                memory_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source_task_id TEXT,
                status TEXT NOT NULL
                    DEFAULT 'active',
                importance INTEGER NOT NULL
                    DEFAULT 50,
                tags_json TEXT NOT NULL
                    DEFAULT '[]',
                dedup_key TEXT,
                superseded_by_memory_id TEXT,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(project_id)
                    REFERENCES projects(project_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS
            idx_project_memories_project
            ON project_memories (
                project_id,
                status,
                created_at
            );

            CREATE INDEX IF NOT EXISTS
            idx_project_memories_source_task
            ON project_memories (
                source_task_id
            );
            """
        )

        # Project memory dedup migration.
        # CREATE TABLE IF NOT EXISTS eski veritabanlarina
        # yeni sutun eklemez; bu nedenle migration burada
        # deterministik olarak uygulanir.
        column_rows = connection.execute(
            "PRAGMA table_info(project_memories)"
        ).fetchall()

        column_names = {
            str(row["name"])
            for row in column_rows
        }

        if "dedup_key" not in column_names:
            connection.execute(
                """
                ALTER TABLE project_memories
                ADD COLUMN dedup_key TEXT
                """
            )

        if (
            "superseded_by_memory_id"
            not in column_names
        ):
            connection.execute(
                """
                ALTER TABLE project_memories
                ADD COLUMN superseded_by_memory_id TEXT
                """
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_project_memories_superseded_by
            ON project_memories (
                project_id,
                superseded_by_memory_id
            )
            """
        )

        # Eski memory kayitlarini da yeni dedup sistemine
        # dahil et.
        legacy_rows = connection.execute(
            """
            SELECT
                memory_id,
                kind,
                title,
                content
            FROM project_memories
            WHERE dedup_key IS NULL
               OR dedup_key = ''
            """
        ).fetchall()

        for row in legacy_rows:
            dedup_key = _build_dedup_key(
                kind=str(row["kind"]),
                title=str(row["title"]),
                content=str(row["content"]),
            )

            connection.execute(
                """
                UPDATE project_memories
                SET dedup_key = ?
                WHERE memory_id = ?
                """,
                (
                    dedup_key,
                    row["memory_id"],
                ),
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_project_memories_dedup
            ON project_memories (
                project_id,
                dedup_key,
                status
            )
            """
        )

        connection.commit()

    finally:
        connection.close()


def create_project_memory(
    project_id: str,
    *,
    kind: str,
    title: str,
    content: str,
    source_task_id: str | None = None,
    importance: int = 50,
    tags: list[str] | tuple[str, ...] | None = None,
    memory_id: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    project_id = _require_text(
        project_id,
        "project_id",
    )

    kind = _normalize_kind(
        kind
    )

    title = _require_text(
        title,
        "memory title",
    )

    content = _require_text(
        content,
        "memory content",
    )

    if not isinstance(
        importance,
        int,
    ):
        raise ValueError(
            "memory importance must be an integer"
        )

    if not 0 <= importance <= 100:
        raise ValueError(
            "memory importance must be between "
            "0 and 100"
        )

    normalized_tags = (
        _normalize_tags(tags)
    )


    dedup_key = _build_dedup_key(
        kind=kind,
        title=title,
        content=content,
    )
    if source_task_id is not None:
        source_task_id = _require_text(
            source_task_id,
            "source_task_id",
        )

    memory_id = (
        _require_text(
            memory_id,
            "memory_id",
        )
        if memory_id is not None
        else f"MEM-{uuid.uuid4().hex[:12].upper()}"
    )

    init_project_memory_store(
        db_path
    )

    if get_project(
        project_id,
        db_path=db_path,
    ) is None:
        raise KeyError(
            f"Unknown project: {project_id}"
        )

    connection = get_connection(
        db_path
    )

    try:
        existing = connection.execute(
            """
            SELECT *
            FROM project_memories
            WHERE project_id = ?
              AND dedup_key = ?
              AND status = 'active'
            ORDER BY created_at ASC, memory_id ASC
            LIMIT 1
            """,
            (
                project_id,
                dedup_key,
            ),
        ).fetchone()

        if existing is not None:
            return _row_to_memory(
                existing
            )

        connection.execute(
            """
            INSERT INTO project_memories (
                memory_id,
                project_id,
                kind,
                title,
                content,
                source_task_id,
                status,
                importance,
                tags_json,
                dedup_key
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                project_id,
                kind,
                title,
                content,
                source_task_id,
                "active",
                importance,
                json.dumps(
                    normalized_tags,
                    ensure_ascii=False,
                ),
                dedup_key,
            ),
        )

        connection.commit()

    finally:
        connection.close()

    memory = get_project_memory(
        memory_id,
        db_path=db_path,
    )

    if memory is None:
        raise RuntimeError(
            "Project memory could not be loaded"
        )

    return memory


def get_project_memory(
    memory_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    memory_id = _require_text(
        memory_id,
        "memory_id",
    )

    init_project_memory_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT *
            FROM project_memories
            WHERE memory_id = ?
            """,
            (memory_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_memory(
            row
        )

    finally:
        connection.close()


def list_project_memories(
    project_id: str,
    *,
    status: str | None = "active",
    kind: str | None = None,
    limit: int | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    project_id = _require_text(
        project_id,
        "project_id",
    )

    if status is not None:
        status = _normalize_status(
            status
        )

    if kind is not None:
        kind = _normalize_kind(
            kind
        )

    if limit is not None:
        if (
            not isinstance(limit, int)
            or limit < 1
        ):
            raise ValueError(
                "limit must be >= 1"
            )

    init_project_memory_store(
        db_path
    )

    conditions = [
        "project_id = ?"
    ]

    params: list[Any] = [
        project_id
    ]

    if status is not None:
        conditions.append(
            "status = ?"
        )
        params.append(
            status
        )

    if kind is not None:
        conditions.append(
            "kind = ?"
        )
        params.append(
            kind
        )

    sql = (
        """
        SELECT *
        FROM project_memories
        WHERE
        """
        + " AND ".join(
            conditions
        )
        + """
        ORDER BY
            importance DESC,
            created_at DESC,
            memory_id ASC
        """
    )

    if limit is not None:
        sql += " LIMIT ?"
        params.append(
            limit
        )

    connection = get_connection(
        db_path
    )

    try:
        rows = connection.execute(
            sql,
            tuple(params),
        ).fetchall()

        return [
            _row_to_memory(row)
            for row in rows
        ]

    finally:
        connection.close()


def update_project_memory(
    memory_id: str,
    *,
    title: str | None = None,
    content: str | None = None,
    status: str | None = None,
    importance: int | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    memory_id = _require_text(
        memory_id,
        "memory_id",
    )

    if (
        title is None
        and content is None
        and status is None
        and importance is None
        and tags is None
    ):
        raise ValueError(
            "No project memory fields supplied"
        )

    init_project_memory_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        current = connection.execute(
            """
            SELECT *
            FROM project_memories
            WHERE memory_id = ?
            """,
            (memory_id,),
        ).fetchone()

        if current is None:
            raise KeyError(
                f"Unknown project memory: "
                f"{memory_id}"
            )

        new_title = (
            _require_text(
                title,
                "memory title",
            )
            if title is not None
            else str(current["title"])
        )

        new_content = (
            _require_text(
                content,
                "memory content",
            )
            if content is not None
            else str(current["content"])
        )

        new_status = (
            _normalize_status(status)
            if status is not None
            else str(current["status"])
        )

        if importance is not None:
            if (
                not isinstance(
                    importance,
                    int,
                )
                or not 0 <= importance <= 100
            ):
                raise ValueError(
                    "memory importance must be "
                    "between 0 and 100"
                )

        dedup_key = _build_dedup_key(
            kind=str(current["kind"]),
            title=new_title,
            content=new_content,
        )

        # Bir superseded/archived memory tekrar active
        # yapilirken veya title/content degistirilirken
        # mevcut active duplicate olusmasina izin verme.
        if new_status == "active":
            duplicate = connection.execute(
                """
                SELECT memory_id
                FROM project_memories
                WHERE project_id = ?
                  AND dedup_key = ?
                  AND status = 'active'
                  AND memory_id <> ?
                ORDER BY created_at ASC, memory_id ASC
                LIMIT 1
                """,
                (
                    current["project_id"],
                    dedup_key,
                    memory_id,
                ),
            ).fetchone()

            if duplicate is not None:
                raise ValueError(
                    "Active duplicate project memory "
                    "already exists: "
                    f"{duplicate['memory_id']}"
                )

        fields = []
        values: list[Any] = []

        if title is not None:
            fields.append(
                "title = ?"
            )
            values.append(
                new_title
            )

        if content is not None:
            fields.append(
                "content = ?"
            )
            values.append(
                new_content
            )

        if status is not None:
            fields.append(
                "status = ?"
            )
            values.append(
                new_status
            )

        if importance is not None:
            fields.append(
                "importance = ?"
            )
            values.append(
                importance
            )

        if tags is not None:
            fields.append(
                "tags_json = ?"
            )
            values.append(
                json.dumps(
                    _normalize_tags(tags),
                    ensure_ascii=False,
                )
            )

        # title/content degismese bile eski bir kaydin
        # migration sonrasi anahtarini deterministik
        # bicimde dogru tut.
        fields.append(
            "dedup_key = ?"
        )
        values.append(
            dedup_key
        )

        fields.append(
            "updated_at = CURRENT_TIMESTAMP"
        )

        values.append(
            memory_id
        )

        connection.execute(
            f"""
            UPDATE project_memories
            SET {", ".join(fields)}
            WHERE memory_id = ?
            """,
            tuple(values),
        )

        connection.commit()

    finally:
        connection.close()

    memory = get_project_memory(
        memory_id,
        db_path=db_path,
    )

    if memory is None:
        raise RuntimeError(
            "Updated project memory disappeared"
        )

    return memory


def supersede_project_memory(
    old_memory_id: str,
    new_memory_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    old_memory_id = _require_text(
        old_memory_id,
        "old_memory_id",
    )

    new_memory_id = _require_text(
        new_memory_id,
        "new_memory_id",
    )

    if old_memory_id == new_memory_id:
        raise ValueError(
            "A memory cannot supersede itself"
        )

    init_project_memory_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        old_memory = connection.execute(
            """
            SELECT *
            FROM project_memories
            WHERE memory_id = ?
            """,
            (old_memory_id,),
        ).fetchone()

        if old_memory is None:
            raise KeyError(
                f"Unknown project memory: "
                f"{old_memory_id}"
            )

        new_memory = connection.execute(
            """
            SELECT *
            FROM project_memories
            WHERE memory_id = ?
            """,
            (new_memory_id,),
        ).fetchone()

        if new_memory is None:
            raise KeyError(
                f"Unknown project memory: "
                f"{new_memory_id}"
            )

        if (
            old_memory["project_id"]
            != new_memory["project_id"]
        ):
            raise ValueError(
                "Project memories must belong "
                "to the same project"
            )

        if old_memory["status"] != "active":
            raise ValueError(
                "Only an active memory can "
                "be superseded"
            )

        if new_memory["status"] != "active":
            raise ValueError(
                "Superseding memory must be active"
            )

        if (
            new_memory["superseded_by_memory_id"]
            is not None
        ):
            raise ValueError(
                "Superseding memory cannot itself "
                "already be superseded"
            )

        connection.execute(
            """
            UPDATE project_memories
            SET
                status = 'superseded',
                superseded_by_memory_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE memory_id = ?
            """,
            (
                new_memory_id,
                old_memory_id,
            ),
        )

        connection.commit()

    finally:
        connection.close()

    old_result = get_project_memory(
        old_memory_id,
        db_path=db_path,
    )

    new_result = get_project_memory(
        new_memory_id,
        db_path=db_path,
    )

    if (
        old_result is None
        or new_result is None
    ):
        raise RuntimeError(
            "Supersede operation lost a memory"
        )

    return {
        "superseded": old_result,
        "replacement": new_result,
    }

def delete_project_memory(
    memory_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    memory_id = _require_text(
        memory_id,
        "memory_id",
    )

    init_project_memory_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        cursor = connection.execute(
            """
            DELETE FROM project_memories
            WHERE memory_id = ?
            """,
            (memory_id,),
        )

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()


def list_project_memories_for_source_task(
    project_id: str,
    source_task_id: str,
    *,
    status: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    project_id = _require_text(
        project_id,
        "project_id",
    )

    source_task_id = _require_text(
        source_task_id,
        "source_task_id",
    )

    if status is not None:
        status = _normalize_status(
            status
        )

    init_project_memory_store(
        db_path
    )

    conditions = [
        "project_id = ?",
        "source_task_id = ?",
    ]

    params: list[Any] = [
        project_id,
        source_task_id,
    ]

    if status is not None:
        conditions.append(
            "status = ?"
        )
        params.append(
            status
        )

    connection = get_connection(
        db_path
    )

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM project_memories
            WHERE
            """
            + " AND ".join(conditions)
            + """
            ORDER BY
                created_at ASC,
                memory_id ASC
            """,
            tuple(params),
        ).fetchall()

        return [
            _row_to_memory(row)
            for row in rows
        ]

    finally:
        connection.close()


DEFAULT_MAX_ACTIVE_MEMORIES = 100
DEFAULT_PROTECTED_IMPORTANCE = 80


def enforce_project_memory_retention(
    project_id: str,
    *,
    max_active: int = DEFAULT_MAX_ACTIVE_MEMORIES,
    protected_importance: int = DEFAULT_PROTECTED_IMPORTANCE,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    project_id = _require_text(
        project_id,
        "project_id",
    )

    if (
        not isinstance(max_active, int)
        or max_active < 1
    ):
        raise ValueError(
            "max_active must be >= 1"
        )

    if (
        not isinstance(
            protected_importance,
            int,
        )
        or not 0 <= protected_importance <= 100
    ):
        raise ValueError(
            "protected_importance must be "
            "between 0 and 100"
        )

    init_project_memory_store(
        db_path
    )

    if get_project(
        project_id,
        db_path=db_path,
    ) is None:
        raise KeyError(
            f"Unknown project: {project_id}"
        )

    connection = get_connection(
        db_path
    )

    try:
        active_rows = connection.execute(
            """
            SELECT
                memory_id,
                importance,
                created_at
            FROM project_memories
            WHERE project_id = ?
              AND status = 'active'
            ORDER BY
                importance ASC,
                created_at ASC,
                memory_id ASC
            """,
            (project_id,),
        ).fetchall()

        active_count = len(
            active_rows
        )

        excess = max(
            0,
            active_count - max_active,
        )

        archived_ids: list[str] = []

        if excess > 0:
            candidates = [
                row
                for row in active_rows
                if int(
                    row["importance"]
                ) < protected_importance
            ]

            for row in candidates[:excess]:
                memory_id = str(
                    row["memory_id"]
                )

                connection.execute(
                    """
                    UPDATE project_memories
                    SET
                        status = 'archived',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE memory_id = ?
                      AND status = 'active'
                    """,
                    (memory_id,),
                )

                archived_ids.append(
                    memory_id
                )

            connection.commit()

        remaining_active = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM project_memories
            WHERE project_id = ?
              AND status = 'active'
            """,
            (project_id,),
        ).fetchone()

        protected_active = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM project_memories
            WHERE project_id = ?
              AND status = 'active'
              AND importance >= ?
            """,
            (
                project_id,
                protected_importance,
            ),
        ).fetchone()

        remaining_count = int(
            remaining_active["count"]
        )

        protected_count = int(
            protected_active["count"]
        )

        return {
            "project_id": project_id,
            "max_active": max_active,
            "protected_importance": (
                protected_importance
            ),
            "active_before": active_count,
            "archived_count": len(
                archived_ids
            ),
            "archived_memory_ids": (
                archived_ids
            ),
            "active_after": remaining_count,
            "protected_active": (
                protected_count
            ),
            "limit_satisfied": (
                remaining_count <= max_active
            ),
        }

    finally:
        connection.close()
