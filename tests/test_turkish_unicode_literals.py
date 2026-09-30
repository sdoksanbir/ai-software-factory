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

# Deliberate literal backslash-u input — must NOT be globally decoded.
LITERAL_BACKSLASH_U = "\\u0131"

REPO_ROOT = Path(__file__).resolve().parents[1]

APP_PY = REPO_ROOT / "api" / "app.py"
APP_TSX = REPO_ROOT / "frontend" / "src" / "App.tsx"
PIPELINE_PY = REPO_ROOT / "factory" / "pipeline.py"

# Visible escape forms that must not appear in user-facing prose source.
FORBIDDEN_ESCAPE_FORMS = (
    "\\u0131",
    "\\u00f6",
    "\\u015f",
    "\\u011f",
    "\\u00e7",
    "\\u00fc",
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
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")

    assert "Görev bulunamadı." in text
    assert "Proje açılamadı:" in text
    assert "Ollama servisine ulaşılamıyor." in text
    assert "Ollama geçersiz JSON döndürdü." in text
    assert "Ollama yanıtı bulunamadı." in text
    assert "Model adı zorunludur." in text
    assert "Proje bulunamadı." in text
    assert "Bu projeye ait aktif görevler " in text
    assert "bulunduğu için proje " in text
    assert "kaldırılamıyor." in text

    # Symptom-1 style corruption must stay gone.
    assert "G?rev bulunamad?" not in text
    assert "a??lamad?" not in text
    assert "ula??lam?yor" not in text

    # Source must use real UTF-8, not visible \\uXXXX prose.
    for form in FORBIDDEN_ESCAPE_FORMS:
        assert form not in text, form


def test_frontend_app_tsx_source_has_utf8_turkish():
    raw = APP_TSX.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")

    assert 'queued: "Sırada"' in text
    assert 'running: "İşleniyor"' in text
    assert 'failed: "Başarısız"' in text
    assert '"Kullanıcı Görevi"' in text
    assert '"İnsan Onayı"' in text
    assert "görevler yüklenemedi." in text or "Görevler yüklenemedi." in text

    for form in FORBIDDEN_ESCAPE_FORMS:
        assert form not in text, form


def test_pipeline_source_has_utf8_labels():
    text = PIPELINE_PY.read_text(encoding="utf-8")
    assert '"Görev Alındı"' in text
    assert '"İnsan Onayı"' in text
    assert '"Eylem Hazırlığı"' in text
    assert '"Yerel Çalıştırma"' in text
    assert '"Sonuç"' in text
    assert '"Tamamlandı"' in text

    for form in FORBIDDEN_ESCAPE_FORMS:
        assert form not in text, form


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


def test_literal_backslash_u_input_not_globally_decoded(
    client,
):
    """User input that looks like \\u0131 must stay literal."""
    test_client, project = client

    created = test_client.post(
        "/tasks",
        json={
            "prompt": LITERAL_BACKSLASH_U,
            "max_attempts": 1,
            "project_id": project["project_id"],
        },
    )

    assert created.status_code == 202, created.text
    payload = created.json()
    assert payload["prompt"] == LITERAL_BACKSLASH_U
    assert payload["prompt"] == "\\u0131"
    assert payload["prompt"] != "ı"
    assert "\\" in payload["prompt"]
    assert payload["prompt"].startswith("\\u")

    task_id = payload["task_id"]
    fetched = test_client.get(f"/tasks/{task_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["prompt"] == "\\u0131"
    assert body["prompt"] != "ı"
