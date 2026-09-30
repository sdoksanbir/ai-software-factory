"""Execution evidence pack and diagnosis grounding tests."""

from __future__ import annotations

from types import SimpleNamespace

from factory.agent_execution_store import (
    create_agent_execution,
    fail_agent_execution,
    init_agent_execution_store,
)
from factory.database import (
    init_database,
    upsert_task,
    append_task_log,
)
from factory.read_task_runner import run_read_task
from factory.task_command_models import (
    NetworkPolicy,
    PermissionLevel,
    TaskCommandResult,
)
from factory.task_command_store import (
    init_task_command_store,
    save_task_command,
)
from factory.task_execution_evidence import (
    DIAGNOSIS_SYSTEM_GUIDANCE,
    build_task_execution_evidence,
    format_execution_evidence_for_prompt,
    is_failure_diagnosis_request,
    should_attach_related_execution_evidence,
    validate_related_task_id,
)
from factory.task_plan_store import (
    init_task_plan_store,
    save_task_plan,
)


def test_failure_diagnosis_detection():
    assert is_failure_diagnosis_request(
        "neden başarısız oldu?"
    )
    assert is_failure_diagnosis_request(
        "what caused this task to fail?"
    )
    assert is_failure_diagnosis_request(
        "neden başarısız oldu?",
        intent="explain_or_inspect",
    )
    assert not is_failure_diagnosis_request(
        "Django nedir?",
        intent="explain_or_inspect",
    )
    assert not should_attach_related_execution_evidence(
        related_task_id=None,
        prompt="neden başarısız oldu?",
    )
    assert should_attach_related_execution_evidence(
        related_task_id="TASK-1",
        prompt="neden başarısız oldu?",
        intent="explain_or_inspect",
    )


def test_validate_related_task_same_project(tmp_path):
    db_path = tmp_path / "factory.db"
    init_database(db_path)

    upsert_task(
        "TASK-A",
        prompt="prior",
        status="failed",
        max_attempts=2,
        state="failed",
        project_id="PROJ-1",
        db_path=db_path,
    )
    upsert_task(
        "TASK-B",
        prompt="other",
        status="failed",
        max_attempts=2,
        state="failed",
        project_id="PROJ-2",
        db_path=db_path,
    )

    related = validate_related_task_id(
        related_task_id="TASK-A",
        project_id="PROJ-1",
        db_path=db_path,
    )
    assert related["task_id"] == "TASK-A"

    try:
        validate_related_task_id(
            related_task_id="TASK-B",
            project_id="PROJ-1",
            db_path=db_path,
        )
        raised = False
    except ValueError as exc:
        raised = True
        assert "same project" in str(exc)

    assert raised

    try:
        validate_related_task_id(
            related_task_id="TASK-MISSING",
            project_id="PROJ-1",
            db_path=db_path,
        )
        missing_raised = False
    except ValueError as exc:
        missing_raised = True
        assert "not found" in str(exc)

    assert missing_raised


def test_build_task_execution_evidence_priority(tmp_path):
    db_path = tmp_path / "factory.db"
    init_database(db_path)
    init_task_command_store(db_path)
    init_agent_execution_store(db_path)
    init_task_plan_store(db_path)

    task_id = "TASK-EV-1"
    upsert_task(
        task_id,
        prompt="create superuser",
        status="failed",
        max_attempts=2,
        state="failed",
        project_id="PROJ-1",
        db_path=db_path,
    )

    save_task_command(
        result=TaskCommandResult(
            command_id="cmd-1",
            task_id=task_id,
            argv=[
                "python",
                "manage.py",
                "createsuperuser",
                "--noinput",
            ],
            cwd=".",
            permission_level=(
                PermissionLevel.EXECUTE_MUTATING.value
            ),
            started_at="t0",
            finished_at="t1",
            duration_ms=10,
            exit_code=2,
            stdout="",
            stderr=(
                "can't open file '/app/manage.py': "
                "[Errno 2] No such file or directory"
            ),
            status="failed",
            secret_env_keys=["DJANGO_SUPERUSER_PASSWORD"],
            execution_boundary="PROJECT_CODE_SANDBOX",
            network_policy=NetworkPolicy.NETWORK_NONE.value,
        ),
        db_path=db_path,
    )

    save_task_plan(
        task_id,
        steps=[
            {
                "title": "run",
                "instruction": "run command",
                "kind": "write",
                "status": "failed",
                "error": "plan step exploded",
            }
        ],
        status="failed",
        db_path=db_path,
    )

    created = create_agent_execution(
        task_id=task_id,
        step_index=1,
        agent_name="coder",
        provider_name="local",
        model_name="m",
        db_path=db_path,
    )
    fail_agent_execution(
        created["execution_id"],
        error="agent boom",
        db_path=db_path,
    )
    append_task_log(
        task_id,
        "Agent Terminal basarisiz: cwd",
        db_path=db_path,
    )

    evidence = build_task_execution_evidence(
        task_id,
        db_path=db_path,
    )

    assert evidence["task_id"] == task_id
    assert len(evidence["commands"]) == 1
    command = evidence["commands"][0]
    assert command["argv"][2] == "createsuperuser"
    assert "can't open file '/app/manage.py'" in (
        command["stderr"]
    )
    assert "secret_env_keys" not in command
    assert evidence["failed_plan_steps"]
    assert evidence["agent_execution_errors"]
    assert evidence["logs"]

    rendered = format_execution_evidence_for_prompt(
        evidence
    )
    assert "EXECUTION EVIDENCE FOR RELATED TASK" in (
        rendered
    )
    assert "createsuperuser" in rendered
    assert "can't open file '/app/manage.py'" in (
        rendered
    )
    assert "primary factual ground truth" in rendered
    assert "untrusted observation" in rendered
    assert "DJANGO_SUPERUSER_PASSWORD" not in rendered


