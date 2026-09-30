import subprocess
from pathlib import Path

import pytest

from factory.tools.git_ops import GitWorktreeManager
from factory.tools.patch import PatchTool, PatchToolError

from factory.schemas import MultiFilePatch


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink not permitted: {exc}")


def _patch_payload(files):
    return MultiFilePatch.model_validate(
        {
            "files": files,
            "explanation": "test",
        }
    )


def test_delete_one_existing_file(tmp_path):
    target = tmp_path / "old.py"
    target.write_text("OLD\n", encoding="utf-8")

    changed = PatchTool.apply_multi_file_patch(
        str(tmp_path),
        _patch_payload(
            [
                {
                    "path": "old.py",
                    "operation": "delete",
                }
            ]
        ),
    )

    assert not target.exists()
    assert any(
        Path(item).name == "old.py"
        for item in changed
    )


def test_delete_multiple_existing_files(tmp_path):
    (tmp_path / "a.py").write_text("A\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("B\n", encoding="utf-8")

    PatchTool.apply_multi_file_patch(
        str(tmp_path),
        _patch_payload(
            [
                {
                    "path": "a.py",
                    "operation": "delete",
                },
                {
                    "path": "b.py",
                    "operation": "delete",
                },
            ]
        ),
    )

    assert not (tmp_path / "a.py").exists()
    assert not (tmp_path / "b.py").exists()


def test_delete_and_modify_same_patch(tmp_path):
    (tmp_path / "old.py").write_text(
        "OLD\n",
        encoding="utf-8",
    )
    settings = tmp_path / "settings.py"
    settings.write_text(
        "APPS = ['users']\n",
        encoding="utf-8",
    )

    PatchTool.apply_multi_file_patch(
        str(tmp_path),
        _patch_payload(
            [
                {
                    "path": "old.py",
                    "operation": "delete",
                },
                {
                    "path": "settings.py",
                    "operation": "write",
                    "content": "APPS = []\n",
                },
            ]
        ),
    )

    assert not (tmp_path / "old.py").exists()
    assert settings.read_text(
        encoding="utf-8"
    ) == "APPS = []\n"


def test_absolute_delete_path_rejected(tmp_path):
    absolute = str((tmp_path / "x.py").resolve())

    with pytest.raises(
        PatchToolError,
        match="Absolute path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": absolute,
                        "operation": "delete",
                    }
                ]
            ),
        )


def test_traversal_delete_rejected(tmp_path):
    outside = tmp_path.parent / "escape.py"
    outside.write_text("NO\n", encoding="utf-8")

    with pytest.raises(PatchToolError):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "../escape.py",
                        "operation": "delete",
                    }
                ]
            ),
        )

    assert outside.exists()


def test_git_config_delete_rejected(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    config = git_dir / "config"
    config.write_text("x\n", encoding="utf-8")

    with pytest.raises(
        PatchToolError,
        match=r"\.git path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": ".git/config",
                        "operation": "delete",
                    }
                ]
            ),
        )

    assert config.exists()


def test_git_objects_delete_rejected(tmp_path):
    target = (
        tmp_path
        / ".git"
        / "objects"
        / "ab"
        / "cd"
    )
    target.parent.mkdir(parents=True)
    target.write_text("blob\n", encoding="utf-8")

    with pytest.raises(
        PatchToolError,
        match=r"\.git path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": ".git/objects/ab/cd",
                        "operation": "delete",
                    }
                ]
            ),
        )


def test_project_root_delete_rejected(tmp_path):
    with pytest.raises(
        PatchToolError,
        match="Project root path rejected|Empty path",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": ".",
                        "operation": "delete",
                    }
                ]
            ),
        )


def test_directory_delete_rejected(tmp_path):
    folder = tmp_path / "users"
    folder.mkdir()
    (folder / "apps.py").write_text(
        "x\n",
        encoding="utf-8",
    )

    with pytest.raises(
        PatchToolError,
        match="Directory deletion is unsupported",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "users",
                        "operation": "delete",
                    }
                ]
            ),
        )


def test_missing_delete_target_rejected(tmp_path):
    with pytest.raises(
        PatchToolError,
        match="Delete target does not exist",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "missing.py",
                        "operation": "delete",
                    }
                ]
            ),
        )


def test_symlink_file_escape_delete_rejected(tmp_path):
    outside = tmp_path.parent / "outside_secret.py"
    outside.write_text("SECRET\n", encoding="utf-8")
    link = tmp_path / "link.py"
    _symlink(link, outside)

    with pytest.raises(
        PatchToolError,
        match="Symlink path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "link.py",
                        "operation": "delete",
                    }
                ]
            ),
        )

    assert outside.exists()


def test_symlinked_parent_escape_write_rejected(tmp_path):
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    _symlink(link, outside)

    with pytest.raises(
        PatchToolError,
        match="Symlink path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "link/file.py",
                        "operation": "write",
                        "content": "NO\n",
                    }
                ]
            ),
        )

    assert not (outside / "file.py").exists()


