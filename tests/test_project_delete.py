"""Safe Factory project registration delete."""

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import api.app as api_module
from factory.database import (
    create_project,
    delete_project,
    get_project,
    get_task,
    init_database,
    list_projects,
    list_tasks_for_project,
    project_has_active_tasks,
    upsert_task,
)


client = TestClient(api_module.app)


def _seed_project(
    db_path: Path,
    project_id: str,
    *,
    name: str,
    path: str,
):
    init_database(db_path)
    return create_project(
        project_id,
        name=name,
        path=path,
        db_path=db_path,
    )


def test_delete_project_removes_registration_only(
    tmp_path,
    monkeypatch,
):
    project_dir = tmp_path / "eduben"
    project_dir.mkdir()
    marker = project_dir / "README.md"
    marker.write_text("keep me", encoding="utf-8")
    git_dir = project_dir / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(
        "ref: refs/heads/main\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "factory.db"
    project_id = "PROJECT-DEL-1"
    _seed_project(
        db_path,
        project_id,
        name="Eduben",
        path=str(project_dir),
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda pid: get_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_delete_project",
        lambda pid: delete_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_project_has_active_tasks",
        lambda pid: project_has_active_tasks(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "TASKS",
        {},
    )

    response = client.delete(
        f"/projects/{project_id}"
    )

    assert response.status_code == 200
    assert response.json() == {
        "project_id": project_id,
        "deleted": True,
    }
    assert (
        get_project(
            project_id,
            db_path=db_path,
        )
        is None
    )
    assert project_dir.is_dir()
    assert marker.is_file()
    assert marker.read_text(
        encoding="utf-8"
    ) == "keep me"
    assert git_dir.is_dir()
    assert (git_dir / "HEAD").is_file()


def test_deleted_project_absent_from_list(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    project_dir = tmp_path / "proj-a"
    project_dir.mkdir()

    _seed_project(
        db_path,
        "PROJECT-A",
        name="Alpha",
        path=str(project_dir),
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda pid: get_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_delete_project",
        lambda pid: delete_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_project_has_active_tasks",
        lambda pid: False,
    )
    monkeypatch.setattr(
        api_module,
        "db_list_projects",
        lambda: list_projects(
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "TASKS",
        {},
    )

    delete_response = client.delete(
        "/projects/PROJECT-A"
    )
    assert delete_response.status_code == 200

    listed = client.get("/projects")
    assert listed.status_code == 200
    ids = [
        row["project_id"]
        for row in listed.json()
    ]
    assert "PROJECT-A" not in ids


def test_unknown_project_delete_returns_404(
    monkeypatch,
):
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda project_id: None,
    )
    monkeypatch.setattr(
        api_module,
        "TASKS",
        {},
    )

    response = client.delete(
        "/projects/PROJECT-MISSING"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Project not found"
    )


def test_active_task_blocks_project_delete(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    project_dir = tmp_path / "busy"
    project_dir.mkdir()
    project_id = "PROJECT-BUSY"

    _seed_project(
        db_path,
        project_id,
        name="Busy",
        path=str(project_dir),
    )

    upsert_task(
        "TASK-ACTIVE",
        prompt="do work",
        status="created",
        max_attempts=2,
        project_id=project_id,
        state="running",
        db_path=db_path,
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda pid: get_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_delete_project",
        lambda pid: delete_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_project_has_active_tasks",
        lambda pid: project_has_active_tasks(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "TASKS",
        {
            "TASK-ACTIVE": SimpleNamespace(
                task_id="TASK-ACTIVE",
                project_id=project_id,
                state="running",
            ),
        },
    )

    response = client.delete(
        f"/projects/{project_id}"
    )

    assert response.status_code == 409
    assert "aktif" in response.json()[
        "detail"
    ].lower()
    assert (
        get_project(
            project_id,
            db_path=db_path,
        )
        is not None
    )
    assert project_dir.is_dir()


def test_completed_task_history_preserved(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    project_dir = tmp_path / "done-proj"
    project_dir.mkdir()
    project_id = "PROJECT-DONE"

    _seed_project(
        db_path,
        project_id,
        name="Done",
        path=str(project_dir),
    )

    upsert_task(
        "TASK-DONE",
        prompt="finished work",
        status="approved",
        max_attempts=2,
        project_id=project_id,
        state="approved",
        db_path=db_path,
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda pid: get_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_delete_project",
        lambda pid: delete_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_project_has_active_tasks",
        lambda pid: project_has_active_tasks(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "TASKS",
        {},
    )

    response = client.delete(
        f"/projects/{project_id}"
    )

    assert response.status_code == 200

    task = get_task(
        "TASK-DONE",
        db_path=db_path,
    )
    assert task is not None
    assert task["project_id"] == project_id
    assert task["state"] == "approved"

    remaining = list_tasks_for_project(
        project_id,
        db_path=db_path,
    )
    assert len(remaining) == 1


def test_delete_project_a_leaves_project_b(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    path_a = tmp_path / "proj-a"
    path_b = tmp_path / "proj-b"
    path_a.mkdir()
    path_b.mkdir()
    (path_b / "keep.txt").write_text(
        "b",
        encoding="utf-8",
    )

    _seed_project(
        db_path,
        "PROJECT-A",
        name="A",
        path=str(path_a),
    )
    _seed_project(
        db_path,
        "PROJECT-B",
        name="B",
        path=str(path_b),
    )

    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda pid: get_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_delete_project",
        lambda pid: delete_project(
            pid,
            db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "db_project_has_active_tasks",
        lambda pid: False,
    )
    monkeypatch.setattr(
        api_module,
        "TASKS",
        {},
    )

    response = client.delete(
        "/projects/PROJECT-A"
    )
    assert response.status_code == 200

    assert (
        get_project(
            "PROJECT-A",
            db_path=db_path,
        )
        is None
    )
    project_b = get_project(
        "PROJECT-B",
        db_path=db_path,
    )
    assert project_b is not None
    assert project_b["name"] == "B"
    assert path_b.is_dir()
    assert (path_b / "keep.txt").is_file()


def test_db_delete_project_never_touches_path(
    tmp_path,
):
    project_dir = tmp_path / "external"
    project_dir.mkdir()
    nested = project_dir / "src" / "main.py"
    nested.parent.mkdir(parents=True)
    nested.write_text(
        "print('hi')\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "factory.db"
    init_database(db_path)
    create_project(
        "PROJECT-SAFE",
        name="Safe",
        path=str(project_dir),
        db_path=db_path,
    )

    assert delete_project(
        "PROJECT-SAFE",
        db_path=db_path,
    ) is True

    assert project_dir.is_dir()
    assert nested.is_file()
    assert nested.read_text(
        encoding="utf-8"
    ) == "print('hi')\n"
