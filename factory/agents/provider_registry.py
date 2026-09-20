from factory.agents.contracts import (
    AgentProvider,
)
from factory.agents.provider_adapter import (
    ProviderDescriptor,
    resolve_provider_descriptor,
)


class AgentProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[
            str,
            AgentProvider,
        ] = {}

        self._descriptors: dict[
            str,
            ProviderDescriptor,
        ] = {}

    @staticmethod
    def _normalize_name(
        name: str,
    ) -> str:
        normalized = (
            str(name or "")
            .strip()
            .lower()
        )

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
        descriptor: (
            ProviderDescriptor
            | None
        ) = None,
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

        resolved_descriptor = (
            resolve_provider_descriptor(
                provider,
                explicit=descriptor,
            )
        )

        self._providers[name] = provider
        self._descriptors[
            name
        ] = resolved_descriptor

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

    def descriptor(
        self,
        provider_name: str,
    ) -> ProviderDescriptor:
        name = self._normalize_name(
            provider_name
        )

        if name not in self._descriptors:
            # Keep unknown-provider behavior
            # aligned with get().
            self.get(name)

            raise RuntimeError(
                "Provider descriptor missing: "
                f"{name}"
            )

        return self._descriptors[name]

    def descriptors(
        self,
    ) -> tuple[
        ProviderDescriptor,
        ...,
    ]:
        return tuple(
            self._descriptors[name]
            for name
            in sorted(
                self._descriptors
            )
        )

    def names(self) -> tuple[str, ...]:
        return tuple(
            sorted(self._providers)
        )
