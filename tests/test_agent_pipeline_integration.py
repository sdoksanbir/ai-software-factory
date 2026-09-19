from types import SimpleNamespace

from factory.agents.capabilities import (
    AgentCapability,
)
from factory.read_task_runner import (
    _complete_agent,
)


class FakeRuntime:
    def __init__(self):
        self.provider_registry = object()
        self.calls = []

    def complete(
        self,
        request,
        required,
        *,
        preferred_provider=None,
    ):
        self.calls.append(
            {
                "request": request,
                "required": required,
                "preferred_provider": (
                    preferred_provider
                ),
            }
        )

        return SimpleNamespace(
            content="ok",
            provider="fake",
            model=request.model_name,
        )


def test_read_complete_uses_execution_router(
    monkeypatch,
):
    runtime = FakeRuntime()
    client = object()

    monkeypatch.setattr(
        "factory.read_task_runner."
        "build_default_agent_execution_router",
        lambda model_client: runtime,
    )

    monkeypatch.setattr(
        "factory.read_task_runner."
        "resolve_provider_for_role",
        lambda model_client, role, registry: (
            "ollama"
        ),
    )

    result = _complete_agent(
        client,
        model_role="fast_local",
        system_prompt="system",
        user_prompt="user",
        model_name_override=(
            "qwen2.5-coder:14b"
        ),
    )

    assert result.content == "ok"
    assert len(runtime.calls) == 1

    call = runtime.calls[0]

    assert call["required"] == {
        AgentCapability.READ_REPOSITORY,
    }

    assert (
        call["preferred_provider"]
        == "ollama"
    )

    assert (
        call["request"].model_name
        == "qwen2.5-coder:14b"
    )
