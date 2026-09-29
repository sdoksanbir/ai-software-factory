"""Phase 4G cross-layer provider/runtime contract matrix.

Production code is not exercised against real
providers. Fakes keep the suite offline.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

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
from factory.agents.provider_errors import (
    AgentProviderUnavailableError,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.providers.model_client import (
    ModelClientProvider,
)
from factory.agents.router import AgentRouter
from factory.agents.runtime import (
    build_default_agent_descriptors,
    build_default_agent_execution_router,
)
from factory.agents.timeout_policy import (
    DEFAULT_AGENT_TIMEOUT,
)
from factory.models import ModelResponse
from factory.read_task_runner import (
    _complete_agent,
)
from factory.task_planner import (
    PLANNER_MODEL_ROLE,
    _complete_planner,
    build_task_plan,
)
from factory.task_step_handlers import (
    TaskStepHandlers,
)
from factory.orchestrator import Orchestrator


PLAN_JSON = json.dumps(
    {
        "summary": "Matrix",
        "steps": [
            {
                "title": "Read",
                "instruction": "Inspect.",
                "kind": "read",
            },
            {
                "title": "Write",
                "instruction": "Change.",
                "kind": "write",
            },
            {
                "title": "Verify",
                "instruction": "Test.",
                "kind": "verify",
            },
        ],
    }
)

COMPLEX_PROMPT = (
    "Backend API ekle, frontend'i bagla "
    "ve testlerini yaz."
)


class RecordingClient:
    def __init__(
        self,
        response,
        *,
        config=None,
    ):
        self.response = response
        self.config = config
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class StubProvider:
    def __init__(
        self,
        name: str,
        *,
        content: str = "ok",
        error: Exception | None = None,
        metadata: dict | None = None,
    ):
        self.provider_name = name
        self.content = content
        self.error = error
        self.metadata = metadata or {}
        self.requests = []

    def complete(self, request: AgentRequest):
        self.requests.append(request)

        if self.error is not None:
            raise self.error

        return AgentResult(
            content=self.content,
            provider=self.provider_name,
            model=request.model_name,
            metadata=dict(self.metadata),
        )


def _router(*providers: StubProvider):
    registry = AgentProviderRegistry()
    agents = []

    for provider in providers:
        registry.register(provider)
        agents.append(
            AgentDescriptor(
                name=f"{provider.provider_name}-coder",
                provider_name=provider.provider_name,
                capabilities=frozenset(
                    {
                        AgentCapability.WRITE_CODE,
                        AgentCapability.READ_REPOSITORY,
                    }
                ),
            )
        )

    return AgentExecutionRouter(
        agent_router=AgentRouter(agents),
        provider_registry=registry,
        config={
            "models": {
                "fast_local": {
                    "timeout_seconds": 90,
                }
            }
        },
    )


# --- Timeout matrix ---


def test_timeout_matrix_explicit_across_layers():
    client = RecordingClient(
        SimpleNamespace(content=PLAN_JSON)
    )

    _complete_planner(
        client,
        system_prompt="s",
        user_prompt="u",
        model_name="m",
        timeout=30,
    )
    assert client.calls[-1]["timeout"] == 30

    client.calls.clear()
    ModelClientProvider(client).complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            timeout=30,
        )
    )
    assert client.calls[-1]["timeout"] == 30

    primary = StubProvider("ollama")
    runtime = _router(primary)
    runtime.complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            timeout=30,
        ),
        {AgentCapability.WRITE_CODE},
    )
    assert primary.requests[-1].timeout == 30


def test_timeout_matrix_role_and_default():
    role_client = RecordingClient(
        SimpleNamespace(content="ok"),
        config={
            "models": {
                "fast_local": {
                    "provider": "openai",
                    "model": "x",
                    "timeout_seconds": 75,
                }
            }
        },
    )

    ModelClientProvider(role_client).complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            model_role="fast_local",
        )
    )
    assert role_client.calls[-1]["timeout"] == 75

    default_client = RecordingClient(
        SimpleNamespace(content="ok")
    )
    ModelClientProvider(default_client).complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        )
    )
    assert default_client.calls[-1][
        "timeout"
    ] == DEFAULT_AGENT_TIMEOUT

    primary = StubProvider("ollama")
    runtime = _router(primary)
    runtime.complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        ),
        {AgentCapability.WRITE_CODE},
    )
    assert primary.requests[-1].timeout == 90


# --- Fallback matrix ---


def test_fallback_matrix_no_fallback():
    primary = StubProvider("ollama", content="ok")
    runtime = _router(primary)

    execution = runtime.execute_with_fallback(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        ),
        {AgentCapability.WRITE_CODE},
        preferred_provider="ollama",
    )

    meta = execution.result.metadata
    assert meta["router_fallback_used"] is False
    assert meta["transport_fallback_used"] is False
    assert meta["router_primary_provider"] == (
        "ollama"
    )
    assert meta["router_final_provider"] == (
        "ollama"
    )


def test_fallback_matrix_router_only():
    primary = StubProvider(
        "gemini_cli",
        error=AgentProviderUnavailableError(
            "down"
        ),
    )
    secondary = StubProvider(
        "ollama",
        content="secondary",
    )
    runtime = _router(primary, secondary)

    execution = runtime.execute_with_fallback(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        ),
        {AgentCapability.WRITE_CODE},
        preferred_provider="gemini_cli",
    )

    meta = execution.result.metadata
    assert meta["router_fallback_used"] is True
    assert meta["router_primary_provider"] == (
        "gemini_cli"
    )
    assert meta["router_final_provider"] == (
        "ollama"
    )
    assert meta["transport_fallback_used"] is False


def test_fallback_matrix_transport_only():
    client = RecordingClient(
        ModelResponse(
            content="ok",
            model="fallback-model",
            provider="ollama",
            fallback_used=True,
        ),
        config={
            "models": {
                "fast_local": {
                    "provider": "openrouter",
                    "model": "primary-model",
                }
            }
        },
    )

    result = ModelClientProvider(client).complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            model_role="fast_local",
        )
    )

    assert result.provider == "ollama"
    assert result.metadata[
        "transport_fallback_used"
    ] is True
    assert result.metadata[
        "configured_provider"
    ] == "openrouter"
    assert result.metadata[
        "actual_provider"
    ] == "ollama"
    assert "router_fallback_used" not in (
        result.metadata
    )


def test_fallback_matrix_router_and_transport():
    primary = StubProvider(
        "gemini_cli",
        error=AgentProviderUnavailableError(
            "down"
        ),
    )
    secondary = StubProvider(
        "model_client",
        content="ok",
        metadata={
            "fallback_used": True,
            "transport_fallback_used": True,
            "configured_provider": "openrouter",
            "actual_provider": "ollama",
        },
    )
    runtime = _router(primary, secondary)

    execution = runtime.execute_with_fallback(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
        ),
        {AgentCapability.WRITE_CODE},
        preferred_provider="gemini_cli",
    )

    meta = execution.result.metadata
    assert meta["router_fallback_used"] is True
    assert meta["transport_fallback_used"] is True
    assert meta["router_final_provider"] == (
        "model_client"
    )


def test_fallback_matrix_non_eligible_raises():
    primary = StubProvider(
        "gemini_cli",
        error=ValueError("bad"),
    )
    secondary = StubProvider("ollama")
    runtime = _router(primary, secondary)

    with pytest.raises(ValueError, match="bad"):
        runtime.execute_with_fallback(
            AgentRequest(
                system_prompt="s",
                user_prompt="u",
            ),
            {AgentCapability.WRITE_CODE},
            preferred_provider="gemini_cli",
        )

    assert secondary.requests == []


def test_content_only_is_not_transport_fallback():
    client = RecordingClient(
        SimpleNamespace(content="ok"),
        config={
            "models": {
                "fast_local": {
                    "provider": "openai",
                    "model": "cloud",
                }
            }
        },
    )

    result = ModelClientProvider(client).complete(
        AgentRequest(
            system_prompt="s",
            user_prompt="u",
            model_role="fast_local",
        )
    )

    assert result.provider == "model_client"
    assert result.metadata[
        "transport_fallback_used"
    ] is False
    assert result.metadata[
        "fallback_used"
    ] is False


# --- Runtime registry ---


def test_runtime_descriptors_stable_and_non_recursive():
    client = RecordingClient(
        SimpleNamespace(content="ok"),
        config={
            "models": {
                "fast_local": {
                    "provider": "ollama",
                    "model": "llama",
                }
            }
        },
    )

    runtime = (
        build_default_agent_execution_router(
            client
        )
    )
    first = build_default_agent_descriptors(
        runtime.provider_registry
    )
    second = build_default_agent_descriptors(
        runtime.provider_registry
    )

    assert first
    assert first == second
    assert len(
        {item.name for item in first}
    ) == len(first)
    assert {
        item.provider_name
        for item in first
    } == set(
        runtime.provider_registry.names()
    )


# --- Planner / READ / WRITE paths ---


def test_planner_contract_matrix():
    client = RecordingClient(
        SimpleNamespace(content=PLAN_JSON)
    )

    agent_result = _complete_planner(
        client,
        system_prompt="s",
        user_prompt="u",
        model_name="planner-model",
        timeout=45,
    )

    assert isinstance(agent_result, AgentResult)
    assert agent_result.provider == "model_client"
    assert agent_result.model == "planner-model"
    assert "router_fallback_used" not in (
        agent_result.metadata
    )
    assert client.calls[0]["model_role"] == (
        PLANNER_MODEL_ROLE
    )
    assert client.calls[0]["timeout"] == 45

    plan = build_task_plan(
        COMPLEX_PROMPT,
        model_client=RecordingClient(
            SimpleNamespace(content=PLAN_JSON)
        ),
        model_name="planner-model",
    )

    assert set(plan) >= {
        "summary",
        "steps",
        "planner_mode",
    }
    assert "provider" not in plan
    assert "transport_fallback_used" not in plan
    assert "router_fallback_used" not in plan


def test_read_contract_matrix():
    client = RecordingClient(
        SimpleNamespace(
            content="read-ok",
            provider="openrouter",
            model="read-model",
        ),
        config={
            "models": {
                "fast_local": {
                    "provider": "openai",
                    "model": "cfg",
                    "timeout_seconds": 55,
                }
            }
        },
    )

    result = _complete_agent(
        client,
        model_role="fast_local",
        system_prompt="s",
        user_prompt="u",
        timeout=30,
        model_name_override="override",
    )

    assert isinstance(result, AgentResult)
    assert result.content == "read-ok"
    assert result.provider == "openrouter"
    assert result.model == "read-model"
    assert result.metadata[
        "router_fallback_used"
    ] is False
    assert "router_final_provider" in (
        result.metadata
    )
    assert client.calls[0]["timeout"] == 30


def test_write_checkpoint_keeps_fallback_metadata(
    monkeypatch,
    tmp_path,
):
    class FakeOrchestrator:
        _validate_explicit_file_scope = (
            staticmethod(
                Orchestrator
                ._validate_explicit_file_scope
            )
        )

        def __init__(self):
            self.model_client = object()
            self.sandbox = None

    route = SimpleNamespace(
        agent=SimpleNamespace(
            name="fallback-coder",
        ),
        provider=SimpleNamespace(
            provider_name="ollama",
        ),
    )

    patch = json.dumps(
        {
            "files": [
                {
                    "path": "hello.txt",
                    "content": "OK",
                }
            ],
            "explanation": "done",
        }
    )

    class FakeRuntime:
        provider_registry = object()

        def route(self, *args, **kwargs):
            return route

        def execute_with_fallback(
            self,
            request,
            required,
            *,
            preferred_provider=None,
            policy=None,
        ):
            return SimpleNamespace(
                route=route,
                result=AgentResult(
                    content=patch,
                    provider="ollama",
                    model="write-model",
                    metadata={
                        "router_fallback_used": True,
                        "router_primary_provider": (
                            "gemini_cli"
                        ),
                        "router_final_provider": (
                            "ollama"
                        ),
                        "transport_fallback_used": True,
                        "fallback_used": True,
                        "configured_provider": (
                            "openrouter"
                        ),
                        "actual_provider": "ollama",
                    },
                ),
                failures=(
                    SimpleNamespace(
                        agent_name="gemini-coder",
                        provider_name="gemini_cli",
                        error="down",
                        error_type=(
                            "AgentProviderUnavailableError"
                        ),
                    ),
                ),
            )

    monkeypatch.setattr(
        "factory.task_step_handlers."
        "build_default_agent_execution_router",
        lambda model_client: FakeRuntime(),
    )
    monkeypatch.setattr(
        "factory.task_step_handlers."
        "resolve_provider_for_role",
        lambda *args, **kwargs: "gemini_cli",
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(),
        model_name="write-model",
    )

    result = handlers.write(
        {
            "instruction": (
                "hello.txt dosyasi olustur"
            )
        },
        str(tmp_path),
    )

    payload = result.checkpoint_payload

    assert result.agent_name == "fallback-coder"
    assert result.provider_name == "ollama"
    assert payload["model"] == "write-model"
    assert payload["router_fallback_used"] is True
    assert payload[
        "transport_fallback_used"
    ] is True
    assert payload["fallback_used"] is True
    assert payload["configured_provider"] == (
        "openrouter"
    )
    assert payload["actual_provider"] == "ollama"
    assert (
        tmp_path / "hello.txt"
    ).read_text(
        encoding="utf-8"
    ) == "OK\n"
