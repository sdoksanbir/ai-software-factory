from pathlib import Path
from types import SimpleNamespace

from factory.agent_telemetry import (
    build_agent_chain_telemetry,
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
from factory.agents.router import (
    AgentRouter,
)
from factory.multi_step_task_runner import (
    run_multi_step_task,
)
from factory.task_plan_store import (
    get_task_plan,
    save_task_plan,
)
from factory.task_step_executor import (
    StepHandlerResult,
    StepHandoffRequest,
    execute_task_plan as real_execute_task_plan,
)


class _Provider:
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
        self.requests.append(
            request
        )

        return AgentResult(
            content=self.content,
            provider=self.provider_name,
            model=(
                self.provider_name
                + "-model"
            ),
            metadata={
                "e2e": True,
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


class _GitManager:
    def __init__(
        self,
        worktree_path: Path,
    ) -> None:
        self.worktree_path = (
            worktree_path
        )
        self.created: list[str] = []

    def create_worktree(
        self,
        task_id: str,
    ):
        self.created.append(
            task_id
        )

        self.worktree_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        return SimpleNamespace(
            path=str(
                self.worktree_path
            ),
            branch=(
                f"agent/{task_id}"
            ),
        )

    def get_diff(
        self,
        worktree_path: str,
    ) -> str:
        assert (
            Path(worktree_path)
            == self.worktree_path
        )

        return (
            "diff --git "
            "a/feature.py "
            "b/feature.py"
        )


class _E2EHandlers:
    def __init__(
        self,
        runtime: AgentExecutionRouter,
        db_path: Path,
    ) -> None:
        self.runtime = runtime
        self.db_path = db_path

    def _execute_role(
        self,
        *,
        required,
        instruction: str,
    ):
        request = AgentRequest(
            model_role="fast_local",
            system_prompt=(
                "Deterministic E2E role "
                "execution."
            ),
            user_prompt=instruction,
            metadata={
                "test": (
                    "agent-chain-e2e"
                ),
            },
        )

        return (
            self.runtime
            .execute_with_fallback(
                request,
                required,
            )
        )

    def read(
        self,
        step,
        worktree_path,
    ):
        execution = self._execute_role(
            required={
                AgentCapability
                .READ_REPOSITORY,
                AgentCapability
                .PLAN_TASK,
            },
            instruction=(
                step["instruction"]
            ),
        )

        return StepHandlerResult(
            output=(
                execution.result.content
            ),
            agent_name=(
                execution.route.agent.name
            ),
            provider_name=(
                execution
                .route
                .provider
                .provider_name
            ),
            checkpoint_payload={
                "model": (
                    execution.result.model
                ),
                "role": "analyst",
            },
        )

    def write(
        self,
        step,
        worktree_path,
    ):
        execution = self._execute_role(
            required={
                AgentCapability.WRITE_CODE,
            },
            instruction=(
                step["instruction"]
            ),
        )

        return StepHandlerResult(
            output=(
                execution.result.content
            ),
            agent_name=(
                execution.route.agent.name
            ),
            provider_name=(
                execution
                .route
                .provider
                .provider_name
            ),
            checkpoint_payload={
                "model": (
                    execution.result.model
                ),
                "role": "coder",
                "files": [
                    "feature.py",
                ],
                "diff": (
                    "diff --git "
                    "a/feature.py "
                    "b/feature.py"
                ),
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
                        "Independent E2E review"
                    ),
                    instruction=(
                        "Review the implementation"
                    ),
                    required=True,
                )
            ),
        )

    def verify(
        self,
        step,
        worktree_path,
    ):
        execution = self._execute_role(
            required={
                AgentCapability.RUN_TESTS,
            },
            instruction=(
                step["instruction"]
            ),
        )

        return StepHandlerResult(
            output=(
                execution.result.content
            ),
            agent_name=(
                execution.route.agent.name
            ),
            provider_name=(
                execution
                .route
                .provider
                .provider_name
            ),
            checkpoint_payload={
                "model": (
                    execution.result.model
                ),
                "role": "verifier",
                "execution_mode": "tool",
                "verification": {
                    "passed": True,
                },
                "test_result": "passed",
            },
        )

    def handoff(
        self,
        source_checkpoint,
        request,
        actual_db_path,
    ):
        assert (
            Path(actual_db_path)
            == self.db_path
        )

        prepared = prepare_agent_handoff(
            source_checkpoint[
                "checkpoint_id"
            ],
            required_capabilities=(
                request
                .required_capabilities
            ),
            reason=request.reason,
            runtime=self.runtime,
            db_path=self.db_path,
        )

        executed = (
            execute_prepared_handoff(
                prepared,
                instruction=(
                    request.instruction
                ),
                db_path=self.db_path,
            )
        )

        return (
            executed.target_checkpoint
        )


def test_production_runner_executes_complete_four_role_chain(
    tmp_path,
    monkeypatch,
):
    from factory import (
        multi_step_task_runner
        as runner_module,
    )

    db_path = tmp_path / "factory.db"

    task_id = "TASK-1960"

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
                    "Verify implementation"
                ),
                "kind": "verify",
            },
        ],
        db_path=db_path,
    )

    analyst_provider = _Provider(
        "analyst_provider",
        "analysis complete",
    )

    coder_provider = _Provider(
        "coder_provider",
        "implementation complete",
    )

    reviewer_provider = _Provider(
        "reviewer_provider",
        "review complete",
    )

    verifier_provider = _Provider(
        "verifier_provider",
        "verification complete",
    )

    registry = AgentProviderRegistry()

    for provider in (
        analyst_provider,
        coder_provider,
        reviewer_provider,
        verifier_provider,
    ):
        registry.register(
            provider
        )

    runtime = AgentExecutionRouter(
        agent_router=AgentRouter(
            [
                _agent(
                    "e2e-analyst",
                    "analyst_provider",
                    AgentCapability
                    .READ_REPOSITORY,
                    AgentCapability
                    .PLAN_TASK,
                ),
                _agent(
                    "e2e-coder",
                    "coder_provider",
                    AgentCapability
                    .READ_REPOSITORY,
                    AgentCapability
                    .WRITE_CODE,
                ),
                _agent(
                    "e2e-reviewer",
                    "reviewer_provider",
                    AgentCapability
                    .REVIEW_CODE,
                ),
                _agent(
                    "e2e-verifier",
                    "verifier_provider",
                    AgentCapability
                    .READ_REPOSITORY,
                    AgentCapability
                    .RUN_TESTS,
                ),
            ]
        ),
        provider_registry=registry,
    )

    handlers = _E2EHandlers(
        runtime,
        db_path,
    )

    # run_multi_step_task must remain the
    # production entry point. We only inject
    # deterministic handlers.
    monkeypatch.setattr(
        runner_module,
        "TaskStepHandlers",
        lambda *args, **kwargs: (
            handlers
        ),
    )

    def execute_with_test_db(
        current_task_id,
        worktree_path,
        **kwargs,
    ):
        return real_execute_task_plan(
            current_task_id,
            worktree_path,
            db_path=db_path,
            **kwargs,
        )

    monkeypatch.setattr(
        runner_module,
        "execute_task_plan",
        execute_with_test_db,
    )

    worktree_path = (
        tmp_path / "worktree"
    )

    git_manager = _GitManager(
        worktree_path
    )

    orchestrator = SimpleNamespace(
        project_path=str(tmp_path),
        git_manager=git_manager,
    )

    approval_calls = []

    def approval_handler(
        current_task_id,
        state_machine,
        wt_result,
        diff_output,
    ):
        approval_calls.append(
            {
                "task_id": (
                    current_task_id
                ),
                "branch": (
                    wt_result.branch
                ),
                "diff": diff_output,
            }
        )

        return "approved"

    result = run_multi_step_task(
        orchestrator=orchestrator,
        prompt=(
            "Implement feature through "
            "the complete multi-agent chain"
        ),
        task_id=task_id,
        max_attempts=2,
        approval_handler=(
            approval_handler
        ),
    )

    assert result == "approved"

    assert git_manager.created == [
        task_id.lower()
    ]

    assert len(
        approval_calls
    ) == 1

    assert (
        approval_calls[0]["task_id"]
        == task_id
    )

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert plan is not None
    assert (
        plan["status"]
        == "completed"
    )

    assert [
        step["status"]
        for step in plan["steps"]
    ] == [
        "completed",
        "completed",
        "completed",
    ]

    telemetry = (
        build_agent_chain_telemetry(
            task_id,
            db_path=db_path,
        )
    )

    assert (
        telemetry["summary"][
            "lineage_ok"
        ]
        is True
    )

    assert (
        telemetry["summary"][
            "lineage_orphan_count"
        ]
        == 0
    )

    assert (
        telemetry["summary"][
            "handoff_count"
        ]
        == 1
    )

    assert (
        telemetry["summary"][
            "completed_handoff_count"
        ]
        == 1
    )

    assert (
        telemetry["summary"][
            "fallback_attempt_count"
        ]
        == 0
    )

    chain = telemetry["chain"]

    assert [
        item["role"]
        for item in chain
    ] == [
        "analyst",
        "coder",
        "reviewer",
        "verifier",
    ]

    assert [
        item["depth"]
        for item in chain
    ] == [
        0,
        1,
        2,
        3,
    ]

    assert [
        item["provider_name"]
        for item in chain
    ] == [
        "analyst_provider",
        "coder_provider",
        "reviewer_provider",
        "verifier_provider",
    ]

    assert len(
        analyst_provider.requests
    ) == 1

    assert len(
        coder_provider.requests
    ) == 1

    assert len(
        reviewer_provider.requests
    ) == 1

    assert len(
        verifier_provider.requests
    ) == 1

    assert (
        telemetry["handoffs"][0][
            "source_agent"
        ]
        == "e2e-coder"
    )

    assert (
        telemetry["handoffs"][0][
            "target_agent"
        ]
        == "e2e-reviewer"
    )

    # The production path must also produce
    # observable executions, not just checkpoints.
    assert (
        telemetry["summary"][
            "execution_count"
        ]
        >= 4
    )
