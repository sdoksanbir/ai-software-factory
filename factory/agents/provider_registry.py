from factory.agents.contracts import (
    AgentProvider,
)


class AgentProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[
            str,
            AgentProvider,
        ] = {}

    @staticmethod
    def _normalize_name(
        name: str,
    ) -> str:
        normalized = name.strip().lower()

        if not normalized:
            raise ValueError(
                "Provider name cannot be empty."
            )

        return normalized

    def register(
        self,
        provider: AgentProvider,
        *,
        replace: bool = False,
    ) -> None:
        name = self._normalize_name(
            provider.provider_name
        )

        if (
            name in self._providers
            and not replace
        ):
            raise ValueError(
                "Provider is already registered: "
                f"{name}"
            )

        self._providers[name] = provider

    def has(
        self,
        provider_name: str,
    ) -> bool:
        name = self._normalize_name(
            provider_name
        )

        return name in self._providers

    def get(
        self,
        provider_name: str,
    ) -> AgentProvider:
        name = self._normalize_name(
            provider_name
        )

        if name not in self._providers:
            available = ", ".join(
                sorted(self._providers)
            )

            if not available:
                available = "<none>"

            raise KeyError(
                "Provider is not registered: "
                f"{name}. "
                "Available providers: "
                f"{available}"
            )

        return self._providers[name]

    def names(self) -> tuple[str, ...]:
        return tuple(
            sorted(self._providers)
        )
