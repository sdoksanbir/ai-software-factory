from types import SimpleNamespace

from factory.database import (
    create_project,
    init_database,
)
from factory.project_memory_retrieval import (
    build_project_memory_context,
)
from factory.project_memory_store import (
    create_project_memory,
)
from factory.task_step_handlers import (
    TaskStepHandlers,
)


def _setup(
    db_path,
):
    init_database(db_path)

    create_project(
        "PROJECT-7101",
        name="Context Project",
        path=str(
            db_path.parent / "project"
        ),
        db_path=db_path,
    )


def test_build_memory_context_returns_relevant_memory(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup(db_path)

    create_project_memory(
        "PROJECT-7101",
        kind="decision",
        title="SQLite persistence",
        content=(
            "Project state remains in SQLite."
        ),
        tags=["sqlite", "database"],
        memory_id="MEM-SQLITE",
        db_path=db_path,
    )

    context = build_project_memory_context(
        "PROJECT-7101",
        "Update SQLite database persistence",
        db_path=db_path,
    )

    assert (
        "PROJECT_MEMORY_REFERENCE:"
        in context
    )

    assert (
        "SQLite persistence"
        in context
    )

    assert (
        "Current repository state has priority."
        in context
    )


def test_memory_context_excludes_irrelevant_memory(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup(db_path)

    create_project_memory(
        "PROJECT-7101",
        kind="convention",
        title="Dashboard spacing",
        content="Use compact dashboard cards.",
        tags=["dashboard"],
        memory_id="MEM-UI",
        db_path=db_path,
    )

    context = build_project_memory_context(
        "PROJECT-7101",
        "SQLite migration",
        db_path=db_path,
    )

    assert context == ""


def test_memory_context_respects_char_limit(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup(db_path)

    create_project_memory(
        "PROJECT-7101",
        kind="fact",
        title="Provider runtime",
        content=(
            "provider " * 500
        ),
        tags=["provider"],
        memory_id="MEM-LONG",
        db_path=db_path,
    )

    context = build_project_memory_context(
        "PROJECT-7101",
        "provider runtime",
        max_chars=500,
        db_path=db_path,
    )

    assert len(context) <= 500


def test_handler_without_project_has_no_memory():
    handlers = TaskStepHandlers(
        SimpleNamespace(),
        scope_prompt="SQLite task",
        project_id=None,
    )

    assert (
        handlers._project_memory_context(
            "SQLite change"
        )
        == ""
    )
