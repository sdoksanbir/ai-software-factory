from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.contracts import (
    AgentRequest,
    AgentResult,
)
from factory.agents.execution_router import (
    AgentExecutionRouter,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import AgentRouter


class FakeProvider:
    def __init__(
        self,
        name: str,
        content: str,
    ) -> None:
        self.provider_name = name
        self.content = content
        self.requests = []

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        self.requests.append(request)

        return AgentResult(
            content=self.content,
            provider=self.provider_name,
            model=request.model_name,
        )


def _build_runtime():
    ollama = FakeProvider(
        "ollama",
        "local-result",
    )

    gemini = FakeProvider(
        "gemini_cli",
        "review-result",
    )

    registry = AgentProviderRegistry()
    registry.register(ollama)
    registry.register(gemini)

    router = AgentRouter(
        [
            AgentDescriptor(
                name="local-coder",
                provider_name="ollama",
                capabilities=frozenset(
                    {
                        AgentCapability.READ_REPOSITORY,
                        AgentCapability.WRITE_CODE,
                        AgentCapability.RUN_TESTS,
                    }
                ),
            ),
            AgentDescriptor(
                name="cloud-reviewer",
                provider_name="gemini_cli",
                capabilities=frozenset(
                    {
                        AgentCapability.READ_REPOSITORY,
                        AgentCapability.REVIEW_CODE,
                    }
                ),
            ),
        ]
    )

    runtime = AgentExecutionRouter(
        agent_router=router,
        provider_registry=registry,
    )

    return runtime, ollama, gemini


def test_execution_router_resolves_agent_and_provider():
    runtime, ollama, _ = _build_runtime()

    route = runtime.route(
        {
            AgentCapability.WRITE_CODE,
        }
    )

    assert route.agent.name == "local-coder"
    assert route.provider is ollama


def test_execution_router_completes_with_selected_provider():
    runtime, ollama, _ = _build_runtime()

    result = runtime.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="write code",
            model_role="fast_local",
            model_name="qwen2.5-coder:14b",
        ),
        {
            AgentCapability.WRITE_CODE,
        },
    )

    assert result.content == "local-result"
    assert result.provider == "ollama"
    assert len(ollama.requests) == 1


def test_execution_router_honors_preferred_provider():
    runtime, _, gemini = _build_runtime()

    result = runtime.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="review code",
            model_role="fast_local",
        ),
        {
            AgentCapability.READ_REPOSITORY,
        },
        preferred_provider="gemini_cli",
    )

    assert result.content == "review-result"
    assert result.provider == "gemini_cli"
    assert len(gemini.requests) == 1
