from pathlib import Path

from factory.agents.provider_health import (
    resolve_cli_executable,
)
from factory.agents.providers.gemini import (
    GeminiCliProvider,
)


def test_gemini_provider_prefers_path_resolution(
    monkeypatch,
):
    provider = GeminiCliProvider()

    monkeypatch.setattr(
        "factory.agents.providers.gemini."
        "shutil.which",
        lambda executable: (
            r"C:\Users\Test\AppData\Roaming"
            r"\npm\gemini.cmd"
        ),
    )

    resolved = provider._resolve_executable()

    assert resolved.endswith(
        r"npm\gemini.cmd"
    )


def test_gemini_provider_uses_appdata_fallback(
    monkeypatch,
    tmp_path,
):
    app_data = tmp_path / "Roaming"
    npm_dir = app_data / "npm"
    npm_dir.mkdir(
        parents=True
    )

    executable = (
        npm_dir
        / "gemini.cmd"
    )

    executable.write_text(
        "@echo off",
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "APPDATA",
        str(app_data),
    )

    monkeypatch.setattr(
        "factory.agents.providers.gemini."
        "shutil.which",
        lambda executable: None,
    )

    provider = GeminiCliProvider()

    assert (
        provider._resolve_executable()
        == str(executable)
    )


def test_gemini_health_uses_appdata_fallback(
    monkeypatch,
    tmp_path,
):
    app_data = tmp_path / "Roaming"
    npm_dir = app_data / "npm"

    npm_dir.mkdir(
        parents=True
    )

    executable = (
        npm_dir
        / "gemini.cmd"
    )

    executable.write_text(
        "@echo off",
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "APPDATA",
        str(app_data),
    )

    monkeypatch.setattr(
        "factory.agents.provider_health."
        "shutil.which",
        lambda executable: None,
    )

    descriptor = (
        GeminiCliProvider()
        .describe()
    )

    resolved = resolve_cli_executable(
        descriptor
    )

    assert resolved == str(
        executable
    )


def test_gemini_complete_runs_resolved_executable(
    monkeypatch,
):
    captured = {}

    def fake_run(
        command,
        **kwargs,
    ):
        captured["command"] = (
            command
        )

        class Result:
            returncode = 0
            stdout = (
                '{"response":"OK",'
                '"stats":{}}'
            )
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "factory.agents.providers.gemini."
        "shutil.which",
        lambda executable: (
            r"C:\Users\Test\AppData\Roaming"
            r"\npm\gemini.cmd"
        ),
    )

    provider = GeminiCliProvider(
        run_fn=fake_run
    )

    from factory.agents.contracts import (
        AgentRequest,
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="",
            user_prompt="Return OK",
        )
    )

    assert result.content == "OK"

    assert (
        captured["command"][0]
        .lower()
        .endswith("gemini.cmd")
    )