def test_symlinked_parent_escape_delete_rejected(tmp_path):
    outside = tmp_path.parent / "outside_dir2"
    outside.mkdir(exist_ok=True)
    victim = outside / "victim.py"
    victim.write_text("KEEP\n", encoding="utf-8")
    link = tmp_path / "link2"
    _symlink(link, outside)

    with pytest.raises(
        PatchToolError,
        match="Symlink path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "link2/victim.py",
                        "operation": "delete",
                    }
                ]
            ),
        )

    assert victim.exists()


def test_in_root_file_symlink_write_rejected(tmp_path):
    real = tmp_path / "real.py"
    real.write_text("REAL\n", encoding="utf-8")
    alias = tmp_path / "alias.py"
    _symlink(alias, real)

    with pytest.raises(
        PatchToolError,
        match="Symlink path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "alias.py",
                        "operation": "write",
                        "content": "HIJACK\n",
                    }
                ]
            ),
        )

    assert real.read_text(encoding="utf-8") == "REAL\n"


def test_in_root_file_symlink_delete_rejected(tmp_path):
    real = tmp_path / "config" / "settings.py"
    real.parent.mkdir()
    real.write_text("SETTINGS\n", encoding="utf-8")
    alias = tmp_path / "alias.py"
    _symlink(alias, real)

    with pytest.raises(
        PatchToolError,
        match="Symlink path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "alias.py",
                        "operation": "delete",
                    }
                ]
            ),
        )

    assert real.exists()


def test_in_root_dir_symlink_write_rejected(tmp_path):
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    alias_dir = tmp_path / "alias_dir"
    _symlink(alias_dir, real_dir)

    with pytest.raises(
        PatchToolError,
        match="Symlink path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "alias_dir/file.py",
                        "operation": "write",
                        "content": "NO\n",
                    }
                ]
            ),
        )


def test_in_root_dir_symlink_delete_rejected(tmp_path):
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    victim = real_dir / "file.py"
    victim.write_text("KEEP\n", encoding="utf-8")
    alias_dir = tmp_path / "alias_dir"
    _symlink(alias_dir, real_dir)

    with pytest.raises(
        PatchToolError,
        match="Symlink path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "alias_dir/file.py",
                        "operation": "delete",
                    }
                ]
            ),
        )

    assert victim.exists()


def test_nested_git_config_delete_rejected(tmp_path):
    target = (
        tmp_path
        / "vendor"
        / "pkg"
        / ".git"
        / "config"
    )
    target.parent.mkdir(parents=True)
    target.write_text("x\n", encoding="utf-8")

    with pytest.raises(
        PatchToolError,
        match=r"\.git path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "vendor/pkg/.git/config",
                        "operation": "delete",
                    }
                ]
            ),
        )


def test_mixed_case_git_path_rejected(tmp_path):
    with pytest.raises(
        PatchToolError,
        match=r"\.git path rejected",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "folder/.GIT/index",
                        "operation": "write",
                        "content": "no\n",
                    }
                ]
            ),
        )


def test_write_then_delete_conflict_same_path_rejected(tmp_path):
    (tmp_path / "foo.py").write_text(
        "x\n",
        encoding="utf-8",
    )

    with pytest.raises(
        PatchToolError,
        match="Duplicate target path",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "foo.py",
                        "operation": "write",
                        "content": "y\n",
                    },
                    {
                        "path": "foo.py",
                        "operation": "delete",
                    },
                ]
            ),
        )


def test_rollback_restores_delete_and_overwrite(
    tmp_path,
    monkeypatch,
):
    a = tmp_path / "A.py"
    b = tmp_path / "B.py"
    c = tmp_path / "C.py"
    a.write_text("ORIGINAL_A\n", encoding="utf-8")
    b.write_text("ORIGINAL_B\n", encoding="utf-8")
    c.write_text("ORIGINAL_C\n", encoding="utf-8")

    real_write_text = Path.write_text

    def flaky_write_text(self, data, *args, **kwargs):
        if self.name == "C.py":
            # Simulate truncate/partial write before crash.
            real_write_text(
                self,
                "PARTIAL\n",
                *args,
                **kwargs,
            )
            raise OSError("forced write failure")

        return real_write_text(
            self,
            data,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        Path,
        "write_text",
        flaky_write_text,
    )

    with pytest.raises(
        PatchToolError,
        match="rolled back",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "A.py",
                        "operation": "delete",
                    },
                    {
                        "path": "B.py",
                        "operation": "write",
                        "content": "NEW_B\n",
                    },
                    {
                        "path": "C.py",
                        "operation": "write",
                        "content": "NEW_C\n",
                    },
                ]
            ),
        )

    assert a.read_text(encoding="utf-8") == "ORIGINAL_A\n"
    assert b.read_text(encoding="utf-8") == "ORIGINAL_B\n"
    assert c.read_text(encoding="utf-8") == "ORIGINAL_C\n"


