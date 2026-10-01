import pytest
import sqlite3

from factory.task_plan_store import (
    delete_task_plan,
    get_task_plan,
    init_task_plan_store,
    is_resumable_multi_step_plan,
    save_task_plan,
    update_task_plan_status,
    update_task_step,
)


def _sample_steps():
    return [
        {
            "title": "Repository analysis",
            "instruction": "Inspect current structure.",
            "kind": "read",
        },
        {
            "title": "Implement change",
            "instruction": "Apply required code changes.",
            "kind": "write",
        },
        {
            "title": "Verify result",
            "instruction": "Run final verification.",
            "kind": "verify",
        },
    ]


def test_save_and_load_plan(tmp_path):
    db_path = tmp_path / "factory.db"

    saved = save_task_plan(
        "TASK-1001",
        _sample_steps(),
        summary="Three step plan",
        planner_mode="multi_step",
        db_path=db_path,
    )

    assert saved["task_id"] == "TASK-1001"
    assert saved["status"] == "pending"
    assert saved["summary"] == "Three step plan"
    assert saved["planner_mode"] == "multi_step"

    assert [
        step["step_index"]
        for step in saved["steps"]
    ] == [1, 2, 3]

    assert [
        step["kind"]
        for step in saved["steps"]
    ] == [
        "read",
        "write",
        "verify",
    ]


def test_plan_survives_new_connection(tmp_path):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-1002",
        _sample_steps(),
        planner_mode="multi_step",
        db_path=db_path,
    )

    loaded = get_task_plan(
        "TASK-1002",
        db_path=db_path,
    )

    assert loaded is not None
    assert len(loaded["steps"]) == 3
    assert loaded["steps"][0]["status"] == "pending"
    assert loaded["planner_mode"] == "multi_step"


def test_update_single_step(tmp_path):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-1003",
        _sample_steps(),
        planner_mode="multi_step",
        db_path=db_path,
    )

    update_task_step(
        "TASK-1003",
        2,
        status="completed",
        attempt=1,
        result="Patch applied",
        db_path=db_path,
    )

    loaded = get_task_plan(
        "TASK-1003",
        db_path=db_path,
    )

    step = loaded["steps"][1]

    assert step["status"] == "completed"
    assert step["attempt"] == 1
    assert step["result"] == "Patch applied"


def test_update_plan_status(tmp_path):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-1004",
        _sample_steps(),
        planner_mode="multi_step",
        db_path=db_path,
    )

    update_task_plan_status(
        "TASK-1004",
        "running",
        db_path=db_path,
    )

    loaded = get_task_plan(
        "TASK-1004",
        db_path=db_path,
    )

    assert loaded["status"] == "running"


def test_replace_plan_steps(tmp_path):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-1005",
        _sample_steps(),
        planner_mode="multi_step",
        db_path=db_path,
    )

    save_task_plan(
        "TASK-1005",
        [
            {
                "title": "Replacement step",
                "instruction": "Use new plan.",
                "kind": "write",
            }
        ],
        summary="Replacement",
        planner_mode="single_step",
        db_path=db_path,
    )

    loaded = get_task_plan(
        "TASK-1005",
        db_path=db_path,
    )

    assert len(loaded["steps"]) == 1
    assert loaded["steps"][0]["title"] == (
        "Replacement step"
    )
    assert loaded["planner_mode"] == "single_step"


def test_delete_plan(tmp_path):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-1006",
        _sample_steps(),
        planner_mode="multi_step",
        db_path=db_path,
    )

    delete_task_plan(
        "TASK-1006",
        db_path=db_path,
    )

    assert get_task_plan(
        "TASK-1006",
        db_path=db_path,
    ) is None


def test_invalid_step_kind_rejected(tmp_path):
    db_path = tmp_path / "factory.db"

    with pytest.raises(ValueError):
        save_task_plan(
            "TASK-1007",
            [
                {
                    "title": "Bad step",
                    "instruction": "Bad kind",
                    "kind": "unknown",
                }
            ],
            db_path=db_path,
        )


