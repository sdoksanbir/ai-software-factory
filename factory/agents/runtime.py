from typing import Any

from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
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


MODEL_AGENT_CAPABILITIES = frozenset(
    {
        AgentCapability.READ_REPOSITORY,
        AgentCapability.WRITE_CODE,
        AgentCapability.REVIEW_CODE,
        AgentCapability.PLAN_TASK,
    }
)


def build_default_agent_execution_router(
    model_client: Any,
) -> AgentExecutionRouter:
    compatibility_provider = (
        ModelClientProvider(
            model_client
        )
    )

    registry = (
        compatibility_provider.registry
    )

    if not registry.has(
        compatibility_provider.provider_name
    ):
        registry.register(
            compatibility_provider
        )

    agents = []

    for provider_name in registry.names():
        agents.append(
            AgentDescriptor(
                name=(
                    f"{provider_name}-agent"
                ),
                provider_name=provider_name,
                capabilities=(
                    MODEL_AGENT_CAPABILITIES
                ),
            )
        )

    return AgentExecutionRouter(
        agent_router=AgentRouter(
            agents
        ),
        provider_registry=registry,
    )


def resolve_provider_for_role(
    model_client: Any,
    model_role: str,
    registry: AgentProviderRegistry,
) -> str | None:
    config = getattr(
        model_client,
        "config",
        None,
    )

    if isinstance(config, dict):
        models = config.get(
            "models",
            {},
        )

        if isinstance(models, dict):
            role_config = models.get(
                model_role
            )

            if isinstance(
                role_config,
                dict,
            ):
                configured = (
                    role_config.get(
                        "provider"
                    )
                )

                if configured:
                    provider_name = (
                        str(configured)
                        .strip()
                        .lower()
                    )

                    if registry.has(
                        provider_name
                    ):
                        return provider_name

    if registry.has(
        "model_client"
    ):
        return "model_client"

    return None
