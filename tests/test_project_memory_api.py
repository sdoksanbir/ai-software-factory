from fastapi.testclient import TestClient

import api.app as api_module


client = TestClient(
    api_module.app
)


def _project(
    project_id="PROJECT-API-1",
):
    return {
        "project_id": project_id,
        "name": "API Project",
        "path": r"C:\fake\project",
        "created_at": None,
        "updated_at": None,
    }


def _memory(
    memory_id="MEM-1",
    project_id="PROJECT-API-1",
    *,
    status="active",
    kind="decision",
):
    return {
        "memory_id": memory_id,
        "project_id": project_id,
        "kind": kind,
        "title": "SQLite decision",
        "content": "Use SQLite persistence.",
        "source_task_id": "TASK-1",
        "status": status,
        "importance": 70,
        "tags": [
            "sqlite",
            "database",
        ],
        "dedup_key": "abc123",
        "superseded_by_memory_id": None,
        "created_at": None,
        "updated_at": None,
    }


def test_list_project_memories_defaults_to_active(
    monkeypatch,
):
    calls = {}

    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    def fake_list(
        project_id,
        *,
        status,
        kind,
        limit,
    ):
        calls.update(
            {
                "project_id": project_id,
                "status": status,
                "kind": kind,
                "limit": limit,
            }
        )

        return [
            _memory(
                project_id=project_id
            )
        ]

    monkeypatch.setattr(
        api_module,
        "db_list_project_memories",
        fake_list,
    )

    response = client.get(
        "/projects/PROJECT-API-1/memories"
    )

    assert response.status_code == 200

    assert calls == {
        "project_id": "PROJECT-API-1",
        "status": "active",
        "kind": None,
        "limit": 100,
    }

    body = response.json()

    assert len(body) == 1
    assert body[0]["memory_id"] == "MEM-1"


def test_list_project_memories_forwards_filters(
    monkeypatch,
):
    calls = {}

    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    def fake_list(
        project_id,
        *,
        status,
        kind,
        limit,
    ):
        calls.update(
            {
                "project_id": project_id,
                "status": status,
                "kind": kind,
                "limit": limit,
            }
        )

        return []

    monkeypatch.setattr(
        api_module,
        "db_list_project_memories",
        fake_list,
    )

    response = client.get(
        "/projects/PROJECT-API-1/memories"
        "?status=superseded"
        "&kind=decision"
        "&limit=25"
    )

    assert response.status_code == 200

    assert calls == {
        "project_id": "PROJECT-API-1",
        "status": "superseded",
        "kind": "decision",
        "limit": 25,
    }


def test_list_project_memories_unknown_project(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: None,
    )

    response = client.get(
        "/projects/UNKNOWN/memories"
    )

    assert response.status_code == 404


