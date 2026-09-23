from pathlib import Path

import pytest

from factory import project_creator


def test_create_new_git_project_builds_initial_repo_files(
    tmp_path,
    monkeypatch,
):
    calls: list[list[str]] = []

    def fake_run_git(args, *, cwd):
        calls.append(list(args))

    monkeypatch.setattr(
        project_creator,
        "_run_git",
        fake_run_git,
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
    assert ["init"] in calls
    assert ["branch", "-M", "main"] in calls
    assert ["add", "."] in calls
    assert ["commit", "-m", "Initial commit"] in calls


def test_create_new_git_project_refuses_existing_target(
    tmp_path,
):
    (tmp_path / "mevcut").mkdir()

    with pytest.raises(FileExistsError):
        project_creator.create_new_git_project(
            str(tmp_path),
            "mevcut",
        )


@pytest.mark.parametrize(
    "name",
    [
        "",
        "..",
        "bad/name",
        "bad:name",
        "CON",
        "trailing.",
    ],
)
def test_validate_project_name_rejects_unsafe_names(name):
    with pytest.raises(ValueError):
        project_creator.validate_project_name(name)
