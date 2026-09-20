from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
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
from factory.agents.handoff_context import (
    HANDOFF_CONTEXT_SCHEMA,
    build_handoff_context,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import AgentRouter


class _Provider:
    def __init__(
        self,
        name: str,
    ) -> None:
        self.provider_name = name

    def complete(self, request):
        raise AssertionError(
            "Provider execution is not "
            "expected in context tests"
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


def test_context_preserves_legacy_fields_and_adds_schema(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    checkpoint = create_agent_checkpoint(
        "TASK-CTX-1",
        step_index=2,
        agent_name="coder-agent",
        provider_name="ollama",
        status="completed",
        summary="Implementation complete",
        payload={
            "attempt": 1,
            "step_kind": "write",
            "model": "qwen2.5-coder:14b",
            "files": [
                "b.py",
                "a.py",
            ],
        },
        checkpoint_id="CHK-CTX-1",
        db_path=db_path,
    )

    target = _agent(
        "reviewer-agent",
        "gemini_cli",
        AgentCapability.REVIEW_CODE,
    )

    context = build_handoff_context(
        checkpoint,
        reason="Independent review",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        target_agent=target,
        db_path=db_path,
    )

    assert (
        context["schema"]
        == HANDOFF_CONTEXT_SCHEMA
    )

    # Backward compatible fields.
    assert (
        context["task_id"]
        == "TASK-CTX-1"
    )
    assert (
        context["source_checkpoint_id"]
        == "CHK-CTX-1"
    )
    assert (
        context["source_agent"]
        == "coder-agent"
    )
    assert (
        context["payload"]["attempt"]
        == 1
    )

    # Structured context.
    assert context["target"] == {
        "agent_name": "reviewer-agent",
        "provider_name": "gemini_cli",
    }

    assert context["handoff"] == {
        "reason": "Independent review",
        "required_capabilities": [
            "review_code"
        ],
    }

    assert context["artifacts"] == {
        "files": [
            "a.py",
            "b.py",
        ],
        "model": "qwen2.5-coder:14b",
    }


def test_context_transfers_optional_diff_and_test_data(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    checkpoint = create_agent_checkpoint(
        "TASK-CTX-2",
        step_index=3,
        agent_name="reviewer-agent",
        provider_name="gemini_cli",
        status="completed",
        summary="Review completed",
        payload={
            "model": "review-model",
            "files": [
                "math_utils.py",
            ],
            "diff": (
                "+def factorial(n): ..."
            ),
            "test_result": {
                "passed": True,
                "command": (
                    "python -m pytest -q"
                ),
            },
        },
        checkpoint_id="CHK-CTX-2",
        db_path=db_path,
    )

    target = _agent(
        "verifier-agent",
        "ollama",
        AgentCapability.RUN_TESTS,
    )

    context = build_handoff_context(
        checkpoint,
        reason="Verify reviewed change",
        required_capabilities={
            AgentCapability.RUN_TESTS,
        },
        target_agent=target,
        db_path=db_path,
    )

    artifacts = context["artifacts"]

    assert artifacts["files"] == [
        "math_utils.py"
    ]

    assert (
        artifacts["diff"]
        == "+def factorial(n): ..."
    )

    assert artifacts["test_result"][
        "passed"
    ] is True


def test_context_contains_checkpoint_lineage(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_checkpoint(
        "TASK-CTX-3",
        step_index=1,
        agent_name="analyst-agent",
        provider_name="ollama",
        status="completed",
        summary="Repository analysed",
        payload={
            "model": "analysis-model",
        },
        checkpoint_id="CHK-ROOT",
        db_path=db_path,
    )

    child = create_agent_checkpoint(
        "TASK-CTX-3",
        step_index=2,
        agent_name="coder-agent",
        provider_name="ollama",
        status="completed",
        summary="Code written",
        payload={
            "model": "coder-model",
            "files": ["feature.py"],
            "source_checkpoint_id": (
                "CHK-ROOT"
            ),
        },
        checkpoint_id="CHK-CHILD",
        db_path=db_path,
    )

    target = _agent(
        "reviewer-agent",
        "gemini_cli",
        AgentCapability.REVIEW_CODE,
    )

    context = build_handoff_context(
        child,
        reason="Review code",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        target_agent=target,
        db_path=db_path,
    )

    ids = [
        item["checkpoint_id"]
        for item
        in context[
            "checkpoint_lineage"
        ]
    ]

    assert ids == [
        "CHK-CHILD",
        "CHK-ROOT",
    ]

    assert (
        context["lineage_state"][
            "complete"
        ]
        is True
    )


def test_prepare_handoff_uses_versioned_context(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    create_agent_checkpoint(
        "TASK-CTX-4",
        step_index=1,
        agent_name="coder-agent",
        provider_name="ollama",
        status="completed",
        summary="Code written",
        payload={
            "files": [
                "math_utils.py"
            ],
            "model": "coder-model",
        },
        checkpoint_id="CHK-CTX-4",
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
                "coder-agent",
                "ollama",
                AgentCapability.WRITE_CODE,
            ),
            _agent(
                "reviewer-agent",
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
        "CHK-CTX-4",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Independent review",
        runtime=runtime,
        db_path=db_path,
    )

    assert (
        prepared.context["schema"]
        == HANDOFF_CONTEXT_SCHEMA
    )

    assert prepared.context[
        "artifacts"
    ]["files"] == [
        "math_utils.py"
    ]

    assert prepared.context[
        "handoff"
    ]["reason"] == (
        "Independent review"
    )

    assert prepared.context[
        "target"
    ]["agent_name"] == (
        "reviewer-agent"
    )
