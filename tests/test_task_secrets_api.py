"""API create-task structured secrets tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import api.app as api_module
from factory.database import (
    create_project,
    get_connection,
    get_task,
    init_database,
    upsert_task,
)
from factory.task_secret_store import (
    get_task_secret,
    list_task_secret_names,
    reset_task_secret_store_for_tests,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    reset_task_secret_store_for_tests()
    db_path = tmp_path / "factory.db"
    init_database(db_path)

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    project = create_project(
        "PROJECT-SEC-1",
        name="secret-api-proj",
        path=str(project_dir),
        db_path=db_path,
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda pid: (
            project
            if pid == project["project_id"]
            else None
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_list_projects",
        lambda: [project],
    )
    monkeypatch.setattr(
        api_module,
        "db_upsert_task",
        lambda *args, **kwargs: upsert_task(
            *args,
            **{
                **kwargs,
                "db_path": db_path,
            },
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_append_task_log",
        lambda *_args, **_kwargs: None,
    )

    api_module.TASKS.clear()
    api_module.TASK_LOGS.clear()
    api_module.TASK_CONTEXTS.clear()
    api_module.TASK_DIFFS.clear()

    monkeypatch.setattr(
        api_module,
        "run_task_for_api",
        lambda *_a, **_k: None,
    )

    test_client = TestClient(api_module.app)
    yield test_client, project, db_path

    reset_task_secret_store_for_tests()
    api_module.TASKS.clear()
    api_module.TASK_LOGS.clear()


def test_create_task_accepts_secret_without_echo(
    client,
):
    test_client, project, db_path = client
    secret = "SuperSecret-Create-99"

    response = test_client.post(
        "/tasks",
        json={
            "prompt": (
                "projeye superuser oluştur "
                f"şifre {secret}"
            ),
            "max_attempts": 1,
            "project_id": project["project_id"],
            "secrets": [
                {
                    "name": "user_password",
                    "value": secret,
                }
            ],
        },
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    blob = json.dumps(payload)

    assert secret not in blob
    assert payload["secret_names"] == [
        "user_password"
    ]
    assert (
        "[SECRET:user_password]"
        in payload["prompt"]
    )
    assert secret not in payload["prompt"]

    task_id = payload["task_id"]
    assert (
        get_task_secret(task_id, "user_password")
        == secret
    )
    assert list_task_secret_names(task_id) == [
        "user_password"
    ]

    detail = test_client.get(
        f"/tasks/{task_id}"
    ).json()
    assert secret not in json.dumps(detail)

    listed = test_client.get(
        "/tasks",
        params={
            "project_id": project["project_id"]
        },
    ).json()
    assert secret not in json.dumps(listed)

    row = get_task(task_id, db_path=db_path)
    assert row is not None
    assert secret not in row["prompt"]
    assert (
        "[SECRET:user_password]" in row["prompt"]
    )

    connection = get_connection(db_path)

    try:
        tables = {
            str(item[0])
            for item in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table'"
            ).fetchall()
        }
        assert "task_secrets" not in tables

        task_blob = " ".join(
            str(item)
            for item in connection.execute(
                "SELECT * FROM tasks "
                "WHERE task_id = ?",
                (task_id,),
            ).fetchall()
        )
    finally:
        connection.close()

    assert secret not in task_blob


def test_invalid_secret_rejected(client):
    test_client, project, _db_path = client

    response = test_client.post(
        "/tasks",
        json={
            "prompt": "hello",
            "project_id": project["project_id"],
            "secrets": [
                {
                    "name": "BAD",
                    "value": "x",
                }
            ],
        },
    )

    assert response.status_code == 400
