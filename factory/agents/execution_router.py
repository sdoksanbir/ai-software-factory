from dataclasses import dataclass, replace
from typing import Any, Mapping

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
from factory.agents.timeout_policy import (
    ensure_agent_request_timeout,
)


@dataclass(frozen=True)
class AgentRoute:
    agent: AgentDescriptor
    provider: AgentProvider


@dataclass(frozen=True)
class AgentFallbackFailure:
    agent_name: str
    provider_name: str
    error: str
    error_type: str


@dataclass(frozen=True)
class AgentFallbackExecution:
    route: AgentRoute
    result: AgentResult
    failures: tuple[AgentFallbackFailure, ...] = ()


class AgentExecutionRouter:
    def __init__(
        self,
        *,
        agent_router: AgentRouter,
        provider_registry: AgentProviderRegistry,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.agent_router = agent_router
        self.provider_registry = provider_registry
        self.config = config

    def _prepare_request(
        self,
        request: AgentRequest,
    ) -> AgentRequest:
        # Resolve timeout for the request. Do not
        # enforce wall-clock here; providers apply
        # the transport timeout themselves.
        return ensure_agent_request_timeout(
            request,
            config=self.config,
        )

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
            self._prepare_request(request)
        )


    def execute_with_fallback(
        self,
        request: AgentRequest,
        required: set[AgentCapability]
        | frozenset[AgentCapability],
        *,
        preferred_provider: str | None = None,
        policy: AgentFallbackPolicy | None = None,
    ) -> AgentFallbackExecution:
        policy = (
            policy
            or AgentFallbackPolicy()
        )

        request = self._prepare_request(
            request
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

        failures: list[
            AgentFallbackFailure
        ] = []

        failed_providers: set[str] = set()

        primary_provider = (
            candidates[0]
            .provider_name
        )

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

            route = AgentRoute(
                agent=agent,
                provider=provider,
            )

            try:
                result = provider.complete(
                    request
                )

                return AgentFallbackExecution(
                    route=route,
                    result=(
                        self._annotate_router_fallback(
                            result,
                            primary_provider=(
                                primary_provider
                            ),
                            final_provider=(
                                agent.provider_name
                            ),
                            failures=tuple(
                                failures
                            ),
                        )
                    ),
                    failures=tuple(failures),
                )

            except Exception as exc:
                if not is_fallback_eligible_error(
                    exc
                ):
                    raise

                failures.append(
                    AgentFallbackFailure(
                        agent_name=agent.name,
                        provider_name=(
                            agent.provider_name
                        ),
                        error=str(exc),
                        error_type=(
                            type(exc).__name__
                        ),
                    )
                )

                failed_providers.add(
                    provider_name
                )

        details = "; ".join(
            (
                f"{failure.agent_name}"
                f"/{failure.provider_name}: "
                f"{failure.error}"
            )
            for failure in failures
        )

        raise RuntimeError(
            "All fallback agent attempts "
            f"failed: {details}"
        )

    @staticmethod
    def _annotate_router_fallback(
        result: AgentResult,
        *,
        primary_provider: str,
        final_provider: str,
        failures: tuple[
            AgentFallbackFailure,
            ...,
        ],
    ) -> AgentResult:
        metadata = dict(
            result.metadata or {}
        )

        metadata[
            "router_fallback_used"
        ] = bool(failures)

        metadata[
            "router_primary_provider"
        ] = primary_provider

        metadata[
            "router_final_provider"
        ] = final_provider

        # Preserve transport/model-client signal
        # when present; otherwise default false so
        # callers can distinguish layers.
        if (
            "transport_fallback_used"
            not in metadata
        ):
            if "fallback_used" in metadata:
                metadata[
                    "transport_fallback_used"
                ] = bool(
                    metadata["fallback_used"]
                )
            else:
                metadata[
                    "transport_fallback_used"
                ] = False

        return replace(
            result,
            metadata=metadata,
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
        execution = (
            self.execute_with_fallback(
                request,
                required,
                preferred_provider=(
                    preferred_provider
                ),
                policy=policy,
            )
        )

        return execution.result
