import pytest

from factory.agents.capabilities import (
    AgentCapability,
)
from factory.agents.contracts import (
    AgentRequest,
    AgentResult,
)
from factory.agents.provider_adapter import (
    PROVIDER_ADAPTER_STANDARD_VERSION,
    ProviderDescriptor,
    ProviderFeature,
    ProviderTransport,
    resolve_provider_descriptor,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)


class _LegacyProvider:
    provider_name = "legacy"

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        return AgentResult(
            content="ok",
            provider=self.provider_name,
            model=request.model_name,
        )


class _CliProvider:
    provider_name = "gemini_cli"

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        return AgentResult(
            content="ok",
            provider=self.provider_name,
            model=request.model_name,
        )

    def describe(
        self,
    ) -> ProviderDescriptor:
        return ProviderDescriptor(
            name=self.provider_name,
            transport=(
                ProviderTransport.CLI
            ),
            features=frozenset(
                {
                    ProviderFeature
                    .SYSTEM_PROMPT,
                    ProviderFeature
                    .MODEL_OVERRIDE,
                    ProviderFeature
                    .TIMEOUT,
                }
            ),
            executable="gemini",
            metadata={
                "auth": "external_cli",
            },
        )


def test_descriptor_normalizes_provider_name():
    descriptor = ProviderDescriptor(
        name=" GEMINI_CLI ",
        transport=ProviderTransport.CLI,
    )

    assert (
        descriptor.name
        == "gemini_cli"
    )


def test_descriptor_supports_features():
    descriptor = ProviderDescriptor(
        name="gemini_cli",
        transport=ProviderTransport.CLI,
        features=frozenset(
            {
                ProviderFeature.TIMEOUT,
                ProviderFeature.MODEL_OVERRIDE,
            }
        ),
    )

    assert descriptor.supports(
        ProviderFeature.TIMEOUT
    )

    assert descriptor.supports(
        ProviderFeature.MODEL_OVERRIDE
    )

    assert not descriptor.supports(
        ProviderFeature.STREAMING
    )


def test_legacy_provider_gets_backward_compatible_descriptor():
    registry = AgentProviderRegistry()

    provider = _LegacyProvider()

    registry.register(
        provider
    )

    descriptor = registry.descriptor(
        "legacy"
    )

    assert (
        descriptor.name
        == "legacy"
    )

    assert (
        descriptor.transport
        == ProviderTransport.IN_PROCESS
    )

    assert (
        descriptor.adapter_version
        == "legacy"
    )

    assert (
        descriptor.metadata[
            "descriptor_source"
        ]
        == "registry_default"
    )


def test_described_provider_registers_cli_capabilities():
    registry = AgentProviderRegistry()

    provider = _CliProvider()

    registry.register(
        provider
    )

    descriptor = registry.descriptor(
        "GEMINI_CLI"
    )

    assert (
        descriptor.transport
        == ProviderTransport.CLI
    )

    assert (
        descriptor.executable
        == "gemini"
    )

    assert descriptor.supports(
        ProviderFeature.SYSTEM_PROMPT
    )

    assert descriptor.supports(
        ProviderFeature.MODEL_OVERRIDE
    )

    assert descriptor.supports(
        ProviderFeature.TIMEOUT
    )

    assert (
        descriptor.adapter_version
        == PROVIDER_ADAPTER_STANDARD_VERSION
    )


def test_registry_lists_descriptors_in_name_order():
    registry = AgentProviderRegistry()

    class ZProvider(
        _LegacyProvider
    ):
        provider_name = "zeta"

    class AProvider(
        _LegacyProvider
    ):
        provider_name = "alpha"

    registry.register(
        ZProvider()
    )

    registry.register(
        AProvider()
    )

    assert [
        item.name
        for item
        in registry.descriptors()
    ] == [
        "alpha",
        "zeta",
    ]


def test_explicit_descriptor_is_supported():
    registry = AgentProviderRegistry()

    provider = _LegacyProvider()

    registry.register(
        provider,
        descriptor=(
            ProviderDescriptor(
                name="legacy",
                transport=(
                    ProviderTransport.HTTP
                ),
                features=frozenset(
                    {
                        ProviderFeature
                        .TIMEOUT,
                    }
                ),
            )
        ),
    )

    assert (
        registry
        .descriptor(
            "legacy"
        )
        .transport
        == ProviderTransport.HTTP
    )


def test_descriptor_name_must_match_provider_name():
    registry = AgentProviderRegistry()

    with pytest.raises(
        ValueError,
        match="must match provider_name",
    ):
        registry.register(
            _LegacyProvider(),
            descriptor=(
                ProviderDescriptor(
                    name="wrong",
                    transport=(
                        ProviderTransport.CLI
                    ),
                )
            ),
        )


def test_invalid_describe_result_is_rejected():
    class BrokenProvider(
        _LegacyProvider
    ):
        provider_name = "broken"

        def describe(self):
            return {
                "name": "broken"
            }

    with pytest.raises(
        TypeError,
        match="ProviderDescriptor",
    ):
        resolve_provider_descriptor(
            BrokenProvider()
        )


def test_registry_replace_replaces_descriptor_too():
    registry = AgentProviderRegistry()

    registry.register(
        _LegacyProvider()
    )

    replacement = _LegacyProvider()

    registry.register(
        replacement,
        replace=True,
        descriptor=(
            ProviderDescriptor(
                name="legacy",
                transport=(
                    ProviderTransport.CLI
                ),
                executable="replacement-cli",
            )
        ),
    )

    assert (
        registry.get("legacy")
        is replacement
    )

    descriptor = registry.descriptor(
        "legacy"
    )

    assert (
        descriptor.transport
        == ProviderTransport.CLI
    )

    assert (
        descriptor.executable
        == "replacement-cli"
    )
