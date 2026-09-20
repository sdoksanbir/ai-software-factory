import pytest

from factory.agent_checkpoint_store import (
    list_agent_checkpoints,
)
from factory.agent_execution_store import (
    list_agent_executions,
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
    execute_prepared_handoff,
    prepare_agent_handoff,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import AgentRouter
from factory.task_plan_store import (
    get_task_plan,
    save_task_plan,
)
from factory.task_step_executor import (
    StepExecutionError,
    StepHandlerResult,
    StepHandoffRequest,
    execute_task_plan,
)


class _Provider:
    def __init__(
        self,
        name: str,
        *,
        content: str = "review ok",
        fail: bool = False,
    ) -> None:
        self.provider_name = name
        self.content = content
        self.fail = fail
        self.requests: list[
            AgentRequest
        ] = []

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        self.requests.append(request)

        if self.fail:
            raise RuntimeError(
                "review agent failed"
            )

        return AgentResult(
            content=self.content,
            provider=self.provider_name,
            model=(
                self.provider_name
                + "-model"
            ),
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


def _save_write_plan(
    db_path,
    task_id: str,
):
    save_task_plan(
        task_id,
        [
            {
                "title": "Implement feature",
                "instruction": (
                    "Implement feature.py"
                ),
                "kind": "write",
            }
        ],
        db_path=db_path,
    )


def _write_result():
    return StepHandlerResult(
        output="feature.py written",
        agent_name="coder-agent",
        provider_name="ollama",
        checkpoint_payload={
            "model": "coder-model",
            "files": [
                "feature.py",
            ],
        },
        handoff_request=(
            StepHandoffRequest(
                required_capabilities=(
                    frozenset(
                        {
                            AgentCapability
                            .REVIEW_CODE,
                        }
                    )
                ),
                reason=(
                    "Independent code review"
                ),
                instruction=(
                    "Review the completed code"
                ),
            )
        ),
    )


def _runtime(
    *,
    review_fails: bool = False,
):
    source_provider = _Provider(
        "ollama"
    )

    review_provider = _Provider(
        "gemini_cli",
        content="review completed",
        fail=review_fails,
    )

    registry = AgentProviderRegistry()
    registry.register(source_provider)
    registry.register(review_provider)

    router = AgentRouter(
        [
            _agent(
                "coder-agent",
                "ollama",
                AgentCapability
                .READ_REPOSITORY,
                AgentCapability.WRITE_CODE,
            ),
            _agent(
                "reviewer-agent",
                "gemini_cli",
                AgentCapability.REVIEW_CODE,
            ),
        ]
    )

    return (
        AgentExecutionRouter(
            agent_router=router,
            provider_registry=registry,
        ),
        review_provider,
    )


def test_step_checkpoint_triggers_real_handoff(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-STEP-HANDOFF-1"

    _save_write_plan(
        db_path,
        task_id,
    )

    runtime, review_provider = _runtime()

    def handoff_executor(
        source_checkpoint,
        request,
        actual_db_path,
    ):
        # The executor must call handoff only
        # after the source checkpoint exists.
        checkpoints = (
            list_agent_checkpoints(
                task_id,
                db_path=actual_db_path,
            )
        )

        assert [
            item["checkpoint_id"]
            for item in checkpoints
        ] == [
            source_checkpoint[
                "checkpoint_id"
            ]
        ]

        prepared = prepare_agent_handoff(
            source_checkpoint[
                "checkpoint_id"
            ],
            required_capabilities=(
                request
                .required_capabilities
            ),
            reason=request.reason,
            runtime=runtime,
            preferred_provider=(
                request
                .preferred_provider
            ),
            db_path=actual_db_path,
        )

        executed = execute_prepared_handoff(
            prepared,
            instruction=request.instruction,
            db_path=actual_db_path,
        )

        return executed.target_checkpoint

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=lambda *_: (
            _write_result()
        ),
        verify_handler=lambda *_: None,
        handoff_executor=handoff_executor,
        db_path=db_path,
    )

    assert plan["status"] == "completed"
    assert (
        plan["steps"][0]["status"]
        == "completed"
    )

    checkpoints = list_agent_checkpoints(
        task_id,
        db_path=db_path,
    )

    assert len(checkpoints) == 2

    source_checkpoint = next(
        item
        for item in checkpoints
        if item["agent_name"]
        == "coder-agent"
    )

    review_checkpoint = next(
        item
        for item in checkpoints
        if item["agent_name"]
        == "reviewer-agent"
    )

    assert (
        source_checkpoint["agent_name"]
        == "coder-agent"
    )

    assert (
        source_checkpoint["payload"][
            "handoff_request"
        ]["required_capabilities"]
        == ["review_code"]
    )

    assert (
        review_checkpoint["agent_name"]
        == "reviewer-agent"
    )

    assert (
        review_checkpoint["payload"][
            "source_checkpoint_id"
        ]
        == source_checkpoint[
            "checkpoint_id"
        ]
    )

    handoffs = list_agent_handoffs(
        task_id,
        db_path=db_path,
    )

    assert len(handoffs) == 1
    assert (
        handoffs[0]["status"]
        == "completed"
    )

    executions = list_agent_executions(
        task_id,
        db_path=db_path,
    )

    assert len(executions) == 2

    assert sorted(
        item["status"]
        for item in executions
    ) == [
        "completed",
        "completed",
    ]

    assert len(
        review_provider.requests
    ) == 1


def test_optional_handoff_without_alternate_agent_is_skipped(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-STEP-HANDOFF-2"

    _save_write_plan(
        db_path,
        task_id,
    )

    calls = []

    def no_alternate(
        source_checkpoint,
        request,
        actual_db_path,
    ):
        calls.append(
            source_checkpoint[
                "checkpoint_id"
            ]
        )

        raise LookupError(
            "No alternate reviewer"
        )

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=lambda *_: (
            _write_result()
        ),
        verify_handler=lambda *_: None,
        handoff_executor=no_alternate,
        db_path=db_path,
    )

    assert len(calls) == 1
    assert plan["status"] == "completed"
    assert (
        plan["steps"][0]["status"]
        == "completed"
    )


def test_handoff_execution_failure_fails_step_but_not_source_execution(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-STEP-HANDOFF-3"

    _save_write_plan(
        db_path,
        task_id,
    )

    runtime, _ = _runtime(
        review_fails=True
    )

    def failing_handoff(
        source_checkpoint,
        request,
        actual_db_path,
    ):
        prepared = prepare_agent_handoff(
            source_checkpoint[
                "checkpoint_id"
            ],
            required_capabilities=(
                request
                .required_capabilities
            ),
            reason=request.reason,
            runtime=runtime,
            db_path=actual_db_path,
        )

        return execute_prepared_handoff(
            prepared,
            instruction=request.instruction,
            db_path=actual_db_path,
        ).target_checkpoint

    with pytest.raises(
        StepExecutionError,
        match="review agent failed",
    ):
        execute_task_plan(
            task_id,
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=lambda *_: (
                _write_result()
            ),
            verify_handler=lambda *_: None,
            handoff_executor=(
                failing_handoff
            ),
            db_path=db_path,
        )

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert plan is not None
    assert plan["status"] == "failed"
    assert (
        plan["steps"][0]["status"]
        == "failed"
    )

    executions = list_agent_executions(
        task_id,
        db_path=db_path,
    )

    assert len(executions) == 2

    source_execution = next(
        item
        for item in executions
        if item["agent_name"]
        == "coder-agent"
    )

    review_execution = next(
        item
        for item in executions
        if item["agent_name"]
        == "reviewer-agent"
    )

    # Source work succeeded and its checkpoint
    # remains authoritative even though the
    # downstream handoff failed.
    assert (
        source_execution["status"]
        == "completed"
    )

    assert (
        review_execution["status"]
        == "failed"
    )

    handoffs = list_agent_handoffs(
        task_id,
        db_path=db_path,
    )

    assert len(handoffs) == 1
    assert (
        handoffs[0]["status"]
        == "failed"
    )


def test_task_without_handoff_request_does_not_call_executor(
    tmp_path,
):
    db_path = tmp_path / "factory.db"
    task_id = "TASK-STEP-HANDOFF-4"

    _save_write_plan(
        db_path,
        task_id,
    )

    calls = []

    def handoff_executor(*args):
        calls.append(True)

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=lambda *_: (
            StepHandlerResult(
                output="done",
                agent_name="coder-agent",
                provider_name="ollama",
                checkpoint_payload={
                    "model": "coder-model",
                },
            )
        ),
        verify_handler=lambda *_: None,
        handoff_executor=handoff_executor,
        db_path=db_path,
    )

    assert calls == []
    assert plan["status"] == "completed"
