"""Production Agent Terminal Loop contracts.

Controller-owned policy and structured results.
Independent of experimental general_agent_* stack.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


AgentTerminalStatus = Literal[
    "completed",
    "failed",
    "stalled",
    "budget_exceeded",
]


@dataclass(frozen=True)
class AgentTerminalPolicy:
    """Controller authority for one terminal session.

    The model cannot modify these fields.
    """

    allow_mutating: bool = False
    # Git repository mutation (refs/config/stash/...).
    # Independent of filesystem allow_mutating.
    # Default True preserves non-EXECUTE callers.
    allow_git_mutation: bool = True
    max_agent_steps: int = 16
    max_command_executions: int = 12
    max_identical_command_executions: int = 2
    max_consecutive_command_failures: int = 3
    max_consecutive_invalid_actions: int = 3
    max_provider_decision_failures: int = 3
    max_wall_clock_seconds: int = 900
    command_timeout_seconds: int = 180
    require_successful_command_before_complete: bool = (
        True
    )


@dataclass(frozen=True)
class RunCommandAction:
    action_type: Literal["run_command"] = (
        "run_command"
    )
    argv: tuple[str, ...] = ()
    cwd: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class CompleteAction:
    action_type: Literal["complete"] = "complete"
    reason: str = ""
    summary: str | None = None


@dataclass(frozen=True)
class FailAction:
    action_type: Literal["fail"] = "fail"
    reason: str = ""


TerminalAction = (
    RunCommandAction
    | CompleteAction
    | FailAction
)


@dataclass(frozen=True)
class TerminalObservation:
    """Model-facing view of a command outcome."""

    command_id: str
    argv: list[str]
    cwd: str
    permission_level: str
    execution_boundary: str
    network_policy: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    rejection_reason: str | None = None
    timed_out: bool = False
    controller_feedback: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentTerminalResult:
    status: AgentTerminalStatus
    summary: str
    reason: str
    steps_used: int = 0
    commands_executed: int = 0
    successful_commands: int = 0
    failed_commands: int = 0
    rejected_commands: int = 0
    last_observation: TerminalObservation | None = (
        None
    )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "summary": self.summary,
            "reason": self.reason,
            "steps_used": self.steps_used,
            "commands_executed": (
                self.commands_executed
            ),
            "successful_commands": (
                self.successful_commands
            ),
            "failed_commands": (
                self.failed_commands
            ),
            "rejected_commands": (
                self.rejected_commands
            ),
            "last_observation": None,
        }

        if self.last_observation is not None:
            payload["last_observation"] = (
                self.last_observation.to_dict()
            )

        return payload


@dataclass(frozen=True)
class AgentTerminalRouteContext:
    intent: str | None = None
    target: str | None = None
    framework: str | None = None


def build_execute_terminal_policy() -> (
    AgentTerminalPolicy
):
    """Production EXECUTE mutation policy.

    allow_mutating=True is controller-owned so
    controlled package install / project execution
    can pass TaskCommand gates. DANGEROUS remains
    unconditionally rejected by the runner.

    allow_git_mutation=False: linked worktrees share
    common-dir refs/config/stash; EXECUTE must not
    mutate repository-wide Git metadata. Filesystem
    writes stay allowed inside the disposable worktree.
    """
    return AgentTerminalPolicy(
        allow_mutating=True,
        allow_git_mutation=False,
    )


def observation_from_task_command_result(
    result: Any,
    *,
    rejection_reason: str | None = None,
    controller_feedback: str | None = None,
) -> TerminalObservation:
    status = str(
        getattr(result, "status", "") or ""
    )
    return TerminalObservation(
        command_id=str(
            getattr(result, "command_id", "")
            or ""
        ),
        argv=list(
            getattr(result, "argv", []) or []
        ),
        cwd=str(
            getattr(result, "cwd", "") or ""
        ),
        permission_level=str(
            getattr(
                result,
                "permission_level",
                "",
            )
            or ""
        ),
        execution_boundary=str(
            getattr(
                result,
                "execution_boundary",
                "",
            )
            or ""
        ),
        network_policy=str(
            getattr(
                result,
                "network_policy",
                "",
            )
            or ""
        ),
        status=status,
        exit_code=getattr(
            result,
            "exit_code",
            None,
        ),
        stdout=str(
            getattr(result, "stdout", "") or ""
        ),
        stderr=str(
            getattr(result, "stderr", "") or ""
        ),
        duration_ms=int(
            getattr(result, "duration_ms", 0)
            or 0
        ),
        rejection_reason=rejection_reason,
        timed_out=(status == "timed_out"),
        controller_feedback=controller_feedback,
    )


def rejected_observation(
    *,
    argv: list[str],
    cwd: str | None,
    rejection_reason: str,
    controller_feedback: str | None = None,
) -> TerminalObservation:
    return TerminalObservation(
        command_id="",
        argv=list(argv),
        cwd=str(cwd or "."),
        permission_level="",
        execution_boundary="",
        network_policy="",
        status="rejected",
        exit_code=None,
        stdout="",
        stderr="",
        duration_ms=0,
        rejection_reason=rejection_reason,
        timed_out=False,
        controller_feedback=controller_feedback,
    )


def controller_feedback_observation(
    message: str,
) -> TerminalObservation:
    return TerminalObservation(
        command_id="",
        argv=[],
        cwd=".",
        permission_level="",
        execution_boundary="",
        network_policy="",
        status="controller",
        exit_code=None,
        stdout="",
        stderr="",
        duration_ms=0,
        rejection_reason=None,
        timed_out=False,
        controller_feedback=message,
    )
