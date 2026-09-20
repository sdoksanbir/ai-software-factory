from dataclasses import dataclass

from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.router import AgentRouter


@dataclass(frozen=True)
class HandoffDecision:
    source_agent: str
    target_agent: AgentDescriptor
    required_capabilities: frozenset[
        AgentCapability
    ]
    reason: str
    preferred_provider: str | None
    eligible_agents: tuple[str, ...]
    selection_policy: str = (
        "capability_specificity_then_agent_name"
    )


def decide_handoff_target(
    *,
    source_agent: str,
    required_capabilities: set[
        AgentCapability
    ]
    | frozenset[
        AgentCapability
    ],
    reason: str,
    router: AgentRouter,
    preferred_provider: str | None = None,
) -> HandoffDecision:
    source = str(
        source_agent or ""
    ).strip()

    if not source:
        raise ValueError(
            "source_agent must not be blank"
        )

    normalized_reason = str(
        reason or ""
    ).strip()

    if not normalized_reason:
        raise ValueError(
            "handoff reason must not be blank"
        )

    required = frozenset(
        required_capabilities
    )

    normalized_provider = (
        str(
            preferred_provider or ""
        )
        .strip()
        .lower()
        or None
    )

    matches = router.matching_agents(
        required,
        preferred_provider=(
            normalized_provider
        ),
    )

    source_key = source.casefold()

    eligible = [
        agent
        for agent in matches
        if (
            agent.name
            .strip()
            .casefold()
            != source_key
        )
    ]

    # Prefer the most specialized capable
    # agent. A REVIEW-only reviewer therefore
    # wins over a generic catch-all agent.
    # Agent name/provider make ties stable
    # regardless of registration order.
    eligible.sort(
        key=lambda agent: (
            len(
                agent.capabilities
                - required
            ),
            agent.name.casefold(),
            agent.provider_name.casefold(),
        )
    )

    if not eligible:
        required_names = (
            ", ".join(
                sorted(
                    capability.value
                    for capability
                    in required
                )
            )
            or "<none>"
        )

        provider_text = (
            ""
            if normalized_provider is None
            else (
                " for provider "
                f"{normalized_provider}"
            )
        )

        raise LookupError(
            "No alternate agent supports "
            "required capabilities "
            f"{required_names}"
            f"{provider_text}"
        )

    return HandoffDecision(
        source_agent=source,
        target_agent=eligible[0],
        required_capabilities=required,
        reason=normalized_reason,
        preferred_provider=(
            normalized_provider
        ),
        eligible_agents=tuple(
            agent.name
            for agent in eligible
        ),
    )
