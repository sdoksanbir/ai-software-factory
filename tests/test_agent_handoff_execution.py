import pytest

from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
    list_agent_checkpoints,
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
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import AgentRouter


class FakeProvider:
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
        self.requests = []

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        self.requests.append(request)

        if self.fail:
            raise RuntimeError(
                "target agent failed"
            )

        return AgentResult(
            content=self.content,
            provider=self.provider_name,
            model="review-model",
            metadata={
                "reviewed": True,
            },
        )


def _runtime(
    *,
    fail_target=False,
):
    source_provider = FakeProvider(
        "ollama"
    )

    target_provider = FakeProvider(
        "gemini_cli",
        content="Code review completed",
        fail=fail_target,
    )

    registry = AgentProviderRegistry()
    registry.register(source_provider)
    registry.register(target_provider)

    router = AgentRouter(
        [
            AgentDescriptor(
                name="ollama-agent",
                provider_name="ollama",
                capabilities=frozenset(
                    {
                        AgentCapability.WRITE_CODE,
                    }
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

    runtime = AgentExecutionRouter(
        agent_router=router,
        provider_registry=registry,
    )

    return runtime, target_provider


def test_execute_handoff_creates_target_checkpoint(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_checkpoint(
        "TASK-HX-1",
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
        checkpoint_id="CHK-HX-1",
        db_path=db_path,
    )

    runtime, target_provider = _runtime()

    prepared = prepare_agent_handoff(
        "CHK-HX-1",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Independent code review",
        runtime=runtime,
        db_path=db_path,
    )

    executed = execute_prepared_handoff(
        prepared,
        instruction=(
            "Review the generated code"
        ),
        model_name="review-model",
        db_path=db_path,
    )

    assert (
        executed.handoff["status"]
        == "completed"
    )

    assert (
        executed.result.content
        == "Code review completed"
    )

    assert (
        executed.target_checkpoint[
            "agent_name"
        ]
        == "gemini-agent"
    )

    assert (
        executed.target_checkpoint[
            "provider_name"
        ]
        == "gemini_cli"
    )

    assert (
        executed.target_checkpoint[
            "payload"
        ]["source_checkpoint_id"]
        == "CHK-HX-1"
    )

    assert (
        executed.target_checkpoint[
            "payload"
        ]["handoff_id"]
        == prepared.handoff["handoff_id"]
    )

    assert len(
        target_provider.requests
    ) == 1

    request = target_provider.requests[0]

    assert (
        "math_utils.py"
        in request.user_prompt
    )

    assert (
        request.metadata[
            "source_checkpoint_id"
        ]
        == "CHK-HX-1"
    )

    checkpoints = list_agent_checkpoints(
        "TASK-HX-1",
        db_path=db_path,
    )

    assert len(checkpoints) == 2


def test_failed_target_marks_handoff_failed(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_checkpoint(
        "TASK-HX-2",
        step_index=1,
        agent_name="ollama-agent",
        provider_name="ollama",
        checkpoint_id="CHK-HX-2",
        db_path=db_path,
    )

    runtime, _ = _runtime(
        fail_target=True
    )

    prepared = prepare_agent_handoff(
        "CHK-HX-2",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Review",
        runtime=runtime,
        db_path=db_path,
    )

    with pytest.raises(
        RuntimeError,
        match="target agent failed",
    ):
        execute_prepared_handoff(
            prepared,
            instruction="Review code",
            db_path=db_path,
        )

    handoff = get_agent_handoff(
        prepared.handoff["handoff_id"],
        db_path=db_path,
    )

    assert handoff is not None

    assert (
        handoff["status"]
        == "failed"
    )

    checkpoints = list_agent_checkpoints(
        "TASK-HX-2",
        db_path=db_path,
    )

    assert len(checkpoints) == 1
