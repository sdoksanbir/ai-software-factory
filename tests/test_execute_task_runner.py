from types import SimpleNamespace

import pytest

from factory.execute_task_runner import (
    ExecuteTaskError,
    run_execute_task,
)


def test_create_venv_in_project_root(
    tmp_path,
    monkeypatch,
):
    calls = []

    def fake_run(
        args,
        *,
        cwd,
        capture_output,
        text,
        check,
        timeout=None,
    ):
        calls.append((args, cwd, timeout))

        if args[:3] == [
            "git",
            "rev-parse",
            "--git-dir",
        ]:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="not a repo",
            )

        assert args[1:3] == [
            "-m",
            "venv",
        ]
        assert args[3] == "venv"

        target = tmp_path / "venv"
        target.mkdir()
        (target / "pyvenv.cfg").write_text(
            "home = test\n",
            encoding="utf-8",
        )

        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "factory.execute_task_runner.subprocess.run",
        fake_run,
    )

    result = run_execute_task(
        project_path=str(tmp_path),
        prompt="Ana klasore venv sanal ortami kur.",
    )

    assert "Sanal ortam olusturuldu" in result
    assert (tmp_path / "venv" / "pyvenv.cfg").exists()


def test_existing_venv_is_idempotent(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / ".venv"
    target.mkdir()
    (target / "pyvenv.cfg").write_text(
        "home = test\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "factory.execute_task_runner._ensure_local_git_exclude",
        lambda *args, **kwargs: None,
    )

    result = run_execute_task(
        project_path=str(tmp_path),
        prompt="Proje kokunde .venv olustur.",
    )

    assert "zaten mevcut" in result


def test_unsupported_execute_action_is_rejected(
    tmp_path,
):
    with pytest.raises(ExecuteTaskError):
        run_execute_task(
            project_path=str(tmp_path),
            prompt="Sunucuyu yeniden baslat.",
        )


def test_pip_setup_uses_project_venv(
    tmp_path,
    monkeypatch,
):
    from types import SimpleNamespace

    venv_python = (
        tmp_path
        / "venv"
        / "Scripts"
        / "python.exe"
    )
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text(
        "",
        encoding="utf-8",
    )

    calls = []

    def fake_run(
        args,
        *,
        cwd,
        capture_output,
        text,
        check,
        timeout=None,
    ):
        calls.append(args)

        if args[-2:] == [
            "ensurepip",
            "--upgrade",
        ]:
            return SimpleNamespace(
                returncode=0,
                stdout="ensurepip ok",
                stderr="",
            )

        if args[-2:] == [
            "pip",
            "--version",
        ]:
            return SimpleNamespace(
                returncode=0,
                stdout="pip 25.0 from test",
                stderr="",
            )

        raise AssertionError(
            f"Beklenmeyen komut: {args}"
        )

    monkeypatch.setattr(
        "factory.execute_task_runner.subprocess.run",
        fake_run,
    )

    result = run_execute_task(
        project_path=str(tmp_path),
        prompt=(
            "Simdi bu klasore pip "
            "kurulumunu gerceklestir."
        ),
    )

    assert (
        "Pip kurulumu tamamlandi"
        in result
    )
    assert calls[0][0] == str(
        venv_python
    )
    assert calls[0][1:] == [
        "-m",
        "ensurepip",
        "--upgrade",
    ]
    assert calls[1][1:] == [
        "-m",
        "pip",
        "--version",
    ]
