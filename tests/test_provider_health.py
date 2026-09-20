from pathlib import Path

from factory.agents.provider_adapter import (
    ProviderDescriptor,
    ProviderFeature,
    ProviderTransport,
)
from factory.agents.provider_health import (
    ProviderHealthStatus,
    discover_provider,
    probe_provider_descriptor,
    resolve_cli_executable,
)


def test_cli_health_available_when_executable_resolves(
    monkeypatch,
):
    descriptor = ProviderDescriptor(
        name="codex_cli",
        transport=ProviderTransport.CLI,
        executable="codex",
        features=frozenset(
            {
                ProviderFeature.TIMEOUT,
                ProviderFeature
                .USAGE_METADATA,
            }
        ),
    )

    monkeypatch.setattr(
        "factory.agents.provider_health."
        "shutil.which",
        lambda executable: (
            r"C:\tools\codex.exe"
        ),
    )

    health = (
        probe_provider_descriptor(
            descriptor
        )
    )

    assert (
        health.status
        == ProviderHealthStatus.AVAILABLE
    )

    assert health.available is True

    assert (
        health.resolved_executable
        == r"C:\tools\codex.exe"
    )

    assert health.features == (
        "timeout",
        "usage_metadata",
    )


def test_cli_health_unavailable_when_missing(
    monkeypatch,
):
    descriptor = ProviderDescriptor(
        name="missing_cli",
        transport=ProviderTransport.CLI,
        executable=(
            "definitely-missing-cli"
        ),
    )

    monkeypatch.setattr(
        "factory.agents.provider_health."
        "shutil.which",
        lambda executable: None,
    )

    health = (
        probe_provider_descriptor(
            descriptor
        )
    )

    assert (
        health.status
        == ProviderHealthStatus.UNAVAILABLE
    )

    assert health.available is False
    assert (
        health.resolved_executable
        is None
    )


def test_in_process_provider_is_available():
    descriptor = ProviderDescriptor(
        name="model_client",
        transport=(
            ProviderTransport.IN_PROCESS
        ),
        adapter_version="legacy",
    )

    health = (
        probe_provider_descriptor(
            descriptor
        )
    )

    assert (
        health.status
        == ProviderHealthStatus.AVAILABLE
    )

    assert (
        health.checked_via
        == "registry"
    )


def test_http_provider_is_unknown_without_probe():
    descriptor = ProviderDescriptor(
        name="remote",
        transport=(
            ProviderTransport.HTTP
        ),
    )

    health = (
        probe_provider_descriptor(
            descriptor
        )
    )

    assert (
        health.status
        == ProviderHealthStatus.UNKNOWN
    )


def test_discovery_contains_descriptor_and_health(
    monkeypatch,
):
    descriptor = ProviderDescriptor(
        name="antigravity_cli",
        transport=ProviderTransport.CLI,
        executable="agy",
        features=frozenset(
            {
                ProviderFeature
                .MODEL_OVERRIDE,
            }
        ),
        metadata={
            "cli_family": (
                "google_antigravity"
            ),
        },
    )

    monkeypatch.setattr(
        "factory.agents.provider_health."
        "shutil.which",
        lambda executable: (
            r"C:\tools\agy.exe"
        ),
    )

    discovery = discover_provider(
        descriptor
    )

    assert (
        discovery["name"]
        == "antigravity_cli"
    )

    assert (
        discovery["transport"]
        == "cli"
    )

    assert discovery["features"] == [
        "model_override",
    ]

    assert (
        discovery["health"][
            "status"
        ]
        == "available"
    )

    assert (
        discovery["health"][
            "resolved_executable"
        ]
        == r"C:\tools\agy.exe"
    )


def test_known_codex_windows_location_can_resolve(
    monkeypatch,
    tmp_path,
):
    local = (
        tmp_path / "Local"
    )

    codex = (
        local
        / "Programs"
        / "OpenAI"
        / "Codex"
        / "bin"
        / "codex.exe"
    )

    codex.parent.mkdir(
        parents=True
    )

    codex.write_bytes(
        b"codex"
    )

    monkeypatch.setenv(
        "LOCALAPPDATA",
        str(local),
    )

    monkeypatch.setattr(
        "factory.agents.provider_health."
        "shutil.which",
        lambda executable: None,
    )

    descriptor = ProviderDescriptor(
        name="codex_cli",
        transport=ProviderTransport.CLI,
        executable="codex",
        metadata={
            "cli_family": (
                "openai_codex"
            ),
        },
    )

    assert (
        resolve_cli_executable(
            descriptor
        )
        == str(codex)
    )


def test_known_antigravity_windows_location_can_resolve(
    monkeypatch,
    tmp_path,
):
    local = (
        tmp_path / "Local"
    )

    agy = (
        local
        / "agy"
        / "bin"
        / "agy.exe"
    )

    agy.parent.mkdir(
        parents=True
    )

    agy.write_bytes(
        b"agy"
    )

    monkeypatch.setenv(
        "LOCALAPPDATA",
        str(local),
    )

    monkeypatch.setattr(
        "factory.agents.provider_health."
        "shutil.which",
        lambda executable: None,
    )

    descriptor = ProviderDescriptor(
        name="antigravity_cli",
        transport=ProviderTransport.CLI,
        executable="agy",
        metadata={
            "cli_family": (
                "google_antigravity"
            ),
        },
    )

    assert (
        resolve_cli_executable(
            descriptor
        )
        == str(agy)
    )
