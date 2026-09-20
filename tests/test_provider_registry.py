import pytest

from factory.agents.contracts import (
    AgentRequest,
    AgentResult,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)


class FakeProvider:
    def __init__(
        self,
        name: str,
        content: str = "ok",
    ) -> None:
        self.provider_name = name
        self.content = content

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        return AgentResult(
            content=self.content,
            provider=self.provider_name,
            model=request.model_name,
        )


def test_registry_registers_and_resolves_provider():
    registry = AgentProviderRegistry()
    provider = FakeProvider("ollama")

    registry.register(provider)

    assert registry.has("ollama")
    assert registry.has("OLLAMA")
    assert registry.get("ollama") is provider
    assert registry.names() == ("ollama",)


def test_registry_rejects_duplicate_provider():
    registry = AgentProviderRegistry()

    registry.register(
        FakeProvider("ollama")
    )

    with pytest.raises(
        ValueError,
        match="already registered",
    ):
        registry.register(
            FakeProvider("ollama")
        )


def test_registry_can_replace_provider():
    registry = AgentProviderRegistry()

    first = FakeProvider(
        "ollama",
        "first",
    )
    second = FakeProvider(
        "OLLAMA",
        "second",
    )

    registry.register(first)

    registry.register(
        second,
        replace=True,
    )

    assert registry.get(
        "ollama"
    ) is second


def test_registry_reports_unknown_provider():
    registry = AgentProviderRegistry()

    registry.register(
        FakeProvider("ollama")
    )

    with pytest.raises(
        KeyError,
        match="gemini_cli",
    ):
        registry.get("gemini_cli")


def test_registry_exposes_provider_health(
    monkeypatch,
):
    from factory.agents.provider_adapter import (
        ProviderDescriptor,
        ProviderTransport,
    )

    registry = AgentProviderRegistry()

    provider = FakeProvider(
        "codex_cli"
    )

    registry.register(
        provider,
        descriptor=(
            ProviderDescriptor(
                name="codex_cli",
                transport=(
                    ProviderTransport.CLI
                ),
                executable="codex",
            )
        ),
    )

    monkeypatch.setattr(
        "factory.agents.provider_health."
        "shutil.which",
        lambda executable: (
            r"C:\tools\codex.exe"
        ),
    )

    health = registry.health(
        "codex_cli"
    )

    assert health.available is True

    assert (
        health.provider_name
        == "codex_cli"
    )


def test_registry_discover_all_is_sorted(
    monkeypatch,
):
    from factory.agents.provider_adapter import (
        ProviderDescriptor,
        ProviderTransport,
    )

    registry = AgentProviderRegistry()

    registry.register(
        FakeProvider(
            "zeta"
        ),
        descriptor=(
            ProviderDescriptor(
                name="zeta",
                transport=(
                    ProviderTransport
                    .IN_PROCESS
                ),
            )
        ),
    )

    registry.register(
        FakeProvider(
            "alpha"
        ),
        descriptor=(
            ProviderDescriptor(
                name="alpha",
                transport=(
                    ProviderTransport
                    .IN_PROCESS
                ),
            )
        ),
    )

    discoveries = (
        registry.discover_all()
    )

    assert [
        item["name"]
        for item
        in discoveries
    ] == [
        "alpha",
        "zeta",
    ]

    assert all(
        "health" in item
        for item in discoveries
    )
