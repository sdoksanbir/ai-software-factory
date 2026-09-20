from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
)
from factory.agent_execution_store import (
    complete_agent_execution,
    create_agent_execution,
    fail_agent_execution,
)
from factory.agent_handoff_store import (
    create_agent_handoff,
    update_agent_handoff,
)
from factory.agent_telemetry import (
    AGENT_CHAIN_TELEMETRY_SCHEMA,
    build_agent_chain_telemetry,
)


def test_agent_chain_telemetry_builds_four_role_lineage(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-TEL-CHAIN-1"

    analyst = create_agent_checkpoint(
        task_id,
        step_index=1,
        agent_name="ollama-analyst",
        provider_name="ollama",
        status="completed",
        summary="analysis",
        checkpoint_id="CHK-TEL-A",
        db_path=db_path,
    )

    coder = create_agent_checkpoint(
        task_id,
        step_index=2,
        agent_name="ollama-coder",
        provider_name="ollama",
        status="completed",
        summary="code",
        payload={
            "source_checkpoint_id": (
                analyst["checkpoint_id"]
            ),
        },
        checkpoint_id="CHK-TEL-C",
        db_path=db_path,
    )

    handoff = create_agent_handoff(
        source_checkpoint_id=(
            coder["checkpoint_id"]
        ),
        target_agent="gemini-reviewer",
        reason="Review",
        handoff_id="HOF-TEL-1",
        db_path=db_path,
    )

    reviewer = create_agent_checkpoint(
        task_id,
        step_index=2,
        agent_name="gemini-reviewer",
        provider_name="gemini_cli",
        status="completed",
        summary="review",
        payload={
            "handoff_id": (
                handoff["handoff_id"]
            ),
            "source_checkpoint_id": (
                coder["checkpoint_id"]
            ),
            "fallback_used": True,
        },
        checkpoint_id="CHK-TEL-R",
        db_path=db_path,
    )

    update_agent_handoff(
        handoff["handoff_id"],
        status="completed",
        db_path=db_path,
    )

    verifier = create_agent_checkpoint(
        task_id,
        step_index=3,
        agent_name="ollama-verifier",
        provider_name="ollama",
        status="completed",
        summary="verified",
        payload={
            "source_checkpoint_id": (
                reviewer[
                    "checkpoint_id"
                ]
            ),
        },
        checkpoint_id="CHK-TEL-V",
        db_path=db_path,
    )

    failed = create_agent_execution(
        task_id,
        step_index=2,
        handoff_id=(
            handoff["handoff_id"]
        ),
        source_checkpoint_id=(
            coder["checkpoint_id"]
        ),
        agent_name="gemini-reviewer",
        provider_name="gemini_cli",
        capabilities=["review_code"],
        metadata={
            "provider_attempt": 1,
            "fallback": False,
        },
        db_path=db_path,
    )

    fail_agent_execution(
        failed["execution_id"],
        error="provider unavailable",
        metadata={
            "provider_attempt": 1,
            "fallback": False,
        },
        db_path=db_path,
    )

    fallback = create_agent_execution(
        task_id,
        step_index=2,
        handoff_id=(
            handoff["handoff_id"]
        ),
        source_checkpoint_id=(
            coder["checkpoint_id"]
        ),
        agent_name="backup-reviewer",
        provider_name="codex",
        capabilities=["review_code"],
        metadata={
            "provider_attempt": 2,
            "fallback": True,
        },
        db_path=db_path,
    )

    complete_agent_execution(
        fallback["execution_id"],
        result_checkpoint_id=(
            reviewer[
                "checkpoint_id"
            ]
        ),
        metadata={
            "provider_attempt": 2,
            "fallback": True,
        },
        db_path=db_path,
    )

    telemetry = (
        build_agent_chain_telemetry(
            task_id,
            db_path=db_path,
        )
    )

    assert (
        telemetry["schema"]
        == AGENT_CHAIN_TELEMETRY_SCHEMA
    )

    assert telemetry["summary"] == {
        "execution_count": 2,
        "checkpoint_count": 4,
        "handoff_count": 1,
        "completed_handoff_count": 1,
        "failed_execution_count": 1,
        "fallback_attempt_count": 1,
        "lineage_orphan_count": 0,
        "lineage_ok": True,
    }

    assert [
        item["role"]
        for item in telemetry["chain"]
    ] == [
        "analyst",
        "coder",
        "reviewer",
        "verifier",
    ]

    assert [
        item["depth"]
        for item in telemetry["chain"]
    ] == [
        0,
        1,
        2,
        3,
    ]

    assert (
        telemetry[
            "fallback_attempts"
        ][0]["provider_name"]
        == "codex"
    )

    assert (
        telemetry["handoffs"][0][
            "status"
        ]
        == "completed"
    )


def test_agent_chain_telemetry_reports_orphan_lineage(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_checkpoint(
        "TASK-TEL-CHAIN-2",
        step_index=1,
        agent_name="reviewer-agent",
        provider_name="ollama",
        status="completed",
        payload={
            "source_checkpoint_id": (
                "CHK-MISSING"
            ),
        },
        db_path=db_path,
    )

    telemetry = (
        build_agent_chain_telemetry(
            "TASK-TEL-CHAIN-2",
            db_path=db_path,
        )
    )

    assert (
        telemetry["summary"][
            "lineage_ok"
        ]
        is False
    )

    assert (
        telemetry["summary"][
            "lineage_orphan_count"
        ]
        == 1
    )
