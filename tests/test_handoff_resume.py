import pytest

from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
    list_agent_checkpoints,
)
from factory.agent_execution_store import (
    create_agent_execution,
    list_agent_executions,
)
from factory.agent_handoff_store import (
    get_agent_handoff,
    update_agent_handoff,
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
        self.requests.append(request)

        return AgentResult(
            content="review complete",
            provider=self.provider_name,
            model="review-model",
            metadata={
                "source": "provider"
            },
        )


class _FailOnceProvider(
    _SuccessProvider
):
    def __init__(
        self,
        name: str,
    ) -> None:
        super().__init__(name)
        self.calls = 0

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        self.calls += 1
        self.requests.append(request)

        if self.calls == 1:
            raise RuntimeError(
                "review failed once"
            )

        return AgentResult(
            content="review recovered",
            provider=self.provider_name,
            model="review-model",
            metadata={},
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


def _prepare(
    tmp_path,
    *,
    task_id: str,
    provider,
):
    db_path = tmp_path / (
        task_id + ".db"
    )

    source = create_agent_checkpoint(
        task_id,
        step_index=1,
        agent_name="coder-agent",
        provider_name="ollama",
        status="completed",
        summary="code complete",
        checkpoint_id=(
            "CHK-" + task_id
        ),
        db_path=db_path,
    )

    registry = AgentProviderRegistry()
    registry.register(provider)

    runtime = AgentExecutionRouter(
        agent_router=AgentRouter(
            [
                _agent(
                    "coder-agent",
                    "ollama",
                    AgentCapability
                    .READ_REPOSITORY,
                    AgentCapability
                    .WRITE_CODE,
                ),
                _agent(
                    "reviewer-agent",
                    provider.provider_name,
                    AgentCapability
                    .REVIEW_CODE,
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
        preferred_provider=(
            provider.provider_name
        ),
        db_path=db_path,
    )

    return (
        db_path,
        source,
        prepared,
    )


def test_completed_handoff_replay_does_not_call_provider_twice(
    tmp_path,
):
    provider = _SuccessProvider(
        "gemini_cli"
    )

    (
        db_path,
        _,
        prepared,
    ) = _prepare(
        tmp_path,
        task_id="TASK-HR-1",
        provider=provider,
    )

    first = execute_prepared_handoff(
        prepared,
        instruction="Review code",
        db_path=db_path,
    )

    second = execute_prepared_handoff(
        prepared,
        instruction="Review code",
        db_path=db_path,
    )

    assert len(provider.requests) == 1

    assert (
        second.target_checkpoint[
            "checkpoint_id"
        ]
        == first.target_checkpoint[
            "checkpoint_id"
        ]
    )

    checkpoints = list_agent_checkpoints(
        "TASK-HR-1",
        db_path=db_path,
    )

    assert len(checkpoints) == 2

    executions = list_agent_executions(
        "TASK-HR-1",
        db_path=db_path,
    )

    assert len(executions) == 1
    assert (
        executions[0]["status"]
        == "completed"
    )


def test_existing_target_checkpoint_recovers_crashed_handoff(
    tmp_path,
):
    provider = _SuccessProvider(
        "gemini_cli"
    )

    (
        db_path,
        source,
        prepared,
    ) = _prepare(
        tmp_path,
        task_id="TASK-HR-2",
        provider=provider,
    )

    handoff_id = (
        prepared.handoff[
            "handoff_id"
        ]
    )

    update_agent_handoff(
        handoff_id,
        status="accepted",
        db_path=db_path,
    )

    existing = create_agent_checkpoint(
        "TASK-HR-2",
        step_index=1,
        agent_name="reviewer-agent",
        provider_name="gemini_cli",
        status="completed",
        summary="already reviewed",
        payload={
            "handoff_id": handoff_id,
            "source_checkpoint_id": (
                source["checkpoint_id"]
            ),
            "model": "review-model",
            "result_metadata": {
                "recovered": True,
            },
        },
        checkpoint_id=(
            "CHK-RECOVERED-TARGET"
        ),
        db_path=db_path,
    )

    recovered = execute_prepared_handoff(
        prepared,
        instruction="Review code",
        db_path=db_path,
    )

    assert len(provider.requests) == 0

    assert (
        recovered.target_checkpoint[
            "checkpoint_id"
        ]
        == existing["checkpoint_id"]
    )

    assert (
        recovered.result.content
        == "already reviewed"
    )

    handoff = get_agent_handoff(
        handoff_id,
        db_path=db_path,
    )

    assert handoff is not None
    assert (
        handoff["status"]
        == "completed"
    )


def test_failed_handoff_can_resume(
    tmp_path,
):
    provider = _FailOnceProvider(
        "gemini_cli"
    )

    (
        db_path,
        _,
        prepared,
    ) = _prepare(
        tmp_path,
        task_id="TASK-HR-3",
        provider=provider,
    )

    with pytest.raises(
        RuntimeError,
        match="review failed once",
    ):
        execute_prepared_handoff(
            prepared,
            instruction="Review code",
            db_path=db_path,
        )

    failed_handoff = get_agent_handoff(
        prepared.handoff[
            "handoff_id"
        ],
        db_path=db_path,
    )

    assert failed_handoff is not None
    assert (
        failed_handoff["status"]
        == "failed"
    )

    recovered = execute_prepared_handoff(
        prepared,
        instruction="Review code",
        db_path=db_path,
    )

    assert (
        recovered.result.content
        == "review recovered"
    )

    assert provider.calls == 2

    checkpoints = list_agent_checkpoints(
        "TASK-HR-3",
        db_path=db_path,
    )

    # source + exactly one target
    assert len(checkpoints) == 2

    executions = list_agent_executions(
        "TASK-HR-3",
        db_path=db_path,
    )

    statuses = sorted(
        execution["status"]
        for execution in executions
    )

    assert statuses == [
        "completed",
        "failed",
    ]


def test_interrupted_running_handoff_requires_explicit_retry(
    tmp_path,
):
    provider = _SuccessProvider(
        "gemini_cli"
    )

    (
        db_path,
        source,
        prepared,
    ) = _prepare(
        tmp_path,
        task_id="TASK-HR-4",
        provider=provider,
    )

    handoff_id = (
        prepared.handoff[
            "handoff_id"
        ]
    )

    update_agent_handoff(
        handoff_id,
        status="accepted",
        db_path=db_path,
    )

    create_agent_execution(
        "TASK-HR-4",
        step_index=1,
        handoff_id=handoff_id,
        source_checkpoint_id=(
            source["checkpoint_id"]
        ),
        agent_name="reviewer-agent",
        provider_name="gemini_cli",
        capabilities=[
            "review_code"
        ],
        metadata={
            "execution_type": "handoff"
        },
        db_path=db_path,
    )

    with pytest.raises(
        RuntimeError,
        match="explicit retry required",
    ):
        execute_prepared_handoff(
            prepared,
            instruction="Review code",
            db_path=db_path,
        )

    assert len(provider.requests) == 0

    recovered = execute_prepared_handoff(
        prepared,
        instruction="Review code",
        retry_interrupted=True,
        db_path=db_path,
    )

    assert (
        recovered.result.content
        == "review complete"
    )

    assert len(provider.requests) == 1

    executions = list_agent_executions(
        "TASK-HR-4",
        db_path=db_path,
    )

    statuses = sorted(
        execution["status"]
        for execution in executions
    )

    assert statuses == [
        "completed",
        "failed",
    ]

    checkpoints = list_agent_checkpoints(
        "TASK-HR-4",
        db_path=db_path,
    )

    assert len(checkpoints) == 2
