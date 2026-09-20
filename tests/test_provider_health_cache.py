from types import SimpleNamespace

from factory.agents.provider_adapter import (
    ProviderTransport,
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
):
    return SimpleNamespace(
        name=name,
        executable="codex",
        transport=ProviderTransport.CLI,
        metadata={},
        features=(),
        adapter_version="test",
    )


def make_health(
    name="codex_cli",
    version="1.0",
):
    return ProviderHealth(
        provider_name=name,
        status=(
            ProviderHealthStatus.AVAILABLE
        ),
        transport=ProviderTransport.CLI,
        reason="ok",
        checked_via="runtime_cli",
        version=version,
    )


def test_runtime_health_is_cached(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=30,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor()

    calls = []

    def fake_probe(
        descriptor,
        **kwargs,
    ):
        calls.append(
            descriptor.name
        )

        return make_health()

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_probe,
    )

    first = registry.runtime_health(
        "codex_cli"
    )

    second = registry.runtime_health(
        "codex_cli"
    )

    assert first is second
    assert calls == ["codex_cli"]


def test_cache_expires_after_ttl(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=10,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor()

    clock = [100.0]

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "time.monotonic",
        lambda: clock[0],
    )

    versions = iter(
        ["1.0", "2.0"]
    )

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        lambda *args, **kwargs: (
            make_health(
                version=next(versions)
            )
        ),
    )

    first = registry.runtime_health(
        "codex_cli"
    )

    clock[0] = 109.9

    cached = registry.runtime_health(
        "codex_cli"
    )

    clock[0] = 110.0

    refreshed = registry.runtime_health(
        "codex_cli"
    )

    assert first.version == "1.0"
    assert cached is first
    assert refreshed.version == "2.0"


def test_zero_ttl_disables_cache(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=0,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor()

    calls = []

    def fake_probe(
        descriptor,
        **kwargs,
    ):
        calls.append(
            descriptor.name
        )

        return make_health()

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_probe,
    )

    registry.runtime_health(
        "codex_cli"
    )

    registry.runtime_health(
        "codex_cli"
    )

    assert calls == [
        "codex_cli",
        "codex_cli",
    ]


def test_runtime_health_all_reuses_cache(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=30,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor()

    calls = []

    def fake_probe(
        descriptor,
        **kwargs,
    ):
        calls.append(
            descriptor.name
        )

        return make_health()

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_probe,
    )

    registry.runtime_health_all()
    registry.runtime_health_all()

    assert calls == ["codex_cli"]


def test_force_refresh_bypasses_cache(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=30,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor()

    versions = iter(
        ["1.0", "2.0"]
    )

    calls = []

    def fake_probe(
        descriptor,
        **kwargs,
    ):
        calls.append(
            descriptor.name
        )

        return make_health(
            version=next(versions)
        )

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_probe,
    )

    first = registry.runtime_health(
        "codex_cli"
    )

    refreshed = registry.runtime_health(
        "codex_cli",
        force_refresh=True,
    )

    cached = registry.runtime_health(
        "codex_cli"
    )

    assert first.version == "1.0"
    assert refreshed.version == "2.0"
    assert cached is refreshed

    assert calls == [
        "codex_cli",
        "codex_cli",
    ]


def test_invalidate_single_provider(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=30,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor()

    calls = []

    def fake_probe(
        descriptor,
        **kwargs,
    ):
        calls.append(
            descriptor.name
        )

        return make_health()
 
    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_probe,
    )

    registry.runtime_health(
        "codex_cli"
    )

    registry.invalidate_runtime_health(
        "CODEX_CLI"
    )

    registry.runtime_health(
        "codex_cli"
    )

    assert calls == [
        "codex_cli",
        "codex_cli",
    ]


def test_invalidate_all_providers(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=30,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor(
        name="codex_cli"
    )

    registry._descriptors[
        "gemini_cli"
    ] = make_descriptor(
        name="gemini_cli"
    )

    calls = []

    def fake_probe(
        descriptor,
        **kwargs,
    ):
        calls.append(
            descriptor.name
        )

        return make_health(
            name=descriptor.name
        )

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_probe,
    )

    registry.runtime_health_all()
    registry.runtime_health_all()

    assert len(calls) == 2

    registry.invalidate_runtime_health()

    registry.runtime_health_all()

    assert len(calls) == 4


def test_runtime_health_all_force_refresh(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=30,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor()

    calls = []

    def fake_probe(
        descriptor,
        **kwargs,
    ):
        calls.append(
            descriptor.name
        )

        return make_health()

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_probe,
    )

    registry.runtime_health_all()

    registry.runtime_health_all(
        force_refresh=True
    )

    assert calls == [
        "codex_cli",
        "codex_cli",
    ]


def test_runtime_discovery_reuses_health_cache(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=30,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor()

    calls = []

    def fake_probe(
        descriptor,
        **kwargs,
    ):
        calls.append(
            descriptor.name
        )

        return make_health(
            version="1.0"
        )

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_probe,
    )

    first = registry.runtime_discovery(
        "codex_cli"
    )

    second = registry.runtime_discovery(
        "codex_cli"
    )

    assert (
        first["health"]["version"]
        == "1.0"
    )

    assert (
        second["health"]["version"]
        == "1.0"
    )

    assert calls == [
        "codex_cli",
    ]


def test_runtime_discovery_force_refresh(
    monkeypatch,
):
    registry = AgentProviderRegistry(
        health_cache_ttl_seconds=30,
    )

    registry._descriptors[
        "codex_cli"
    ] = make_descriptor()

    versions = iter(
        ["1.0", "2.0"]
    )

    calls = []

    def fake_probe(
        descriptor,
        **kwargs,
    ):
        calls.append(
            descriptor.name
        )

        return make_health(
            version=next(versions)
        )

    monkeypatch.setattr(
        "factory.agents.provider_registry."
        "probe_runtime_provider",
        fake_probe,
    )

    first = registry.runtime_discovery(
        "codex_cli"
    )

    refreshed = registry.runtime_discovery(
        "codex_cli",
        force_refresh=True,
    )

    assert (
        first["health"]["version"]
        == "1.0"
    )

    assert (
        refreshed["health"]["version"]
        == "2.0"
    )

    assert calls == [
        "codex_cli",
        "codex_cli",
    ]
