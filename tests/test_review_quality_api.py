from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.app as app_module


def _checkpoints():
    return [
        {
            "checkpoint_id": "CP-SOURCE",
            "step_index": 0,
            "agent_name": "coder-agent",
            "provider_name": "provider",
            "status": "completed",
            "payload": {
                "handoff_request": {
                    "required_capabilities": [
                        "review_code"
                    ],
                    "quality_gate": True,
                }
            },
        },
        {
            "checkpoint_id": "CP-REVIEW",
            "step_index": 0,
            "agent_name": "reviewer-agent",
            "provider_name": "provider",
            "status": "completed",
            "summary": """
            {
                "verdict": "pass",
                "summary": "Review passed.",
                "findings": []
            }
            """,
            "payload": {
                "source_checkpoint_id": (
                    "CP-SOURCE"
                )
            },
        },
    ]


def test_quality_review_endpoint(
    monkeypatch,
):
    task_id = "TASK-QA-API"

    monkeypatch.setitem(
        app_module.TASKS,
        task_id,
        SimpleNamespace(
            state="ready_for_approval"
        ),
    )

    monkeypatch.setattr(
        app_module,
        "list_agent_checkpoints",
        lambda actual_task_id: (
            _checkpoints()
            if actual_task_id == task_id
            else []
        ),
    )

    result = (
        app_module
        .get_task_quality_reviews_endpoint(
            task_id
        )
    )

    assert result["task_id"] == task_id
    assert (
        result["state"]
        == "ready_for_approval"
    )

    assert (
        result["overall_status"]
        == "passed"
    )

    assert result["total_reviews"] == 1
    assert result["passed"] == 1


def test_quality_review_endpoint_unknown_task():
    task_id = "TASK-QA-MISSING"

    app_module.TASKS.pop(
        task_id,
        None,
    )

    with pytest.raises(
        HTTPException,
    ) as exc_info:
        (
            app_module
            .get_task_quality_reviews_endpoint(
                task_id
            )
        )

    assert (
        exc_info.value.status_code
        == 404
    )
