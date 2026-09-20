from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from factory.agents.contracts import (
    AgentProvider,
    AgentRequest,
    AgentResult,
)


PROVIDER_ADAPTER_STANDARD_VERSION = "1.0"


class ProviderTransport(
    str,
    Enum,
):
    IN_PROCESS = "in_process"
    HTTP = "http"
    CLI = "cli"


class ProviderFeature(
    str,
    Enum,
):
    SYSTEM_PROMPT = "system_prompt"
    MODEL_OVERRIDE = "model_override"
    TEMPERATURE = "temperature"
    TIMEOUT = "timeout"
    USAGE_METADATA = "usage_metadata"
    STREAMING = "streaming"


@dataclass(frozen=True)
class ProviderDescriptor:
    name: str
    transport: ProviderTransport
    features: frozenset[
        ProviderFeature
    ] = field(
        default_factory=frozenset
    )
    executable: str | None = None
    adapter_version: str = (
        PROVIDER_ADAPTER_STANDARD_VERSION
    )
    metadata: Mapping[
        str,
        Any,
    ] = field(
        default_factory=dict
    )

    def __post_init__(
        self,
    ) -> None:
        normalized_name = str(
            self.name or ""
        ).strip().lower()

        if not normalized_name:
            raise ValueError(
                "Provider descriptor name "
                "cannot be empty."
            )

        object.__setattr__(
            self,
            "name",
            normalized_name,
        )

        if not isinstance(
            self.transport,
            ProviderTransport,
        ):
            try:
                transport = (
                    ProviderTransport(
                        str(
                            self.transport
                        )
                    )
                )
            except ValueError as exc:
                raise ValueError(
                    "Invalid provider transport: "
                    f"{self.transport}"
                ) from exc

            object.__setattr__(
                self,
                "transport",
                transport,
            )

        normalized_features = (
            frozenset(
                (
                    feature
                    if isinstance(
                        feature,
                        ProviderFeature,
                    )
                    else ProviderFeature(
                        str(feature)
                    )
                )
                for feature
                in self.features
            )
        )

        object.__setattr__(
            self,
            "features",
            normalized_features,
        )

        executable = (
            None
            if self.executable is None
            else str(
                self.executable
            ).strip()
            or None
        )

        object.__setattr__(
            self,
            "executable",
            executable,
        )

        adapter_version = str(
            self.adapter_version or ""
        ).strip()

        if not adapter_version:
            raise ValueError(
                "adapter_version cannot "
                "be empty."
            )

        object.__setattr__(
            self,
            "adapter_version",
            adapter_version,
        )

        object.__setattr__(
            self,
            "metadata",
            dict(
                self.metadata
                or {}
            ),
        )

    def supports(
        self,
        feature: ProviderFeature,
    ) -> bool:
        return feature in self.features


@runtime_checkable
class DescribedAgentProvider(
    Protocol,
):
    provider_name: str

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        ...

    def describe(
        self,
    ) -> ProviderDescriptor:
        ...


def legacy_provider_descriptor(
    provider: AgentProvider,
) -> ProviderDescriptor:
    return ProviderDescriptor(
        name=provider.provider_name,
        transport=(
            ProviderTransport.IN_PROCESS
        ),
        features=frozenset(),
        adapter_version="legacy",
        metadata={
            "descriptor_source": (
                "registry_default"
            ),
        },
    )


def resolve_provider_descriptor(
    provider: AgentProvider,
    *,
    explicit: (
        ProviderDescriptor
        | None
    ) = None,
) -> ProviderDescriptor:
    if explicit is not None:
        descriptor = explicit

    else:
        describe = getattr(
            provider,
            "describe",
            None,
        )

        if callable(describe):
            descriptor = describe()

            if not isinstance(
                descriptor,
                ProviderDescriptor,
            ):
                raise TypeError(
                    "Provider describe() must "
                    "return ProviderDescriptor."
                )

        else:
            descriptor = (
                legacy_provider_descriptor(
                    provider
                )
            )

    provider_name = str(
        provider.provider_name
    ).strip().lower()

    if (
        descriptor.name
        != provider_name
    ):
        raise ValueError(
            "Provider descriptor name "
            "must match provider_name: "
            f"{descriptor.name} != "
            f"{provider_name}"
        )

    return descriptor
