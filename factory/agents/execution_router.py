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
from factory.agents.fallback import (
    AgentFallbackPolicy,
    build_fallback_candidates,
)
from factory.agents.provider_errors import (
    is_fallback_eligible_error,
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


    def complete_with_fallback(
        self,
        request: AgentRequest,
        required: set[AgentCapability]
        | frozenset[AgentCapability],
        *,
        preferred_provider: str | None = None,
        policy: AgentFallbackPolicy | None = None,
    ) -> AgentResult:
        policy = (
            policy
            or AgentFallbackPolicy()
        )

        candidates = (
            build_fallback_candidates(
                self.agent_router,
                required,
                preferred_provider=(
                    preferred_provider
                ),
                policy=policy,
            )
        )

        if not candidates:
            required_names = ", ".join(
                sorted(
                    capability.value
                    for capability
                    in required
                )
            )

            raise LookupError(
                "No fallback candidates support "
                "required capabilities: "
                f"{required_names}"
            )

        failures = []
        failed_providers = set()

        for agent in candidates:
            provider_name = (
                agent.provider_name
                .strip()
                .lower()
            )

            if (
                policy.skip_failed_provider
                and provider_name
                in failed_providers
            ):
                continue

            provider = (
                self.provider_registry.get(
                    agent.provider_name
                )
            )

            try:
                return provider.complete(
                    request
                )

            except Exception as exc:
                if not is_fallback_eligible_error(
                    exc
                ):
                    raise

                failures.append(
                    (
                        agent.name,
                        agent.provider_name,
                        str(exc),
                    )
                )

                failed_providers.add(
                    provider_name
                )

        details = "; ".join(
            (
                f"{agent_name}"
                f"/{provider_name}: "
                f"{error}"
            )
            for (
                agent_name,
                provider_name,
                error,
            ) in failures
        )

        raise RuntimeError(
            "All fallback agent attempts "
            f"failed: {details}"
        )
