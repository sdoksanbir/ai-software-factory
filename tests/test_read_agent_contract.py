from types import SimpleNamespace

from factory.agents.contracts import AgentResult
from factory.read_task_runner import (
    _complete_agent,
)


class FakeModelClient:
    def __init__(self):
        self.calls = []
        self.config = {
            "models": {
                "fast_local": {
                    "provider": "openai",
                    "model": "cloud-model",
                    "timeout_seconds": 55,
                }
            }
        }

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        return SimpleNamespace(
            content="read-ok",
            provider="openrouter",
            model="read-model",
        )


def test_read_complete_agent_returns_agent_result():
    client = FakeModelClient()
    observed = []

    result = _complete_agent(
        client,
        model_role="fast_local",
        system_prompt="system",
        user_prompt="user",
        temperature=0.0,
        timeout=30,
        model_name_override="override-model",
        execution_observer=observed.append,
    )

    assert isinstance(result, AgentResult)
    assert result.content == "read-ok"
    assert result.provider == "openrouter"
    assert result.model == "read-model"
    assert result.metadata[
        "router_fallback_used"
    ] is False
    assert (
        "router_primary_provider"
        in result.metadata
    )

    assert len(observed) == 1
    assert client.calls[0]["timeout"] == 30
    assert client.calls[0][
        "model_name_override"
    ] == "override-model"


def test_read_complete_agent_resolves_role_timeout():
    client = FakeModelClient()

    _complete_agent(
        client,
        model_role="fast_local",
        system_prompt="system",
        user_prompt="user",
    )

    assert client.calls[0]["timeout"] == 55
