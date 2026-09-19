import pytest

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
from factory.agents.fallback import (
    AgentFallbackPolicy,
)
from factory.agents.provider_errors import (
    AgentProviderUnavailableError,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import (
    AgentRouter,
)


class FakeProvider:
    def __init__(
        self,
        name: str,
        *,
        result: str | None = None,
        error: str | None = None,
    ):
        self.provider_name = name
        self.result = result
        self.error = error
        self.calls = 0

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        self.calls += 1

        if self.error is not None:
            raise AgentProviderUnavailableError(
                self.error
            )

        return AgentResult(
            content=(
                self.result
                or "ok"
            ),
            provider=self.provider_name,
            model=request.model_name,
        )


def _runtime(
    *,
    gemini_error=None,
    ollama_error=None,
):
    gemini = FakeProvider(
        "gemini_cli",
        result="gemini-ok",
        error=gemini_error,
    )

    ollama = FakeProvider(
        "ollama",
        result="ollama-ok",
        error=ollama_error,
    )

    registry = AgentProviderRegistry()
    registry.register(gemini)
    registry.register(ollama)

    router = AgentRouter(
        [
            AgentDescriptor(
                name="gemini-coder",
                provider_name="gemini_cli",
                capabilities=frozenset(
                    {
                        AgentCapability.WRITE_CODE,
                    }
                ),
            ),
            AgentDescriptor(
                name="ollama-coder",
                provider_name="ollama",
                capabilities=frozenset(
                    {
                        AgentCapability.WRITE_CODE,
                    }
                ),
            ),
        ]
    )

    return (
        AgentExecutionRouter(
            agent_router=router,
            provider_registry=registry,
        ),
        gemini,
        ollama,
    )


def test_fallback_uses_second_provider():
    runtime, gemini, ollama = _runtime(
        gemini_error="gemini failed"
    )

    result = runtime.complete_with_fallback(
        AgentRequest(
            system_prompt="system",
            user_prompt="write code",
            model_role="fast_local",
        ),
        {
            AgentCapability.WRITE_CODE,
        },
        preferred_provider="gemini_cli",
    )

    assert result.content == "ollama-ok"
    assert result.provider == "ollama"

    assert gemini.calls == 1
    assert ollama.calls == 1


def test_preferred_provider_succeeds_without_fallback():
    runtime, gemini, ollama = _runtime()

    result = runtime.complete_with_fallback(
        AgentRequest(
            system_prompt="system",
            user_prompt="write code",
            model_role="fast_local",
        ),
        {
            AgentCapability.WRITE_CODE,
        },
        preferred_provider="gemini_cli",
    )

    assert result.content == "gemini-ok"

    assert gemini.calls == 1
    assert ollama.calls == 0


def test_all_fallback_attempts_fail():
    runtime, gemini, ollama = _runtime(
        gemini_error="gemini failed",
        ollama_error="ollama failed",
    )

    with pytest.raises(
        RuntimeError,
        match="All fallback agent attempts failed",
    ) as exc_info:
        runtime.complete_with_fallback(
            AgentRequest(
                system_prompt="system",
                user_prompt="write code",
                model_role="fast_local",
            ),
            {
                AgentCapability.WRITE_CODE,
            },
            preferred_provider="gemini_cli",
        )

    message = str(
        exc_info.value
    )

    assert "gemini failed" in message
    assert "ollama failed" in message

    assert gemini.calls == 1
    assert ollama.calls == 1


def test_fallback_respects_max_attempts():
    runtime, gemini, ollama = _runtime(
        gemini_error="gemini failed"
    )

    with pytest.raises(
        RuntimeError,
        match="All fallback agent attempts failed",
    ):
        runtime.complete_with_fallback(
            AgentRequest(
                system_prompt="system",
                user_prompt="write code",
                model_role="fast_local",
            ),
            {
                AgentCapability.WRITE_CODE,
            },
            preferred_provider="gemini_cli",
            policy=AgentFallbackPolicy(
                max_attempts=1
            ),
        )

    assert gemini.calls == 1
    assert ollama.calls == 0


def test_unexpected_provider_bug_does_not_fallback():
    runtime, gemini, ollama = _runtime()

    def buggy_complete(request):
        gemini.calls += 1

        raise RuntimeError(
            "invalid provider response shape"
        )

    gemini.complete = buggy_complete

    with pytest.raises(
        RuntimeError,
        match="invalid provider response shape",
    ):
        runtime.complete_with_fallback(
            AgentRequest(
                system_prompt="system",
                user_prompt="write code",
                model_role="fast_local",
            ),
            {
                AgentCapability.WRITE_CODE,
            },
            preferred_provider="gemini_cli",
        )

    assert gemini.calls == 1
    assert ollama.calls == 0



def test_execute_with_fallback_returns_actual_route():
    runtime, gemini, ollama = _runtime(
        gemini_error="gemini failed"
    )

    execution = runtime.execute_with_fallback(
        AgentRequest(
            system_prompt="system",
            user_prompt="write code",
            model_role="fast_local",
        ),
        {
            AgentCapability.WRITE_CODE,
        },
        preferred_provider="gemini_cli",
    )

    assert (
        execution.route.agent.name
        == "ollama-coder"
    )

    assert (
        execution.route.provider.provider_name
        == "ollama"
    )

    assert execution.result.content == "ollama-ok"
    assert execution.result.provider == "ollama"

    assert len(execution.failures) == 1

    failure = execution.failures[0]

    assert failure.agent_name == "gemini-coder"
    assert failure.provider_name == "gemini_cli"
    assert failure.error == "gemini failed"

    assert gemini.calls == 1
    assert ollama.calls == 1


def test_execute_with_fallback_has_no_failures_when_first_succeeds():
    runtime, gemini, ollama = _runtime()

    execution = runtime.execute_with_fallback(
        AgentRequest(
            system_prompt="system",
            user_prompt="write code",
            model_role="fast_local",
        ),
        {
            AgentCapability.WRITE_CODE,
        },
        preferred_provider="gemini_cli",
    )

    assert (
        execution.route.agent.name
        == "gemini-coder"
    )

    assert (
        execution.route.provider.provider_name
        == "gemini_cli"
    )

    assert execution.failures == ()

    assert gemini.calls == 1
    assert ollama.calls == 0
