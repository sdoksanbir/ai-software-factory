import logging
from pathlib import Path
from typing import Any

from factory.database import (
    DEFAULT_DB_PATH,
    get_task,
    get_task_diff,
)
from factory.project_memory_store import (
    create_project_memory,
    enforce_project_memory_retention,
    list_project_memories_for_source_task,
)


logger = logging.getLogger(__name__)


def _normalized_task_state(
    task: dict[str, Any],
) -> str:
    return str(
        task.get("state")
        or task.get("status")
        or ""
    ).strip().lower()


def _compact_text(
    value: Any,
) -> str:
    return " ".join(
        str(
            value or ""
        ).split()
    )


def _changed_files_from_diff(
    diff_output: str | None,
) -> list[str]:
    if not diff_output:
        return []

    changed: list[str] = []

    for raw_line in diff_output.splitlines():
        line = raw_line.strip()

        path = None

        if line.startswith("+++ b/"):
            path = line[6:]

        elif line.startswith("--- a/"):
            path = line[6:]

        if not path:
            continue

        path = path.strip()

        if (
            not path
            or path == "/dev/null"
            or path in changed
        ):
            continue

        changed.append(path)

    return changed


def capture_approved_task_memory(
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    task_id = str(
        task_id or ""
    ).strip()

    if not task_id:
        raise ValueError(
            "task_id must not be blank"
        )

    task = get_task(
        task_id,
        db_path=db_path,
    )

    if task is None:
        raise KeyError(
            f"Unknown task: {task_id}"
        )

    state = _normalized_task_state(
        task
    )

    if state != "approved":
        raise ValueError(
            "Project memory capture requires "
            "an approved task"
        )

    project_id = str(
        task.get(
            "project_id"
        )
        or ""
    ).strip()

    if not project_id:
        raise ValueError(
            "Approved task has no project_id"
        )

    existing = (
        list_project_memories_for_source_task(
            project_id,
            task_id,
            status="active",
            db_path=db_path,
        )
    )

    for memory in existing:
        tags = {
            str(tag).strip().lower()
            for tag in memory.get(
                "tags",
                []
            )
        }

        if "approved-task" in tags:
            return memory

    prompt = _compact_text(
        task.get("prompt")
    )

    if not prompt:
        prompt = task_id

    changed_files = (
        _changed_files_from_diff(
            get_task_diff(
                task_id,
                db_path=db_path,
            )
        )
    )

    test_result = _compact_text(
        task.get(
            "test_result"
        )
    )

    content_parts = [
        f"Task: {task_id}",
        f"Request: {prompt}",
        "Outcome: approved and merged.",
    ]

    if test_result:
        content_parts.append(
            f"Validation: {test_result}"
        )

    if changed_files:
        content_parts.append(
            "Changed files: "
            + ", ".join(
                changed_files
            )
        )

    title_prompt = prompt

    if len(title_prompt) > 96:
        title_prompt = (
            title_prompt[:93].rstrip()
            + "..."
        )

    memory = create_project_memory(
        project_id,
        kind="fact",
        title=(
            "Approved task: "
            f"{title_prompt}"
        ),
        content="\n".join(
            content_parts
        ),
        source_task_id=task_id,
        importance=65,
        tags=[
            "task-history",
            "approved-task",
        ],
        db_path=db_path,
    )

    # Retention is maintenance, not part of the
    # correctness of the approved task itself.
    # A retention failure must never invalidate an
    # already captured project memory.
    try:
        enforce_project_memory_retention(
            project_id,
            db_path=db_path,
        )

    except Exception as exc:
        logger.warning(
            "Project memory retention failed "
            "after capture for task %s: %s",
            task_id,
            exc,
        )

    return memory
