from types import SimpleNamespace

from factory.execute_task_runner import (
    ExecuteTaskError,
    run_execute_task,
)


def test_semantic_package_install_uses_project_venv(
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
    python_exe.write_text(
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

        if "install" in args:
            return SimpleNamespace(
                returncode=0,
                stdout="installed",
                stderr="",
            )

        if "show" in args:
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "Name: Django\n"
                    "Version: 5.2.6\n"
                ),
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
        prompt="Django'nun en son surumunu kur",
        intent="package_install",
        target="django",
    )

    assert result == (
        "Paket kurulumu tamamlandi: django 5.2.6"
    )
    assert calls[0][1:] == [
        "-m",
        "pip",
        "install",
        "--upgrade",
        "django",
    ]
    assert calls[1][1:] == [
        "-m",
        "pip",
        "show",
        "django",
    ]


def test_package_target_rejects_shell_syntax(
    tmp_path,
):
    try:
        run_execute_task(
            project_path=str(tmp_path),
            prompt="kur",
            intent="package_install",
            target="django;rm",
        )
    except ExecuteTaskError as exc:
        assert "Guvenli olmayan" in str(exc)
    else:
        raise AssertionError(
            "Guvenli olmayan paket adi reddedilmeliydi."
        )