def test_persist_single_step_planner_mode(tmp_path):
    db_path = tmp_path / "factory.db"

    saved = save_task_plan(
        "TASK-MODE-1",
        [
            {
                "title": "Write",
                "instruction": "Write file",
                "kind": "write",
            },
            {
                "title": "Verify",
                "instruction": "Verify",
                "kind": "verify",
            },
        ],
        summary="Tek adimli gorev",
        planner_mode="single_step",
        db_path=db_path,
    )

    loaded = get_task_plan(
        "TASK-MODE-1",
        db_path=db_path,
    )

    assert saved["planner_mode"] == "single_step"
    assert loaded["planner_mode"] == "single_step"
    assert len(loaded["steps"]) == 2


def test_persist_multi_step_planner_mode(tmp_path):
    db_path = tmp_path / "factory.db"

    saved = save_task_plan(
        "TASK-MODE-2",
        _sample_steps(),
        planner_mode="multi_step",
        db_path=db_path,
    )

    loaded = get_task_plan(
        "TASK-MODE-2",
        db_path=db_path,
    )

    assert saved["planner_mode"] == "multi_step"
    assert loaded["planner_mode"] == "multi_step"


def test_invalid_planner_mode_rejected(tmp_path):
    db_path = tmp_path / "factory.db"

    with pytest.raises(
        ValueError,
        match="Invalid planner_mode",
    ):
        save_task_plan(
            "TASK-MODE-3",
            [
                {
                    "title": "Write",
                    "instruction": "Write",
                    "kind": "write",
                }
            ],
            planner_mode="two_steps",
            db_path=db_path,
        )


def test_legacy_schema_migrates_planner_mode_null(
    tmp_path,
):
    db_path = tmp_path / "legacy.db"

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        connection.executescript(
            """
            CREATE TABLE task_plans (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                summary TEXT,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE task_steps (
                task_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                instruction TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt INTEGER NOT NULL DEFAULT 0,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (
                    task_id,
                    step_index
                )
            );

            INSERT INTO task_plans (
                task_id,
                status,
                summary
            )
            VALUES (
                'TASK-LEGACY-1',
                'failed',
                'Legacy plan'
            );

            INSERT INTO task_steps (
                task_id,
                step_index,
                title,
                instruction,
                kind,
                status
            )
            VALUES (
                'TASK-LEGACY-1',
                1,
                'Write',
                'Write file',
                'write',
                'failed'
            ),
            (
                'TASK-LEGACY-1',
                2,
                'Verify',
                'Verify',
                'verify',
                'pending'
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    init_task_plan_store(db_path)

    loaded = get_task_plan(
        "TASK-LEGACY-1",
        db_path=db_path,
    )

    assert loaded is not None
    assert loaded["summary"] == "Legacy plan"
    assert loaded["status"] == "failed"
    assert loaded["planner_mode"] is None
    assert len(loaded["steps"]) == 2


def test_is_resumable_single_step_always_false():
    assert is_resumable_multi_step_plan(
        {
            "planner_mode": "single_step",
            "status": "failed",
            "steps": [
                {"status": "failed"},
                {"status": "pending"},
            ],
        }
    ) is False


def test_is_resumable_multi_step_unfinished():
    assert is_resumable_multi_step_plan(
        {
            "planner_mode": "multi_step",
            "status": "failed",
            "steps": [
                {"status": "completed"},
                {"status": "failed"},
                {"status": "pending"},
            ],
        }
    ) is True


def test_is_resumable_multi_step_completed_false():
    assert is_resumable_multi_step_plan(
        {
            "planner_mode": "multi_step",
            "status": "completed",
            "steps": [
                {"status": "completed"},
                {"status": "completed"},
            ],
        }
    ) is False


def test_is_resumable_single_step_completed_noop_false():
    # TASK-7503 style: single_step + completed
    # steps, failed only at final no-op gate.
    assert is_resumable_multi_step_plan(
        {
            "planner_mode": "single_step",
            "status": "completed",
            "steps": [
                {"status": "completed"},
                {"status": "completed"},
            ],
        }
    ) is False


def test_is_resumable_legacy_null_uses_step_count():
    assert is_resumable_multi_step_plan(
        {
            "planner_mode": None,
            "status": "failed",
            "steps": [
                {"status": "failed"},
                {"status": "pending"},
            ],
        }
    ) is True

    assert is_resumable_multi_step_plan(
        {
            "planner_mode": None,
            "status": "completed",
            "steps": [
                {"status": "completed"},
                {"status": "completed"},
            ],
        }
    ) is False

    assert is_resumable_multi_step_plan(
        {
            "planner_mode": None,
            "status": "failed",
            "steps": [
                {"status": "failed"},
            ],
        }
    ) is False
