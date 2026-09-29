"""Phase 5+6 decision / review / retry / handoff regressions.

Fake/fixture only — no real API/provider calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.handoff_context import (
    build_handoff_context,
)
from factory.agents.provider_errors import (
    AgentProviderTimeoutError,
    AgentProviderUnavailableError,
)
from factory.failure_taxonomy import (
    EXECUTION_FAILED,
    INVALID_RESPONSE,
    PATCH_FAILED,
    PROVIDER_UNAVAILABLE,
    REVIEW_FAILED,
    TEST_FAILED,
    TIMEOUT,
    classify_failure,
    extract_failure_reason,
    format_failure_message,
)
from factory.retry_ownership import (
    AGENT_PROVIDER_FALLBACK,
    FULL_TASK_RETRY,
    PROVIDER_TRANSPORT_RETRY,
    STEP_ATTEMPT_OWNER,
    STEP_RETRY,
    RETRY_LAYERS,
)
from factory.review_quality import (
    ReviewVerdictParseError,
)
from factory.semantic_task_router import (
    route_task_semantic,
)
from factory.task_planner import (
    build_task_plan,
)
from factory.task_router import route_task
from factory.task_execution_service import (
    TaskExecutionDeps,
    TaskExecutionService,
)


class FakeModelClient:
    def __init__(self, content=None, *, error=None):
        self.content = content
        self.error = error
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        if self.error is not None:
            raise self.error

        return SimpleNamespace(
            content=self.content
        )


def test_read_route_deterministic():
    route = route_task(
        "Bu projeyi incele ve ne yaptigini acikla."
    )

    assert route.kind == "read"


def test_write_route_deterministic():
    route = route_task(
        "README.md dosyasini guncelle."
    )

    assert route.kind == "write"


def test_execute_route_deterministic():
    route = route_task(
        "Ana klasore venv sanal ortami kur."
    )

    assert route.kind == "execute"


def test_semantic_router_success_provenance():
    client = FakeModelClient(
        '{"kind":"write","intent":"code_change",'
        '"target":"app.py","confidence":0.95,'
        '"reason":"Kod degisikligi."}'
    )

    route = route_task_semantic(
        "app.py icine helper ekle",
        model_client=client,
    )

    assert route.kind == "write"
    assert route.source == "semantic"
    assert len(client.calls) == 1


def test_semantic_router_failure_deterministic_fallback():
    client = FakeModelClient(
        error=RuntimeError("model down")
    )

    route = route_task_semantic(
        "README.md dosyasini guncelle.",
        model_client=client,
    )

    assert route.source == (
        "deterministic_fallback"
    )
    assert route.kind == "write"
    assert "Semantic router kullanilamadi" in (
        route.reason
    )


def test_planner_domain_contract_no_provider_metadata():
    client = FakeModelClient('{"steps":[]}')

    plan = build_task_plan(
        "hello.txt dosyasi olustur",
        model_client=client,
        task_kind="write",
    )

    assert plan["planner_mode"] == "single_step"
    assert set(plan.keys()) == {
        "summary",
        "steps",
        "planner_mode",
    }
    assert plan["steps"][0]["kind"] == "write"
    assert client.calls == []


def test_single_step_reuses_task_kind_without_reclassify(
    monkeypatch,
):
    calls = []

    def boom(prompt):
        calls.append(prompt)
        raise AssertionError(
            "route_task must not re-classify "
            "when task_kind is supplied"
        )

    monkeypatch.setattr(
        "factory.task_planner.route_task",
        boom,
    )

    plan = build_task_plan(
        "projeyi biraz duzenle",
        model_client=FakeModelClient("{}"),
        task_kind="write",
    )

    assert plan["steps"][0]["kind"] == "write"
    assert calls == []


def test_failure_taxonomy_classifies_common_cases():
    assert classify_failure(
        AgentProviderUnavailableError("down")
    ) == PROVIDER_UNAVAILABLE

    assert classify_failure(
        AgentProviderTimeoutError("slow")
    ) == TIMEOUT

    assert classify_failure(
        ReviewVerdictParseError("bad json")
    ) == INVALID_RESPONSE

    assert classify_failure(
        "Quality gate blocked the WRITE step",
        context="review",
    ) == REVIEW_FAILED

    assert classify_failure(
        "pytest failed",
        step_kind="verify",
    ) == TEST_FAILED

    assert classify_failure(
        "failed to apply patch"
    ) == PATCH_FAILED

    formatted = format_failure_message(
        REVIEW_FAILED,
        "Quality gate blocked",
    )

    assert formatted.startswith(
        "review_failed:"
    )
    assert extract_failure_reason(
        formatted
    ) == REVIEW_FAILED


def test_retry_layers_are_distinct():
    assert PROVIDER_TRANSPORT_RETRY in (
        RETRY_LAYERS
    )
    assert AGENT_PROVIDER_FALLBACK in (
        RETRY_LAYERS
    )
    assert STEP_RETRY in RETRY_LAYERS
    assert FULL_TASK_RETRY in RETRY_LAYERS
    assert STEP_ATTEMPT_OWNER == (
        "execute_task_plan"
    )
    assert PROVIDER_TRANSPORT_RETRY != (
        STEP_RETRY
    )
    assert FULL_TASK_RETRY != STEP_RETRY


def test_handoff_context_preserves_structured_fields(
    tmp_path,
):
    from factory.agent_checkpoint_store import (
        create_agent_checkpoint,
    )

    db_path = tmp_path / "factory.db"

    checkpoint = create_agent_checkpoint(
        "TASK-P56-1",
        step_index=1,
        agent_name="coder-agent",
        provider_name="ollama",
        status="completed",
        summary="wrote helper",
        payload={
            "attempt": 2,
            "step_kind": "write",
            "model": "fake-model",
            "original_task": (
                "helper ekle"
            ),
            "write_instruction": (
                "add helper.py"
            ),
            "project_path": "/repo",
            "files": ["helper.py"],
            "diff": "+def helper():\n  pass",
            "failure_reason": None,
        },
        checkpoint_id="CHK-P56-1",
        db_path=db_path,
    )

    target = AgentDescriptor(
        name="reviewer-agent",
        provider_name="gemini_cli",
        capabilities=frozenset(
            {
                AgentCapability.REVIEW_CODE,
            }
        ),
    )

    context = build_handoff_context(
        checkpoint,
        reason="Independent review after WRITE",
        required_capabilities={
            AgentCapability.REVIEW_CODE,
        },
        target_agent=target,
        db_path=db_path,
    )

    assert context["task_id"] == "TASK-P56-1"
    assert context["attempt"] == 2
    assert context["task"]["attempt"] == 2
    assert context["task"][
        "original_prompt"
    ] == "helper ekle"
    assert context["task"][
        "project_path"
    ] == "/repo"
    assert context["task"][
        "plan_step_instruction"
    ] == "add helper.py"
    assert context["source"][
        "model"
    ] == "fake-model"
    assert context["artifacts"]["files"] == [
        "helper.py"
    ]
    assert "diff" in context["artifacts"]
    assert context["failure"][
        "handoff_reason"
    ] == "Independent review after WRITE"


def test_route_store_persists_source(
    tmp_path,
    monkeypatch,
):
    import sqlite3
    import factory.task_route_store as store

    database_path = tmp_path / "routes.db"

    monkeypatch.setattr(
        store,
        "get_connection",
        lambda: sqlite3.connect(
            database_path
        ),
    )

    store.save_task_route(
        "TASK-P56-ROUTE",
        "write",
        "semantic decision",
        source="semantic",
    )

    record = store.get_task_route(
        "TASK-P56-ROUTE"
    )

    assert record is not None
    assert record["kind"] == "write"
    assert record["source"] == "semantic"

    store.save_task_route(
        "TASK-P56-ROUTE",
        "read",
        "fallback",
        source="deterministic_fallback",
    )

    record = store.get_task_route(
        "TASK-P56-ROUTE"
    )

    assert record["source"] == (
        "deterministic_fallback"
    )


def test_execution_service_passes_task_kind_and_source(
    monkeypatch,
):
    task = SimpleNamespace(
        task_id="TASK-P56-SVC",
        prompt="helper dosyasi olustur",
        max_attempts=2,
        status="queued",
        state="queued",
        task_kind=None,
        model=None,
        attempt=0,
        test_result=None,
    )

    saved_routes = []
    write_calls = []

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_task_semantic",
        lambda prompt, **kwargs: (
            SimpleNamespace(
                kind="write",
                reason="write path",
                intent="code_change",
                target="helper.py",
                framework=None,
                confidence=0.91,
                source="semantic",
            )
        ),
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "save_task_route",
        lambda *args, **kwargs: (
            saved_routes.append(
                (args, kwargs)
            )
        ),
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "get_task_model_preference",
        lambda *_a, **_k: None,
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "route_model",
        lambda prompt: SimpleNamespace(
            model="fake-model",
            profile="test",
            reason="test",
            code_score=1,
        ),
    )

    monkeypatch.setattr(
        "factory.task_execution_service."
        "execute_write_task",
        lambda **kwargs: (
            write_calls.append(kwargs)
            or (
                "ready_for_approval",
                {
                    "planner_mode": (
                        "single_step"
                    ),
                    "steps": [],
                },
            )
        ),
    )

    deps = TaskExecutionDeps(
        get_task=lambda tid: task,
        iter_tasks=lambda: [
            (task.task_id, task)
        ],
        append_log=lambda *_a, **_k: None,
        update_runtime=lambda *_a, **_k: None,
        evaluate_gate=lambda tid, _s: {
            "task_id": tid,
            "allowed": True,
            "state": "allowed",
            "graph_ids": [],
            "blocked_graphs": [],
            "failed_graphs": [],
            "pending_dependencies": [],
            "failed_dependencies": [],
        },
        build_orchestrator=lambda _t: (
            SimpleNamespace(
                project_path="/repo",
                model_client=object(),
                run_task=MagicMock(
                    side_effect=AssertionError(
                        "Orchestrator.run_task "
                        "must not be called"
                    )
                ),
            )
        ),
        approval_handler=lambda *_a, **_k: (
            "ready_for_approval"
        ),
        progress_handler=lambda *_a, **_k: None,
        cleanup_failed=lambda *_a, **_k: None,
        release_dependents=lambda *_a: [],
    )

    TaskExecutionService(deps).run(
        task.task_id
    )

    assert saved_routes[0][1][
        "source"
    ] == "semantic"
    assert write_calls[0][
        "task_kind"
    ] == "write"


def test_step_execution_error_carries_failure_reason():
    from factory.task_step_executor import (
        StepExecutionError,
    )

    exc = StepExecutionError(
        "TASK-1",
        2,
        format_failure_message(
            REVIEW_FAILED,
            "Quality gate blocked",
        ),
        failure_reason=REVIEW_FAILED,
    )

    assert exc.failure_reason == REVIEW_FAILED
    assert "review_failed:" in str(exc)


def test_provider_fallback_not_confused_with_step_retry():
    """A/B vs C ownership must remain separate."""
    assert AGENT_PROVIDER_FALLBACK != (
        STEP_RETRY
    )
    assert PROVIDER_TRANSPORT_RETRY != (
        AGENT_PROVIDER_FALLBACK
    )

    # Transport/fallback failures map to provider
    # codes, not step-retry semantics.
    assert classify_failure(
        AgentProviderUnavailableError("x")
    ) == PROVIDER_UNAVAILABLE
    assert classify_failure(
        "maximum step attempts already reached"
    ) == EXECUTION_FAILED


def test_reviewer_success_and_block_contract():
    from factory.review_quality import (
        ReviewVerdictStatus,
        evaluate_review_checkpoint_quality_gate,
        parse_review_verdict,
    )

    passed = parse_review_verdict(
        '{"verdict":"pass","summary":"ok",'
        '"findings":[]}'
    )

    assert passed.verdict == (
        ReviewVerdictStatus.PASS
    )
    assert passed.blocks_quality_gate is False

    blocked = parse_review_verdict(
        '{"verdict":"block","summary":"bad",'
        '"findings":[{"severity":"critical",'
        '"category":"correctness",'
        '"message":"broken logic",'
        '"blocking":true}]}'
    )

    assert blocked.blocks_quality_gate is True

    decision = (
        evaluate_review_checkpoint_quality_gate(
            {
                "summary": (
                    '{"verdict":"block",'
                    '"summary":"bad",'
                    '"findings":[{"severity":'
                    '"critical","category":'
                    '"correctness","message":'
                    '"broken","blocking":true}]}'
                )
            }
        )
    )

    assert decision.blocked is True


def test_step_retry_increments_attempt_once(
    tmp_path,
):
    from factory.task_plan_store import (
        get_task_plan,
        save_task_plan,
    )
    from factory.task_step_executor import (
        StepExecutionError,
        execute_task_plan,
    )

    db_path = tmp_path / "factory.db"
    task_id = "TASK-P56-STEP-RETRY"
    attempts = []

    save_task_plan(
        task_id,
        [
            {
                "title": "Write",
                "instruction": "write",
                "kind": "write",
                "status": "failed",
                "attempt": 1,
            }
        ],
        db_path=db_path,
    )

    def write_handler(step, _path):
        attempts.append(
            int(step.get("attempt") or 0)
        )

        if len(attempts) == 1:
            raise RuntimeError(
                "transient write failure"
            )

        return "ok"

    with pytest.raises(StepExecutionError) as first:
        execute_task_plan(
            task_id,
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=write_handler,
            verify_handler=lambda *_: None,
            max_step_attempts=2,
            db_path=db_path,
        )

    assert first.value.failure_reason == (
        EXECUTION_FAILED
    )

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert plan["steps"][0]["attempt"] == 2
    assert extract_failure_reason(
        plan["steps"][0]["error"]
    ) == EXECUTION_FAILED

    # Non-retryable: budget exhausted — step
    # attempt must not climb further.
    with pytest.raises(
        StepExecutionError,
        match="maximum step attempts",
    ):
        execute_task_plan(
            task_id,
            str(tmp_path),
            read_handler=lambda *_: None,
            write_handler=write_handler,
            verify_handler=lambda *_: None,
            max_step_attempts=2,
            db_path=db_path,
        )

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert plan["steps"][0]["attempt"] == 2
    assert attempts == [2]


def test_full_task_retry_resets_failed_step_only(
    tmp_path,
):
    from factory.task_plan_store import (
        get_task_plan,
        reset_retryable_task_steps,
        save_task_plan,
        update_task_step,
    )

    db_path = tmp_path / "factory.db"
    task_id = "TASK-P56-FULL-RETRY"

    save_task_plan(
        task_id,
        [
            {
                "title": "done",
                "instruction": "done",
                "kind": "write",
            },
            {
                "title": "failed",
                "instruction": "failed",
                "kind": "verify",
            },
        ],
        db_path=db_path,
    )

    update_task_step(
        task_id,
        1,
        status="completed",
        attempt=1,
        result="ok",
        db_path=db_path,
    )
    update_task_step(
        task_id,
        2,
        status="failed",
        attempt=2,
        error=format_failure_message(
            TEST_FAILED,
            "pytest failed",
        ),
        db_path=db_path,
    )

    reset_count = reset_retryable_task_steps(
        task_id,
        db_path=db_path,
    )

    assert reset_count == 1

    plan = get_task_plan(
        task_id,
        db_path=db_path,
    )

    assert plan["steps"][0]["status"] == (
        "completed"
    )
    assert plan["steps"][0]["attempt"] == 1
    assert plan["steps"][1]["status"] == (
        "pending"
    )
    assert plan["steps"][1]["attempt"] == 0


def test_checkpoint_resume_does_not_recomplete(
    tmp_path,
):
    from factory.agent_checkpoint_store import (
        create_agent_checkpoint,
    )
    from factory.task_plan_store import (
        save_task_plan,
    )
    from factory.task_step_executor import (
        execute_task_plan,
    )

    db_path = tmp_path / "factory.db"
    task_id = "TASK-P56-RESUME"

    save_task_plan(
        task_id,
        [
            {
                "title": "Write",
                "instruction": "write",
                "kind": "write",
                "status": "running",
                "attempt": 1,
            }
        ],
        db_path=db_path,
    )

    create_agent_checkpoint(
        task_id,
        step_index=1,
        agent_name="coder",
        provider_name="ollama",
        status="completed",
        summary="done once",
        payload={
            "attempt": 1,
            "step_kind": "write",
        },
        db_path=db_path,
    )

    calls = []

    plan = execute_task_plan(
        task_id,
        str(tmp_path),
        read_handler=lambda *_: None,
        write_handler=lambda *_: (
            calls.append("write")
            or "should-not-run"
        ),
        verify_handler=lambda *_: None,
        max_step_attempts=2,
        db_path=db_path,
    )

    assert calls == []
    assert plan["steps"][0]["status"] == (
        "completed"
    )
    assert plan["steps"][0]["attempt"] == 1
