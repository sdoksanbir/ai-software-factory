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