def test_rollback_incomplete_is_reported(
    tmp_path,
    monkeypatch,
):
    a = tmp_path / "A.py"
    b = tmp_path / "B.py"
    a.write_text("ORIGINAL_A\n", encoding="utf-8")
    b.write_text("ORIGINAL_B\n", encoding="utf-8")

    real_write_text = Path.write_text
    real_write_bytes = Path.write_bytes

    def flaky_write_text(self, data, *args, **kwargs):
        if self.name == "B.py":
            raise OSError("forced write failure")

        return real_write_text(
            self,
            data,
            *args,
            **kwargs,
        )

    def flaky_write_bytes(self, data, *args, **kwargs):
        if self.name == "A.py":
            raise OSError("forced restore failure")

        return real_write_bytes(
            self,
            data,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        Path,
        "write_text",
        flaky_write_text,
    )
    monkeypatch.setattr(
        Path,
        "write_bytes",
        flaky_write_bytes,
    )

    with pytest.raises(
        PatchToolError,
        match="rollback was incomplete",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "A.py",
                        "operation": "delete",
                    },
                    {
                        "path": "B.py",
                        "operation": "write",
                        "content": "NEW_B\n",
                    },
                ]
            ),
        )


def test_rollback_restores_executable_mode(
    tmp_path,
    monkeypatch,
):
    script = tmp_path / "run.sh"
    script.write_text(
        "#!/bin/sh\necho hi\n",
        encoding="utf-8",
    )

    try:
        script.chmod(0o755)
    except OSError as exc:
        pytest.skip(f"chmod not supported: {exc}")

    if not (script.stat().st_mode & 0o111):
        pytest.skip("executable bit not supported")

    other = tmp_path / "other.py"
    other.write_text("OTHER\n", encoding="utf-8")

    real_write_text = Path.write_text

    def flaky_write_text(self, data, *args, **kwargs):
        if self.name == "other.py":
            raise OSError("forced write failure")

        return real_write_text(
            self,
            data,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        Path,
        "write_text",
        flaky_write_text,
    )

    with pytest.raises(
        PatchToolError,
        match="rolled back",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "run.sh",
                        "operation": "delete",
                    },
                    {
                        "path": "other.py",
                        "operation": "write",
                        "content": "NEW\n",
                    },
                ]
            ),
        )

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert (
        script.read_text(encoding="utf-8")
        == "#!/bin/sh\necho hi\n"
    )


def test_rollback_removes_new_write_after_later_failure(
    tmp_path,
    monkeypatch,
):
    existing = tmp_path / "keep.py"
    existing.write_text("KEEP\n", encoding="utf-8")
    doomed = tmp_path / "doomed.py"
    doomed.write_text("DOOMED\n", encoding="utf-8")

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "doomed.py":
            raise OSError("forced delete failure")

        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(
        Path,
        "unlink",
        flaky_unlink,
    )

    with pytest.raises(
        PatchToolError,
        match="rolled back",
    ):
        PatchTool.apply_multi_file_patch(
            str(tmp_path),
            _patch_payload(
                [
                    {
                        "path": "new.py",
                        "operation": "write",
                        "content": "NEW\n",
                    },
                    {
                        "path": "doomed.py",
                        "operation": "delete",
                    },
                ]
            ),
        )

    assert not (tmp_path / "new.py").exists()
    assert existing.read_text(encoding="utf-8") == "KEEP\n"
    assert doomed.read_text(encoding="utf-8") == "DOOMED\n"


def test_deleted_and_modified_appear_in_git_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    wt_root = tmp_path / "wt"
    wt_root.mkdir()

    subprocess.run(
        ["git", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    users = repo / "users"
    users.mkdir()
    apps = users / "apps.py"
    apps.write_text(
        "class UsersConfig:\n    pass\n",
        encoding="utf-8",
    )
    settings = repo / "settings.py"
    settings.write_text(
        "INSTALLED_APPS = ['users']\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "-A"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    PatchTool.apply_multi_file_patch(
        str(repo),
        _patch_payload(
            [
                {
                    "path": "users/apps.py",
                    "operation": "delete",
                },
                {
                    "path": "settings.py",
                    "operation": "write",
                    "content": "INSTALLED_APPS = []\n",
                },
            ]
        ),
    )

    manager = GitWorktreeManager(
        str(repo),
        str(wt_root),
    )
    diff = manager.get_diff(str(repo))

    assert "users/apps.py" in diff
    assert (
        "deleted file mode" in diff
        or "--- a/users/apps.py" in diff
    )
    assert "settings.py" in diff
    assert "INSTALLED_APPS = []" in diff


def test_create_and_modify_still_work(tmp_path):
    existing = tmp_path / "edit.py"
    existing.write_text("OLD\n", encoding="utf-8")

    PatchTool.apply_multi_file_patch(
        str(tmp_path),
        _patch_payload(
            [
                {
                    "path": "edit.py",
                    "content": "NEW\n",
                },
                {
                    "path": "created.py",
                    "content": "CREATED\n",
                },
            ]
        ),
    )

    assert existing.read_text(encoding="utf-8") == "NEW\n"
    assert (
        tmp_path / "created.py"
    ).read_text(encoding="utf-8") == "CREATED\n"
