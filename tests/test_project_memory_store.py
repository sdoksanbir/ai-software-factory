import pytest

from factory.database import (
    create_project,
    delete_project,
    init_database,
)
from factory.project_memory_store import (
    create_project_memory,
    delete_project_memory,
    get_project_memory,
    list_project_memories,
    update_project_memory,
)


def _project(
    db_path,
    project_id="PROJECT-1001",
):
    init_database(db_path)

    return create_project(
        project_id,
        name="Test Project",
        path=str(
            db_path.parent
            / project_id
        ),
        db_path=db_path,
    )


def test_create_and_get_project_memory(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    created = create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Use SQLite",
        content=(
            "Project state remains in SQLite."
        ),
        source_task_id="TASK-1001",
        importance=80,
        tags=[
            "database",
            "architecture",
            "database",
        ],
        memory_id="MEM-TEST-1",
        db_path=db_path,
    )

    assert created["memory_id"] == "MEM-TEST-1"
    assert created["project_id"] == "PROJECT-1001"
    assert created["kind"] == "decision"
    assert created["status"] == "active"
    assert created["importance"] == 80

    assert created["tags"] == [
        "database",
        "architecture",
    ]

    loaded = get_project_memory(
        "MEM-TEST-1",
        db_path=db_path,
    )

    assert loaded == created


def test_list_project_memories_filters(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Decision",
        content="Decision content",
        importance=90,
        memory_id="MEM-A",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-1001",
        kind="lesson",
        title="Lesson",
        content="Lesson content",
        importance=40,
        memory_id="MEM-B",
        db_path=db_path,
    )

    decisions = list_project_memories(
        "PROJECT-1001",
        kind="decision",
        db_path=db_path,
    )

    assert [
        item["memory_id"]
        for item in decisions
    ] == ["MEM-A"]


def test_update_project_memory(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    create_project_memory(
        "PROJECT-1001",
        kind="constraint",
        title="Old title",
        content="Old content",
        memory_id="MEM-C",
        db_path=db_path,
    )

    updated = update_project_memory(
        "MEM-C",
        title="New title",
        content="New content",
        status="superseded",
        importance=75,
        tags=["runtime"],
        db_path=db_path,
    )

    assert updated["title"] == "New title"
    assert updated["content"] == "New content"
    assert updated["status"] == "superseded"
    assert updated["importance"] == 75
    assert updated["tags"] == ["runtime"]


def test_unknown_project_is_rejected(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    with pytest.raises(
        KeyError,
        match="Unknown project",
    ):
        create_project_memory(
            "PROJECT-MISSING",
            kind="fact",
            title="Fact",
            content="Content",
            db_path=db_path,
        )


def test_invalid_kind_is_rejected(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    with pytest.raises(
        ValueError,
        match="Invalid memory kind",
    ):
        create_project_memory(
            "PROJECT-1001",
            kind="random",
            title="Invalid",
            content="Invalid",
            db_path=db_path,
        )


def test_invalid_importance_is_rejected(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    with pytest.raises(
        ValueError,
        match="between 0 and 100",
    ):
        create_project_memory(
            "PROJECT-1001",
            kind="fact",
            title="Fact",
            content="Content",
            importance=101,
            db_path=db_path,
        )


def test_delete_project_memory(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    create_project_memory(
        "PROJECT-1001",
        kind="fact",
        title="Temporary",
        content="Temporary memory",
        memory_id="MEM-D",
        db_path=db_path,
    )

    assert delete_project_memory(
        "MEM-D",
        db_path=db_path,
    ) is True

    assert get_project_memory(
        "MEM-D",
        db_path=db_path,
    ) is None


def test_project_delete_cascades_memories(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Architecture",
        content="Persistent decision",
        memory_id="MEM-E",
        db_path=db_path,
    )

    assert delete_project(
        "PROJECT-1001",
        db_path=db_path,
    ) is True

    assert get_project_memory(
        "MEM-E",
        db_path=db_path,
    ) is None


def test_exact_duplicate_returns_existing_memory(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    first = create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Use SQLite",
        content="Persist project state in SQLite.",
        memory_id="MEM-FIRST",
        db_path=db_path,
    )

    second = create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Use SQLite",
        content="Persist project state in SQLite.",
        memory_id="MEM-SECOND",
        db_path=db_path,
    )

    assert (
        first["memory_id"]
        == second["memory_id"]
        == "MEM-FIRST"
    )

    memories = list_project_memories(
        "PROJECT-1001",
        db_path=db_path,
    )

    assert len(memories) == 1


def test_dedup_normalizes_case_and_whitespace(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    first = create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Use SQLite",
        content="Persist   project state in SQLite.",
        memory_id="MEM-FIRST",
        db_path=db_path,
    )

    second = create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="  use sqlite  ",
        content="persist project state in sqlite.",
        memory_id="MEM-SECOND",
        db_path=db_path,
    )

    assert (
        second["memory_id"]
        == first["memory_id"]
    )


def test_update_recalculates_dedup_key(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    updated = create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Old storage",
        content="Use old storage.",
        memory_id="MEM-UPDATE",
        db_path=db_path,
    )

    updated = update_project_memory(
        updated["memory_id"],
        title="Use SQLite",
        content="Persist project state in SQLite.",
        db_path=db_path,
    )

    duplicate = create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Use SQLite",
        content="Persist project state in SQLite.",
        memory_id="MEM-NEW",
        db_path=db_path,
    )

    assert (
        duplicate["memory_id"]
        == updated["memory_id"]
        == "MEM-UPDATE"
    )


def test_update_cannot_create_active_duplicate(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _project(db_path)

    create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Use SQLite",
        content="Persist project state in SQLite.",
        memory_id="MEM-ONE",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-1001",
        kind="decision",
        title="Use JSON",
        content="Persist project state in JSON.",
        memory_id="MEM-TWO",
        db_path=db_path,
    )

    import pytest

    with pytest.raises(
        ValueError,
        match="Active duplicate",
    ):
        update_project_memory(
            "MEM-TWO",
            title="Use SQLite",
            content="Persist project state in SQLite.",
            db_path=db_path,
        )
