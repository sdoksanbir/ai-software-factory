from factory.database import (
    create_project,
    init_database,
)
from factory.project_memory_store import (
    create_project_memory,
    enforce_project_memory_retention,
    get_project_memory,
)


def _setup_project(
    db_path,
):
    init_database(
        db_path
    )

    create_project(
        "PROJECT-9001",
        name="Retention Project",
        path=str(
            db_path.parent / "project"
        ),
        db_path=db_path,
    )


def _memory(
    db_path,
    memory_id,
    importance,
):
    return create_project_memory(
        "PROJECT-9001",
        kind="fact",
        title=f"Memory {memory_id}",
        content=f"Content for {memory_id}.",
        importance=importance,
        memory_id=memory_id,
        db_path=db_path,
    )


def test_retention_does_nothing_under_limit(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(
        db_path
    )

    _memory(
        db_path,
        "MEM-1",
        20,
    )

    _memory(
        db_path,
        "MEM-2",
        30,
    )

    result = (
        enforce_project_memory_retention(
            "PROJECT-9001",
            max_active=3,
            db_path=db_path,
        )
    )

    assert result["archived_count"] == 0
    assert result["active_before"] == 2
    assert result["active_after"] == 2
    assert result["limit_satisfied"] is True


def test_retention_archives_lowest_importance_first(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(
        db_path
    )

    _memory(
        db_path,
        "MEM-LOW",
        10,
    )

    _memory(
        db_path,
        "MEM-MID",
        30,
    )

    _memory(
        db_path,
        "MEM-HIGH",
        60,
    )

    result = (
        enforce_project_memory_retention(
            "PROJECT-9001",
            max_active=2,
            db_path=db_path,
        )
    )

    assert result[
        "archived_memory_ids"
    ] == [
        "MEM-LOW",
    ]

    low = get_project_memory(
        "MEM-LOW",
        db_path=db_path,
    )

    assert low is not None
    assert low["status"] == "archived"

    assert result["active_after"] == 2
    assert result["limit_satisfied"] is True


def test_retention_protects_high_importance_memory(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(
        db_path
    )

    _memory(
        db_path,
        "MEM-PROTECTED",
        90,
    )

    _memory(
        db_path,
        "MEM-LOW",
        10,
    )

    result = (
        enforce_project_memory_retention(
            "PROJECT-9001",
            max_active=1,
            protected_importance=80,
            db_path=db_path,
        )
    )

    protected = get_project_memory(
        "MEM-PROTECTED",
        db_path=db_path,
    )

    low = get_project_memory(
        "MEM-LOW",
        db_path=db_path,
    )

    assert protected is not None
    assert protected["status"] == "active"

    assert low is not None
    assert low["status"] == "archived"

    assert result["protected_active"] == 1
    assert result["limit_satisfied"] is True


def test_retention_reports_unsatisfied_limit_when_all_protected(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(
        db_path
    )

    _memory(
        db_path,
        "MEM-P1",
        90,
    )

    _memory(
        db_path,
        "MEM-P2",
        95,
    )

    result = (
        enforce_project_memory_retention(
            "PROJECT-9001",
            max_active=1,
            protected_importance=80,
            db_path=db_path,
        )
    )

    assert result["active_before"] == 2
    assert result["archived_count"] == 0
    assert result["active_after"] == 2
    assert result["protected_active"] == 2
    assert result["limit_satisfied"] is False
