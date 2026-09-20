import subprocess
from types import SimpleNamespace

from factory.agents.provider_adapter import (
    ProviderTransport,
)
from factory.agents.provider_discovery import (
    discover_runtime_provider,
    probe_runtime_provider,
)
from factory.agents.provider_health import (
    ProviderHealth,
    ProviderHealthStatus,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)


def make_descriptor(
    name="codex_cli",
    executable="codex",
    transport=ProviderTransport.CLI,
    metadata=None,
):
    return SimpleNamespace(
        name=name,
        executable=executable,
        transport=transport,
        metadata=dict(metadata or {}),
        features=(),
        adapter_version="test",
    )


def test_executable_not_found(
    monkeypatch,
):
    descriptor = make_descriptor()

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "resolve_cli_executable",
        lambda _: None,
    )

    health = probe_runtime_provider(
        descriptor
    )

    assert (
        health.status
        == ProviderHealthStatus.UNAVAILABLE
    )
    assert health.available is False
    assert (
        health.error_code
        == "EXECUTABLE_NOT_FOUND"
    )
    assert health.latency_ms is not None


def test_successful_version_probe(
    monkeypatch,
):
    descriptor = make_descriptor()

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "resolve_cli_executable",
        lambda _: r"C:\Tools\codex.exe",
    )

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs

        return SimpleNamespace(
            returncode=0,
            stdout="codex-cli 0.155.1\n",
            stderr="",
        )

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "subprocess.run",
        fake_run,
    )

    health = probe_runtime_provider(
        descriptor,
        timeout_seconds=2.5,
    )

    assert health.available is True
    assert (
        health.status
        == ProviderHealthStatus.AVAILABLE
    )
    assert (
        health.version
        == "codex-cli 0.155.1"
    )
    assert health.error_code is None
    assert health.latency_ms is not None

    assert captured["command"] == [
        r"C:\Tools\codex.exe",
        "--version",
    ]
    assert (
        captured["kwargs"]["timeout"]
        == 2.5
    )


def test_version_can_use_stderr(
    monkeypatch,
):
    descriptor = make_descriptor()

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "resolve_cli_executable",
        lambda _: "/tmp/codex",
    )

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "subprocess.run",
        lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="codex 1.2.3\n",
            )
        ),
    )

    health = probe_runtime_provider(
        descriptor
    )

    assert health.available is True
    assert health.version == "codex 1.2.3"


def test_probe_timeout(
    monkeypatch,
):
    descriptor = make_descriptor()

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "resolve_cli_executable",
        lambda _: "/tmp/codex",
    )

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["codex", "--version"],
            timeout=5,
        )

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "subprocess.run",
        fake_run,
    )

    health = probe_runtime_provider(
        descriptor
    )

    assert health.available is False
    assert (
        health.status
        == ProviderHealthStatus.UNAVAILABLE
    )
    assert (
        health.error_code
        == "PROBE_TIMEOUT"
    )
    assert health.latency_ms is not None


def test_probe_os_error(
    monkeypatch,
):
    descriptor = make_descriptor()

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "resolve_cli_executable",
        lambda _: "/tmp/codex",
    )

    def fake_run(*args, **kwargs):
        raise OSError(
            "cannot execute"
        )

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "subprocess.run",
        fake_run,
    )

    health = probe_runtime_provider(
        descriptor
    )

    assert health.available is False
    assert (
        health.error_code
        == "PROBE_ERROR"
    )
    assert "cannot execute" in health.reason


def test_non_zero_exit(
    monkeypatch,
):
    descriptor = make_descriptor()

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "resolve_cli_executable",
        lambda _: "/tmp/codex",
    )

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "subprocess.run",
        lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=7,
                stdout="",
                stderr="bad invocation\n",
            )
        ),
    )

    health = probe_runtime_provider(
        descriptor
    )

    assert health.available is False
    assert (
        health.error_code
        == "PROBE_NON_ZERO_EXIT"
    )
    assert (
        health.version
        == "bad invocation"
    )


def test_custom_health_probe_command(
    monkeypatch,
):
    descriptor = make_descriptor(
        metadata={
            "health_probe_command": [
                "version",
                "--short",
            ]
        }
    )

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "resolve_cli_executable",
        lambda _: "/tmp/tool",
    )

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command

        return SimpleNamespace(
            returncode=0,
            stdout="1.0\n",
            stderr="",
        )

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "subprocess.run",
        fake_run,
    )

    health = probe_runtime_provider(
        descriptor
    )

    assert health.available is True
    assert captured["command"] == [
        "/tmp/tool",
        "version",
        "--short",
    ]


