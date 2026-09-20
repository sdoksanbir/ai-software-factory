from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
)
from factory.agent_execution_store import (
    list_agent_executions,
)
from factory.agent_handoff_store import (
    get_agent_handoff,
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
    execute_prepared_handoff,
    prepare_agent_handoff,
)
from factory.agents.provider_errors import (
    AgentProviderUnavailableError,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import AgentRouter


class _SuccessProvider:
    def __init__(
        self,
        name: str,
    ) -> None:
        self.provider_name = name
        self.requests = []

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        self.requests.append(
            request
        )

        return AgentResult(
            content=(
                f"{self.provider_name} review ok"
            ),
            provider=self.provider_name,
            model=(
                self.provider_name
                + "-model"
            ),
            metadata={},
        )


class _UnavailableProvider:
    def __init__(
        self,
        name: str,
    ) -> None:
        self.provider_name = name
        self.requests = []

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        self.requests.append(
            request
        )

        raise AgentProviderUnavailableError(
            f"{self.provider_name} unavailable"
        )


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


def test_handoff_falls_back_and_records_actual_route(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    source = create_agent_checkpoint(
        "TASK-HF-1",
        step_index=2,
        agent_name="ollama-coder",
        provider_name="ollama",
        status="completed",
        summary="Code complete",
        checkpoint_id="CHK-HF-1",
        db_path=db_path,
    )

    ollama = _SuccessProvider(
        "ollama"
    )

    gemini = _UnavailableProvider(
        "gemini_cli"
    )

    codex = _SuccessProvider(
        "codex"
    )

    registry = AgentProviderRegistry()
    registry.register(ollama)
    registry.register(gemini)
    registry.register(codex)

    runtime = AgentExecutionRouter(
        agent_router=AgentRouter(
            [
                _agent(
                    "ollama-coder",
                    "ollama",
                    AgentCapability.READ_REPOSITORY,
                    AgentCapability.WRITE_CODE,
                ),
                _agent(
                    "gemini-reviewer",
                    "gemini_cli",
                    AgentCapability.REVIEW_CODE,
                ),
                _agent(
                    "codex-reviewer",
                    "codex",
                    AgentCapability.REVIEW_CODE,
                ),
            ]
        ),
        provider_registry=registry,
    )

    prepared = prepare_agent_handoff(
        source["checkpoint_id"],
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Independent review",
        runtime=runtime,
        preferred_provider="gemini_cli",
        db_path=db_path,
    )

    assert (
        prepared.target_agent.name
        == "gemini-reviewer"
    )

    executed = execute_prepared_handoff(
        prepared,
        instruction="Review the change",
        db_path=db_path,
    )

    checkpoint = (
        executed.target_checkpoint
    )

    assert (
        checkpoint["agent_name"]
        == "codex-reviewer"
    )

    assert (
        checkpoint["provider_name"]
        == "codex"
    )

    payload = checkpoint["payload"]

    assert (
        payload["planned_target_agent"]
        == "gemini-reviewer"
    )

    assert (
        payload["planned_target_provider"]
        == "gemini_cli"
    )

    assert payload["fallback_used"] is True

    assert len(
        payload["fallback_attempts"]
    ) == 1

    assert (
        payload["fallback_attempts"][0][
            "provider_name"
        ]
        == "gemini_cli"
    )

    assert len(gemini.requests) == 1
    assert len(codex.requests) == 1

    handoff = get_agent_handoff(
        prepared.handoff["handoff_id"],
        db_path=db_path,
    )

    assert handoff is not None
    assert (
        handoff["status"]
        == "completed"
    )

    executions = list_agent_executions(
        "TASK-HF-1",
        db_path=db_path,
    )

    failed = [
        item
        for item in executions
        if item["status"] == "failed"
    ]

    completed = [
        item
        for item in executions
        if item["status"] == "completed"
    ]

    assert len(failed) == 1
    assert len(completed) == 1

    assert (
        failed[0]["provider_name"]
        == "gemini_cli"
    )

    assert (
        completed[0]["provider_name"]
        == "codex"
    )

    assert (
        completed[0]["agent_name"]
        == "codex-reviewer"
    )


def test_handoff_fallback_never_returns_to_source_agent(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    source = create_agent_checkpoint(
        "TASK-HF-2",
        step_index=1,
        agent_name="source-agent",
        provider_name="ollama",
        status="completed",
        summary="Source work",
        checkpoint_id="CHK-HF-2",
        db_path=db_path,
    )

    source_provider = _SuccessProvider(
        "ollama"
    )

    failed_provider = _UnavailableProvider(
        "gemini_cli"
    )

    backup_provider = _SuccessProvider(
        "codex"
    )

    registry = AgentProviderRegistry()

    registry.register(
        source_provider
    )

    registry.register(
        failed_provider
    )

    registry.register(
        backup_provider
    )

    runtime = AgentExecutionRouter(
        agent_router=AgentRouter(
            [
                # Source intentionally also has
                # REVIEW_CODE. Fallback still
                # must never return to it.
                _agent(
                    "source-agent",
                    "ollama",
                    AgentCapability.REVIEW_CODE,
                ),
                _agent(
                    "gemini-reviewer",
                    "gemini_cli",
                    AgentCapability.REVIEW_CODE,
                ),
                _agent(
                    "codex-reviewer",
                    "codex",
                    AgentCapability.REVIEW_CODE,
                ),
            ]
        ),
        provider_registry=registry,
    )

    prepared = prepare_agent_handoff(
        source["checkpoint_id"],
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Independent review",
        runtime=runtime,
        preferred_provider="gemini_cli",
        db_path=db_path,
    )

    executed = execute_prepared_handoff(
        prepared,
        instruction="Review",
        db_path=db_path,
    )

    assert (
        executed.target_checkpoint[
            "agent_name"
        ]
        == "codex-reviewer"
    )

    assert len(
        source_provider.requests
    ) == 0

    assert len(
        failed_provider.requests
    ) == 1

    assert len(
        backup_provider.requests
    ) == 1
