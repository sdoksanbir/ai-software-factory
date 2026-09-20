from fastapi.testclient import TestClient

import api.app as app_module


client = TestClient(
    app_module.app
)


def test_add_graph_node_api(
    monkeypatch,
):
    graph_id = "GRAPH-1"

    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda _graph_id: {
            "graph_id": graph_id,
            "project_id": None,
            "root_task_id": None,
            "status": "pending",
            "created_at": None,
            "updated_at": None,
            "nodes": [],
        },
    )

    captured = {}

    def fake_add_node(
        graph_id,
        task_id,
        *,
        parent_task_id=None,
    ):
        captured["graph_id"] = graph_id
        captured["task_id"] = task_id
        captured[
            "parent_task_id"
        ] = parent_task_id

    monkeypatch.setattr(
        app_module,
        "db_add_task_graph_node",
        fake_add_node,
    )

    response = client.post(
        "/task-graphs/GRAPH-1/nodes",
        json={
            "task_id": "TASK-1001",
            "parent_task_id": None,
        },
    )

    assert response.status_code == 200

    assert captured == {
        "graph_id": "GRAPH-1",
        "task_id": "TASK-1001",
        "parent_task_id": None,
    }


def test_add_graph_dependency_api(
    monkeypatch,
):
    graph_id = "GRAPH-1"

    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda _graph_id: {
            "graph_id": graph_id,
            "project_id": None,
            "root_task_id": None,
            "status": "pending",
            "created_at": None,
            "updated_at": None,
            "nodes": [],
        },
    )

    captured = {}

    def fake_add_dependency(
        graph_id,
        task_id,
        depends_on_task_id,
    ):
        captured["graph_id"] = graph_id
        captured["task_id"] = task_id
        captured[
            "depends_on_task_id"
        ] = depends_on_task_id

    monkeypatch.setattr(
        app_module,
        "db_add_task_dependency",
        fake_add_dependency,
    )

    response = client.post(
        "/task-graphs/GRAPH-1/dependencies",
        json={
            "task_id": "TASK-1002",
            "depends_on_task_id": "TASK-1001",
        },
    )

    assert response.status_code == 200

    assert captured == {
        "graph_id": "GRAPH-1",
        "task_id": "TASK-1002",
        "depends_on_task_id": "TASK-1001",
    }


def test_graph_node_unknown_graph_returns_404(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda _graph_id: None,
    )

    response = client.post(
        "/task-graphs/GRAPH-404/nodes",
        json={
            "task_id": "TASK-1001",
        },
    )

    assert response.status_code == 404


def test_graph_dependency_cycle_returns_409(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda _graph_id: {
            "graph_id": "GRAPH-1",
            "project_id": None,
            "root_task_id": None,
            "status": "pending",
            "created_at": None,
            "updated_at": None,
            "nodes": [],
        },
    )

    def fail_dependency(
        *_args,
        **_kwargs,
    ):
        raise ValueError(
            "Dependency cycle detected"
        )

    monkeypatch.setattr(
        app_module,
        "db_add_task_dependency",
        fail_dependency,
    )

    response = client.post(
        "/task-graphs/GRAPH-1/dependencies",
        json={
            "task_id": "TASK-1001",
            "depends_on_task_id": "TASK-1002",
        },
    )

    assert response.status_code == 409

    assert (
        "Dependency cycle"
        in response.json()["detail"]
    )