def test_in_process_provider_does_not_spawn_cli(
    monkeypatch,
):
    descriptor = make_descriptor(
        name="local",
        executable=None,
        transport=(
            ProviderTransport.IN_PROCESS
        ),
    )

    def forbidden_run(*args, **kwargs):
        raise AssertionError(
            "subprocess must not run"
        )

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "subprocess.run",
        forbidden_run,
    )

    health = probe_runtime_provider(
        descriptor
    )

    assert health.available is True
    assert health.latency_ms is not None


def test_runtime_discovery_contains_health(
    monkeypatch,
):
    descriptor = make_descriptor()

    expected = ProviderHealth(
        provider_name="codex_cli",
        status=(
            ProviderHealthStatus.AVAILABLE
        ),
        transport=ProviderTransport.CLI,
        reason="ok",
        checked_via="runtime_cli",
        executable="codex",
        resolved_executable="/tmp/codex",
        version="codex 1.0",
        latency_ms=3.5,
    )

    monkeypatch.setattr(
        "factory.agents.provider_discovery."
        "probe_runtime_provider",
        lambda *args, **kwargs: expected,
    )

    result = discover_runtime_provider(
        descriptor
    )

    assert result["name"] == "codex_cli"
    assert (
        result["health"]["available"]
        is True
    )
    assert (
        result["health"]["version"]
        == "codex 1.0"
    )


def test_registry_runtime_health(
    monkeypatch,
):
    registry = AgentProviderRegistry()
    descriptor = make_descriptor()

    registry._descriptors[
        "codex_cli"
    ] = descriptor

    expected = ProviderHealth(
        provider_name="codex_cli",
        status=(
            ProviderHealthStatus.AVAILABLE
        ),
        transport=ProviderTransport.CLI,
        reason="ok",
        checked_via="runtime_cli",
    )

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        lambda *args, **kwargs: expected,
    )

    result = registry.runtime_health(
        "codex_cli"
    )

    assert result is expected


def test_runtime_health_all_isolates_failure(
    monkeypatch,
):
    registry = AgentProviderRegistry()

    registry._descriptors.update(
        {
            "bad_cli": make_descriptor(
                name="bad_cli",
                executable="bad",
            ),
            "good_cli": make_descriptor(
                name="good_cli",
                executable="good",
            ),
        }
    )

    def fake_runtime_probe(
        descriptor,
        **kwargs,
    ):
        if descriptor.name == "bad_cli":
            raise RuntimeError(
                "probe exploded"
            )

        return ProviderHealth(
            provider_name=(
                descriptor.name
            ),
            status=(
                ProviderHealthStatus.AVAILABLE
            ),
            transport=(
                descriptor.transport
            ),
            reason="ok",
            checked_via="runtime_cli",
        )

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_runtime_probe,
    )

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_provider_descriptor",
        lambda descriptor: (
            ProviderHealth(
                provider_name=(
                    descriptor.name
                ),
                status=(
                    ProviderHealthStatus.AVAILABLE
                ),
                transport=(
                    descriptor.transport
                ),
                reason="passive",
                checked_via="test",
                resolved_executable=(
                    descriptor.executable
                ),
            )
        ),
    )

    results = (
        registry.runtime_health_all()
    )

    by_name = {
        health.provider_name: health
        for health in results
    }

    assert (
        by_name["good_cli"].available
        is True
    )

    assert (
        by_name["bad_cli"].status
        == ProviderHealthStatus.UNAVAILABLE
    )
    assert (
        by_name["bad_cli"].error_code
        == "PROBE_EXCEPTION"
    )
    assert "probe exploded" in (
        by_name["bad_cli"].reason
    )


def test_health_dict_contains_runtime_fields():
    health = ProviderHealth(
        provider_name="codex_cli",
        status=(
            ProviderHealthStatus.AVAILABLE
        ),
        transport=ProviderTransport.CLI,
        reason="ok",
        checked_via="runtime_cli",
        authenticated=None,
        version="0.155.1",
        latency_ms=12.5,
        error_code=None,
    )

    result = health.as_dict()

    assert (
        result["authenticated"]
        is None
    )
    assert result["version"] == "0.155.1"
    assert result["latency_ms"] == 12.5
    assert result["error_code"] is None
