import factory.project_memory_capture as capture_module

from factory.database import (
    create_project,
    init_database,
    upsert_task,
)
from factory.project_memory_store import (
    list_project_memories_for_source_task,
)


def _setup_approved_task(
    db_path,
):
    init_database(
        db_path
    )

    create_project(
        "PROJECT-9101",
        name="Capture Retention Project",
        path=str(
            db_path.parent / "project"
        ),
        db_path=db_path,
    )

    upsert_task(
        "TASK-9101",
        prompt="Implement durable project memory.",
        status="approved",
        max_attempts=2,
        state="approved",
        project_id="PROJECT-9101",
        test_result="passed",
        db_path=db_path,
    )


def test_capture_runs_retention_after_memory_creation(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"

    _setup_approved_task(
        db_path
    )

    calls = []

    def fake_retention(
        project_id,
        *,
        db_path,
        **kwargs,
    ):
        calls.append(
            project_id
        )

        memories = (
            list_project_memories_for_source_task(
                project_id,
                "TASK-9101",
                db_path=db_path,
            )
        )

        assert len(memories) == 1

        return {
            "project_id": project_id,
            "archived_count": 0,
        }

    monkeypatch.setattr(
        capture_module,
        "enforce_project_memory_retention",
        fake_retention,
    )

    memory = (
        capture_module
        .capture_approved_task_memory(
            "TASK-9101",
            db_path=db_path,
        )
    )

    assert (
        memory["source_task_id"]
        == "TASK-9101"
    )

    assert calls == [
        "PROJECT-9101",
    ]


def test_retention_failure_does_not_undo_capture(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"

    _setup_approved_task(
        db_path
    )

    def failing_retention(
        project_id,
        *,
        db_path,
        **kwargs,
    ):
        raise RuntimeError(
            "simulated retention failure"
        )

    monkeypatch.setattr(
        capture_module,
        "enforce_project_memory_retention",
        failing_retention,
    )

    memory = (
        capture_module
        .capture_approved_task_memory(
            "TASK-9101",
            db_path=db_path,
        )
    )

    assert (
        memory["source_task_id"]
        == "TASK-9101"
    )

    stored = (
        list_project_memories_for_source_task(
            "PROJECT-9101",
            "TASK-9101",
            db_path=db_path,
        )
    )

    assert len(stored) == 1

    assert (
        stored[0]["memory_id"]
        == memory["memory_id"]
    )

    assert (
        stored[0]["status"]
        == "active"
    )
