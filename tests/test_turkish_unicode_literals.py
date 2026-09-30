"""Regression: Turkish UTF-8 literals survive source → API → Python."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app as api_module
from factory.database import (
    create_project,
    init_database,
    upsert_task,
)
from factory.task_secret_store import (
    reset_task_secret_store_for_tests,
)

TURKISH_PROBE = (
    "Türkçe: çğıöşü ÇĞİÖŞÜ — dosyasının çalıştırılması"
)

APP_PY = (
    Path(__file__).resolve().parents[1]
    / "api"
    / "app.py"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    reset_task_secret_store_for_tests()
    db_path = tmp_path / "factory.db"
    init_database(db_path)

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    project = create_project(
        "PROJECT-UNICODE-1",
        name="unicode-api-proj",
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
    yield test_client, project

    reset_task_secret_store_for_tests()
    api_module.TASKS.clear()
    api_module.TASK_LOGS.clear()


def test_app_py_source_has_utf8_turkish_literals():
    raw = APP_PY.read_bytes()
    text = raw.decode("utf-8")

    assert "Görev bulunamadı." in text
    assert "Proje açılamadı:" in text
    assert "Ollama servisine ulaşılamıyor." in text
    assert "Ollama geçersiz JSON döndürdü." in text
    assert "Ollama yanıtı bulunamadı." in text
    assert "Model adı zorunludur." in text

    # Symptom-1 style corruption must stay gone.
    assert "G?rev bulunamad?" not in text
    assert "a??lamad?" not in text
    assert "ula??lam?yor" not in text


def test_pipeline_404_detail_preserves_turkish(
    client,
):
    test_client, _project = client

    response = test_client.get(
        "/tasks/TASK-MISSING/pipeline"
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail == "Görev bulunamadı."
    assert "?" not in detail
    assert "ö" in detail
    assert "ı" in detail


def test_create_and_get_task_preserves_turkish_prompt(
    client,
):
    test_client, project = client

    created = test_client.post(
        "/tasks",
        json={
            "prompt": TURKISH_PROBE,
            "max_attempts": 1,
            "project_id": project["project_id"],
        },
    )

    assert created.status_code == 202, created.text
    payload = created.json()
    assert payload["prompt"] == TURKISH_PROBE

    task_id = payload["task_id"]
    fetched = test_client.get(f"/tasks/{task_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["prompt"] == TURKISH_PROBE

    # JSON wire → Python string must be exact Unicode.
    assert body["prompt"] == (
        "Türkçe: çğıöşü ÇĞİÖŞÜ — dosyasının çalıştırılması"
    )
