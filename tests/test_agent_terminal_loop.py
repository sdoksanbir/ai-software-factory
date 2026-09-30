"""Agent Terminal Loop unit and acceptance tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from factory.agent_terminal_loop import (
    command_fingerprint,
    is_deterministic_git_ls_files_discovery,
    is_deterministic_missing_path_failure,
    is_successful_empty_discovery_result,
    run_agent_terminal_loop,
)
from factory.agent_terminal_models import (
    AgentTerminalPolicy,
    build_execute_terminal_policy,
)
from factory.task_command_models import (
    NetworkPolicy,
    PermissionLevel,
    TaskCommandPolicyError,
    TaskCommandRequest,
    TaskCommandResult,
    TaskCommandSandboxRuntimeError,
)
from factory.task_command_runner import (
    run_task_command,
)
from factory.task_command_store import (
    init_task_command_store,
    list_task_commands,
)


class ScriptedDecider:
    def __init__(self, scripts: list[str]):
        self.scripts = list(scripts)
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> str:
        self.calls.append(kwargs)
        if not self.scripts:
            raise RuntimeError("No scripted decisions left")
        return self.scripts.pop(0)


def _action(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _success_result(
    *,
    argv: list[str],
    cwd: str = ".",
    command_id: str = "cmd-ok",
) -> TaskCommandResult:
    return TaskCommandResult(
        command_id=command_id,
        task_id="TASK-T",
        argv=argv,
        cwd=cwd,
        permission_level=PermissionLevel.EXECUTE_SAFE.value,
        started_at="t0",
        finished_at="t1",
        duration_ms=5,
        exit_code=0,
        stdout="ok",
        stderr="",
        status="succeeded",
        execution_boundary="HOST_SAFE",
        network_policy=NetworkPolicy.NETWORK_NONE.value,
    )


def _failed_result(
    *,
    argv: list[str],
    cwd: str = ".",
    command_id: str = "cmd-fail",
    exit_code: int = 1,
    stderr: str = "boom",
    stdout: str = "",
) -> TaskCommandResult:
    return TaskCommandResult(
        command_id=command_id,
        task_id="TASK-T",
        argv=argv,
        cwd=cwd,
        permission_level=PermissionLevel.EXECUTE_SAFE.value,
        started_at="t0",
        finished_at="t1",
        duration_ms=5,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        status="failed",
        execution_boundary="HOST_SAFE",
        network_policy=NetworkPolicy.NETWORK_NONE.value,
    )


def test_happy_path_complete_after_success():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        req = kwargs["request"]
        return _success_result(argv=list(req.argv))

    decider = ScriptedDecider(
        [
            _action(
                {
                    "action_type": "run_command",
                    "argv": ["python", "--version"],
                    "cwd": None,
                    "reason": "inspect",
                }
            ),
            _action(
                {
                    "action_type": "complete",
                    "reason": "command succeeded",
                    "summary": "Python is available.",
                }
            ),
        ]
    )

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-1",
        prompt="Inspect Python and finish.",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=False),
        command_runner=fake_runner,
        decision_caller=decider,
    )

    assert result.status == "completed"
    assert result.commands_executed == 1
    assert result.successful_commands == 1
    assert len(runner_calls) == 1
    request = runner_calls[0]["request"]
    assert isinstance(request, TaskCommandRequest)
    assert request.allow_mutating is False
    assert request.env == {}
    assert request.secret_env_keys == []
    assert "allow_mutating" not in decider.calls[0][
        "user_prompt"
    ]


def test_observe_then_adapt_includes_observation():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        req = kwargs["request"]
        if req.argv == ["missing-tool"]:
            return _failed_result(argv=list(req.argv))
        return _success_result(argv=list(req.argv))

    decider = ScriptedDecider(
        [
            _action(
                {
                    "action_type": "run_command",
                    "argv": ["missing-tool"],
                    "cwd": None,
                    "reason": "try",
                }
            ),
            _action(
                {
                    "action_type": "run_command",
                    "argv": ["python", "--version"],
                    "cwd": None,
                    "reason": "fallback",
                }
            ),
            _action(
                {
                    "action_type": "complete",
                    "reason": "ok",
                    "summary": "done",
                }
            ),
        ]
    )

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-2",
        prompt="adapt",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=False),
        command_runner=fake_runner,
        decision_caller=decider,
    )

    assert result.status == "completed"
    assert len(runner_calls) == 2
    assert "missing-tool" in decider.calls[1]["user_prompt"]
    assert "boom" in decider.calls[1]["user_prompt"]


def test_dangerous_command_rejected_and_bounded():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        raise TaskCommandPolicyError(
            "DANGEROUS komut reddedildi."
        )

    scripts = [
        _action(
            {
                "action_type": "run_command",
                "argv": ["python", "-c", "print(1)"],
                "cwd": None,
                "reason": "bad",
            }
        )
        for _ in range(6)
    ]
    decider = ScriptedDecider(scripts)

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-3",
        prompt="dangerous",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=True),
        command_runner=fake_runner,
        decision_caller=decider,
    )

    assert result.status == "stalled"
    assert result.reason in {
        "stall_identical_command",
        "stall_repeated_failure",
        "max_consecutive_command_failures",
    }
    # Rejections never execute; identical/repeated
    # still consume fingerprint budget.
    assert len(runner_calls) == 2
    assert all(
        call["request"].allow_mutating is True
        for call in runner_calls
    )


def test_mutating_authority_is_controller_owned():
    seen: list[bool] = []

    def fake_runner(**kwargs):
        seen.append(kwargs["request"].allow_mutating)
        raise TaskCommandPolicyError(
            "EXECUTE_MUTATING komut icin "
            "allow_mutating=True gerekli."
        )

    blocked = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-4a",
        prompt="pip",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_consecutive_command_failures=1,
        ),
        command_runner=fake_runner,
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": [
                            "pip",
                            "install",
                            "six",
                        ],
                        "cwd": None,
                        "reason": "deps",
                    }
                )
            ]
        ),
    )
    assert blocked.status == "stalled"
    assert seen == [False]

    seen.clear()

    def allow_runner(**kwargs):
        seen.append(kwargs["request"].allow_mutating)
        return _success_result(
            argv=list(kwargs["request"].argv)
        )

    allowed = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-4b",
        prompt="pip",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=True),
        command_runner=allow_runner,
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": [
                            "pip",
                            "install",
                            "six",
                        ],
                        "cwd": None,
                        "reason": "deps",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "installed",
                        "summary": "ok",
                    }
                ),
            ]
        ),
    )
    assert allowed.status == "completed"
    assert seen == [True]


def test_identical_command_stall_skips_third():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        return _failed_result(
            argv=list(kwargs["request"].argv)
        )

    scripts = [
        _action(
            {
                "action_type": "run_command",
                "argv": ["python", "bad.py"],
                "cwd": None,
                "reason": "retry",
            }
        )
        for _ in range(5)
    ]

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-5",
        prompt="stall",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=False),
        command_runner=fake_runner,
        decision_caller=ScriptedDecider(scripts),
    )

    assert result.status == "stalled"
    assert result.reason in {
        "stall_identical_command",
        "stall_repeated_failure",
    }
    # Transient / non-missing-path failures still
    # allow the general identical budget of 2.
    assert len(runner_calls) == 2


def test_deterministic_missing_path_classifier():
    assert is_deterministic_missing_path_failure(
        status="failed",
        exit_code=2,
        stderr=(
            "can't open file '/app/manage.py': "
            "[Errno 2] No such file or directory"
        ),
    )
    assert is_deterministic_missing_path_failure(
        status="failed",
        exit_code=1,
        stderr="The system cannot find the path specified.",
    )
    assert not is_deterministic_missing_path_failure(
        status="failed",
        exit_code=1,
        stderr="boom",
    )
    assert not is_deterministic_missing_path_failure(
        status="succeeded",
        exit_code=0,
        stderr="No such file or directory",
    )
    assert not is_deterministic_missing_path_failure(
        status="timed_out",
        exit_code=None,
        stderr="No such file or directory",
    )


def test_missing_path_blocks_identical_retry_then_recovers():
    runner_calls: list[dict] = []
    missing_stderr = (
        "can't open file '/app/manage.py': "
        "[Errno 2] No such file or directory"
    )

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        req = kwargs["request"]
        argv = list(req.argv)
        cwd = str(req.cwd or ".")

        if (
            argv[:3] == ["python", "manage.py", "check"]
            and cwd in {".", None, ""}
        ):
            return _failed_result(
                argv=argv,
                cwd=".",
                exit_code=2,
                stderr=missing_stderr,
                command_id=f"miss-{len(runner_calls)}",
            )

        if argv[:2] == ["git", "ls-files"]:
            return TaskCommandResult(
                command_id=f"git-{len(runner_calls)}",
                task_id="TASK-T",
                argv=argv,
                cwd=".",
                permission_level=(
                    PermissionLevel.EXECUTE_SAFE.value
                ),
                started_at="t0",
                finished_at="t1",
                duration_ms=3,
                exit_code=0,
                stdout="edusen/manage.py\n",
                stderr="",
                status="succeeded",
                execution_boundary="HOST_SAFE",
                network_policy=(
                    NetworkPolicy.NETWORK_NONE.value
                ),
            )

        if (
            argv[:3] == ["python", "manage.py", "check"]
            and cwd == "edusen"
        ):
            return _success_result(
                argv=argv,
                cwd="edusen",
                command_id=f"ok-{len(runner_calls)}",
            )

        raise AssertionError(
            f"Unexpected command: argv={argv!r} cwd={cwd!r}"
        )

    scripts = [
        _action(
            {
                "action_type": "run_command",
                "argv": ["python", "manage.py", "check"],
                "cwd": ".",
                "reason": "assume root",
            }
        ),
        # Identical miss — must be blocked without runner.
        _action(
            {
                "action_type": "run_command",
                "argv": ["python", "manage.py", "check"],
                "cwd": ".",
                "reason": "retry identical",
            }
        ),
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "git",
                    "ls-files",
                    "*manage.py",
                ],
                "cwd": None,
                "reason": "discover",
            }
        ),
        _action(
            {
                "action_type": "run_command",
                "argv": ["python", "manage.py", "check"],
                "cwd": "edusen",
                "reason": "correct cwd",
            }
        ),
        _action(
            {
                "action_type": "complete",
                "reason": "django check ok",
                "summary": "Recovered via discovery.",
            }
        ),
    ]
    decider = ScriptedDecider(scripts)

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-MISS-1",
        prompt="django check",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=True),
        command_runner=fake_runner,
        decision_caller=decider,
    )

    assert result.status == "completed"
    assert len(runner_calls) == 3

    first = runner_calls[0]["request"]
    assert list(first.argv) == [
        "python",
        "manage.py",
        "check",
    ]
    assert (first.cwd or ".") in {".", None}

    second = runner_calls[1]["request"]
    assert list(second.argv)[:2] == ["git", "ls-files"]

    third = runner_calls[2]["request"]
    assert list(third.argv) == [
        "python",
        "manage.py",
        "check",
    ]
    assert third.cwd == "edusen"

    # Blocked identical retry appears as controller feedback.
    assert any(
        "Inspect the repository and change cwd or argv"
        in call["user_prompt"]
        for call in decider.calls[2:]
    )
    assert any(
        missing_stderr in call["user_prompt"]
        for call in decider.calls[1:]
    )


def test_git_ls_files_discovery_classifier():
    assert is_deterministic_git_ls_files_discovery(
        ["git", "ls-files", "*manage.py"]
    )
    assert is_deterministic_git_ls_files_discovery(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "*manage.py",
        ]
    )
    assert not is_deterministic_git_ls_files_discovery(
        ["git", "status", "--short"]
    )
    assert not is_deterministic_git_ls_files_discovery(
        ["python", "manage.py", "check"]
    )
    assert is_successful_empty_discovery_result(
        status="succeeded",
        exit_code=0,
        stdout="",
    )
    assert is_successful_empty_discovery_result(
        status="succeeded",
        exit_code=0,
        stdout="   \n",
    )
    assert not is_successful_empty_discovery_result(
        status="succeeded",
        exit_code=0,
        stdout="ajan/manage.py\n",
    )
    assert not is_successful_empty_discovery_result(
        status="failed",
        exit_code=1,
        stdout="",
    )


def test_empty_tracked_discovery_blocks_identical_retry():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        req = kwargs["request"]
        argv = list(req.argv)

        if argv == ["git", "ls-files", "*manage.py"]:
            return TaskCommandResult(
                command_id=f"git-{len(runner_calls)}",
                task_id="TASK-EMPTY-1",
                argv=argv,
                cwd=".",
                permission_level=(
                    PermissionLevel.EXECUTE_SAFE.value
                ),
                started_at="t0",
                finished_at="t1",
                duration_ms=2,
                exit_code=0,
                stdout="",
                stderr="",
                status="succeeded",
                execution_boundary="HOST_SAFE",
                network_policy=(
                    NetworkPolicy.NETWORK_NONE.value
                ),
            )

        if argv == [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "*manage.py",
        ]:
            return TaskCommandResult(
                command_id=f"git-u-{len(runner_calls)}",
                task_id="TASK-EMPTY-1",
                argv=argv,
                cwd=".",
                permission_level=(
                    PermissionLevel.EXECUTE_SAFE.value
                ),
                started_at="t0",
                finished_at="t1",
                duration_ms=2,
                exit_code=0,
                stdout="ajan/manage.py\n",
                stderr="",
                status="succeeded",
                execution_boundary="HOST_SAFE",
                network_policy=(
                    NetworkPolicy.NETWORK_NONE.value
                ),
            )

        raise AssertionError(
            f"Unexpected command: {argv!r}"
        )

    scripts = [
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "git",
                    "ls-files",
                    "*manage.py",
                ],
                "cwd": None,
                "reason": "tracked discovery",
            }
        ),
        # Identical empty discovery — must not re-run.
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "git",
                    "ls-files",
                    "*manage.py",
                ],
                "cwd": None,
                "reason": "repeat empty",
            }
        ),
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "git",
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "*manage.py",
                ],
                "cwd": None,
                "reason": "untracked discovery",
            }
        ),
        _action(
            {
                "action_type": "complete",
                "reason": "found untracked manage.py",
                "summary": "Untracked discovery worked.",
            }
        ),
    ]
    decider = ScriptedDecider(scripts)

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-EMPTY-1",
        prompt="find manage.py",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=True),
        command_runner=fake_runner,
        decision_caller=decider,
    )

    assert result.status == "completed"
    assert len(runner_calls) == 2
    assert list(runner_calls[0]["request"].argv) == [
        "git",
        "ls-files",
        "*manage.py",
    ]
    assert list(runner_calls[1]["request"].argv) == [
        "git",
        "ls-files",
        "--others",
        "--exclude-standard",
        "*manage.py",
    ]
    assert any(
        "returned no matches" in call["user_prompt"]
        for call in decider.calls[2:]
    )


def test_untracked_discovery_then_django_check_flow():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        req = kwargs["request"]
        argv = list(req.argv)
        cwd = str(req.cwd or ".")

        if argv == ["git", "ls-files", "*manage.py"]:
            return TaskCommandResult(
                command_id=f"tracked-{len(runner_calls)}",
                task_id="TASK-AJAN-1",
                argv=argv,
                cwd=".",
                permission_level=(
                    PermissionLevel.EXECUTE_SAFE.value
                ),
                started_at="t0",
                finished_at="t1",
                duration_ms=2,
                exit_code=0,
                stdout="",
                stderr="",
                status="succeeded",
                execution_boundary="HOST_SAFE",
                network_policy=(
                    NetworkPolicy.NETWORK_NONE.value
                ),
            )

        if argv == [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "*manage.py",
        ]:
            return TaskCommandResult(
                command_id=(
                    f"untracked-{len(runner_calls)}"
                ),
                task_id="TASK-AJAN-1",
                argv=argv,
                cwd=".",
                permission_level=(
                    PermissionLevel.EXECUTE_SAFE.value
                ),
                started_at="t0",
                finished_at="t1",
                duration_ms=2,
                exit_code=0,
                stdout="ajan/manage.py\n",
                stderr="",
                status="succeeded",
                execution_boundary="HOST_SAFE",
                network_policy=(
                    NetworkPolicy.NETWORK_NONE.value
                ),
            )

        if (
            argv[:3]
            == ["python", "manage.py", "check"]
            and cwd == "ajan"
        ):
            return _success_result(
                argv=argv,
                cwd="ajan",
                command_id=f"check-{len(runner_calls)}",
            )

        raise AssertionError(
            f"Unexpected command: argv={argv!r} cwd={cwd!r}"
        )

    scripts = [
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "git",
                    "ls-files",
                    "*manage.py",
                ],
                "cwd": None,
                "reason": "tracked",
            }
        ),
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "git",
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "*manage.py",
                ],
                "cwd": None,
                "reason": "untracked",
            }
        ),
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "python",
                    "manage.py",
                    "check",
                ],
                "cwd": "ajan",
                "reason": "from evidence",
            }
        ),
        _action(
            {
                "action_type": "complete",
                "reason": "django check ok",
                "summary": "Found via untracked discovery.",
            }
        ),
    ]
    decider = ScriptedDecider(scripts)

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-AJAN-1",
        prompt="django check",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=True),
        command_runner=fake_runner,
        decision_caller=decider,
    )

    assert result.status == "completed"
    assert len(runner_calls) == 3
    assert list(runner_calls[0]["request"].argv) == [
        "git",
        "ls-files",
        "*manage.py",
    ]
    assert list(runner_calls[1]["request"].argv) == [
        "git",
        "ls-files",
        "--others",
        "--exclude-standard",
        "*manage.py",
    ]
    assert list(runner_calls[2]["request"].argv) == [
        "python",
        "manage.py",
        "check",
    ]
    assert runner_calls[2]["request"].cwd == "ajan"
    # cwd must come from evidence, not prompt hardcoding
    # in controller — scripts derive it from stdout.
    assert "ajan/manage.py" in decider.calls[2][
        "user_prompt"
    ]


def test_oscillation_stall():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        return _failed_result(
            argv=list(kwargs["request"].argv)
        )

    scripts = []
    for argv in (
        ["cmd-a"],
        ["cmd-b"],
        ["cmd-a"],
        ["cmd-b"],
        ["cmd-a"],
        ["cmd-b"],
        ["cmd-a"],
    ):
        scripts.append(
            _action(
                {
                    "action_type": "run_command",
                    "argv": argv,
                    "cwd": None,
                    "reason": "osc",
                }
            )
        )

    # Raise consecutive failure / identical limits so
    # oscillation is the terminating reason. ABABAB
    # repeats each fingerprint three times.
    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-6",
        prompt="osc",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_consecutive_command_failures=99,
            max_identical_command_executions=3,
        ),
        command_runner=fake_runner,
        decision_caller=ScriptedDecider(scripts),
    )

    assert result.status == "stalled"
    assert result.reason == "stall_oscillation"
    assert len(runner_calls) == 6


def test_complete_without_evidence_rejected():
    decider = ScriptedDecider(
        [
            _action(
                {
                    "action_type": "complete",
                    "reason": "done",
                    "summary": "no evidence",
                }
            ),
            _action(
                {
                    "action_type": "complete",
                    "reason": "done again",
                    "summary": "still no",
                }
            ),
            _action(
                {
                    "action_type": "complete",
                    "reason": "done third",
                    "summary": "again",
                }
            ),
        ]
    )

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-7",
        prompt="complete early",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_consecutive_invalid_actions=3,
        ),
        command_runner=lambda **k: (_ for _ in ()).throw(
            AssertionError("no command")
        ),
        decision_caller=decider,
    )

    assert result.status == "budget_exceeded"
    assert (
        result.reason
        == "max_consecutive_invalid_actions"
    )
    assert "successful command" in decider.calls[1][
        "user_prompt"
    ]


def test_complete_after_failure_then_success():
    def fake_runner(**kwargs):
        argv = list(kwargs["request"].argv)
        if argv == ["bad"]:
            return _failed_result(argv=argv)
        return _success_result(argv=argv)

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-8",
        prompt="recover",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=False),
        command_runner=fake_runner,
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": ["bad"],
                        "cwd": None,
                        "reason": "fail first",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "too soon",
                        "summary": "nope",
                    }
                ),
                _action(
                    {
                        "action_type": "run_command",
                        "argv": ["good"],
                        "cwd": None,
                        "reason": "recover",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "now ok",
                        "summary": "done",
                    }
                ),
            ]
        ),
    )

    assert result.status == "completed"
    assert result.successful_commands == 1
    assert result.failed_commands == 1


def test_max_agent_steps_budget():
    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-9",
        prompt="budget",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_agent_steps=2,
            max_consecutive_invalid_actions=99,
        ),
        command_runner=lambda **k: (_ for _ in ()).throw(
            AssertionError("no command")
        ),
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "complete",
                        "reason": "a",
                        "summary": "a",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "b",
                        "summary": "b",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "c",
                        "summary": "c",
                    }
                ),
            ]
        ),
    )
    assert result.status == "budget_exceeded"
    assert result.reason == "max_agent_steps"
    assert result.steps_used == 2


def test_provider_decision_failures_bounded():
    def boom(**kwargs):
        raise RuntimeError("provider down")

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-10",
        prompt="provider",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_provider_decision_failures=3,
        ),
        command_runner=lambda **k: (_ for _ in ()).throw(
            AssertionError("no command")
        ),
        decision_caller=boom,
    )
    assert result.status == "failed"
    assert (
        result.reason
        == "max_provider_decision_failures"
    )
    assert "provider down" not in result.summary
    assert "provider down" not in result.reason


def test_wall_clock_budget_with_injectable_clock():
    ticks = iter([0.0, 0.0, 1000.0])

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-11",
        prompt="clock",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_wall_clock_seconds=10,
            max_consecutive_invalid_actions=99,
        ),
        command_runner=lambda **k: (_ for _ in ()).throw(
            AssertionError("no command")
        ),
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "complete",
                        "reason": "x",
                        "summary": "x",
                    }
                )
            ]
        ),
        clock=lambda: next(ticks),
    )
    assert result.status == "budget_exceeded"
    assert result.reason == "max_wall_clock_seconds"


def test_wall_clock_discards_provider_action_after_deadline():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        return _success_result(
            argv=list(kwargs["request"].argv)
        )

    # start=0, pre-decide wall=0, post-decide wall=100
    ticks = iter([0.0, 0.0, 100.0])

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-WC-LATE",
        prompt="late action",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_wall_clock_seconds=10,
            command_timeout_seconds=180,
        ),
        command_runner=fake_runner,
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": ["python", "--version"],
                        "cwd": None,
                        "reason": "should not run",
                    }
                )
            ]
        ),
        clock=lambda: next(ticks),
    )

    assert result.status == "budget_exceeded"
    assert result.reason == "max_wall_clock_seconds"
    assert runner_calls == []


def test_wall_clock_reduces_command_timeout():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        return _success_result(
            argv=list(kwargs["request"].argv)
        )

    # start=0, loop wall=1, post-provider=1,
    # remaining before command ≈ 10-5 = 5
    timeline = [0.0, 1.0, 1.0, 5.0]
    index = {"i": 0}

    def clock() -> float:
        i = index["i"]
        index["i"] = min(i + 1, len(timeline) - 1)
        return timeline[i]

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-WC-TIMEOUT",
        prompt="reduce timeout",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_wall_clock_seconds=10,
            command_timeout_seconds=180,
        ),
        command_runner=fake_runner,
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": ["python", "--version"],
                        "cwd": None,
                        "reason": "inspect",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "ok",
                        "summary": "done",
                    }
                ),
            ]
        ),
        clock=clock,
    )

    assert result.status == "completed"
    assert len(runner_calls) == 1
    assert (
        runner_calls[0]["request"].timeout_seconds
        == 5
    )


def test_wall_clock_no_usable_time_skips_command():
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        raise AssertionError("must not execute")

    # After provider, remaining < MIN_TIMEOUT (1).
    # start=0, pre-wall=0, post-provider=0,
    # remaining check before command → 9.5 → int 9?
    # Need remaining < 1 at command time.
    # start=0, wall pre=0, post=0, remaining at cmd=0.4 → int 0
    timeline = [0.0, 0.0, 0.0, 9.6]
    index = {"i": 0}

    def clock() -> float:
        i = index["i"]
        index["i"] = min(i + 1, len(timeline) - 1)
        return timeline[i]

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-WC-ZERO",
        prompt="no time",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_wall_clock_seconds=10,
            command_timeout_seconds=180,
        ),
        command_runner=fake_runner,
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": ["python", "--version"],
                        "cwd": None,
                        "reason": "inspect",
                    }
                )
            ]
        ),
        clock=clock,
    )

    assert result.status == "budget_exceeded"
    assert result.reason == "max_wall_clock_seconds"
    assert runner_calls == []


def test_provider_error_secret_absent_from_next_prompt():
    secret = "SECRET_TOKEN_ABC"
    prompts: list[str] = []
    failures_left = {"n": 1}

    def caller(**kwargs):
        prompts.append(kwargs["user_prompt"])
        if failures_left["n"] > 0:
            failures_left["n"] -= 1
            raise RuntimeError(secret)
        return _action(
            {
                "action_type": "fail",
                "reason": "done",
            }
        )

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-PROV-PROMPT",
        prompt="sanitize prompt",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_provider_decision_failures=3,
        ),
        command_runner=lambda **k: (_ for _ in ()).throw(
            AssertionError("no command")
        ),
        decision_caller=caller,
    )

    assert result.status == "failed"
    assert len(prompts) == 2
    assert secret not in prompts[1]
    assert "RuntimeError" in prompts[1]
    assert "Provider decision failed" in prompts[1]
    assert secret not in result.summary
    assert secret not in result.reason


def test_provider_max_failures_result_has_no_secret():
    secret = "SECRET_TOKEN_ABC"

    def boom(**kwargs):
        raise RuntimeError(secret)

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-PROV-FINAL",
        prompt="sanitize final",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=False,
            max_provider_decision_failures=3,
        ),
        command_runner=lambda **k: (_ for _ in ()).throw(
            AssertionError("no command")
        ),
        decision_caller=boom,
    )

    assert result.status == "failed"
    assert (
        result.reason
        == "max_provider_decision_failures"
    )
    assert secret not in result.summary
    assert secret not in result.reason
    assert result.last_observation is not None
    assert secret not in (
        result.last_observation.controller_feedback
        or ""
    )


def test_infrastructure_failure_terminates():
    def boom(**kwargs):
        raise TaskCommandSandboxRuntimeError(
            "Docker unavailable"
        )

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-12",
        prompt="infra",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=True),
        command_runner=boom,
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": ["python", "x.py"],
                        "cwd": None,
                        "reason": "run",
                    }
                ),
                _action(
                    {
                        "action_type": "run_command",
                        "argv": ["python", "y.py"],
                        "cwd": None,
                        "reason": "should not run",
                    }
                ),
            ]
        ),
    )
    assert result.status == "failed"
    assert "infrastructure_failure" in result.reason
    assert "Docker unavailable" in result.reason


def test_fail_action_returns_failed():
    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-13",
        prompt="fail",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=False),
        command_runner=lambda **k: (_ for _ in ()).throw(
            AssertionError("no command")
        ),
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "fail",
                        "reason": "cannot proceed",
                    }
                )
            ]
        ),
    )
    assert result.status == "failed"
    assert result.reason == "cannot proceed"


def test_execute_policy_defaults_allow_mutating():
    policy = build_execute_terminal_policy()
    assert policy.allow_mutating is True
    assert policy.max_agent_steps == 16
    assert policy.max_command_executions == 12


def test_fingerprint_ignores_reason():
    assert command_fingerprint(
        ["python", "--version"],
        None,
    ) == command_fingerprint(
        ["python", "--version"],
        ".",
    )


def test_command_history_via_real_runner(tmp_path):
    db_path = tmp_path / "history.db"
    init_task_command_store(db_path)

    def runner(**kwargs):
        return run_task_command(
            project_path=tmp_path,
            request=kwargs["request"],
            db_path=db_path,
            persist=True,
        )

    result = run_agent_terminal_loop(
        project_path=str(tmp_path),
        task_id="TASK-HIST",
        prompt="version",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=False),
        command_runner=runner,
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": [
                            sys.executable,
                            "--version",
                        ],
                        "cwd": None,
                        "reason": "inspect",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "ok",
                        "summary": "version checked",
                    }
                ),
            ]
        ),
    )
    assert result.status == "completed"
    history = list_task_commands(
        "TASK-HIST",
        db_path=db_path,
    )
    assert len(history) == 1
    assert history[0]["status"] == "succeeded"


def test_fake_provider_host_safe_acceptance(tmp_path):
    result = run_agent_terminal_loop(
        project_path=str(tmp_path),
        task_id="TASK-HOST",
        prompt="Inspect Python and finish.",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=False),
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": [
                            sys.executable,
                            "--version",
                        ],
                        "cwd": None,
                        "reason": "inspect",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "ok",
                        "summary": "Python available",
                    }
                ),
            ]
        ),
    )
    assert result.status == "completed"
    assert result.last_observation is not None
    assert (
        result.last_observation.execution_boundary
        == "HOST_SAFE"
    )


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        completed = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
            shell=False,
        )
        return completed.returncode == 0
    except Exception:
        return False


def test_fake_provider_project_code_sandbox_simulated(
    tmp_path,
    monkeypatch,
):
    """PROJECT_CODE_SANDBOX path without requiring Docker daemon."""
    import os

    from factory.task_command_dependency_environment import (
        CONTAINER_VENV_PYTHON,
        dependency_environment_name,
    )
    from factory.task_command_sandbox import (
        TaskCommandSandboxResult,
        build_docker_run_argv,
        map_argv_for_container,
    )

    script = tmp_path / "hello.py"
    script.write_text(
        "print('sandbox-ok')\n",
        encoding="utf-8",
    )

    def _fake_ensure(**kwargs):
        return dependency_environment_name(
            project_root=kwargs["project_root"],
            task_id=kwargs["task_id"],
        )

    def _fake(
        *,
        project_root,
        workdir,
        host_argv,
        request_env,
        network_policy,
        command_id,
        timeout_seconds,
        image_name="ai-factory-python-test",
        host_environ=None,
        dependency_volume_name=None,
    ):
        container_argv = map_argv_for_container(
            host_argv=host_argv,
            project_root=project_root,
            workdir=workdir,
            use_dependency_environment=(
                dependency_volume_name is not None
            ),
        )
        short_id = command_id.replace("-", "")[:12]
        container_name = (
            f"ai-factory-taskcmd-{short_id}"
        )
        docker_argv = build_docker_run_argv(
            project_root=project_root,
            workdir=workdir,
            container_argv=container_argv,
            network_policy=network_policy,
            container_name=container_name,
            image_name=image_name,
            dependency_volume_name=(
                dependency_volume_name
            ),
        )
        run_argv = list(container_argv)
        if run_argv and run_argv[0] in {
            "python",
            CONTAINER_VENV_PYTHON,
        }:
            run_argv[0] = sys.executable

        process_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get(
                "SYSTEMROOT",
                "",
            ),
            "WINDIR": os.environ.get("WINDIR", ""),
        }
        process_env.update(request_env or {})

        completed = subprocess.run(
            run_argv,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=timeout_seconds,
            env=process_env,
        )
        return TaskCommandSandboxResult(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            timed_out=False,
            docker_argv=docker_argv,
            container_argv=container_argv,
            container_name=container_name,
        )

    monkeypatch.setattr(
        "factory.task_command_runner."
        "ensure_dependency_environment",
        _fake_ensure,
    )
    monkeypatch.setattr(
        "factory.task_command_runner."
        "run_in_task_command_sandbox",
        _fake,
    )

    result = run_agent_terminal_loop(
        project_path=str(tmp_path),
        task_id="TASK-SBX-SIM",
        prompt="Run hello.py",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=True),
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": [
                            "python",
                            "hello.py",
                        ],
                        "cwd": None,
                        "reason": "run script",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "ok",
                        "summary": "script ran",
                    }
                ),
            ]
        ),
    )
    assert result.status == "completed"
    assert result.last_observation is not None
    assert (
        result.last_observation.execution_boundary
        == "PROJECT_CODE_SANDBOX"
    )
    assert "sandbox-ok" in (
        result.last_observation.stdout
    )


@pytest.mark.skipif(
    not _docker_ready(),
    reason="Docker unavailable",
)
def test_fake_provider_project_code_sandbox_acceptance(
    tmp_path,
):
    script = tmp_path / "hello.py"
    script.write_text(
        "print('sandbox-ok')\n",
        encoding="utf-8",
    )

    result = run_agent_terminal_loop(
        project_path=str(tmp_path),
        task_id="TASK-SBX",
        prompt="Run hello.py",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=True),
        decision_caller=ScriptedDecider(
            [
                _action(
                    {
                        "action_type": "run_command",
                        "argv": [
                            "python",
                            "hello.py",
                        ],
                        "cwd": None,
                        "reason": "run script",
                    }
                ),
                _action(
                    {
                        "action_type": "complete",
                        "reason": "ok",
                        "summary": "script ran",
                    }
                ),
            ]
        ),
    )
    assert result.status == "completed"
    assert result.last_observation is not None
    assert (
        result.last_observation.execution_boundary
        == "PROJECT_CODE_SANDBOX"
    )
    assert "sandbox-ok" in (
        result.last_observation.stdout
    )


@pytest.mark.skipif(
    not _docker_ready(),
    reason="Docker unavailable",
)
def test_package_persistence_acceptance(tmp_path):
    from factory.task_command_dependency_environment import (
        remove_dependency_environment,
    )

    project = tmp_path / "proj"
    project.mkdir()
    script = project / "use_six.py"
    script.write_text(
        "import six\nprint(six.__version__)\n",
        encoding="utf-8",
    )
    task_id = "TASK-PIP"

    try:
        result = run_agent_terminal_loop(
            project_path=str(project),
            task_id=task_id,
            prompt="Install six and import it.",
            model_route=SimpleNamespace(model="m"),
            model_client=object(),
            policy=AgentTerminalPolicy(
                allow_mutating=True
            ),
            decision_caller=ScriptedDecider(
                [
                    _action(
                        {
                            "action_type": "run_command",
                            "argv": [
                                "python",
                                "-m",
                                "pip",
                                "install",
                                "six",
                            ],
                            "cwd": None,
                            "reason": "install",
                        }
                    ),
                    _action(
                        {
                            "action_type": "run_command",
                            "argv": [
                                "python",
                                "use_six.py",
                            ],
                            "cwd": None,
                            "reason": "import",
                        }
                    ),
                    _action(
                        {
                            "action_type": "complete",
                            "reason": "ok",
                            "summary": "six works",
                        }
                    ),
                ]
            ),
        )
        assert result.status == "completed"
        assert result.commands_executed == 2
        assert result.successful_commands == 2

        history = list_task_commands(task_id)
        assert len(history) >= 2
        install = history[0]
        follow = history[1]
        assert (
            install["network_policy"]
            == NetworkPolicy.NETWORK_PACKAGE_INSTALL.value
        )
        assert (
            follow["network_policy"]
            == NetworkPolicy.NETWORK_NONE.value
        )
        assert follow["status"] == "succeeded"
    finally:
        remove_dependency_environment(
            project_root=project,
            task_id=task_id,
        )


def test_provider_router_integration_with_fake_runtime(
    monkeypatch,
):
    from factory.agents.contracts import AgentResult
    from factory.agents.execution_router import (
        AgentFallbackExecution,
        AgentRoute,
    )
    from factory.agents.capabilities import (
        AgentCapability,
        AgentDescriptor,
    )

    class FakeProvider:
        provider_name = "fake"

        def complete(self, request):
            assert "ORIGINAL USER TASK" in (
                request.user_prompt
            )
            return AgentResult(
                content=_action(
                    {
                        "action_type": "fail",
                        "reason": "stop",
                    }
                ),
                provider="fake",
                model="m",
            )

    class FakeRouter:
        provider_registry = SimpleNamespace()

        def execute_with_fallback(
            self,
            request,
            required,
            *,
            preferred_provider=None,
            policy=None,
        ):
            assert AgentCapability.RUN_TESTS in required
            provider = FakeProvider()
            result = provider.complete(request)
            return AgentFallbackExecution(
                route=AgentRoute(
                    agent=AgentDescriptor(
                        name="fake-verifier",
                        provider_name="fake",
                        capabilities=frozenset(
                            {
                                AgentCapability.READ_REPOSITORY,
                                AgentCapability.RUN_TESTS,
                            }
                        ),
                    ),
                    provider=provider,
                ),
                result=result,
            )

    monkeypatch.setattr(
        "factory.agent_terminal_loop."
        "build_default_agent_execution_router",
        lambda _client: FakeRouter(),
    )
    monkeypatch.setattr(
        "factory.agent_terminal_loop."
        "resolve_provider_for_role",
        lambda *_a, **_k: "fake",
    )

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-ROUTE",
        prompt="router path",
        model_route=SimpleNamespace(model="chosen"),
        model_client=object(),
        policy=AgentTerminalPolicy(allow_mutating=False),
        command_runner=lambda **k: (_ for _ in ()).throw(
            AssertionError("no command")
        ),
    )
    assert result.status == "failed"
    assert result.reason == "stop"


def test_django_admin_reject_then_replan_to_python_module(
    tmp_path,
):
    """Rejected django-admin becomes observation; supported forms succeed."""
    db_path = tmp_path / "factory.db"
    init_task_command_store(db_path)
    runner_calls: list[list[str]] = []

    def fake_runner(**kwargs):
        request = kwargs["request"]
        argv = list(request.argv)
        runner_calls.append(argv)
        cwd = request.cwd or "."

        if argv and argv[0] == "django-admin":
            # Mimic real runner: persist REJECTED, return result.
            from factory.task_command_models import (
                CommandStatus,
            )
            from factory.task_command_store import (
                save_task_command,
            )

            result = TaskCommandResult(
                command_id="rej-1",
                task_id=request.task_id,
                argv=argv,
                cwd=cwd,
                permission_level=(
                    PermissionLevel.DANGEROUS.value
                ),
                started_at="t0",
                finished_at="t0",
                duration_ms=0,
                exit_code=None,
                stdout="",
                stderr=(
                    "Executable izinli degil: django-admin"
                ),
                status=CommandStatus.REJECTED.value,
            )
            if kwargs.get("persist", True):
                save_task_command(
                    result=result,
                    db_path=db_path,
                )
            return result

        return _success_result(
            argv=argv,
            cwd=str(cwd),
            command_id=f"ok-{len(runner_calls)}",
        )

    scripts = [
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "django-admin",
                    "startproject",
                    "ajan",
                ],
                "cwd": None,
                "reason": "scaffold",
            }
        ),
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "python",
                    "-m",
                    "django",
                    "startproject",
                    "ajan",
                ],
                "cwd": None,
                "reason": "supported form",
            }
        ),
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "python",
                    "manage.py",
                    "startapp",
                    "users",
                ],
                "cwd": "ajan",
                "reason": "app",
            }
        ),
        _action(
            {
                "action_type": "run_command",
                "argv": [
                    "python",
                    "manage.py",
                    "check",
                ],
                "cwd": "ajan",
                "reason": "verify",
            }
        ),
        _action(
            {
                "action_type": "complete",
                "reason": "done",
                "summary": "Django scaffold ready",
            }
        ),
    ]
    decider = ScriptedDecider(scripts)

    result = run_agent_terminal_loop(
        project_path=str(tmp_path),
        task_id="TASK-DJANGO-REPLAN",
        prompt=(
            "ajan adinda django projesi ve users app"
        ),
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=True,
            max_consecutive_command_failures=3,
        ),
        command_runner=fake_runner,
        decision_caller=decider,
    )

    assert result.status == "completed"
    assert len(runner_calls) == 4
    assert runner_calls[0][0] == "django-admin"
    assert runner_calls[1][:3] == [
        "python",
        "-m",
        "django",
    ]

    # Rejection visible in next model context.
    assert len(decider.calls) >= 2
    second_prompt = decider.calls[1]["user_prompt"]
    assert "django-admin" in second_prompt
    assert "rejected" in second_prompt.casefold()
    assert (
        "izinli degil" in second_prompt.casefold()
        or "rejection_reason" in second_prompt
    )

    history = list_task_commands(
        "TASK-DJANGO-REPLAN",
        db_path=db_path,
    )
    assert any(
        row["status"] == "rejected"
        and row["argv"][0] == "django-admin"
        for row in history
    )


def test_controller_injects_secret_for_createsuperuser():
    from factory.task_secret_store import (
        reset_task_secret_store_for_tests,
        set_task_secrets,
    )

    reset_task_secret_store_for_tests()
    secret = "loop-secret-pw-55"
    set_task_secrets(
        "TASK-SEC-1",
        {"user_password": secret},
    )

    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        req = kwargs["request"]
        return _success_result(argv=list(req.argv))

    decider = ScriptedDecider(
        [
            _action(
                {
                    "action_type": "run_command",
                    "argv": [
                        "python",
                        "manage.py",
                        "createsuperuser",
                        "--noinput",
                        "--username",
                        "admin",
                        "--email",
                        "a@b.c",
                    ],
                    "cwd": "edusen",
                    "reason": "create admin",
                }
            ),
            _action(
                {
                    "action_type": "run_command",
                    "argv": ["python", "--version"],
                    "cwd": None,
                    "reason": "unrelated",
                }
            ),
            _action(
                {
                    "action_type": "complete",
                    "reason": "done",
                    "summary": "created",
                }
            ),
        ]
    )

    try:
        result = run_agent_terminal_loop(
            project_path="/repo",
            task_id="TASK-SEC-1",
            prompt=(
                "projeye superuser olustur "
                "[SECRET:user_password]"
            ),
            model_route=SimpleNamespace(model="m"),
            model_client=object(),
            policy=build_execute_terminal_policy(),
            command_runner=fake_runner,
            decision_caller=decider,
        )
    finally:
        reset_task_secret_store_for_tests()

    assert result.status == "completed"
    assert len(runner_calls) == 2

    create_req = runner_calls[0]["request"]
    assert create_req.env == {
        "DJANGO_SUPERUSER_PASSWORD": secret,
    }
    assert create_req.secret_env_keys == [
        "DJANGO_SUPERUSER_PASSWORD",
    ]
    assert secret not in create_req.argv

    version_req = runner_calls[1]["request"]
    assert version_req.env == {}
    assert version_req.secret_env_keys == []

    first_prompt = decider.calls[0]["user_prompt"]
    assert "user_password" in first_prompt
    assert "AVAILABLE CONTROLLER SECRETS" in (
        first_prompt
    )
    assert secret not in first_prompt
    assert secret not in json.dumps(
        result.to_dict()
    )


def test_missing_required_secret_rejects_safely():
    from factory.task_secret_injection import (
        MISSING_TASK_SECRET_MESSAGE,
    )
    from factory.task_secret_store import (
        reset_task_secret_store_for_tests,
        set_task_secrets,
        clear_task_secrets,
    )

    reset_task_secret_store_for_tests()
    set_task_secrets(
        "TASK-SEC-2",
        {"user_password": "will-clear"},
    )

    # Capture names at loop start, then clear so
    # required_secret_names still expects the secret.
    runner_calls: list[dict] = []

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        req = kwargs["request"]
        return _success_result(argv=list(req.argv))

    decider = ScriptedDecider(
        [
            _action(
                {
                    "action_type": "run_command",
                    "argv": [
                        "python",
                        "manage.py",
                        "createsuperuser",
                        "--noinput",
                    ],
                    "cwd": None,
                    "reason": "create",
                }
            ),
            _action(
                {
                    "action_type": "fail",
                    "reason": "cannot continue",
                }
            ),
        ]
    )

    clear_task_secrets("TASK-SEC-2")
    # Re-seed names expectation path: set then clear
    # after loop starts is hard; instead set names by
    # re-adding then clearing inside decision.
    set_task_secrets(
        "TASK-SEC-2",
        {"user_password": "temp-visible-name"},
    )

    cleared = {"done": False}

    class ClearingDecider(ScriptedDecider):
        def __call__(self, **kwargs) -> str:
            if not cleared["done"]:
                clear_task_secrets("TASK-SEC-2")
                cleared["done"] = True
            return super().__call__(**kwargs)

    clearing = ClearingDecider(decider.scripts)

    try:
        result = run_agent_terminal_loop(
            project_path="/repo",
            task_id="TASK-SEC-2",
            prompt="create superuser",
            model_route=SimpleNamespace(model="m"),
            model_client=object(),
            policy=build_execute_terminal_policy(),
            command_runner=fake_runner,
            decision_caller=clearing,
        )
    finally:
        reset_task_secret_store_for_tests()

    assert runner_calls == []
    assert result.status in {
        "failed",
        "stalled",
    }
    obs = result.last_observation
    assert obs is not None
    assert (
        MISSING_TASK_SECRET_MESSAGE
        in (obs.rejection_reason or "")
    )
    assert "temp-visible-name" not in json.dumps(
        result.to_dict()
    )
    assert "will-clear" not in json.dumps(
        result.to_dict()
    )


def test_django_createsuperuser_recovers_after_install_and_migrate():
    """Missing dependency → install → schema miss → migrate → retry → complete.

    Failed subprocess commands must not count toward
    max_consecutive_invalid_actions. After remediation
    succeeds, retrying the original operation must be
    able to finish without exhausting the invalid budget.
    """
    createsuperuser = [
        "python",
        "manage.py",
        "createsuperuser",
        "--noinput",
        "--username",
        "admin",
        "--email",
        "admin@example.com",
    ]
    install = [
        "python",
        "-m",
        "pip",
        "install",
        "django",
    ]
    migrate = [
        "python",
        "manage.py",
        "migrate",
    ]

    runner_calls: list[dict] = []
    phase = {"n": 0}

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        req = kwargs["request"]
        argv = list(req.argv)
        cwd = req.cwd
        phase["n"] += 1

        if phase["n"] == 1:
            assert argv == createsuperuser
            assert cwd == "ajan"
            return _failed_result(
                argv=argv,
                cwd=cwd or ".",
                stderr=(
                    "ModuleNotFoundError: "
                    "No module named 'django'"
                ),
            )

        if phase["n"] == 2:
            assert argv == install
            return _success_result(
                argv=argv,
                cwd=cwd or ".",
            )

        if phase["n"] == 3:
            assert argv == createsuperuser
            assert cwd == "ajan"
            return _failed_result(
                argv=argv,
                cwd=cwd or ".",
                stderr=(
                    "django.db.utils.OperationalError: "
                    "no such table: auth_user"
                ),
            )

        if phase["n"] == 4:
            assert argv == migrate
            assert cwd == "ajan"
            return _success_result(
                argv=argv,
                cwd=cwd or ".",
            )

        if phase["n"] == 5:
            assert argv == createsuperuser
            assert cwd == "ajan"
            return _success_result(
                argv=argv,
                cwd=cwd or ".",
                command_id="cmd-superuser-ok",
            )

        raise AssertionError(
            f"unexpected command #{phase['n']}: {argv}"
        )

    decider = ScriptedDecider(
        [
            _action(
                {
                    "action_type": "run_command",
                    "argv": createsuperuser,
                    "cwd": "ajan",
                    "reason": "create superuser",
                }
            ),
            _action(
                {
                    "action_type": "run_command",
                    "argv": install,
                    "cwd": None,
                    "reason": "install missing django",
                }
            ),
            _action(
                {
                    "action_type": "run_command",
                    "argv": createsuperuser,
                    "cwd": "ajan",
                    "reason": "retry after install",
                }
            ),
            _action(
                {
                    "action_type": "run_command",
                    "argv": migrate,
                    "cwd": "ajan",
                    "reason": "apply schema",
                }
            ),
            _action(
                {
                    "action_type": "run_command",
                    "argv": createsuperuser,
                    "cwd": "ajan",
                    "reason": "retry after migrate",
                }
            ),
            _action(
                {
                    "action_type": "complete",
                    "reason": "superuser created",
                    "summary": "createsuperuser succeeded",
                }
            ),
        ]
    )

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-DJANGO-RECOVERY",
        prompt=(
            "ajan Django projesinde admin "
            "superuser olustur"
        ),
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=True,
            max_consecutive_invalid_actions=3,
        ),
        command_runner=fake_runner,
        decision_caller=decider,
    )

    assert result.status == "completed"
    assert result.reason != "max_consecutive_invalid_actions"
    assert result.commands_executed == 5
    assert result.successful_commands == 3
    assert result.failed_commands == 2
    assert len(runner_calls) == 5
    assert list(runner_calls[-1]["request"].argv) == (
        createsuperuser
    )
    assert runner_calls[-1]["request"].cwd == "ajan"
    # Failed subprocesses must not appear as controller
    # invalid-action feedback in the completion path.
    assert result.last_observation is not None
    assert result.last_observation.status == "succeeded"


def test_malformed_actions_remain_bounded_after_remediation():
    """Valid remediation resets the invalid streak; later
    malformed decisions still exhaust the budget.
    """
    prompts: list[str] = []

    def fake_runner(**kwargs):
        return _success_result(
            argv=list(kwargs["request"].argv)
        )

    class TrackingDecider(ScriptedDecider):
        def __call__(self, **kwargs) -> str:
            prompts.append(kwargs["user_prompt"])
            return super().__call__(**kwargs)

    decider = TrackingDecider(
        [
            _action(
                {
                    "action_type": "run_command",
                    "argv": [
                        "python",
                        "-m",
                        "pip",
                        "install",
                        "django",
                    ],
                    "cwd": None,
                    "reason": "remediate",
                }
            ),
            "not json at all",
            "```json\n{\"action_type\":\"complete\"}\n```",
            "still not a raw json object",
        ]
    )

    result = run_agent_terminal_loop(
        project_path="/repo",
        task_id="TASK-INVALID-BOUND",
        prompt="bounded malformed",
        model_route=SimpleNamespace(model="m"),
        model_client=object(),
        policy=AgentTerminalPolicy(
            allow_mutating=True,
            max_consecutive_invalid_actions=3,
        ),
        command_runner=fake_runner,
        decision_caller=decider,
    )

    assert result.status == "budget_exceeded"
    assert (
        result.reason
        == "max_consecutive_invalid_actions"
    )
    assert result.successful_commands == 1
    assert result.commands_executed == 1
    # Corrective feedback must reach the model.
    assert len(prompts) == 4
    assert "Invalid action rejected" in prompts[2]
    assert "retry the original" in prompts[2].casefold()
    assert "Invalid action rejected" in prompts[3]
