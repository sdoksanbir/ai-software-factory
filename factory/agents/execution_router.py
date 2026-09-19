from dataclasses import dataclass

from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.contracts import (
    AgentProvider,
    AgentRequest,
    AgentResult,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import AgentRouter


@dataclass(frozen=True)
class AgentRoute:
    agent: AgentDescriptor
    provider: AgentProvider


class AgentExecutionRouter:
    def __init__(
        self,
        *,
        agent_router: AgentRouter,
        provider_registry: AgentProviderRegistry,
    ) -> None:
        self.agent_router = agent_router
        self.provider_registry = provider_registry

    def route(
        self,
        required: set[AgentCapability]
        | frozenset[AgentCapability],
        *,
        preferred_provider: str | None = None,
    ) -> AgentRoute:
        agent = self.agent_router.route(
            required,
            preferred_provider=preferred_provider,
        )

        provider = self.provider_registry.get(
            agent.provider_name
        )

        return AgentRoute(
            agent=agent,
            provider=provider,
        )

    def complete(
        self,
        request: AgentRequest,
        required: set[AgentCapability]
        | frozenset[AgentCapability],
        *,
        preferred_provider: str | None = None,
    ) -> AgentResult:
        route = self.route(
            required,
            preferred_provider=preferred_provider,
        )

        return route.provider.complete(
            request
        )
