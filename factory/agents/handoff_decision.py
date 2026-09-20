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
        "capability_then_agent_name"
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
    source_agent = str(
        source_agent or ""
    ).strip()

    if not source_agent:
        raise ValueError(
            "source_agent must not be blank"
        )

    reason = str(
        reason or ""
    ).strip()

    if not reason:
        raise ValueError(
            "handoff reason must not be blank"
        )

    required = frozenset(
        required_capabilities
    )

    normalized_provider = None

    if preferred_provider:
        normalized_provider = str(
            preferred_provider
        ).strip()

        if not normalized_provider:
            normalized_provider = None

    matches = router.matching_agents(
        required,
        preferred_provider=(
            normalized_provider
        ),
    )

    source_key = source_agent.casefold()

    eligible = [
        agent
        for agent in matches
        if agent.name.strip().casefold()
        != source_key
    ]

    # Handoff routing must not depend on
    # registration/config insertion order.
    eligible.sort(
        key=lambda agent: (
            agent.name.strip().casefold(),
            agent.provider_name
            .strip()
            .casefold(),
        )
    )

    if not eligible:
        required_names = ", ".join(
            sorted(
                capability.value
                for capability
                in required
            )
        )

        if not required_names:
            required_names = "<none>"

        provider_text = ""

        if normalized_provider:
            provider_text = (
                " for provider "
                f"'{normalized_provider}'"
            )

        raise LookupError(
            "No alternate agent supports "
            "required capabilities: "
            f"{required_names}"
            f"{provider_text}"
        )

    target = eligible[0]

    return HandoffDecision(
        source_agent=source_agent,
        target_agent=target,
        required_capabilities=required,
        reason=reason,
        preferred_provider=(
            normalized_provider
        ),
        eligible_agents=tuple(
            agent.name
            for agent in eligible
        ),
    )
