from dataclasses import dataclass

from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.router import AgentRouter


@dataclass(frozen=True)
class AgentFallbackPolicy:
    max_attempts: int = 3
    skip_failed_provider: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(
                "max_attempts must be >= 1"
            )


def build_fallback_candidates(
    router: AgentRouter,
    required: set[AgentCapability]
    | frozenset[AgentCapability],
    *,
    preferred_provider: str | None = None,
    policy: AgentFallbackPolicy | None = None,
) -> tuple[AgentDescriptor, ...]:
    policy = policy or AgentFallbackPolicy()

    all_matches = list(
        router.matching_agents(
            required
        )
    )

    if not all_matches:
        return ()

    preferred = None

    if preferred_provider:
        preferred = (
            preferred_provider
            .strip()
            .lower()
        )

    ordered = []

    if preferred:
        ordered.extend(
            agent
            for agent in all_matches
            if (
                agent.provider_name
                .strip()
                .lower()
                == preferred
            )
        )

    ordered.extend(
        agent
        for agent in all_matches
        if agent not in ordered
    )

    return tuple(
        ordered[
            : policy.max_attempts
        ]
    )


def remaining_fallback_candidates(
    candidates: tuple[
        AgentDescriptor,
        ...
    ],
    *,
    failed_agent: AgentDescriptor,
    policy: AgentFallbackPolicy,
) -> tuple[
    AgentDescriptor,
    ...
]:
    remaining = []

    failed_provider = (
        failed_agent
        .provider_name
        .strip()
        .lower()
    )

    for candidate in candidates:
        if (
            candidate.name
            == failed_agent.name
        ):
            continue

        if (
            policy.skip_failed_provider
            and candidate.provider_name
            .strip()
            .lower()
            == failed_provider
        ):
            continue

        remaining.append(
            candidate
        )

    return tuple(remaining)
