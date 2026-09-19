from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
    get_agent_checkpoint,
)
from factory.agent_handoff_store import (
    list_agent_handoffs,
)
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
from factory.agents.handoff import (
    prepare_agent_handoff,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import AgentRouter


class FakeProvider:
    def __init__(
        self,
        name: str,
    ) -> None:
        self.provider_name = name

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        return AgentResult(
            content="ok",
            provider=self.provider_name,
            model=request.model_name,
        )


def _runtime(
    *,
    source_can_review=False,
):
    ollama = FakeProvider(
        "ollama"
    )

    gemini = FakeProvider(
        "gemini_cli"
    )

    registry = AgentProviderRegistry()
    registry.register(ollama)
    registry.register(gemini)

    source_capabilities = {
        AgentCapability.READ_REPOSITORY,
        AgentCapability.WRITE_CODE,
    }

    if source_can_review:
        source_capabilities.add(
            AgentCapability.REVIEW_CODE
        )

    router = AgentRouter(
        [
            AgentDescriptor(
                name="ollama-agent",
                provider_name="ollama",
                capabilities=frozenset(
                    source_capabilities
                ),
            ),
            AgentDescriptor(
                name="gemini-agent",
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

    return AgentExecutionRouter(
        agent_router=router,
        provider_registry=registry,
    )


def test_prepare_handoff_selects_alternate_agent(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_checkpoint(
        "TASK-HANDOFF-1",
        step_index=2,
        agent_name="ollama-agent",
        provider_name="ollama",
        status="completed",
        summary="Code written",
        payload={
            "files": [
                "math_utils.py",
            ],
        },
        checkpoint_id="CHK-SOURCE-1",
        db_path=db_path,
    )

    prepared = prepare_agent_handoff(
        "CHK-SOURCE-1",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Review generated code",
        runtime=_runtime(),
        db_path=db_path,
    )

    assert (
        prepared.target_agent.name
        == "gemini-agent"
    )

    assert (
        prepared.target_provider.provider_name
        == "gemini_cli"
    )

    assert (
        prepared.handoff["source_agent"]
        == "ollama-agent"
    )

    assert (
        prepared.handoff["target_agent"]
        == "gemini-agent"
    )

    assert prepared.context["payload"] == {
        "files": [
            "math_utils.py",
        ],
    }

    checkpoint = get_agent_checkpoint(
        "CHK-SOURCE-1",
        db_path=db_path,
    )

    assert checkpoint is not None

    assert (
        checkpoint["status"]
        == "handed_off"
    )


def test_handoff_never_selects_source_agent(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_checkpoint(
        "TASK-HANDOFF-2",
        step_index=1,
        agent_name="ollama-agent",
        provider_name="ollama",
        checkpoint_id="CHK-SOURCE-2",
        db_path=db_path,
    )

    prepared = prepare_agent_handoff(
        "CHK-SOURCE-2",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Independent review",
        runtime=_runtime(
            source_can_review=True
        ),
        db_path=db_path,
    )

    assert (
        prepared.target_agent.name
        == "gemini-agent"
    )


def test_handoff_fails_without_alternate_agent(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    provider = FakeProvider(
        "ollama"
    )

    registry = AgentProviderRegistry()
    registry.register(provider)

    runtime = AgentExecutionRouter(
        agent_router=AgentRouter(
            [
                AgentDescriptor(
                    name="ollama-agent",
                    provider_name="ollama",
                    capabilities=frozenset(
                        {
                            AgentCapability.REVIEW_CODE,
                        }
                    ),
                )
            ]
        ),
        provider_registry=registry,
    )

    create_agent_checkpoint(
        "TASK-HANDOFF-3",
        step_index=1,
        agent_name="ollama-agent",
        provider_name="ollama",
        checkpoint_id="CHK-SOURCE-3",
        db_path=db_path,
    )

    try:
        prepare_agent_handoff(
            "CHK-SOURCE-3",
            required_capabilities={
                AgentCapability.REVIEW_CODE,
            },
            reason="Review",
            runtime=runtime,
            db_path=db_path,
        )
    except LookupError as exc:
        assert (
            "No alternate agent"
            in str(exc)
        )
    else:
        raise AssertionError(
            "Expected LookupError"
        )

    assert list_agent_handoffs(
        "TASK-HANDOFF-3",
        db_path=db_path,
    ) == []
