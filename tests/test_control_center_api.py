from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.app as api_app


def test_control_center_endpoint_wires_full_snapshot(
    monkeypatch,
):
    captured = {}

    monkeypatch.setattr(
        api_app,
        "Orchestrator",
        lambda: SimpleNamespace(
            project_path="fallback-project"
        ),
    )

    monkeypatch.setattr(
        api_app,
        "TASKS",
        {
            "TASK-1": SimpleNamespace(
                task_id="TASK-1",
                project_id="PROJECT-1",
                state="running",
            ),
            "TASK-2": SimpleNamespace(
                task_id="TASK-2",
                project_id="PROJECT-2",
                state="failed",
            ),
        },
    )

    monkeypatch.setattr(
        api_app,
        "db_get_project",
        lambda project_id: {
            "project_id": project_id,
            "path": "project-one",
        },
    )

    expected = {
        "providers": {
            "total": 2,
        },
        "agents": {
            "total": 10,
        },
        "task_graphs": {
            "total": 1,
        },
        "project_memory": {
            "total": 4,
        },
        "health": {
            "status": "healthy",
        },
    }

    def fake_control_center_status(
        **kwargs,
    ):
        captured.update(
            kwargs
        )
        return expected

    monkeypatch.setattr(
        api_app,
        "get_control_center_status",
        fake_control_center_status,
    )

    result = (
        api_app.control_center_status(
            project_id="PROJECT-1"
        )
    )

    assert result == expected

    assert (
        captured["project_path"]
        == "project-one"
    )

    assert (
        captured["project_id"]
        == "PROJECT-1"
    )

    assert (
        captured["provider_registry"]
        is api_app.API_PROVIDER_REGISTRY
    )

    assert (
        captured["db_path"]
        == api_app.DEFAULT_DB_PATH
    )

    assert (
        captured["use_cache"]
        is True
    )

    assert len(
        captured["tasks"]
    ) == 1

    assert (
        captured["tasks"][0].task_id
        == "TASK-1"
    )


def test_control_center_unknown_project_returns_404(
    monkeypatch,
):
    monkeypatch.setattr(
        api_app,
        "Orchestrator",
        lambda: SimpleNamespace(
            project_path="fallback-project"
        ),
    )

    monkeypatch.setattr(
        api_app,
        "db_get_project",
        lambda project_id: None,
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        api_app.control_center_status(
            project_id="MISSING"
        )

    assert (
        exc_info.value.status_code
        == 404
    )



def test_control_center_refresh_bypasses_cache(
    monkeypatch,
):
    captured = {}

    monkeypatch.setattr(
        api_app,
        "Orchestrator",
        lambda: SimpleNamespace(
            project_path="fallback-project"
        ),
    )

    monkeypatch.setattr(
        api_app,
        "TASKS",
        {},
    )

    def fake_control_center_status(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return {
            "health": {
                "status": "healthy",
            },
        }

    monkeypatch.setattr(
        api_app,
        "get_control_center_status",
        fake_control_center_status,
    )

    result = (
        api_app.control_center_status(
            refresh=True
        )
    )

    assert (
        result["health"]["status"]
        == "healthy"
    )

    assert (
        captured["use_cache"]
        is False
    )

    assert (
        captured["project_id"]
        is None
    )

    assert (
        captured["provider_registry"]
        is api_app.API_PROVIDER_REGISTRY
    )


def test_project_control_center_endpoint_delegates_project_id(
    monkeypatch,
):
    captured = {}

    def fake_control_center_status(
        *,
        project_id=None,
        refresh=False,
    ):
        captured["project_id"] = project_id
        captured["refresh"] = refresh

        return {
            "project_id": project_id,
            "refresh": refresh,
        }

    monkeypatch.setattr(
        api_app,
        "control_center_status",
        fake_control_center_status,
    )

    result = (
        api_app.project_control_center_status(
            project_id="PROJECT-42",
        )
    )

    assert result == {
        "project_id": "PROJECT-42",
        "refresh": False,
    }

    assert (
        captured["project_id"]
        == "PROJECT-42"
    )

    assert (
        captured["refresh"]
        is False
    )


def test_project_control_center_endpoint_preserves_refresh(
    monkeypatch,
):
    captured = {}

    def fake_control_center_status(
        *,
        project_id=None,
        refresh=False,
    ):
        captured["project_id"] = project_id
        captured["refresh"] = refresh

        return {
            "ok": True,
        }

    monkeypatch.setattr(
        api_app,
        "control_center_status",
        fake_control_center_status,
    )

    result = (
        api_app.project_control_center_status(
            project_id="PROJECT-42",
            refresh=True,
        )
    )

    assert result == {
        "ok": True,
    }

    assert (
        captured["project_id"]
        == "PROJECT-42"
    )

    assert (
        captured["refresh"]
        is True
    )
