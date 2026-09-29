from types import SimpleNamespace

import pytest

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
from factory.agents.provider_errors import (
    AgentProviderUnavailableError,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.providers.model_client import (
    ModelClientProvider,
)
from factory.agents.router import AgentRouter
from factory.models import ModelResponse


class RecordingProvider:
    def __init__(
        self,
        name: str,
        *,
        result: str | None = None,
        error: Exception | None = None,
        metadata: dict | None = None,
    ):
        self.provider_name = name
        self.result = result
        self.error = error
        self.metadata = metadata or {}
        self.calls = 0

    def complete(self, request):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return AgentResult(
            content=self.result or "ok",
            provider=self.provider_name,
            model=request.model_name,
            metadata=dict(self.metadata),
        )


def _router(*providers: RecordingProvider):
    registry = AgentProviderRegistry()

    agents = []

    for provider in providers:
        registry.register(provider)
        agents.append(
            AgentDescriptor(
                name=f"{provider.provider_name}-coder",
                provider_name=provider.provider_name,
                capabilities=frozenset(
                    {
                        AgentCapability.WRITE_CODE,
                    }
                ),
            )
        )

    return AgentExecutionRouter(
        agent_router=AgentRouter(agents),
        provider_registry=registry,
    )


def test_router_primary_success_no_fallback():
    primary = RecordingProvider(
        "gemini_cli",
        result="primary-ok",
    )
    secondary = RecordingProvider(
        "ollama",
        result="secondary-ok",
    )

    runtime = _router(primary, secondary)

    execution = runtime.execute_with_fallback(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        ),
        {AgentCapability.WRITE_CODE},
        preferred_provider="gemini_cli",
    )

    assert execution.result.content == (
        "primary-ok"
    )
    assert (
        execution.result.metadata[
            "router_fallback_used"
        ]
        is False
    )
    assert (
        execution.result.metadata[
            "router_primary_provider"
        ]
        == "gemini_cli"
    )
    assert (
        execution.result.metadata[
            "router_final_provider"
        ]
        == "gemini_cli"
    )
    assert (
        execution.result.metadata[
            "transport_fallback_used"
        ]
        is False
    )
    assert execution.failures == ()
    assert secondary.calls == 0


def test_router_fallback_to_secondary():
    primary = RecordingProvider(
        "gemini_cli",
        error=AgentProviderUnavailableError(
            "down"
        ),
    )
    secondary = RecordingProvider(
        "ollama",
        result="secondary-ok",
    )

    runtime = _router(primary, secondary)

    execution = runtime.execute_with_fallback(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        ),
        {AgentCapability.WRITE_CODE},
        preferred_provider="gemini_cli",
    )

    assert execution.result.content == (
        "secondary-ok"
    )
    assert (
        execution.result.metadata[
            "router_fallback_used"
        ]
        is True
    )
    assert (
        execution.result.metadata[
            "router_primary_provider"
        ]
        == "gemini_cli"
    )
    assert (
        execution.result.metadata[
            "router_final_provider"
        ]
        == "ollama"
    )
    assert len(execution.failures) == 1


def test_transport_fallback_without_router_fallback():
    calls = []

    class FakeModelClient:
        config = {
            "models": {
                "fast_local": {
                    "provider": "openrouter",
                    "model": "primary-model",
                    "timeout_seconds": 30,
                }
            }
        }

        def complete(self, **kwargs):
            calls.append(kwargs)

            return ModelResponse(
                content="fallback-ok",
                model="fallback-model",
                provider="ollama",
                fallback_used=True,
            )

    provider = ModelClientProvider(
        FakeModelClient()
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            model_role="fast_local",
        )
    )

    assert result.provider == "ollama"
    assert result.metadata["fallback_used"] is True
    assert (
        result.metadata[
            "transport_fallback_used"
        ]
        is True
    )
    assert "router_fallback_used" not in (
        result.metadata
    )


def test_router_and_transport_fallback_visible():
    primary = RecordingProvider(
        "gemini_cli",
        error=AgentProviderUnavailableError(
            "down"
        ),
    )
    secondary = RecordingProvider(
        "model_client",
        result="transport-ok",
        metadata={
            "fallback_used": True,
            "transport_fallback_used": True,
            "configured_provider": "openrouter",
            "actual_provider": "ollama",
        },
    )

    runtime = _router(primary, secondary)

    execution = runtime.execute_with_fallback(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        ),
        {AgentCapability.WRITE_CODE},
        preferred_provider="gemini_cli",
    )

    meta = execution.result.metadata

    assert meta["router_fallback_used"] is True
    assert meta["router_primary_provider"] == (
        "gemini_cli"
    )
    assert meta["router_final_provider"] == (
        "model_client"
    )
    assert meta["transport_fallback_used"] is True
    assert meta["fallback_used"] is True


def test_no_fallback_layers():
    only = RecordingProvider(
        "ollama",
        result="plain-ok",
    )

    runtime = _router(only)

    execution = runtime.execute_with_fallback(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        ),
        {AgentCapability.WRITE_CODE},
    )

    meta = execution.result.metadata

    assert meta["router_fallback_used"] is False
    assert meta["transport_fallback_used"] is False
    assert meta["router_primary_provider"] == (
        "ollama"
    )
    assert meta["router_final_provider"] == (
        "ollama"
    )


def test_non_eligible_error_still_raises():
    primary = RecordingProvider(
        "gemini_cli",
        error=ValueError("bad request"),
    )
    secondary = RecordingProvider(
        "ollama",
        result="should-not-run",
    )

    runtime = _router(primary, secondary)

    with pytest.raises(ValueError, match="bad"):
        runtime.execute_with_fallback(
            AgentRequest(
                system_prompt="s",
                user_prompt="u",
            ),
            {AgentCapability.WRITE_CODE},
            preferred_provider="gemini_cli",
        )

    assert secondary.calls == 0


def test_content_only_response_is_not_transport_fallback():
    class FakeModelClient:
        config = {
            "models": {
                "cloud_senior": {
                    "provider": "openai",
                    "model": "cloud-model",
                }
            }
        }

        def complete(self, **kwargs):
            return SimpleNamespace(
                content="provider-ok"
            )

    provider = ModelClientProvider(
        FakeModelClient()
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            model_role="cloud_senior",
        )
    )

    # Adapter identity fill-in is not transport
    # fallback evidence.
    assert result.provider == "model_client"
    assert result.metadata["fallback_used"] is False
    assert (
        result.metadata[
            "transport_fallback_used"
        ]
        is False
    )
