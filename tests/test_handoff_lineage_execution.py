from factory.agent_checkpoint_store import (
    create_agent_checkpoint,
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
from factory.agents.handoff_context import (
    HANDOFF_CONTEXT_SCHEMA,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.router import AgentRouter


class _SuccessProvider:
    def __init__(
        self,
        name: str,
        content: str,
    ) -> None:
        self.provider_name = name
        self.content = content
        self.requests: list[
            AgentRequest
        ] = []

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        self.requests.append(request)

        return AgentResult(
            content=self.content,
            provider=self.provider_name,
            model=(
                self.provider_name
                + "-model"
            ),
            metadata={
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "cost": 0.0,
                }
            },
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


def test_multi_handoff_preserves_checkpoint_lineage(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    root = create_agent_checkpoint(
        "TASK-LINEAGE-1",
        step_index=1,
        agent_name="coder-agent",
        provider_name="ollama",
        status="completed",
        summary="Implementation complete",
        payload={
            "model": "coder-model",
            "files": [
                "feature.py",
                "tests/test_feature.py",
            ],
        },
        checkpoint_id="CHK-LINEAGE-ROOT",
        db_path=db_path,
    )

    ollama = _SuccessProvider(
        "ollama",
        "verification complete",
    )

    gemini = _SuccessProvider(
        "gemini_cli",
        "review complete",
    )

    registry = AgentProviderRegistry()
    registry.register(ollama)
    registry.register(gemini)

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
            _agent(
                "verifier-agent",
                "ollama",
                AgentCapability.RUN_TESTS,
            ),
        ]
    )

    runtime = AgentExecutionRouter(
        agent_router=router,
        provider_registry=registry,
    )

    # -----------------------------------------------------
    # Coder -> Reviewer
    # -----------------------------------------------------

    review_prepared = prepare_agent_handoff(
        root["checkpoint_id"],
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Independent code review",
        runtime=runtime,
        db_path=db_path,
    )

    review = execute_prepared_handoff(
        review_prepared,
        instruction="Review implementation",
        db_path=db_path,
    )

    review_payload = (
        review
        .target_checkpoint[
            "payload"
        ]
    )

    assert (
        review_payload[
            "source_checkpoint_id"
        ]
        == "CHK-LINEAGE-ROOT"
    )

    assert (
        review_payload[
            "source_agent"
        ]
        == "coder-agent"
    )

    assert (
        review_payload[
            "handoff_context_schema"
        ]
        == HANDOFF_CONTEXT_SCHEMA
    )

    assert (
        review_payload[
            "required_capabilities"
        ]
        == ["review_code"]
    )

    # -----------------------------------------------------
    # Reviewer -> Verifier
    # -----------------------------------------------------

    verify_prepared = prepare_agent_handoff(
        review.target_checkpoint[
            "checkpoint_id"
        ],
        required_capabilities={
            AgentCapability.RUN_TESTS,
        },
        reason="Verify reviewed implementation",
        runtime=runtime,
        db_path=db_path,
    )

    lineage = (
        verify_prepared
        .context[
            "checkpoint_lineage"
        ]
    )

    lineage_ids = [
        item["checkpoint_id"]
        for item in lineage
    ]

    assert lineage_ids == [
        review.target_checkpoint[
            "checkpoint_id"
        ],
        "CHK-LINEAGE-ROOT",
    ]

    assert (
        verify_prepared
        .context[
            "lineage_state"
        ]["complete"]
        is True
    )

    assert (
        verify_prepared
        .context[
            "source"
        ]["agent_name"]
        == "reviewer-agent"
    )

    assert (
        verify_prepared
        .context[
            "target"
        ]["agent_name"]
        == "verifier-agent"
    )

    verify = execute_prepared_handoff(
        verify_prepared,
        instruction=(
            "Verify the reviewed implementation"
        ),
        db_path=db_path,
    )

    final_payload = (
        verify
        .target_checkpoint[
            "payload"
        ]
    )

    assert (
        final_payload[
            "source_checkpoint_id"
        ]
        == review.target_checkpoint[
            "checkpoint_id"
        ]
    )

    assert (
        final_payload[
            "source_agent"
        ]
        == "reviewer-agent"
    )

    assert (
        final_payload[
            "required_capabilities"
        ]
        == ["run_tests"]
    )

    assert len(
        gemini.requests
    ) == 1

    assert len(
        ollama.requests
    ) == 1


def test_next_agent_receives_prior_checkpoint_context(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    source = create_agent_checkpoint(
        "TASK-LINEAGE-2",
        step_index=2,
        agent_name="coder-agent",
        provider_name="ollama",
        status="completed",
        summary="Changed calculator",
        payload={
            "model": "coder-model",
            "files": [
                "calculator.py",
            ],
            "diff": (
                "+def add(a, b): "
                "return a + b"
            ),
            "test_result": {
                "passed": True,
            },
        },
        checkpoint_id="CHK-LINEAGE-2",
        db_path=db_path,
    )

    review_provider = _SuccessProvider(
        "gemini_cli",
        "review ok",
    )

    registry = AgentProviderRegistry()
    registry.register(
        _SuccessProvider(
            "ollama",
            "unused",
        )
    )
    registry.register(
        review_provider
    )

    runtime = AgentExecutionRouter(
        agent_router=AgentRouter(
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
        ),
        provider_registry=registry,
    )

    prepared = prepare_agent_handoff(
        source["checkpoint_id"],
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        reason="Review calculator",
        runtime=runtime,
        db_path=db_path,
    )

    execute_prepared_handoff(
        prepared,
        instruction="Review changes",
        db_path=db_path,
    )

    assert len(
        review_provider.requests
    ) == 1

    prompt = (
        review_provider
        .requests[0]
        .user_prompt
    )

    assert "calculator.py" in prompt
    assert "test_result" in prompt
    assert "passed" in prompt
    assert "checkpoint_lineage" in prompt
    assert HANDOFF_CONTEXT_SCHEMA in prompt
