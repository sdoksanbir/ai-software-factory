import pytest

from factory.database import (
    create_project,
    init_database,
    save_task_diff,
    upsert_task,
)
from factory.project_memory_capture import (
    capture_approved_task_memory,
)
from factory.project_memory_store import (
    list_project_memories,
)


def _setup_project(
    db_path,
):
    init_database(db_path)

    create_project(
        "PROJECT-2001",
        name="Memory Project",
        path=str(
            db_path.parent
            / "project"
        ),
        db_path=db_path,
    )


def _save_task(
    db_path,
    *,
    state="approved",
    project_id="PROJECT-2001",
):
    upsert_task(
        "TASK-2001",
        prompt=(
            "Add persistent project memory."
        ),
        status=state,
        max_attempts=2,
        state=state,
        model="test-model",
        attempt=1,
        test_result="passed",
        project_id=project_id,
        db_path=db_path,
    )


def test_capture_approved_task_memory(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(db_path)
    _save_task(db_path)

    save_task_diff(
        "TASK-2001",
        """
diff --git a/factory/a.py b/factory/a.py
--- a/factory/a.py
+++ b/factory/a.py
@@ -1 +1 @@
-old
+new
diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
""",
        db_path=db_path,
    )

    memory = (
        capture_approved_task_memory(
            "TASK-2001",
            db_path=db_path,
        )
    )

    assert (
        memory["project_id"]
        == "PROJECT-2001"
    )

    assert memory["kind"] == "fact"

    assert (
        memory["source_task_id"]
        == "TASK-2001"
    )

    assert "approved-task" in memory["tags"]
    assert "task-history" in memory["tags"]

    assert (
        "Outcome: approved and merged."
        in memory["content"]
    )

    assert (
        "factory/a.py"
        in memory["content"]
    )

    assert (
        "tests/test_a.py"
        in memory["content"]
    )


def test_capture_is_idempotent_per_task(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(db_path)
    _save_task(db_path)

    first = capture_approved_task_memory(
        "TASK-2001",
        db_path=db_path,
    )

    second = capture_approved_task_memory(
        "TASK-2001",
        db_path=db_path,
    )

    assert (
        first["memory_id"]
        == second["memory_id"]
    )

    memories = list_project_memories(
        "PROJECT-2001",
        db_path=db_path,
    )

    assert len(memories) == 1


def test_ready_for_approval_is_not_captured(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(db_path)

    _save_task(
        db_path,
        state="ready_for_approval",
    )

    with pytest.raises(
        ValueError,
        match="approved task",
    ):
        capture_approved_task_memory(
            "TASK-2001",
            db_path=db_path,
        )

    assert (
        list_project_memories(
            "PROJECT-2001",
            db_path=db_path,
        )
        == []
    )


def test_capture_requires_project(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    init_database(db_path)

    _save_task(
        db_path,
        project_id=None,
    )

    with pytest.raises(
        ValueError,
        match="no project_id",
    ):
        capture_approved_task_memory(
            "TASK-2001",
            db_path=db_path,
        )


def test_capture_unknown_task_fails(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    init_database(db_path)

    with pytest.raises(
        KeyError,
        match="Unknown task",
    ):
        capture_approved_task_memory(
            "TASK-MISSING",
            db_path=db_path,
        )
