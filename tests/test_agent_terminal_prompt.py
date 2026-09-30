"""Agent Terminal prompt builder tests."""

from __future__ import annotations

from factory.agent_terminal_models import (
    AgentTerminalPolicy,
    AgentTerminalRouteContext,
    TerminalObservation,
)
from factory.agent_terminal_prompt import (
    MAX_RECENT_OBSERVATIONS,
    MAX_USER_PROMPT_CHARS,
    SYSTEM_PROMPT,
    build_terminal_system_prompt,
    build_terminal_user_prompt,
)


def test_system_prompt_covers_safety_rules():
    text = build_terminal_system_prompt()
    assert text == SYSTEM_PROMPT
    assert "raw JSON" in text.lower() or "JSON action" in text
    assert "python -c" in text
    assert "untrusted" in text.lower()
    # Mentions allow_mutating only as authority the model must NOT set.
    assert "Never invent or request permission_level" in text
    assert "allow_mutating=True" not in text


def test_system_prompt_capability_guidance():
    text = build_terminal_system_prompt()
    assert "python -m" in text or '"-m"' in text
    assert "django-admin" in text
    assert "rejected" in text.casefold()
    assert "pip" in text.casefold()
    assert "cwd" in text.casefold()
    assert "network_policy" in text
    assert "permission_level" in text
    # Advisory only — model must not control authority.
    assert "Never invent or request permission_level" in text
    assert "SAFE_PATH_EXECUTABLES" not in text


def test_user_prompt_includes_task_budget_observations():
    policy = AgentTerminalPolicy(allow_mutating=True)
    obs = TerminalObservation(
        command_id="cmd-1",
        argv=["python", "--version"],
        cwd=".",
        permission_level="EXECUTE_SAFE",
        execution_boundary="HOST_SAFE",
        network_policy="NETWORK_NONE",
        status="succeeded",
        exit_code=0,
        stdout="Python 3.12",
        stderr="",
        duration_ms=12,
    )
    prompt = build_terminal_user_prompt(
        prompt="Inspect Python",
        policy=policy,
        steps_used=1,
        commands_executed=1,
        successful_commands=1,
        observations=[obs],
        route_context=AgentTerminalRouteContext(
            intent="inspect",
            target="python",
            framework=None,
        ),
    )
    assert "ORIGINAL USER TASK:" in prompt
    assert "Inspect Python" in prompt
    assert "intent: inspect" in prompt
    assert "steps_used=1" in prompt
    assert "Python 3.12" in prompt
    assert "cmd-1" in prompt


def test_user_prompt_trims_oldest_observations():
    policy = AgentTerminalPolicy()
    observations = []

    for index in range(MAX_RECENT_OBSERVATIONS + 3):
        observations.append(
            TerminalObservation(
                command_id=f"cmd-{index}",
                argv=["echo", str(index)],
                cwd=".",
                permission_level="",
                execution_boundary="",
                network_policy="",
                status="succeeded",
                exit_code=0,
                stdout="x" * 100,
                stderr="",
                duration_ms=1,
            )
        )

    prompt = build_terminal_user_prompt(
        prompt="task",
        policy=policy,
        steps_used=0,
        commands_executed=0,
        successful_commands=0,
        observations=observations,
    )
    assert "cmd-0" not in prompt
    assert "cmd-1" not in prompt
    assert "cmd-2" not in prompt
    assert f"cmd-{MAX_RECENT_OBSERVATIONS + 2}" in prompt
    assert len(prompt) <= MAX_USER_PROMPT_CHARS
