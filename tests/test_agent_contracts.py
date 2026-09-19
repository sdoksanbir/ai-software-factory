from factory.agents.contracts import (
    AgentProvider,
    AgentRequest,
    AgentResult,
)


class FakeProvider:
    provider_name = "fake"

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        return AgentResult(
            content=request.user_prompt,
            provider=self.provider_name,
            model=request.model_name,
        )


def test_agent_request_defaults():
    request = AgentRequest(
        system_prompt="system",
        user_prompt="user",
    )

    assert request.model_role == "fast_local"
    assert request.temperature is None
    assert request.timeout is None
    assert request.model_name is None
    assert request.metadata == {}


def test_agent_provider_contract():
    provider = FakeProvider()

    assert isinstance(provider, AgentProvider)

    result = provider.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="hello",
            model_name="test-model",
        )
    )

    assert result.content == "hello"
    assert result.provider == "fake"
    assert result.model == "test-model"
