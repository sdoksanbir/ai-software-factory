from types import SimpleNamespace

from factory.agents.capabilities import (
    AgentCapability,
)
from factory.agents.runtime import (
    build_default_agent_execution_router,
    resolve_provider_for_role,
)


class FakeModelClient:
    def __init__(
        self,
        config,
    ):
        self.config = config
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        return SimpleNamespace(
            content="legacy",
            model="legacy-model",
            provider="legacy",
        )


def test_runtime_registers_ollama_and_compatibility():
    client = FakeModelClient(
        {
            "models": {
                "fast_local": {
                    "provider": "ollama",
                    "model": "llama3.1:8b",
                }
            }
        }
    )

    runtime = (
        build_default_agent_execution_router(
            client
        )
    )

    names = (
        runtime
        .provider_registry
        .names()
    )

    assert "ollama" in names
    assert "model_client" in names


def test_runtime_routes_read_to_ollama():
    client = FakeModelClient(
        {
            "models": {
                "fast_local": {
                    "provider": "ollama",
                    "model": "llama3.1:8b",
                }
            }
        }
    )

    runtime = (
        build_default_agent_execution_router(
            client
        )
    )

    provider_name = (
        resolve_provider_for_role(
            client,
            "fast_local",
            runtime.provider_registry,
        )
    )

    route = runtime.route(
        {
            AgentCapability.READ_REPOSITORY,
        },
        preferred_provider=provider_name,
    )

    assert provider_name == "ollama"
    assert (
        route.agent.provider_name
        == "ollama"
    )
    assert (
        route.provider.provider_name
        == "ollama"
    )


def test_runtime_uses_compatibility_for_unmigrated_provider():
    client = FakeModelClient(
        {
            "models": {
                "cloud_senior": {
                    "provider": "openai",
                    "model": "cloud-model",
                }
            }
        }
    )

    runtime = (
        build_default_agent_execution_router(
            client
        )
    )

    provider_name = (
        resolve_provider_for_role(
            client,
            "cloud_senior",
            runtime.provider_registry,
        )
    )

    assert (
        provider_name
        == "model_client"
    )


def test_model_agents_do_not_claim_run_tests():
    client = FakeModelClient(
        {
            "models": {}
        }
    )

    runtime = (
        build_default_agent_execution_router(
            client
        )
    )

    for agent in (
        runtime.agent_router.agents()
    ):
        assert (
            AgentCapability.RUN_TESTS
            not in agent.capabilities
        )
