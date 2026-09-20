import json

import pytest

from factory.agents.capabilities import (
    AgentCapability,
)
from factory.task_plan_store import (
    get_task_plan,
    save_task_plan,
)
from factory.task_step_executor import (
    StepExecutionError,
    StepHandlerResult,
    StepHandoffRequest,
    execute_task_plan,
)


def _save_plan(
    db_path,
    task_id,
):
    save_task_plan(
        task_id,
        [
            {
                "title": "Write implementation",
                "instruction": "Implement change",
                "kind": "write",
            }
        ],
        db_path=db_path,
    )


def _write_result():
    return StepHandlerResult(
        output="write complete",
        agent_name="coder-agent",
        provider_name="test-provider",
        handoff_request=StepHandoffRequest(
            required_capabilities=frozenset(
                {
                    AgentCapability.REVIEW_CODE,
                }
            ),
            reason="Independent quality review",
            instruction="Review implementation",
            quality_gate=True,
        ),
    )


def _review_checkpoint(
    verdict,
    *,
    severity=None,
    blocking=False,
):
    findings = []

    if severity is not None:
        findings.append(
            {
                "severity": severity,
                "category": "correctness",
                "message": "Review finding",
                "blocking": blocking,
            }
        )

    return {
        "checkpoint_id": "CP-REVIEW",
        "summary": json.dumps(
            {
                "verdict": verdict,
                "summary": (
                    "Structured review result"
                ),
                "findings": findings,
            }
        ),
    }


def test_review_pass_allows_write_step(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-QG-1"

    _save_plan(
        db_path,
        task_id,
    )

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=lambda *_: _write_result(),
        verify_handler=lambda *_: None,
        handoff_executor=(
            lambda *_: _review_checkpoint(
                "pass"
            )
        ),
        db_path=db_path,
    )

    assert plan["status"] == "completed"
    assert (
        plan["steps"][0]["status"]
        == "completed"
    )


def test_review_warn_allows_write_step(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-QG-2"

    _save_plan(
        db_path,
        task_id,
    )

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=lambda *_: _write_result(),
        verify_handler=lambda *_: None,
        handoff_executor=(
            lambda *_: _review_checkpoint(
                "warn",
                severity="warning",
            )
        ),
        db_path=db_path,
    )

    assert plan["status"] == "completed"


def test_review_block_fails_write_step(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-QG-3"

    _save_plan(
        db_path,
        task_id,
    )

    with pytest.raises(
        StepExecutionError,
        match="Quality gate blocked",
    ):
        execute_task_plan(
            task_id,
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=lambda *_: _write_result(),
            verify_handler=lambda *_: None,
            handoff_executor=(
                lambda *_: _review_checkpoint(
                    "block",
                    severity="critical",
                    blocking=True,
                )
            ),
            db_path=db_path,
        )

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert plan is not None
    assert plan["status"] == "failed"
    assert (
        plan["steps"][0]["status"]
        == "failed"
    )


def test_invalid_structured_review_fails_gate(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-QG-4"

    _save_plan(
        db_path,
        task_id,
    )

    with pytest.raises(
        StepExecutionError,
        match="valid JSON",
    ):
        execute_task_plan(
            task_id,
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=lambda *_: _write_result(),
            verify_handler=lambda *_: None,
            handoff_executor=lambda *_: {
                "checkpoint_id": "CP-REVIEW",
                "summary": "review looks fine",
            },
            db_path=db_path,
        )


def _save_write_verify_plan(
    db_path,
    task_id,
):
    save_task_plan(
        task_id,
        [
            {
                "title": "Write implementation",
                "instruction": "Implement change",
                "kind": "write",
            },
            {
                "title": "Verify implementation",
                "instruction": "Verify change",
                "kind": "verify",
            },
        ],
        db_path=db_path,
    )


def test_review_pass_and_verifier_pass_complete_plan(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-QG-COMBINED-1"

    _save_write_verify_plan(
        db_path,
        task_id,
    )

    verifier_calls = []

    def verifier(*_):
        verifier_calls.append(True)
        return "verification passed"

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=lambda *_: _write_result(),
        verify_handler=verifier,
        handoff_executor=(
            lambda *_: _review_checkpoint(
                "pass"
            )
        ),
        db_path=db_path,
    )

    assert plan["status"] == "completed"
    assert verifier_calls == [True]

    assert [
        step["status"]
        for step in plan["steps"]
    ] == [
        "completed",
        "completed",
    ]


def test_review_warn_and_verifier_pass_complete_plan(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-QG-COMBINED-2"

    _save_write_verify_plan(
        db_path,
        task_id,
    )

    verifier_calls = []

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=lambda *_: _write_result(),
        verify_handler=lambda *_: (
            verifier_calls.append(True)
            or "verification passed"
        ),
        handoff_executor=(
            lambda *_: _review_checkpoint(
                "warn",
                severity="warning",
            )
        ),
        db_path=db_path,
    )

    assert plan["status"] == "completed"
    assert verifier_calls == [True]


def test_review_block_prevents_verifier_execution(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-QG-COMBINED-3"

    _save_write_verify_plan(
        db_path,
        task_id,
    )

    verifier_calls = []

    with pytest.raises(
        StepExecutionError,
        match="Quality gate blocked",
    ):
        execute_task_plan(
            task_id,
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=lambda *_: _write_result(),
            verify_handler=lambda *_: (
                verifier_calls.append(True)
                or "verification passed"
            ),
            handoff_executor=(
                lambda *_: _review_checkpoint(
                    "block",
                    severity="critical",
                    blocking=True,
                )
            ),
            db_path=db_path,
        )

    assert verifier_calls == []


def test_verifier_failure_fails_after_review_pass(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-QG-COMBINED-4"

    _save_write_verify_plan(
        db_path,
        task_id,
    )

    def failing_verifier(*_):
        raise RuntimeError(
            "verification failed"
        )

    with pytest.raises(
        StepExecutionError,
        match="verification failed",
    ):
        execute_task_plan(
            task_id,
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=lambda *_: _write_result(),
            verify_handler=failing_verifier,
            handoff_executor=(
                lambda *_: _review_checkpoint(
                    "pass"
                )
            ),
            db_path=db_path,
        )

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert plan is not None
    assert plan["status"] == "failed"

    assert [
        step["status"]
        for step in plan["steps"]
    ] == [
        "completed",
        "failed",
    ]