def test_read_diagnosis_prompt_includes_execution_evidence(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "factory.db"
    init_database(db_path)
    init_task_command_store(db_path)

    prior_id = "TASK-PRIOR-FAIL"
    upsert_task(
        prior_id,
        prompt="projeye bir superuser olustur",
        status="failed",
        max_attempts=2,
        state="failed",
        project_id="PROJ-1",
        db_path=db_path,
    )
    save_task_command(
        result=TaskCommandResult(
            command_id="cmd-super-1",
            task_id=prior_id,
            argv=[
                "python",
                "manage.py",
                "createsuperuser",
                "--noinput",
                "--username",
                "admin",
            ],
            cwd=".",
            permission_level=(
                PermissionLevel.EXECUTE_MUTATING.value
            ),
            started_at="t0",
            finished_at="t1",
            duration_ms=8,
            exit_code=2,
            stdout="",
            stderr=(
                "can't open file '/app/manage.py': "
                "[Errno 2] No such file or directory"
            ),
            status="failed",
            execution_boundary="PROJECT_CODE_SANDBOX",
            network_policy=NetworkPolicy.NETWORK_NONE.value,
        ),
        db_path=db_path,
    )

    evidence = build_task_execution_evidence(
        prior_id,
        db_path=db_path,
    )
    evidence_text = format_execution_evidence_for_prompt(
        evidence
    )

    captured: dict = {}

    def fake_complete_agent(
        model_client,
        *,
        model_role,
        system_prompt,
        user_prompt,
        temperature=0.0,
        model_name_override=None,
        execution_observer=None,
    ):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return SimpleNamespace(
            content=(
                "Komut iki kez calistirildi ancak "
                "manage.py bulunamadi."
            )
        )

    monkeypatch.setattr(
        "factory.read_task_runner._complete_agent",
        fake_complete_agent,
    )
    monkeypatch.setattr(
        "factory.read_task_runner.build_smart_read_context",
        lambda project_path, prompt: (
            "repo map only — no command history"
        ),
    )

    result = run_read_task(
        project_path=str(tmp_path),
        prompt="neden basarisiz oldu?",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        execution_evidence_text=evidence_text,
    )

    assert "manage.py" in result
    assert "EXECUTION EVIDENCE FOR RELATED TASK" in (
        captured["user_prompt"]
    )
    assert "createsuperuser" in captured["user_prompt"]
    assert "can't open file '/app/manage.py'" in (
        captured["user_prompt"]
    )
    assert "repo map only" in captured["user_prompt"]
    # Evidence appears before repository context.
    evidence_pos = captured["user_prompt"].index(
        "EXECUTION EVIDENCE FOR RELATED TASK"
    )
    repo_pos = captured["user_prompt"].index(
        "REPOSITORY BAGLAMI"
    )
    assert evidence_pos < repo_pos
    assert DIAGNOSIS_SYSTEM_GUIDANCE in (
        captured["system_prompt"]
    )
    assert "Do not claim a command was absent" in (
        captured["system_prompt"]
    )
