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
