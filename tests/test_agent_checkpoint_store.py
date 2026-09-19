import pytest

from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
    get_agent_checkpoint,
    list_agent_checkpoints,
    update_agent_checkpoint,
)


def test_create_and_get_checkpoint(
    tmp_path,
):
    db_path = (
        tmp_path
        / "factory.db"
    )

    created = create_agent_checkpoint(
        "TASK-1001",
        step_index=2,
        agent_name="ollama-agent",
        provider_name="ollama",
        status="completed",
        summary="Write step completed",
        payload={
            "files": [
                "math_utils.py",
            ],
            "model": (
                "qwen2.5-coder:14b"
            ),
        },
        checkpoint_id="CHK-TEST-1",
        db_path=db_path,
    )

    assert (
        created["checkpoint_id"]
        == "CHK-TEST-1"
    )
    assert created["task_id"] == "TASK-1001"
    assert created["step_index"] == 2
    assert (
        created["provider_name"]
        == "ollama"
    )
    assert created["status"] == "completed"
    assert created["payload"] == {
        "files": [
            "math_utils.py",
        ],
        "model": (
            "qwen2.5-coder:14b"
        ),
    }

    loaded = get_agent_checkpoint(
        "CHK-TEST-1",
        db_path=db_path,
    )

    assert loaded == created


def test_list_checkpoints_by_task_and_step(
    tmp_path,
):
    db_path = (
        tmp_path
        / "factory.db"
    )

    create_agent_checkpoint(
        "TASK-1002",
        step_index=1,
        agent_name="reader",
        provider_name="ollama",
        checkpoint_id="CHK-A",
        db_path=db_path,
    )

    create_agent_checkpoint(
        "TASK-1002",
        step_index=2,
        agent_name="coder",
        provider_name="ollama",
        checkpoint_id="CHK-B",
        db_path=db_path,
    )

    all_items = list_agent_checkpoints(
        "TASK-1002",
        db_path=db_path,
    )

    step_two = list_agent_checkpoints(
        "TASK-1002",
        step_index=2,
        db_path=db_path,
    )

    assert len(all_items) == 2
    assert [
        item["checkpoint_id"]
        for item in step_two
    ] == [
        "CHK-B"
    ]


def test_update_checkpoint(
    tmp_path,
):
    db_path = (
        tmp_path
        / "factory.db"
    )

    create_agent_checkpoint(
        "TASK-1003",
        step_index=3,
        agent_name="coder",
        provider_name="ollama",
        checkpoint_id="CHK-C",
        db_path=db_path,
    )

    update_agent_checkpoint(
        "CHK-C",
        status="handed_off",
        summary="Ready for review",
        payload={
            "next_capability": (
                "review_code"
            ),
        },
        db_path=db_path,
    )

    loaded = get_agent_checkpoint(
        "CHK-C",
        db_path=db_path,
    )

    assert loaded is not None
    assert (
        loaded["status"]
        == "handed_off"
    )
    assert (
        loaded["summary"]
        == "Ready for review"
    )
    assert loaded["payload"] == {
        "next_capability": (
            "review_code"
        ),
    }


def test_checkpoint_validation(
    tmp_path,
):
    db_path = (
        tmp_path
        / "factory.db"
    )

    with pytest.raises(
        ValueError,
        match="step_index",
    ):
        create_agent_checkpoint(
            "TASK-1004",
            step_index=0,
            agent_name="coder",
            provider_name="ollama",
            db_path=db_path,
        )

    with pytest.raises(
        ValueError,
        match="checkpoint status",
    ):
        create_agent_checkpoint(
            "TASK-1004",
            step_index=1,
            agent_name="coder",
            provider_name="ollama",
            status="unknown",
            db_path=db_path,
        )


def test_update_unknown_checkpoint_fails(
    tmp_path,
):
    db_path = (
        tmp_path
        / "factory.db"
    )

    with pytest.raises(
        KeyError,
        match="CHK-MISSING",
    ):
        update_agent_checkpoint(
            "CHK-MISSING",
            status="failed",
            db_path=db_path,
        )
