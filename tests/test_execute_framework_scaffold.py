from types import SimpleNamespace

import pytest

from factory.execute_task_runner import (
    ExecuteTaskError,
    run_execute_task,
)


def test_django_scaffold_uses_project_venv_and_verifies_files(
    tmp_path,
    monkeypatch,
):
    python_exe = (
        tmp_path
        / "venv"
        / "Scripts"
        / "python.exe"
    )
    python_exe.parent.mkdir(parents=True)
    python_exe.write_text("", encoding="utf-8")

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

        project = tmp_path / "okulprojesi"
        package = project / "okulprojesi"
        package.mkdir(parents=True)
        (project / "manage.py").write_text(
            "# manage",
            encoding="utf-8",
        )
        (package / "settings.py").write_text(
            "# settings",
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
        prompt=(
            "Bu klasorde okulprojesi adinda "
            "yeni bir Django projesi olustur."
        ),
        intent="framework_scaffold",
        target="okulprojesi",
        framework="django",
    )

    assert result == (
        "Django projesi olusturuldu: okulprojesi"
    )

    assert calls == [[
        str(python_exe),
        "-m",
        "django",
        "startproject",
        "okulprojesi",
    ]]


def test_django_scaffold_rejects_existing_target(
    tmp_path,
):
    (tmp_path / "okulprojesi").mkdir()

    with pytest.raises(
        ExecuteTaskError,
        match="zaten mevcut",
    ):
        run_execute_task(
            project_path=str(tmp_path),
            prompt="Django projesi olustur",
            intent="framework_scaffold",
            target="okulprojesi",
            framework="django",
        )


def test_framework_scaffold_rejects_unsafe_project_name(
    tmp_path,
):
    with pytest.raises(
        ExecuteTaskError,
        match="guvenli olmayan",
    ):
        run_execute_task(
            project_path=str(tmp_path),
            prompt="proje olustur",
            intent="framework_scaffold",
            target="../okulprojesi",
            framework="django",
        )
