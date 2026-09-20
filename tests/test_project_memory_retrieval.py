from factory.database import (
    create_project,
    init_database,
)
from factory.project_memory_retrieval import (
    rank_project_memories,
    select_relevant_project_memories,
)
from factory.project_memory_store import (
    create_project_memory,
    update_project_memory,
)


def _setup(
    db_path,
):
    init_database(
        db_path
    )

    create_project(
        "PROJECT-3001",
        name="Retrieval Project",
        path=str(
            db_path.parent
            / "project"
        ),
        db_path=db_path,
    )


def test_relevant_database_memory_wins(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup(db_path)

    create_project_memory(
        "PROJECT-3001",
        kind="decision",
        title="Use SQLite persistence",
        content=(
            "Project state is stored "
            "in SQLite."
        ),
        tags=[
            "database",
            "sqlite",
        ],
        importance=80,
        memory_id="MEM-DB",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-3001",
        kind="convention",
        title="Dashboard button style",
        content=(
            "Dashboard buttons use "
            "compact spacing."
        ),
        tags=[
            "dashboard",
            "ui",
        ],
        importance=90,
        memory_id="MEM-UI",
        db_path=db_path,
    )

    ranked = rank_project_memories(
        "PROJECT-3001",
        (
            "SQLite database persistence "
            "migration"
        ),
        db_path=db_path,
    )

    assert ranked

    assert (
        ranked[0].memory["memory_id"]
        == "MEM-DB"
    )

    assert ranked[0].score > 0


def test_irrelevant_memory_is_not_returned(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup(db_path)

    create_project_memory(
        "PROJECT-3001",
        kind="convention",
        title="Dashboard layout",
        content="Use compact dashboard cards.",
        tags=["dashboard"],
        memory_id="MEM-UI",
        db_path=db_path,
    )

    result = (
        select_relevant_project_memories(
            "PROJECT-3001",
            "SQLite database migration",
            db_path=db_path,
        )
    )

    assert result == []


def test_superseded_memory_is_ignored(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup(db_path)

    create_project_memory(
        "PROJECT-3001",
        kind="decision",
        title="Use SQLite",
        content="Use SQLite storage.",
        tags=["sqlite"],
        memory_id="MEM-OLD",
        db_path=db_path,
    )

    update_project_memory(
        "MEM-OLD",
        status="superseded",
        db_path=db_path,
    )

    result = (
        select_relevant_project_memories(
            "PROJECT-3001",
            "SQLite storage",
            db_path=db_path,
        )
    )

    assert result == []


def test_tag_match_has_strong_relevance(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup(db_path)

    create_project_memory(
        "PROJECT-3001",
        kind="constraint",
        title="Provider limitation",
        content=(
            "External provider has "
            "a runtime limitation."
        ),
        tags=[
            "gemini",
            "provider",
        ],
        memory_id="MEM-GEMINI",
        db_path=db_path,
    )

    result = (
        select_relevant_project_memories(
            "PROJECT-3001",
            "Gemini provider health check",
            db_path=db_path,
        )
    )

    assert len(result) == 1

    assert (
        result[0]["memory_id"]
        == "MEM-GEMINI"
    )

    assert (
        result[0]["relevance_score"]
        > 0
    )


def test_importance_breaks_relevance_tie(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup(db_path)

    create_project_memory(
        "PROJECT-3001",
        kind="fact",
        title="Cache behaviour",
        content="Low-priority retained setting.",
        tags=["cache"],
        importance=20,
        memory_id="MEM-LOW",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-3001",
        kind="fact",
        title="Cache behaviour",
        content="High-priority retained setting.",
        tags=["cache"],
        importance=90,
        memory_id="MEM-HIGH",
        db_path=db_path,
    )

    ranked = rank_project_memories(
        "PROJECT-3001",
        "cache behaviour",
        db_path=db_path,
    )

    assert [
        item.memory["memory_id"]
        for item in ranked
    ] == [
        "MEM-HIGH",
        "MEM-LOW",
    ]


def test_retrieval_limit_is_respected(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    _setup(db_path)

    for index in range(5):
        create_project_memory(
            "PROJECT-3001",
            kind="fact",
            title=f"Provider fact {index}",
            content="Provider runtime information.",
            tags=["provider"],
            memory_id=f"MEM-{index}",
            db_path=db_path,
        )

    result = (
        select_relevant_project_memories(
            "PROJECT-3001",
            "provider runtime",
            limit=2,
            db_path=db_path,
        )
    )

    assert len(result) == 2
