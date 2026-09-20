import time

from factory.agents.contracts import (
    AgentProvider,
)
from factory.agents.provider_adapter import (
    ProviderDescriptor,
    resolve_provider_descriptor,
)
from factory.agents.provider_health import (
    ProviderHealth,
    ProviderHealthStatus,
    discover_provider,
    probe_provider_descriptor,
)
from factory.agents.provider_discovery import (
    build_runtime_discovery,
    discover_runtime_provider,
    probe_runtime_provider,
)


class AgentProviderRegistry:
    def __init__(
        self,
        *,
        health_cache_ttl_seconds: float = 30.0,
    ) -> None:
        self._providers: dict[
            str,
            AgentProvider,
        ] = {}

        self._descriptors: dict[
            str,
            ProviderDescriptor,
        ] = {}

        self._health_cache_ttl_seconds = max(
            0.0,
            float(
                health_cache_ttl_seconds
            ),
        )

        self._runtime_health_cache: dict[
            str,
            tuple[
                float,
                ProviderHealth,
            ],
        ] = {}

    def _cached_runtime_health(
        self,
        provider_name: str,
    ) -> ProviderHealth | None:
        if (
            self._health_cache_ttl_seconds
            <= 0
        ):
            return None

        cached = (
            self._runtime_health_cache.get(
                provider_name
            )
        )

        if cached is None:
            return None

        cached_at, health = cached

        age = (
            time.monotonic()
            - cached_at
        )

        if (
            age
            < self._health_cache_ttl_seconds
        ):
            return health

        self._runtime_health_cache.pop(
            provider_name,
            None,
        )

        return None

    def _store_runtime_health(
        self,
        provider_name: str,
        health: ProviderHealth,
    ) -> ProviderHealth:
        if (
            self._health_cache_ttl_seconds
            > 0
        ):
            self._runtime_health_cache[
                provider_name
            ] = (
                time.monotonic(),
                health,
            )

        return health

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

        self._runtime_health_cache.pop(
            name,
            None,
        )

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

    def health(
        self,
        provider_name: str,
    ) -> ProviderHealth:
        descriptor = self.descriptor(
            provider_name
        )

        return probe_provider_descriptor(
            descriptor
        )

    def discovery(
        self,
        provider_name: str,
    ) -> dict:
        descriptor = self.descriptor(
            provider_name
        )

        return discover_provider(
            descriptor
        )

    def discover_all(
        self,
    ) -> tuple[dict, ...]:
        return tuple(
            discover_provider(
                self._descriptors[name]
            )
            for name
            in sorted(
                self._descriptors
            )
        )

    def runtime_health(
        self,
        provider_name: str,
        *,
        timeout_seconds: float = 5.0,
        force_refresh: bool = False,
    ) -> ProviderHealth:
        name = self._normalize_name(
            provider_name
        )

        descriptor = self.descriptor(
            name
        )

        if not force_refresh:
            cached = (
                self._cached_runtime_health(
                    name
                )
            )

            if cached is not None:
                return cached

        health = probe_runtime_provider(
            descriptor,
            timeout_seconds=(
                timeout_seconds
            ),
        )

        return self._store_runtime_health(
            name,
            health,
        )

    def invalidate_runtime_health(
        self,
        provider_name: str | None = None,
    ) -> None:
        if provider_name is None:
            self._runtime_health_cache.clear()
            return

        name = self._normalize_name(
            provider_name
        )

        self._runtime_health_cache.pop(
            name,
            None,
        )

    def runtime_discovery(
        self,
        provider_name: str,
        *,
        timeout_seconds: float = 5.0,
        force_refresh: bool = False,
    ) -> dict:
        name = self._normalize_name(
            provider_name
        )

        descriptor = self.descriptor(
            name
        )

        health = self.runtime_health(
            name,
            timeout_seconds=(
                timeout_seconds
            ),
            force_refresh=(
                force_refresh
            ),
        )

        return build_runtime_discovery(
            descriptor,
            health,
        )

    def runtime_health_all(
        self,
        *,
        timeout_seconds: float = 5.0,
        force_refresh: bool = False,
    ) -> tuple[ProviderHealth, ...]:
        results: list[
            ProviderHealth
        ] = []

        for name in sorted(
            self._descriptors
        ):
            descriptor = (
                self._descriptors[name]
            )

            try:
                health = self.runtime_health(
                    name,
                    timeout_seconds=(
                        timeout_seconds
                    ),
                    force_refresh=(
                        force_refresh
                    ),
                )

            except Exception as exc:
                passive = (
                    probe_provider_descriptor(
                        descriptor
                    )
                )

                health = ProviderHealth(
                    provider_name=(
                        descriptor.name
                    ),
                    status=(
                        ProviderHealthStatus
                        .UNAVAILABLE
                    ),
                    transport=(
                        descriptor.transport
                    ),
                    reason=(
                        "Runtime health probe "
                        f"failed unexpectedly: {exc}"
                    ),
                    checked_via=(
                        "runtime_registry"
                    ),
                    executable=(
                        descriptor.executable
                    ),
                    resolved_executable=(
                        passive
                        .resolved_executable
                    ),
                    features=(
                        passive.features
                    ),
                    metadata=dict(
                        descriptor.metadata
                    ),
                    authenticated=None,
                    version=None,
                    latency_ms=None,
                    error_code=(
                        "PROBE_EXCEPTION"
                    ),
                )

            results.append(
                health
            )

        return tuple(results)

    def runtime_discover_all(
        self,
        *,
        timeout_seconds: float = 5.0,
        force_refresh: bool = False,
    ) -> tuple[dict, ...]:
        return tuple(
            self.runtime_discovery(
                name,
                timeout_seconds=(
                    timeout_seconds
                ),
                force_refresh=(
                    force_refresh
                ),
            )
            for name
            in sorted(
                self._descriptors
            )
        )

    def names(self) -> tuple[str, ...]:
        return tuple(
            sorted(self._providers)
        )
