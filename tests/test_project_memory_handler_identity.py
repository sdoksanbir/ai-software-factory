from types import SimpleNamespace

from factory.database import (
    create_project,
    init_database,
    upsert_task,
)
from factory.task_step_handlers import (
    TaskStepHandlers,
)


def test_task_step_handlers_keep_project_id():
    handlers = TaskStepHandlers(
        SimpleNamespace(),
        scope_prompt="test",
        project_id="PROJECT-7001",
    )

    assert (
        handlers.project_id
        == "PROJECT-7001"
    )


def test_task_project_identity_is_persistent(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    init_database(
        db_path
    )

    create_project(
        "PROJECT-7001",
        name="Memory Context Project",
        path=str(
            tmp_path / "project"
        ),
        db_path=db_path,
    )

    upsert_task(
        "TASK-7001",
        prompt="Use project memory.",
        status="running",
        max_attempts=2,
        state="running",
        project_id="PROJECT-7001",
        db_path=db_path,
    )

    from factory.database import get_task

    task = get_task(
        "TASK-7001",
        db_path=db_path,
    )

    assert task is not None

    assert (
        task["project_id"]
        == "PROJECT-7001"
    )
