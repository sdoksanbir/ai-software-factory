from types import SimpleNamespace

from factory.task_step_executor import (
    StepHandlerResult,
)
from factory.task_step_handlers import (
    TaskStepHandlers,
)


def test_read_handler_returns_agent_identity(
    monkeypatch,
    tmp_path,
):
    orchestrator = SimpleNamespace(
        model_client=object(),
    )

    runtime = SimpleNamespace(
        provider_registry=object(),
        route=lambda *args, **kwargs: (
            SimpleNamespace(
                agent=SimpleNamespace(
                    name="ollama-agent"
                ),
                provider=SimpleNamespace(
                    provider_name="ollama"
                ),
            )
        ),
    )

    monkeypatch.setattr(
        "factory.task_step_handlers."
        "build_default_agent_execution_router",
        lambda model_client: runtime,
    )

    monkeypatch.setattr(
        "factory.task_step_handlers."
        "resolve_provider_for_role",
        lambda model_client, role, registry: (
            "ollama"
        ),
    )

    monkeypatch.setattr(
        "factory.task_step_handlers.route_model",
        lambda instruction: SimpleNamespace(
            model="qwen2.5-coder:14b",
            profile="read",
            reason="test",
            code_score=0,
        ),
    )

    monkeypatch.setattr(
        "factory.task_step_handlers.run_read_task",
        lambda **kwargs: "read result",
    )

    handlers = TaskStepHandlers(
        orchestrator,
    )

    result = handlers.read(
        {
            "instruction": (
                "Repository yapisini incele"
            ),
        },
        str(tmp_path),
    )

    assert isinstance(
        result,
        StepHandlerResult,
    )

    assert result.output == "read result"
    assert (
        result.agent_name
        == "ollama-agent"
    )
    assert (
        result.provider_name
        == "ollama"
    )
    assert result.checkpoint_payload == {
        "model": "qwen2.5-coder:14b",
    }
