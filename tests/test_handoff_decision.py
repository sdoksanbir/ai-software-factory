import pytest

from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
)
from factory.agent_handoff_store import (
    get_agent_handoff,
)
from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.execution_router import (
    AgentExecutionRouter,
)
from factory.agents.handoff import (
    prepare_agent_handoff,
)
from factory.agents.handoff_decision import (
    decide_handoff_target,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import AgentRouter


def _agent(
    name: str,
    provider: str,
    *capabilities: AgentCapability,
) -> AgentDescriptor:
    return AgentDescriptor(
        name=name,
        provider_name=provider,
        capabilities=frozenset(
            capabilities
        ),
    )


def test_handoff_selection_is_deterministic():
    source = _agent(
        "source-agent",
        "ollama",
        AgentCapability.WRITE_CODE,
    )

    alpha = _agent(
        "alpha-reviewer",
        "gemini_cli",
        AgentCapability.REVIEW_CODE,
    )

    zeta = _agent(
        "zeta-reviewer",
        "ollama",
        AgentCapability.REVIEW_CODE,
    )

    first_router = AgentRouter(
        [
            source,
            zeta,
            alpha,
        ]
    )

    second_router = AgentRouter(
        [
            alpha,
            source,
            zeta,
        ]
    )

    first = decide_handoff_target(
        source_agent="source-agent",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Independent review",
        router=first_router,
    )

    second = decide_handoff_target(
        source_agent="source-agent",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Independent review",
        router=second_router,
    )

    assert (
        first.target_agent.name
        == "alpha-reviewer"
    )

    assert (
        second.target_agent.name
        == "alpha-reviewer"
    )

    assert first.eligible_agents == (
        "alpha-reviewer",
        "zeta-reviewer",
    )

    assert (
        first.selection_policy
        == "capability_specificity_then_agent_name"
    )


def test_handoff_respects_preferred_provider():
    router = AgentRouter(
        [
            _agent(
                "ollama-reviewer",
                "ollama",
                AgentCapability.REVIEW_CODE,
            ),
            _agent(
                "gemini-reviewer",
                "gemini_cli",
                AgentCapability.REVIEW_CODE,
            ),
        ]
    )

    decision = decide_handoff_target(
        source_agent="coder-agent",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Use Gemini review",
        router=router,
        preferred_provider="gemini_cli",
    )

    assert (
        decision.target_agent.name
        == "gemini-reviewer"
    )

    assert (
        decision.preferred_provider
        == "gemini_cli"
    )


def test_handoff_never_targets_source_agent():
    router = AgentRouter(
        [
            _agent(
                "reviewer",
                "ollama",
                AgentCapability.REVIEW_CODE,
            ),
        ]
    )

    with pytest.raises(
        LookupError,
        match="No alternate agent",
    ):
        decide_handoff_target(
            source_agent="reviewer",
            required_capabilities={
                AgentCapability.REVIEW_CODE,
            },
            reason="Review",
            router=router,
        )


def test_handoff_requires_reason():
    router = AgentRouter(
        [
            _agent(
                "reviewer",
                "ollama",
                AgentCapability.REVIEW_CODE,
            ),
        ]
    )

    with pytest.raises(
        ValueError,
        match="reason must not be blank",
    ):
        decide_handoff_target(
            source_agent="coder",
            required_capabilities={
                AgentCapability.REVIEW_CODE,
            },
            reason="   ",
            router=router,
        )


class _Provider:
    def __init__(
        self,
        name: str,
    ) -> None:
        self.provider_name = name

    def complete(self, request):
        raise AssertionError(
            "Provider must not execute "
            "during handoff preparation"
        )


def test_prepare_handoff_records_decision_reason(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_checkpoint(
        "TASK-HD-1",
        step_index=1,
        agent_name="coder-agent",
        provider_name="ollama",
        status="completed",
        summary="Implementation completed",
        checkpoint_id="CHK-HD-1",
        db_path=db_path,
    )

    registry = AgentProviderRegistry()
    registry.register(
        _Provider("ollama")
    )
    registry.register(
        _Provider("gemini_cli")
    )

    router = AgentRouter(
        [
            _agent(
                "zeta-reviewer",
                "ollama",
                AgentCapability.REVIEW_CODE,
            ),
            _agent(
                "alpha-reviewer",
                "gemini_cli",
                AgentCapability.REVIEW_CODE,
            ),
        ]
    )

    runtime = AgentExecutionRouter(
        agent_router=router,
        provider_registry=registry,
    )

    prepared = prepare_agent_handoff(
        "CHK-HD-1",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Independent quality review",
        runtime=runtime,
        db_path=db_path,
    )

    assert (
        prepared.target_agent.name
        == "alpha-reviewer"
    )

    stored = get_agent_handoff(
        prepared.handoff["handoff_id"],
        db_path=db_path,
    )

    assert stored is not None

    assert (
        stored["target_agent"]
        == "alpha-reviewer"
    )

    assert (
        stored["reason"]
        == "Independent quality review"
    )
