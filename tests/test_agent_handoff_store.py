import pytest

from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
    get_agent_checkpoint,
)
from factory.agent_handoff_store import (
    create_agent_handoff,
    get_agent_handoff,
    list_agent_handoffs,
    update_agent_handoff,
)


def test_create_handoff_marks_checkpoint_handed_off(
    tmp_path,
):
    db_path = (
        tmp_path
        / "factory.db"
    )

    create_agent_checkpoint(
        "TASK-2001",
        step_index=2,
        agent_name="ollama-agent",
        provider_name="ollama",
        status="completed",
        checkpoint_id="CHK-H1",
        db_path=db_path,
    )

    handoff = create_agent_handoff(
        source_checkpoint_id="CHK-H1",
        target_agent="gemini-agent",
        reason="Review generated code",
        handoff_id="HOF-1",
        db_path=db_path,
    )

    assert handoff["handoff_id"] == "HOF-1"
    assert handoff["task_id"] == "TASK-2001"
    assert handoff["step_index"] == 2
    assert (
        handoff["source_agent"]
        == "ollama-agent"
    )
    assert (
        handoff["target_agent"]
        == "gemini-agent"
    )
    assert handoff["status"] == "pending"

    checkpoint = get_agent_checkpoint(
        "CHK-H1",
        db_path=db_path,
    )

    assert checkpoint is not None
    assert (
        checkpoint["status"]
        == "handed_off"
    )


def test_list_handoffs_by_task_and_step(
    tmp_path,
):
    db_path = (
        tmp_path
        / "factory.db"
    )

    for index in (1, 2):
        checkpoint_id = (
            f"CHK-H{index + 1}"
        )

        create_agent_checkpoint(
            "TASK-2002",
            step_index=index,
            agent_name="ollama-agent",
            provider_name="ollama",
            checkpoint_id=checkpoint_id,
            db_path=db_path,
        )

        create_agent_handoff(
            source_checkpoint_id=checkpoint_id,
            target_agent="review-agent",
            reason=f"Review step {index}",
            handoff_id=f"HOF-{index + 1}",
            db_path=db_path,
        )

    all_items = list_agent_handoffs(
        "TASK-2002",
        db_path=db_path,
    )

    step_two = list_agent_handoffs(
        "TASK-2002",
        step_index=2,
        db_path=db_path,
    )

    assert len(all_items) == 2
    assert [
        item["handoff_id"]
        for item in step_two
    ] == [
        "HOF-3"
    ]


def test_update_handoff_status(
    tmp_path,
):
    db_path = (
        tmp_path
        / "factory.db"
    )

    create_agent_checkpoint(
        "TASK-2003",
        step_index=1,
        agent_name="ollama-agent",
        provider_name="ollama",
        checkpoint_id="CHK-H4",
        db_path=db_path,
    )

    create_agent_handoff(
        source_checkpoint_id="CHK-H4",
        target_agent="review-agent",
        reason="Review",
        handoff_id="HOF-4",
        db_path=db_path,
    )

    update_agent_handoff(
        "HOF-4",
        status="accepted",
        db_path=db_path,
    )

    loaded = get_agent_handoff(
        "HOF-4",
        db_path=db_path,
    )

    assert loaded is not None
    assert loaded["status"] == "accepted"


def test_handoff_requires_existing_checkpoint(
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
        create_agent_handoff(
            source_checkpoint_id="CHK-MISSING",
            target_agent="review-agent",
            reason="Review",
            db_path=db_path,
        )


def test_handoff_rejects_same_agent(
    tmp_path,
):
    db_path = (
        tmp_path
        / "factory.db"
    )

    create_agent_checkpoint(
        "TASK-2004",
        step_index=1,
        agent_name="ollama-agent",
        provider_name="ollama",
        checkpoint_id="CHK-H5",
        db_path=db_path,
    )

    with pytest.raises(
        ValueError,
        match="target_agent",
    ):
        create_agent_handoff(
            source_checkpoint_id="CHK-H5",
            target_agent="ollama-agent",
            reason="No-op",
            db_path=db_path,
        )
