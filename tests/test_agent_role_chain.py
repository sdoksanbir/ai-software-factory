from types import SimpleNamespace

from factory.agents import runtime as runtime_module
from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.execution_router import (
    AgentRoute,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.task_step_executor import (
    StepHandlerResult,
)
from factory.task_step_handlers import (
    TaskStepHandlers,
)


class _Provider:
    def __init__(
        self,
        name: str,
    ) -> None:
        self.provider_name = name

    def complete(self, request):
        raise AssertionError(
            "Model execution is not expected"
        )


class _CompatibilityProvider:
    def __init__(
        self,
        _model_client,
    ) -> None:
        registry = AgentProviderRegistry()
        registry.register(
            _Provider("ollama")
        )

        self.provider_name = "ollama"
        self.registry = registry


def test_default_runtime_routes_to_four_specialists(
    monkeypatch,
):
    monkeypatch.setattr(
        runtime_module,
        "ModelClientProvider",
        _CompatibilityProvider,
    )

    runtime = (
        runtime_module
        .build_default_agent_execution_router(
            object()
        )
    )

    assert runtime.route(
        {
            AgentCapability.READ_REPOSITORY,
        }
    ).agent.name == "ollama-analyst"

    assert runtime.route(
        {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.WRITE_CODE,
        }
    ).agent.name == "ollama-coder"

    assert runtime.route(
        {
            AgentCapability.REVIEW_CODE,
        }
    ).agent.name == "ollama-reviewer"

    assert runtime.route(
        {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.RUN_TESTS,
        }
    ).agent.name == "ollama-verifier"

    names = {
        agent.name
        for agent
        in runtime.agent_router.agents()
    }

    assert "ollama-agent" in names


class _SandboxResult:
    success = True
    stdout = ""
    stderr = ""


class _Sandbox:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def run_command(
        self,
        worktree_path,
        command,
        timeout_seconds,
    ):
        self.commands.append(command)
        return _SandboxResult()


class _VerifyRuntime:
    def __init__(self) -> None:
        self.provider_registry = (
            AgentProviderRegistry()
        )

        self.provider = _Provider(
            "ollama"
        )

        self.provider_registry.register(
            self.provider
        )

        self.agent = AgentDescriptor(
            name="ollama-verifier",
            provider_name="ollama",
            capabilities=frozenset(
                {
                    AgentCapability.READ_REPOSITORY,
                    AgentCapability.RUN_TESTS,
                }
            ),
        )

    def route(
        self,
        required,
        *,
        preferred_provider=None,
    ):
        assert (
            AgentCapability.RUN_TESTS
            in required
        )

        return AgentRoute(
            agent=self.agent,
            provider=self.provider,
        )


def test_verify_returns_real_verifier_result(
    monkeypatch,
    tmp_path,
):
    import factory.task_step_handlers as module

    runtime = _VerifyRuntime()
    sandbox = _Sandbox()

    monkeypatch.setattr(
        module,
        "build_default_agent_execution_router",
        lambda model_client: runtime,
    )

    monkeypatch.setattr(
        module,
        "resolve_provider_for_role",
        lambda *args, **kwargs: "ollama",
    )

    orchestrator = SimpleNamespace(
        sandbox=sandbox,
        model_client=object(),
    )

    handlers = TaskStepHandlers(
        orchestrator,
        scope_prompt="",
    )

    result = handlers.verify(
        {
            "instruction": (
                "Verify repository"
            )
        },
        str(tmp_path),
    )

    assert isinstance(
        result,
        StepHandlerResult,
    )

    assert (
        result.agent_name
        == "ollama-verifier"
    )

    assert (
        result.provider_name
        == "ollama"
    )

    payload = result.checkpoint_payload

    assert (
        payload["execution_mode"]
        == "tool"
    )

    assert (
        payload["verification"][
            "passed"
        ]
        is True
    )

    assert (
        payload["verification"][
            "compile_command"
        ]
    )

    assert (
        payload["verification"][
            "test_command"
        ]
    )

    assert len(sandbox.commands) == 2
