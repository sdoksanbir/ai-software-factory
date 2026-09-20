from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import app as app_module


def _task():
    return SimpleNamespace(
        state="running",
    )


def test_agent_execution_endpoint(
    monkeypatch,
):
    task_id = "TASK-API-AGENT-1"

    monkeypatch.setitem(
        app_module.TASKS,
        task_id,
        _task(),
    )

    monkeypatch.setattr(
        app_module,
        "list_agent_executions",
        lambda value: [
            {
                "execution_id": "EXE-1",
                "task_id": value,
                "status": "completed",
            }
        ],
    )

    result = (
        app_module
        .get_task_agent_executions_endpoint(
            task_id
        )
    )

    assert result["task_id"] == task_id
    assert result["state"] == "running"
    assert (
        result["executions"][0][
            "execution_id"
        ]
        == "EXE-1"
    )


def test_checkpoint_endpoint(
    monkeypatch,
):
    task_id = "TASK-API-AGENT-2"

    monkeypatch.setitem(
        app_module.TASKS,
        task_id,
        _task(),
    )

    monkeypatch.setattr(
        app_module,
        "list_agent_checkpoints",
        lambda value: [
            {
                "checkpoint_id": "CHK-1",
                "task_id": value,
            }
        ],
    )

    result = (
        app_module
        .get_task_checkpoints_endpoint(
            task_id
        )
    )

    assert (
        result["checkpoints"][0][
            "checkpoint_id"
        ]
        == "CHK-1"
    )


def test_handoff_endpoint(
    monkeypatch,
):
    task_id = "TASK-API-AGENT-3"

    monkeypatch.setitem(
        app_module.TASKS,
        task_id,
        _task(),
    )

    monkeypatch.setattr(
        app_module,
        "list_agent_handoffs",
        lambda value: [
            {
                "handoff_id": "HOF-1",
                "task_id": value,
            }
        ],
    )

    result = (
        app_module
        .get_task_handoffs_endpoint(
            task_id
        )
    )

    assert (
        result["handoffs"][0][
            "handoff_id"
        ]
        == "HOF-1"
    )


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "get_task_agent_executions_endpoint",
        "get_task_checkpoints_endpoint",
        "get_task_handoffs_endpoint",
    ],
)
def test_agent_telemetry_endpoints_return_404(
    endpoint_name,
):
    endpoint = getattr(
        app_module,
        endpoint_name,
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        endpoint(
            "TASK-DOES-NOT-EXIST"
        )

    assert (
        exc_info.value.status_code
        == 404
    )

def test_agent_chain_endpoint(
    monkeypatch,
):
    task_id = "TASK-API-AGENT-CHAIN"

    monkeypatch.setitem(
        app_module.TASKS,
        task_id,
        _task(),
    )

    monkeypatch.setattr(
        app_module,
        "build_agent_chain_telemetry",
        lambda value: {
            "schema": (
                "agent_chain_telemetry.v1"
            ),
            "task_id": value,
            "summary": {
                "lineage_ok": True,
            },
            "chain": [
                {
                    "role": "analyst",
                },
                {
                    "role": "coder",
                },
                {
                    "role": "reviewer",
                },
                {
                    "role": "verifier",
                },
            ],
            "handoffs": [],
            "fallback_attempts": [],
        },
    )

    result = (
        app_module
        .get_task_agent_chain_endpoint(
            task_id
        )
    )

    assert result["task_id"] == task_id
    assert result["state"] == "running"

    assert [
        item["role"]
        for item
        in result["telemetry"]["chain"]
    ] == [
        "analyst",
        "coder",
        "reviewer",
        "verifier",
    ]
