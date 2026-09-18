import pytest

from factory.task_plan_store import (
    delete_task_plan,
    get_task_plan,
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
        db_path=db_path,
    )

    assert saved["task_id"] == "TASK-1001"
    assert saved["status"] == "pending"
    assert saved["summary"] == "Three step plan"

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
        db_path=db_path,
    )

    loaded = get_task_plan(
        "TASK-1002",
        db_path=db_path,
    )

    assert loaded is not None
    assert len(loaded["steps"]) == 3
    assert loaded["steps"][0]["status"] == "pending"


def test_update_single_step(tmp_path):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-1003",
        _sample_steps(),
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


def test_delete_plan(tmp_path):
    db_path = tmp_path / "factory.db"

    save_task_plan(
        "TASK-1006",
        _sample_steps(),
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
