from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app as api_module
from factory import project_creator
from factory.database import (
    create_project,
    get_project,
    init_database,
    list_projects,
)


client = TestClient(api_module.app)


def test_create_new_git_project_builds_initial_repo_files(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[list[str], Path]] = []

    def fake_run_git(args, *, cwd):
        calls.append((list(args), Path(cwd)))

    monkeypatch.setattr(
        project_creator,
        "_run_git",
        fake_run_git,
    )
    monkeypatch.setattr(
        project_creator.subprocess,
        "run",
        lambda *a, **k: type(
            "R",
            (),
            {
                "returncode": 0,
                "stdout": "A README.md\n",
                "stderr": "",
            },
        )(),
    )

    created = Path(
        project_creator.create_new_git_project(
            str(tmp_path),
            "ornek-proje",
        )
    )

    assert created == tmp_path / "ornek-proje"
    assert (created / "README.md").is_file()
    assert (created / ".gitignore").is_file()
    assert not (tmp_path / ".git").exists()

    init_calls = [cwd for args, cwd in calls if args == ["init"]]
    assert init_calls == [created]
    assert any(args == ["branch", "-M", "main"] for args, _ in calls)
    assert any(args == ["add", "."] for args, _ in calls)
    assert any(
        args == ["commit", "-m", "Initial commit"] for args, _ in calls
    )


def test_create_new_project_uses_child_folder_not_parent(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        project_creator,
        "_run_git",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        project_creator.subprocess,
        "run",
        lambda *a, **k: type(
            "R",
            (),
            {"returncode": 0, "stdout": "", "stderr": ""},
        )(),
    )

    created = Path(
        project_creator.create_new_git_project(
            str(tmp_path),
            "Child App",
            init_git=True,
            create_readme=False,
            create_gitignore=False,
        )
    )

    assert created == tmp_path / "Child-App"
    assert created.is_dir()
    assert not (tmp_path / ".git").exists()
    assert not (created / "README.md").exists()


def test_create_new_git_project_refuses_existing_target(
    tmp_path,
):
    (tmp_path / "mevcut").mkdir()

    with pytest.raises(FileExistsError):
        project_creator.create_new_git_project(
            str(tmp_path),
            "mevcut",
        )


def test_project_name_slug_supported_names():
    assert project_creator.project_name_slug("My Project") == "My-Project"
    assert project_creator.project_name_slug("my.project") == "my.project"
    assert (
        project_creator.project_name_slug("Türkçe Proje") == "Türkçe-Proje"
    )


@pytest.mark.parametrize(
    "name",
    [
        "",
        "..",
        ".",
        "bad/name",
        "bad:name",
        "///",
        "CON",
        "trailing.",
        "-",
    ],
)
def test_validate_project_name_rejects_unsafe_names(name):
    with pytest.raises(ValueError):
        project_creator.project_name_slug(name)


