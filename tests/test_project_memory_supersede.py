import pytest

from factory.database import (
    create_project,
    init_database,
)
from factory.project_memory_retrieval import (
    rank_project_memories,
)
from factory.project_memory_store import (
    create_project_memory,
    get_project_memory,
    supersede_project_memory,
    update_project_memory,
)


def _setup_project(
    db_path,
    project_id="PROJECT-8001",
):
    init_database(
        db_path
    )

    create_project(
        project_id,
        name=f"Project {project_id}",
        path=str(
            db_path.parent / project_id
        ),
        db_path=db_path,
    )


def test_supersede_marks_old_and_links_replacement(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(
        db_path
    )

    create_project_memory(
        "PROJECT-8001",
        kind="decision",
        title="Old database decision",
        content="Use JSON storage.",
        memory_id="MEM-OLD",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-8001",
        kind="decision",
        title="New database decision",
        content="Use SQLite storage.",
        memory_id="MEM-NEW",
        db_path=db_path,
    )

    result = supersede_project_memory(
        "MEM-OLD",
        "MEM-NEW",
        db_path=db_path,
    )

    assert (
        result["superseded"]["status"]
        == "superseded"
    )

    assert (
        result["superseded"][
            "superseded_by_memory_id"
        ]
        == "MEM-NEW"
    )

    assert (
        result["replacement"]["status"]
        == "active"
    )


def test_memory_cannot_supersede_itself(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(
        db_path
    )

    create_project_memory(
        "PROJECT-8001",
        kind="fact",
        title="Runtime",
        content="Runtime fact.",
        memory_id="MEM-ONE",
        db_path=db_path,
    )

    with pytest.raises(
        ValueError,
        match="cannot supersede itself",
    ):
        supersede_project_memory(
            "MEM-ONE",
            "MEM-ONE",
            db_path=db_path,
        )


def test_cross_project_supersede_is_rejected(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(
        db_path,
        "PROJECT-8001",
    )

    _setup_project(
        db_path,
        "PROJECT-8002",
    )

    create_project_memory(
        "PROJECT-8001",
        kind="decision",
        title="Project one",
        content="Decision one.",
        memory_id="MEM-P1",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-8002",
        kind="decision",
        title="Project two",
        content="Decision two.",
        memory_id="MEM-P2",
        db_path=db_path,
    )

    with pytest.raises(
        ValueError,
        match="same project",
    ):
        supersede_project_memory(
            "MEM-P1",
            "MEM-P2",
            db_path=db_path,
        )


def test_inactive_replacement_is_rejected(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(
        db_path
    )

    create_project_memory(
        "PROJECT-8001",
        kind="decision",
        title="Old rule",
        content="Old behaviour.",
        memory_id="MEM-OLD",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-8001",
        kind="decision",
        title="Archived rule",
        content="Archived behaviour.",
        memory_id="MEM-ARCHIVED",
        db_path=db_path,
    )

    update_project_memory(
        "MEM-ARCHIVED",
        status="archived",
        db_path=db_path,
    )

    with pytest.raises(
        ValueError,
        match="must be active",
    ):
        supersede_project_memory(
            "MEM-OLD",
            "MEM-ARCHIVED",
            db_path=db_path,
        )


def test_superseded_memory_is_removed_from_retrieval(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup_project(
        db_path
    )

    create_project_memory(
        "PROJECT-8001",
        kind="decision",
        title="Cache storage decision",
        content="Cache uses JSON storage.",
        tags=["cache", "storage"],
        memory_id="MEM-OLD",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-8001",
        kind="decision",
        title="Cache storage decision",
        content="Cache uses SQLite storage.",
        tags=["cache", "storage"],
        memory_id="MEM-NEW",
        db_path=db_path,
    )

    supersede_project_memory(
        "MEM-OLD",
        "MEM-NEW",
        db_path=db_path,
    )

    ranked = rank_project_memories(
        "PROJECT-8001",
        "cache storage decision",
        db_path=db_path,
    )

    ids = [
        item.memory["memory_id"]
        for item in ranked
    ]

    assert "MEM-NEW" in ids
    assert "MEM-OLD" not in ids

    old_memory = get_project_memory(
        "MEM-OLD",
        db_path=db_path,
    )

    assert old_memory is not None
    assert (
        old_memory["status"]
        == "superseded"
    )
