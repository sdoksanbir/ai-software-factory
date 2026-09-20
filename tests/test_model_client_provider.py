from types import SimpleNamespace

from factory.agents.contracts import AgentRequest
from factory.agents.providers.model_client import (
    ModelClientProvider,
)


class FakeModelClient:
    def __init__(self):
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        return SimpleNamespace(
            content="provider-ok"
        )


def test_model_client_provider_maps_request():
    client = FakeModelClient()
    provider = ModelClientProvider(client)

    request = AgentRequest(
        system_prompt="system",
        user_prompt="user",
        model_role="fast_local",
        temperature=0.2,
        timeout=45,
        model_name="qwen2.5-coder:14b",
    )

    result = provider.complete(request)

    assert result.content == "provider-ok"
    assert result.provider == "model_client"
    assert result.model == "qwen2.5-coder:14b"
    assert result.metadata["model_role"] == "fast_local"

    assert client.calls == [
        {
            "model_role": "fast_local",
            "system_prompt": "system",
            "user_prompt": "user",
            "temperature": 0.2,
            "timeout": 45,
            "model_name_override": (
                "qwen2.5-coder:14b"
            ),
        }
    ]


def test_model_client_provider_routes_ollama(
    monkeypatch,
):
    client = FakeModelClient()

    client.config = {
        "models": {
            "fast_local": {
                "provider": "ollama",
                "model": "llama3.1:8b",
            }
        }
    }

    captured = {}

    class FakeOllamaProvider:
        provider_name = "ollama"

        def __init__(self, config):
            captured["config"] = config

        def complete(self, request):
            captured["request"] = request

            return SimpleNamespace(
                content="ollama-routed",
                provider="ollama",
                model=request.model_name,
                metadata={},
            )

    monkeypatch.setattr(
        "factory.agents.providers.model_client."
        "OllamaProvider",
        FakeOllamaProvider,
    )

    provider = ModelClientProvider(
        client
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="user",
            model_role="fast_local",
            model_name="qwen2.5-coder:14b",
        )
    )

    assert result.content == "ollama-routed"
    assert result.provider == "ollama"

    # Legacy ModelClient.complete must not run.
    assert client.calls == []

    assert (
        captured["request"].model_name
        == "qwen2.5-coder:14b"
    )


def test_model_client_provider_keeps_legacy_fallback():
    client = FakeModelClient()

    client.config = {
        "models": {
            "cloud_senior": {
                "provider": "openai",
                "model": "cloud-model",
            }
        }
    }

    provider = ModelClientProvider(
        client
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="user",
            model_role="cloud_senior",
        )
    )

    assert result.content == "provider-ok"
    assert len(client.calls) == 1


def test_model_client_provider_uses_custom_registry():
    from factory.agents.provider_registry import (
        AgentProviderRegistry,
    )

    client = FakeModelClient()

    client.config = {
        "models": {
            "fast_local": {
                "provider": "custom",
                "model": "custom-model",
            }
        }
    }

    class CustomProvider:
        provider_name = "custom"

        def complete(self, request):
            return SimpleNamespace(
                content="custom-result",
                provider="custom",
                model=request.model_name,
                metadata={
                    "routed": True,
                },
            )

    registry = AgentProviderRegistry()

    registry.register(
        CustomProvider()
    )

    provider = ModelClientProvider(
        client,
        registry=registry,
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="user",
            model_role="fast_local",
        )
    )

    assert result.content == "custom-result"
    assert result.provider == "custom"

    # A registered provider must bypass the
    # legacy ModelClient compatibility path.
    assert client.calls == []


def test_model_client_provider_routes_antigravity(
    monkeypatch,
):
    client = FakeModelClient()

    client.config = {
        "models": {
            "cloud_senior": {
                "provider": (
                    "antigravity_cli"
                ),
                "model": (
                    "gemini-2.5-pro"
                ),
            }
        },
        "providers": {
            "antigravity_cli": {
                "executable": (
                    "agy-test"
                ),
                "default_timeout": 75,
                "mode": "plan",
            }
        },
    }

    captured = {}

    class FakeAntigravityProvider:
        provider_name = (
            "antigravity_cli"
        )

        def __init__(
            self,
            *,
            executable,
            default_timeout,
            mode,
        ):
            captured[
                "configuration"
            ] = {
                "executable": executable,
                "default_timeout": (
                    default_timeout
                ),
                "mode": mode,
            }

        def complete(
            self,
            request,
        ):
            captured["request"] = (
                request
            )

            return SimpleNamespace(
                content=(
                    "antigravity-result"
                ),
                provider=(
                    "antigravity_cli"
                ),
                model=(
                    request.model_name
                ),
                metadata={
                    "routed": True,
                },
            )

    monkeypatch.setattr(
        "factory.agents.providers."
        "model_client."
        "AntigravityCliProvider",
        FakeAntigravityProvider,
    )

    provider = ModelClientProvider(
        client
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="user",
            model_role="cloud_senior",
            model_name=(
                "gemini-2.5-pro"
            ),
        )
    )

    assert (
        result.content
        == "antigravity-result"
    )

    assert (
        result.provider
        == "antigravity_cli"
    )

    assert (
        captured[
            "configuration"
        ]
        == {
            "executable": "agy-test",
            "default_timeout": 75,
            "mode": "plan",
        }
    )

    assert (
        captured["request"]
        .model_role
        == "cloud_senior"
    )

    # Configured migrated provider must
    # bypass legacy ModelClient.complete.
    assert client.calls == []


def test_antigravity_can_be_explicitly_disabled(
    monkeypatch,
):
    client = FakeModelClient()

    client.config = {
        "models": {
            "cloud_senior": {
                "provider": (
                    "antigravity_cli"
                ),
                "model": (
                    "gemini-2.5-pro"
                ),
            }
        },
        "providers": {
            "antigravity_cli": {
                "enabled": False,
            }
        },
    }

    created = []

    class FakeAntigravityProvider:
        provider_name = (
            "antigravity_cli"
        )

        def __init__(
            self,
            **kwargs,
        ):
            created.append(
                kwargs
            )

    monkeypatch.setattr(
        "factory.agents.providers."
        "model_client."
        "AntigravityCliProvider",
        FakeAntigravityProvider,
    )

    provider = ModelClientProvider(
        client
    )

    assert not provider.registry.has(
        "antigravity_cli"
    )

    assert created == []