def test_init_git_in_existing_folder_preserves_source_bytes(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "existing-app"
    project.mkdir()
    (project / "app.py").write_bytes(b"print('hello')\n")
    (project / "README.md").write_bytes(b"# keep\n")
    sub = project / "subdir"
    sub.mkdir()
    (sub / "file.txt").write_bytes(b"payload-bytes\n")

    before = {
        "app.py": (project / "app.py").read_bytes(),
        "README.md": (project / "README.md").read_bytes(),
        "subdir/file.txt": (sub / "file.txt").read_bytes(),
    }

    calls: list[tuple[list[str], Path]] = []

    def fake_run_git(args, *, cwd):
        calls.append((list(args), Path(cwd)))

    monkeypatch.setattr(
        project_creator,
        "_run_git",
        fake_run_git,
    )

    result = project_creator.init_git_in_existing_folder(str(project))
    assert Path(result) == project.resolve()
    assert ["init"] in [args for args, _ in calls]
    assert all(cwd == project for _, cwd in calls)
    assert not (tmp_path / "existing-app-child").exists()
    assert list(project.iterdir())  # still the same root

    assert (project / "app.py").read_bytes() == before["app.py"]
    assert (project / "README.md").read_bytes() == before["README.md"]
    assert (sub / "file.txt").read_bytes() == before["subdir/file.txt"]


def test_inspect_project_folder_detects_git(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "package.json").write_text("{}", encoding="utf-8")

    info = project_creator.inspect_project_folder(str(project))
    assert info["has_git"] is True
    assert info["suggested_name"] == "app"
    assert "Node.js / npm" in info["characteristics"]


def test_canonical_path_key_collapses_case_and_trailing_sep(tmp_path):
    project = tmp_path / "CaseProj"
    project.mkdir()
    stored = project_creator.normalize_project_path_for_storage(str(project))
    variant = stored + ("\\" if "\\" in stored else "/")
    if os_name_is_windows():
        flipped = flip_drive_case(variant)
        assert project_creator.project_paths_equivalent(stored, flipped)
    assert project_creator.project_paths_equivalent(stored, variant)


def os_name_is_windows() -> bool:
    return project_creator.os.name == "nt"


def flip_drive_case(path: str) -> str:
    if len(path) >= 2 and path[1] == ":":
        drive = path[0]
        flipped = drive.lower() if drive.isupper() else drive.upper()
        return flipped + path[1:]
    return path.swapcase()


def test_remove_newly_created_project_dir_only_child(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "child"
    child.mkdir()
    (child / "x.txt").write_text("x", encoding="utf-8")

    project_creator.remove_newly_created_project_dir(
        child,
        expected_parent=parent,
    )
    assert not child.exists()
    assert parent.exists()

    with pytest.raises(RuntimeError):
        project_creator.remove_newly_created_project_dir(
            parent,
            expected_parent=parent,
        )


def test_find_project_by_canonical_path_case_and_sep(tmp_path):
    project = tmp_path / "Dup"
    project.mkdir()
    stored = project_creator.normalize_project_path_for_storage(str(project))
    rows = [{"project_id": "P1", "path": stored}]
    probe = stored + ("\\" if "\\" in stored else "/")
    if os_name_is_windows():
        probe = flip_drive_case(probe)
    found = project_creator.find_project_by_canonical_path(probe, rows)
    assert found is not None
    assert found["project_id"] == "P1"


def _patch_project_db(monkeypatch, db_path: Path):
    init_database(db_path)

    monkeypatch.setattr(
        api_module,
        "db_list_projects",
        lambda: list_projects(db_path=db_path),
    )
    monkeypatch.setattr(
        api_module,
        "db_get_project",
        lambda pid: get_project(pid, db_path=db_path),
    )
    monkeypatch.setattr(
        api_module,
        "db_create_project",
        lambda project_id, name, path: create_project(
            project_id,
            name=name,
            path=path,
            db_path=db_path,
        ),
    )


def test_api_create_new_rolls_back_on_db_failure(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    _patch_project_db(monkeypatch, db_path)

    monkeypatch.setattr(
        project_creator,
        "_run_git",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        project_creator.subprocess,
        "run",
        lambda *a, **k: type(
            "R",
            (),
            {"returncode": 0, "stdout": "", "stderr": ""},
        )(),
    )

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(api_module, "db_create_project", boom)

    parent = tmp_path / "parents"
    parent.mkdir()
    response = client.post(
        "/projects/create-new",
        json={
            "name": "orphan-me",
            "parent_path": str(parent),
            "init_git": True,
            "create_readme": True,
            "create_gitignore": False,
        },
    )

    assert response.status_code == 500
    assert "geri alindi" in response.json()["detail"].casefold() or (
        "temizleme" in response.json()["detail"].casefold()
    )
    assert not (parent / "orphan-me").exists()


def test_api_create_new_reports_incomplete_cleanup(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    _patch_project_db(monkeypatch, db_path)

    monkeypatch.setattr(
        project_creator,
        "_run_git",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        project_creator.subprocess,
        "run",
        lambda *a, **k: type(
            "R",
            (),
            {"returncode": 0, "stdout": "", "stderr": ""},
        )(),
    )
    monkeypatch.setattr(
        api_module,
        "db_create_project",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    monkeypatch.setattr(
        api_module,
        "remove_newly_created_project_dir",
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("locked")
        ),
    )

    parent = tmp_path / "parents"
    parent.mkdir()
    response = client.post(
        "/projects/create-new",
        json={
            "name": "stuck-folder",
            "parent_path": str(parent),
            "init_git": False,
            "create_readme": False,
            "create_gitignore": False,
        },
    )

    assert response.status_code == 500
    detail = response.json()["detail"].casefold()
    assert "temizleme" in detail
    assert "stuck-folder" in detail or "stuck-folder" in str(
        parent / "stuck-folder"
    ).casefold()
    # Folder still present because cleanup was forced to fail.
    assert (parent / "stuck-folder").exists()


def test_api_add_existing_git_project(tmp_path, monkeypatch):
    db_path = tmp_path / "factory.db"
    _patch_project_db(monkeypatch, db_path)

    project = tmp_path / "ready"
    project.mkdir()
    (project / ".git").mkdir()

    response = client.post(
        "/projects",
        json={
            "name": "ready",
            "path": str(project),
            "init_git": False,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "ready"
    assert Path(body["path"]) == project.resolve()


def test_api_add_existing_non_git_rejected_without_init(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    _patch_project_db(monkeypatch, db_path)

    project = tmp_path / "nogit"
    project.mkdir()
    (project / "app.py").write_text("x", encoding="utf-8")

    response = client.post(
        "/projects",
        json={
            "name": "nogit",
            "path": str(project),
            "init_git": False,
        },
    )
    assert response.status_code == 400
    assert (project / "app.py").read_text(encoding="utf-8") == "x"
    assert not (project / ".git").exists()


def test_api_git_olustur_ve_ekle_preserves_sources(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    _patch_project_db(monkeypatch, db_path)

    project = tmp_path / "srcproj"
    project.mkdir()
    (project / "app.py").write_bytes(b"AAA")
    (project / "README.md").write_bytes(b"BBB")
    nested = project / "subdir"
    nested.mkdir()
    (nested / "file.txt").write_bytes(b"CCC")

    monkeypatch.setattr(
        project_creator,
        "_run_git",
        lambda *a, **k: None,
    )

    response = client.post(
        "/projects",
        json={
            "name": "srcproj",
            "path": str(project),
            "init_git": True,
        },
    )
    assert response.status_code == 201
    assert (project / "app.py").read_bytes() == b"AAA"
    assert (project / "README.md").read_bytes() == b"BBB"
    assert (nested / "file.txt").read_bytes() == b"CCC"
    # No accidental child created beside the selected root.
    assert not (tmp_path / "srcproj-child").exists()


def test_api_db_failure_after_git_init_keeps_tree(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    _patch_project_db(monkeypatch, db_path)

    project = tmp_path / "alive"
    project.mkdir()
    marker = project / "keep.txt"
    marker.write_text("safe", encoding="utf-8")

    monkeypatch.setattr(
        project_creator,
        "_run_git",
        lambda *a, **k: None,
    )

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(api_module, "db_create_project", boom)

    response = client.post(
        "/projects",
        json={
            "name": "alive",
            "path": str(project),
            "init_git": True,
        },
    )
    assert response.status_code == 500
    detail = response.json()["detail"].casefold()
    assert "git" in detail
    assert "projeyi ekle" in detail or "factory" in detail
    assert project.is_dir()
    assert marker.read_text(encoding="utf-8") == "safe"


def test_api_retry_add_after_git_exists(tmp_path, monkeypatch):
    db_path = tmp_path / "factory.db"
    _patch_project_db(monkeypatch, db_path)

    project = tmp_path / "retry"
    project.mkdir()
    (project / "keep.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(
        project_creator,
        "_run_git",
        lambda *a, **k: None,
    )

    # Simulate prior partial success: .git already present.
    (project / ".git").mkdir()

    response = client.post(
        "/projects",
        json={
            "name": "retry",
            "path": str(project),
            "init_git": False,
        },
    )
    assert response.status_code == 201
    assert (project / "keep.txt").read_text(encoding="utf-8") == "ok"


def test_api_duplicate_exact_and_trailing_sep(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    _patch_project_db(monkeypatch, db_path)

    project = tmp_path / "once"
    project.mkdir()
    (project / ".git").mkdir()
    stored = project_creator.normalize_project_path_for_storage(
        str(project)
    )
    create_project(
        "PROJECT-ONCE",
        name="once",
        path=stored,
        db_path=db_path,
    )

    exact = client.post(
        "/projects",
        json={"name": "once2", "path": stored, "init_git": False},
    )
    assert exact.status_code == 409

    sep = "\\" if "\\" in stored else "/"
    trailing = client.post(
        "/projects",
        json={
            "name": "once3",
            "path": stored + sep,
            "init_git": False,
        },
    )
    assert trailing.status_code == 409

    if os_name_is_windows():
        cased = client.post(
            "/projects",
            json={
                "name": "once4",
                "path": flip_drive_case(stored),
                "init_git": False,
            },
        )
        assert cased.status_code == 409
