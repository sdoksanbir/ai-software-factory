from factory.agent_checkpoint_store import (
    list_agent_checkpoints,
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
    save_task_plan,
)
from factory.task_step_executor import (
    StepHandlerResult,
    StepHandoffRequest,
    execute_task_plan,
)


class _Provider:
    def __init__(
        self,
        name: str,
        content: str,
    ) -> None:
        self.provider_name = name
        self.content = content

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
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


def test_analyst_coder_reviewer_verifier_lineage(
    tmp_path,
):
    db_path = tmp_path / "factory.db"

    task_id = "TASK-ROLE-CHAIN-1"

    save_task_plan(
        task_id,
        [
            {
                "title": "Analyse",
                "instruction": (
                    "Analyse repository"
                ),
                "kind": "read",
            },
            {
                "title": "Implement",
                "instruction": (
                    "Implement feature"
                ),
                "kind": "write",
            },
            {
                "title": "Verify",
                "instruction": (
                    "Verify feature"
                ),
                "kind": "verify",
            },
        ],
        db_path=db_path,
    )

    registry = AgentProviderRegistry()

    provider = _Provider(
        "ollama",
        "review complete",
    )

    registry.register(provider)

    runtime = AgentExecutionRouter(
        agent_router=AgentRouter(
            [
                _agent(
                    "ollama-analyst",
                    "ollama",
                    AgentCapability
                    .READ_REPOSITORY,
                    AgentCapability.PLAN_TASK,
                ),
                _agent(
                    "ollama-coder",
                    "ollama",
                    AgentCapability
                    .READ_REPOSITORY,
                    AgentCapability.WRITE_CODE,
                ),
                _agent(
                    "ollama-reviewer",
                    "ollama",
                    AgentCapability.REVIEW_CODE,
                ),
                _agent(
                    "ollama-verifier",
                    "ollama",
                    AgentCapability
                    .READ_REPOSITORY,
                    AgentCapability.RUN_TESTS,
                ),
            ]
        ),
        provider_registry=registry,
    )

    def read_handler(
        step,
        worktree_path,
    ):
        return StepHandlerResult(
            output="analysis complete",
            agent_name="ollama-analyst",
            provider_name="ollama",
            checkpoint_payload={
                "model": "analysis-model",
            },
        )

    def write_handler(
        step,
        worktree_path,
    ):
        return StepHandlerResult(
            output="implementation complete",
            agent_name="ollama-coder",
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
                        "Independent review"
                    ),
                    instruction=(
                        "Review implementation"
                    ),
                )
            ),
        )

    def verify_handler(
        step,
        worktree_path,
    ):
        return StepHandlerResult(
            output="verification complete",
            agent_name="ollama-verifier",
            provider_name="ollama",
            checkpoint_payload={
                "execution_mode": "tool",
                "verification": {
                    "passed": True,
                },
            },
        )

    def handoff_executor(
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

        executed = execute_prepared_handoff(
            prepared,
            instruction=request.instruction,
            db_path=actual_db_path,
        )

        return executed.target_checkpoint

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=read_handler,
        write_handler=write_handler,
        verify_handler=verify_handler,
        handoff_executor=handoff_executor,
        db_path=db_path,
    )

    assert plan["status"] == "completed"

    checkpoints = list_agent_checkpoints(
        task_id,
        db_path=db_path,
    )

    assert len(checkpoints) == 4

    by_agent = {
        checkpoint["agent_name"]:
        checkpoint
        for checkpoint in checkpoints
    }

    analyst = by_agent[
        "ollama-analyst"
    ]

    coder = by_agent[
        "ollama-coder"
    ]

    reviewer = by_agent[
        "ollama-reviewer"
    ]

    verifier = by_agent[
        "ollama-verifier"
    ]

    # Root of the chain.
    assert not analyst[
        "payload"
    ].get(
        "source_checkpoint_id"
    )

    # Analyst -> Coder
    assert (
        coder["payload"][
            "source_checkpoint_id"
        ]
        == analyst["checkpoint_id"]
    )

    # Coder -> Reviewer
    assert (
        reviewer["payload"][
            "source_checkpoint_id"
        ]
        == coder["checkpoint_id"]
    )

    # Reviewer -> Verifier
    assert (
        verifier["payload"][
            "source_checkpoint_id"
        ]
        == reviewer["checkpoint_id"]
    )

    # Verify by walking backwards rather than
    # relying on database/list ordering.
    checkpoint_by_id = {
        checkpoint["checkpoint_id"]:
        checkpoint
        for checkpoint in checkpoints
    }

    chain = []
    current = verifier

    while current is not None:
        chain.append(
            current["agent_name"]
        )

        source_id = (
            current.get(
                "payload",
                {},
            ).get(
                "source_checkpoint_id"
            )
        )

        current = (
            checkpoint_by_id.get(
                source_id
            )
            if source_id
            else None
        )

    assert chain == [
        "ollama-verifier",
        "ollama-reviewer",
        "ollama-coder",
        "ollama-analyst",
    ]
