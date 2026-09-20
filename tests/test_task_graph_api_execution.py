from types import SimpleNamespace

from fastapi.testclient import TestClient

import api.app as app_module


client = TestClient(
    app_module.app
)


def test_graph_order_api(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda graph_id: {
            "graph_id": graph_id,
            "status": "pending",
            "nodes": [],
        },
    )

    monkeypatch.setattr(
        app_module,
        "db_topological_task_order",
        lambda _graph_id: [
            "TASK-1001",
            "TASK-1002",
            "TASK-1003",
        ],
    )

    monkeypatch.setattr(
        app_module,
        "db_topological_task_layers",
        lambda _graph_id: [
            ["TASK-1001"],
            ["TASK-1002"],
            ["TASK-1003"],
        ],
    )

    response = client.get(
        "/task-graphs/GRAPH-1/order"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["graph_id"] == "GRAPH-1"

    assert payload["order"] == [
        "TASK-1001",
        "TASK-1002",
        "TASK-1003",
    ]

    assert payload["layers"] == [
        ["TASK-1001"],
        ["TASK-1002"],
        ["TASK-1003"],
    ]


def test_graph_order_unknown_graph_returns_404(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda _graph_id: None,
    )

    response = client.get(
        "/task-graphs/GRAPH-404/order"
    )

    assert response.status_code == 404


def test_graph_runnable_api(
    monkeypatch,
):
    old_tasks = dict(
        app_module.TASKS
    )

    app_module.TASKS.clear()

    app_module.TASKS[
        "TASK-1001"
    ] = SimpleNamespace(
        state="approved",
        status="approved",
    )

    app_module.TASKS[
        "TASK-1002"
    ] = SimpleNamespace(
        state="blocked",
        status="queued",
    )

    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda graph_id: {
            "graph_id": graph_id,
            "status": "pending",
            "nodes": [],
        },
    )

    captured = {}

    def fake_runnable(
        graph_id,
        task_states,
    ):
        captured["graph_id"] = graph_id
        captured[
            "task_states"
        ] = dict(task_states)

        return ["TASK-1002"]

    monkeypatch.setattr(
        app_module,
        "db_list_runnable_tasks",
        fake_runnable,
    )

    try:
        response = client.get(
            "/task-graphs/GRAPH-1/runnable"
        )

        assert response.status_code == 200

        assert response.json() == {
            "graph_id": "GRAPH-1",
            "runnable": ["TASK-1002"],
        }

        assert captured[
            "task_states"
        ] == {
            "TASK-1001": "approved",
            "TASK-1002": "blocked",
        }

    finally:
        app_module.TASKS.clear()
        app_module.TASKS.update(
            old_tasks
        )


def test_graph_runnable_unknown_graph_returns_404(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda _graph_id: None,
    )

    response = client.get(
        "/task-graphs/GRAPH-404/runnable"
    )

    assert response.status_code == 404
