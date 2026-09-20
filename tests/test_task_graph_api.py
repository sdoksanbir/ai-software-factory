from fastapi.testclient import TestClient

import api.app as app_module


client = TestClient(
    app_module.app
)


def test_create_task_graph_api(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "db_list_task_graphs",
        lambda: [],
    )

    monkeypatch.setattr(
        app_module.random,
        "randint",
        lambda *_args: 1234,
    )

    captured = {}

    def fake_create(
        graph_id,
        *,
        project_id=None,
        root_task_id=None,
    ):
        captured[
            "graph_id"
        ] = graph_id

        captured[
            "project_id"
        ] = project_id

        captured[
            "root_task_id"
        ] = root_task_id

        return {
            "graph_id": graph_id,
            "project_id": project_id,
            "root_task_id": root_task_id,
            "status": "pending",
            "created_at": None,
            "updated_at": None,
            "nodes": [],
        }

    monkeypatch.setattr(
        app_module,
        "db_create_task_graph",
        fake_create,
    )

    response = client.post(
        "/task-graphs",
        json={
            "project_id": "PROJECT-1",
            "root_task_id": "TASK-1001",
        },
    )

    assert response.status_code == 201

    payload = response.json()

    assert (
        payload["graph_id"]
        == "GRAPH-1234"
    )

    assert (
        payload["project_id"]
        == "PROJECT-1"
    )

    assert (
        payload["root_task_id"]
        == "TASK-1001"
    )

    assert payload["nodes"] == []

    assert captured == {
        "graph_id": "GRAPH-1234",
        "project_id": "PROJECT-1",
        "root_task_id": "TASK-1001",
    }


def test_list_task_graphs_api(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "db_list_task_graphs",
        lambda: [
            {
                "graph_id": "GRAPH-1",
                "project_id": "PROJECT-1",
                "root_task_id": "TASK-1001",
                "status": "pending",
                "created_at": None,
                "updated_at": None,
            }
        ],
    )

    response = client.get(
        "/task-graphs"
    )

    assert response.status_code == 200

    payload = response.json()

    assert len(payload) == 1

    assert (
        payload[0]["graph_id"]
        == "GRAPH-1"
    )

    assert payload[0]["nodes"] == []


def test_get_task_graph_api(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda graph_id: {
            "graph_id": graph_id,
            "project_id": "PROJECT-1",
            "root_task_id": "TASK-1001",
            "status": "pending",
            "created_at": None,
            "updated_at": None,
            "nodes": [
                {
                    "graph_id": graph_id,
                    "task_id": "TASK-1001",
                    "parent_task_id": None,
                    "created_at": None,
                    "depends_on": [],
                }
            ],
        },
    )

    response = client.get(
        "/task-graphs/GRAPH-1"
    )

    assert response.status_code == 200

    payload = response.json()

    assert (
        payload["graph_id"]
        == "GRAPH-1"
    )

    assert (
        payload["nodes"][0]["task_id"]
        == "TASK-1001"
    )


def test_get_unknown_task_graph_returns_404(
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "db_get_task_graph",
        lambda _graph_id: None,
    )

    response = client.get(
        "/task-graphs/GRAPH-404"
    )

    assert response.status_code == 404

    assert (
        response.json()["detail"]
        == "Task graph not found"
    )
