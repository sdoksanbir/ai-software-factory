from collections.abc import Iterable

from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)


class AgentRouter:
    def __init__(
        self,
        agents: Iterable[
            AgentDescriptor
        ] | None = None,
    ) -> None:
        self._agents: list[
            AgentDescriptor
        ] = []

        if agents:
            for agent in agents:
                self.register(agent)

    def register(
        self,
        agent: AgentDescriptor,
    ) -> None:
        if any(
            existing.name == agent.name
            for existing in self._agents
        ):
            raise ValueError(
                "Agent is already registered: "
                f"{agent.name}"
            )

        self._agents.append(agent)

    def agents(
        self,
    ) -> tuple[
        AgentDescriptor,
        ...
    ]:
        return tuple(self._agents)

    def matching_agents(
        self,
        required: set[
            AgentCapability
        ]
        | frozenset[
            AgentCapability
        ],
        *,
        preferred_provider: str | None = None,
    ) -> tuple[
        AgentDescriptor,
        ...
    ]:
        provider_filter = None

        if preferred_provider:
            provider_filter = (
                preferred_provider
                .strip()
                .lower()
            )

        matches = []

        for agent in self._agents:
            if not agent.supports(
                required
            ):
                continue

            if (
                provider_filter
                and agent.provider_name
                .strip()
                .lower()
                != provider_filter
            ):
                continue

            matches.append(agent)

        return tuple(matches)

    def route(
        self,
        required: set[
            AgentCapability
        ]
        | frozenset[
            AgentCapability
        ],
        *,
        preferred_provider: str | None = None,
    ) -> AgentDescriptor:
        matches = self.matching_agents(
            required,
            preferred_provider=(
                preferred_provider
            ),
        )

        if matches:
            return matches[0]

        required_names = ", ".join(
            sorted(
                capability.value
                for capability in required
            )
        )

        if not required_names:
            required_names = "<none>"

        provider_text = ""

        if preferred_provider:
            provider_text = (
                " for provider "
                f"'{preferred_provider}'"
            )

        raise LookupError(
            "No agent supports required "
            f"capabilities: {required_names}"
            f"{provider_text}"
        )
