from types import SimpleNamespace

from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.contracts import (
    AgentRequest,
    AgentResult,
)
from factory.agents.execution_router import (
    AgentExecutionRouter,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.providers.model_client import (
    ModelClientProvider,
)
from factory.agents.router import AgentRouter
from factory.agents.timeout_policy import (
    DEFAULT_AGENT_TIMEOUT,
    ensure_agent_request_timeout,
    resolve_agent_timeout,
)


def test_resolve_explicit_timeout():
    assert resolve_agent_timeout(30) == 30


def test_resolve_role_config_timeout():
    config = {
        "models": {
            "fast_local": {
                "timeout_seconds": 90,
            }
        }
    }

    assert resolve_agent_timeout(
        None,
        config=config,
        model_role="fast_local",
    ) == 90


def test_resolve_default_timeout_when_no_config():
    assert resolve_agent_timeout(
        None
    ) == DEFAULT_AGENT_TIMEOUT
    assert DEFAULT_AGENT_TIMEOUT == 120


def test_ensure_keeps_explicit_timeout():
    request = AgentRequest(
        system_prompt="s",
        user_prompt="u",
        timeout=30,
    )

    ensured = ensure_agent_request_timeout(
        request,
        config={
            "models": {
                "fast_local": {
                    "timeout_seconds": 90,
                }
            }
        },
    )

    assert ensured is request
    assert ensured.timeout == 30


def test_ensure_fills_default_timeout():
    request = AgentRequest(
        system_prompt="s",
        user_prompt="u",
    )

    ensured = ensure_agent_request_timeout(
        request
    )

    assert ensured.timeout == 120


def test_router_forwards_explicit_timeout():
    captured = []

    class RecordingProvider:
        provider_name = "ollama"

        def complete(self, request):
            captured.append(request)

            return AgentResult(
                content="ok",
                provider=self.provider_name,
                model=request.model_name,
            )

    provider = RecordingProvider()
    registry = AgentProviderRegistry()
    registry.register(provider)

    runtime = AgentExecutionRouter(
        agent_router=AgentRouter(
            [
                AgentDescriptor(
                    name="coder",
                    provider_name="ollama",
                    capabilities=frozenset(
                        {
                            AgentCapability
                            .WRITE_CODE,
                        }
                    ),
                )
            ]
        ),
        provider_registry=registry,
        config={
            "models": {
                "fast_local": {
                    "timeout_seconds": 90,
                }
            }
        },
    )

    runtime.complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            timeout=30,
        ),
        {AgentCapability.WRITE_CODE},
    )

    assert len(captured) == 1
    assert captured[0].timeout == 30


def test_router_resolves_role_timeout_when_missing():
    captured = []

    class RecordingProvider:
        provider_name = "ollama"

        def complete(self, request):
            captured.append(request)

            return AgentResult(
                content="ok",
                provider=self.provider_name,
            )

    provider = RecordingProvider()
    registry = AgentProviderRegistry()
    registry.register(provider)

    runtime = AgentExecutionRouter(
        agent_router=AgentRouter(
            [
                AgentDescriptor(
                    name="coder",
                    provider_name="ollama",
                    capabilities=frozenset(
                        {
                            AgentCapability
                            .WRITE_CODE,
                        }
                    ),
                )
            ]
        ),
        provider_registry=registry,
        config={
            "models": {
                "fast_local": {
                    "timeout_seconds": 90,
                }
            }
        },
    )

    runtime.complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        ),
        {AgentCapability.WRITE_CODE},
    )

    assert captured[0].timeout == 90


def test_model_client_provider_forwards_explicit_timeout():
    calls = []

    class FakeModelClient:
        def complete(self, **kwargs):
            calls.append(kwargs)

            return SimpleNamespace(
                content="ok",
                provider="openrouter",
                model="m",
            )

    provider = ModelClientProvider(
        FakeModelClient()
    )

    provider.complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            timeout=30,
        )
    )

    assert calls[0]["timeout"] == 30


def test_model_client_provider_resolves_default_timeout():
    calls = []

    class FakeModelClient:
        def complete(self, **kwargs):
            calls.append(kwargs)

            return SimpleNamespace(
                content="ok"
            )

    provider = ModelClientProvider(
        FakeModelClient()
    )

    provider.complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        )
    )

    assert calls[0]["timeout"] == 120


def test_model_client_provider_resolves_role_timeout():
    calls = []

    class FakeModelClient:
        config = {
            "models": {
                "cloud_senior": {
                    "provider": "openai",
                    "model": "cloud-model",
                    "timeout_seconds": 75,
                }
            }
        }

        def complete(self, **kwargs):
            calls.append(kwargs)

            return SimpleNamespace(
                content="ok"
            )

    provider = ModelClientProvider(
        FakeModelClient()
    )

    provider.complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            model_role="cloud_senior",
        )
    )

    assert calls[0]["timeout"] == 75