def test_list_project_memories_rejects_invalid_limit(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    response = client.get(
        "/projects/PROJECT-API-1/memories"
        "?limit=501"
    )

    assert response.status_code == 400


def test_get_project_memory(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project_memory",
        lambda memory_id: _memory(
            memory_id=memory_id
        ),
    )

    response = client.get(
        "/projects/PROJECT-API-1/"
        "memories/MEM-22"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["memory_id"] == "MEM-22"
    assert body["project_id"] == "PROJECT-API-1"


def test_get_memory_from_other_project_returns_404(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project_memory",
        lambda memory_id: _memory(
            memory_id=memory_id,
            project_id="PROJECT-OTHER",
        ),
    )

    response = client.get(
        "/projects/PROJECT-API-1/"
        "memories/MEM-SECRET"
    )

    assert response.status_code == 404


def test_invalid_memory_filter_becomes_400(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    def fake_list(
        project_id,
        *,
        status,
        kind,
        limit,
    ):
        raise ValueError(
            "Invalid memory status: broken"
        )

    monkeypatch.setattr(
        api_module,
        "db_list_project_memories",
        fake_list,
    )

    response = client.get(
        "/projects/PROJECT-API-1/memories"
        "?status=broken"
    )

    assert response.status_code == 400
    assert (
        "Invalid memory status"
        in response.json()["detail"]
    )


def test_archive_project_memory_success(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project_memory",
        lambda memory_id: _memory(
            memory_id=memory_id
        ),
    )

    def fake_update(
        memory_id,
        *,
        status,
    ):
        memory = _memory(
            memory_id=memory_id
        )
        memory["status"] = status
        return memory

    monkeypatch.setattr(
        api_module,
        "db_update_project_memory",
        fake_update,
    )

    response = client.post(
        "/projects/PROJECT-API-1/"
        "memories/MEM-1/archive"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["memory_id"] == "MEM-1"
    assert body["status"] == "archived"


def test_archive_memory_from_other_project_returns_404(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project_memory",
        lambda memory_id: _memory(
            memory_id=memory_id,
            project_id="PROJECT-OTHER",
        ),
    )

    response = client.post(
        "/projects/PROJECT-API-1/"
        "memories/MEM-SECRET/archive"
    )

    assert response.status_code == 404


def test_superseded_memory_cannot_be_archived(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project_memory",
        lambda memory_id: _memory(
            memory_id=memory_id,
            status="superseded",
        ),
    )

    response = client.post(
        "/projects/PROJECT-API-1/"
        "memories/MEM-OLD/archive"
    )

    assert response.status_code == 409


def test_supersede_project_memory_success(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    def fake_get_memory(
        memory_id,
    ):
        return _memory(
            memory_id=memory_id
        )

    monkeypatch.setattr(
        api_module,
        "db_get_project_memory",
        fake_get_memory,
    )

    def fake_supersede(
        old_memory_id,
        new_memory_id,
    ):
        old_memory = _memory(
            memory_id=old_memory_id
        )
        old_memory["status"] = "superseded"
        old_memory[
            "superseded_by_memory_id"
        ] = new_memory_id

        replacement = _memory(
            memory_id=new_memory_id
        )

        return {
            "superseded": old_memory,
            "replacement": replacement,
        }

    monkeypatch.setattr(
        api_module,
        "db_supersede_project_memory",
        fake_supersede,
    )

    response = client.post(
        "/projects/PROJECT-API-1/"
        "memories/MEM-OLD/supersede",
        json={
            "replacement_memory_id": (
                "MEM-NEW"
            ),
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["superseded"]["memory_id"]
        == "MEM-OLD"
    )

    assert (
        body["superseded"]["status"]
        == "superseded"
    )

    assert (
        body["superseded"][
            "superseded_by_memory_id"
        ]
        == "MEM-NEW"
    )

    assert (
        body["replacement"]["memory_id"]
        == "MEM-NEW"
    )


def test_cross_project_replacement_returns_404(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    def fake_get_memory(
        memory_id,
    ):
        if memory_id == "MEM-NEW":
            return _memory(
                memory_id=memory_id,
                project_id="PROJECT-OTHER",
            )

        return _memory(
            memory_id=memory_id,
            project_id="PROJECT-API-1",
        )

    monkeypatch.setattr(
        api_module,
        "db_get_project_memory",
        fake_get_memory,
    )

    response = client.post(
        "/projects/PROJECT-API-1/"
        "memories/MEM-OLD/supersede",
        json={
            "replacement_memory_id": (
                "MEM-NEW"
            ),
        },
    )

    assert response.status_code == 404


def test_supersede_domain_conflict_becomes_409(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: _project(
            project_id
        ),
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project_memory",
        lambda memory_id: _memory(
            memory_id=memory_id
        ),
    )

    def fake_supersede(
        old_memory_id,
        new_memory_id,
    ):
        raise ValueError(
            "Only an active memory can "
            "be superseded"
        )

    monkeypatch.setattr(
        api_module,
        "db_supersede_project_memory",
        fake_supersede,
    )

    response = client.post(
        "/projects/PROJECT-API-1/"
        "memories/MEM-OLD/supersede",
        json={
            "replacement_memory_id": (
                "MEM-NEW"
            ),
        },
    )

    assert response.status_code == 409

    assert (
        "Only an active memory"
        in response.json()["detail"]
    )
