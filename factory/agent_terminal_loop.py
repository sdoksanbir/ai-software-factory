"""Production Agent Terminal Loop.

Model requests structured actions. Controller owns
policy. All commands go through run_task_command.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from factory.agent_terminal_models import (
    AgentTerminalPolicy,
    AgentTerminalResult,
    AgentTerminalRouteContext,
    CompleteAction,
    FailAction,
    RunCommandAction,
    TerminalObservation,
    build_execute_terminal_policy,
    controller_feedback_observation,
    observation_from_task_command_result,
    rejected_observation,
)
from factory.agent_terminal_parser import (
    AgentTerminalParseError,
    parse_terminal_action,
)
from factory.agent_terminal_prompt import (
    build_terminal_system_prompt,
    build_terminal_user_prompt,
)
from factory.agents.capabilities import (
    AgentCapability,
)
from factory.agents.contracts import (
    AgentRequest,
)
from factory.agents.runtime import (
    build_default_agent_execution_router,
    resolve_provider_for_role,
)
from factory.task_command_models import (
    MIN_TIMEOUT_SECONDS,
    TaskCommandPathError,
    TaskCommandPolicyError,
    TaskCommandRequest,
    TaskCommandSandboxRuntimeError,
    TaskCommandValidationError,
)
from factory.task_command_runner import (
    is_host_safe_git_argv,
    run_task_command,
)
from factory.task_secret_injection import (
    TaskSecretUnavailableError,
    resolve_task_command_secret_env,
)
from factory.task_secret_store import (
    list_task_secret_names,
)


def _sanitized_provider_failure_feedback(
    exc: BaseException,
) -> str:
    """Model-facing provider failure text.

    Exception type name only — never str(exc).
    """
    return (
        "Provider decision failed: "
        f"{type(exc).__name__}."
    )


_PROVIDER_FAILURE_SUMMARY = (
    "Provider decision failed. "
    "The controller exhausted the provider "
    "decision budget."
)


CommandRunner = Callable[..., Any]
DecisionCaller = Callable[..., str]
Clock = Callable[[], float]


# Conservative stderr markers for deterministic
# missing-file/path failures. Do not treat every
# nonzero exit as deterministic.
_MISSING_PATH_STDERR_MARKERS = (
    "no such file or directory",
    "can't open file",
    "cannot open file",
    "cannot find the path",
    "the system cannot find the path",
    "cannot find the file",
    "the system cannot find the file",
    "file not found",
    "path not found",
)

_DETERMINISTIC_MISSING_PATH_FEEDBACK = (
    "The referenced file/path was not found from "
    "the current cwd. Inspect the repository and "
    "change cwd or argv before retrying."
)

_EMPTY_DISCOVERY_FEEDBACK = (
    "Discovery command succeeded but returned no "
    "matches. Do not repeat the same query unchanged. "
    "Try another safe discovery source, including "
    "untracked non-ignored files, or change the "
    "search pattern."
)


def is_deterministic_missing_path_failure(
    *,
    status: str,
    exit_code: int | None,
    stderr: str,
) -> bool:
    """Classify clearly deterministic missing-path fails.

    Controller-owned. Conservative: requires failed
    status plus a known missing-path stderr marker.
    Nonzero exit alone is not enough.
    """
    del exit_code  # reserved for future tightening

    if str(status or "") != "failed":
        return False

    text = str(stderr or "").casefold()

    if not text:
        return False

    return any(
        marker in text
        for marker in _MISSING_PATH_STDERR_MARKERS
    )


def is_deterministic_git_ls_files_discovery(
    argv: Sequence[str],
) -> bool:
    """True for safe ``git ls-files`` discovery argv.

    Targeted to deterministic repository discovery.
    Does not classify arbitrary successful commands.
    """
    tokens = [str(part) for part in argv]

    if not tokens:
        return False

    executable = Path(tokens[0]).name.casefold()

    if executable not in {"git", "git.exe"}:
        return False

    # is_host_safe_git_argv expects subcommand argv
    # without the git executable token.
    return is_host_safe_git_argv(tokens[1:]) and (
        _git_subcommand_is_ls_files(tokens[1:])
    )


def _git_subcommand_is_ls_files(
    args: Sequence[str],
) -> bool:
    index = 0

    while index < len(args):
        lowered = str(args[index]).casefold()

        if lowered == "--no-pager":
            index += 1
            continue

        if lowered.startswith("-"):
            return False

        return lowered == "ls-files"

    return False


def is_successful_empty_discovery_result(
    *,
    status: str,
    exit_code: int | None,
    stdout: str,
) -> bool:
    """Success with empty stdout — discovery found nothing."""
    if str(status or "") != "succeeded":
        return False

    if exit_code not in (0, None):
        return False

    return not str(stdout or "").strip()


def command_fingerprint(
    argv: Sequence[str],
    cwd: str | None,
) -> str:
    normalized_cwd = str(cwd or ".").strip() or "."
    normalized_cwd = normalized_cwd.replace(
        "\\",
        "/",
    )

    if normalized_cwd.endswith("/") and (
        normalized_cwd != "/"
    ):
        normalized_cwd = normalized_cwd[:-1]

    parts = [str(part) for part in argv]
    return "\0".join(
        [
            *parts,
            normalized_cwd,
        ]
    )


def _is_negative_status(status: str) -> bool:
    return status in {
        "failed",
        "timed_out",
        "rejected",
    }


def _is_success_status(status: str) -> bool:
    return status == "succeeded"


def _detect_oscillation(
    fingerprints: Sequence[str],
    outcomes: Sequence[str],
) -> bool:
    if len(fingerprints) < 6:
        return False

    window = list(fingerprints[-6:])
    statuses = list(outcomes[-6:])

    if any(
        _is_success_status(status)
        for status in statuses
    ):
        return False

    a = window[0]
    b = window[1]

    if a == b:
        return False

    expected_ab = [a, b, a, b, a, b]
    expected_ba = [b, a, b, a, b, a]

    return (
        window == expected_ab
        or window == expected_ba
    )


def _default_decision_caller(
    *,
    model_client: Any,
    model_name: str | None,
    system_prompt: str,
    user_prompt: str,
) -> str:
    runtime = (
        build_default_agent_execution_router(
            model_client
        )
    )
    preferred_provider = (
        resolve_provider_for_role(
            model_client,
            "fast_local",
            runtime.provider_registry,
        )
    )
    execution = runtime.execute_with_fallback(
        AgentRequest(
            model_role="fast_local",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            model_name=model_name,
        ),
        {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.RUN_TESTS,
        },
        preferred_provider=preferred_provider,
    )
    return str(
        execution.result.content or ""
    )


def run_agent_terminal_loop(
    *,
    project_path: str,
    task_id: str,
    prompt: str,
    model_route: Any,
    model_client: Any,
    policy: AgentTerminalPolicy | None = None,
    route_context: (
        AgentTerminalRouteContext | None
    ) = None,
    command_runner: CommandRunner | None = None,
    decision_caller: DecisionCaller | None = None,
    clock: Clock | None = None,
) -> AgentTerminalResult:
    """Run the bounded Agent Terminal Loop."""
    active_policy = (
        policy
        if policy is not None
        else build_execute_terminal_policy()
    )
    runner = command_runner or run_task_command
    now = clock or time.monotonic
    started_at = now()

    model_name = None

    if model_route is not None:
        model_name = getattr(
            model_route,
            "model",
            None,
        )

    def _decide(
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        if decision_caller is not None:
            return decision_caller(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_client=model_client,
                model_name=model_name,
                model_route=model_route,
            )

        return _default_decision_caller(
            model_client=model_client,
            model_name=(
                str(model_name)
                if model_name
                else None
            ),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    observations: list[TerminalObservation] = []
    fingerprints_seen: list[str] = []
    outcomes_seen: list[str] = []
    fingerprint_counts: dict[str, int] = {}
    deterministic_missing_path_fps: set[str] = (
        set()
    )
    deterministic_empty_discovery_fps: set[str] = (
        set()
    )

    steps_used = 0
    commands_executed = 0
    successful_commands = 0
    failed_commands = 0
    rejected_commands = 0
    consecutive_failures = 0
    consecutive_invalid = 0
    consecutive_provider_failures = 0
    last_observation: (
        TerminalObservation | None
    ) = None
    last_command_status: str | None = None

    system_prompt = (
        build_terminal_system_prompt()
    )
    available_secret_names = (
        list_task_secret_names(task_id)
    )

    def _result(
        status: str,
        *,
        reason: str,
        summary: str | None = None,
    ) -> AgentTerminalResult:
        return AgentTerminalResult(
            status=status,  # type: ignore[arg-type]
            summary=(
                summary
                if summary is not None
                else reason
            ),
            reason=reason,
            steps_used=steps_used,
            commands_executed=commands_executed,
            successful_commands=(
                successful_commands
            ),
            failed_commands=failed_commands,
            rejected_commands=rejected_commands,
            last_observation=last_observation,
        )

    def _wall_clock_exceeded() -> bool:
        return (
            now() - started_at
            >= active_policy.max_wall_clock_seconds
        )

    def _remaining_wall_clock_seconds() -> int:
        remaining = (
            active_policy.max_wall_clock_seconds
            - (now() - started_at)
        )
        return int(remaining)

    def _budget_exceeded_result() -> (
        AgentTerminalResult
    ):
        return _result(
            "budget_exceeded",
            reason="max_wall_clock_seconds",
        )

    while True:
        if _wall_clock_exceeded():
            return _budget_exceeded_result()

        if (
            steps_used
            >= active_policy.max_agent_steps
        ):
            return _result(
                "budget_exceeded",
                reason="max_agent_steps",
            )

        user_prompt = build_terminal_user_prompt(
            prompt=prompt,
            policy=active_policy,
            steps_used=steps_used,
            commands_executed=commands_executed,
            successful_commands=(
                successful_commands
            ),
            observations=observations,
            route_context=route_context,
            available_secret_names=(
                available_secret_names
            ),
        )

        try:
            raw_content = _decide(
                system_prompt,
                user_prompt,
            )
        except Exception as exc:
            consecutive_provider_failures += 1
            steps_used += 1

            feedback = (
                _sanitized_provider_failure_feedback(
                    exc
                )
            )
            observation = (
                controller_feedback_observation(
                    feedback
                )
            )
            observations.append(observation)
            last_observation = observation

            if (
                consecutive_provider_failures
                >= active_policy
                .max_provider_decision_failures
            ):
                return _result(
                    "failed",
                    reason=(
                        "max_provider_decision_failures"
                    ),
                    summary=(
                        _PROVIDER_FAILURE_SUMMARY
                    ),
                )

            continue

        consecutive_provider_failures = 0
        steps_used += 1

        # Controller wall-clock authority: discard
        # any action returned after the deadline.
        if _wall_clock_exceeded():
            return _budget_exceeded_result()

        try:
            action = parse_terminal_action(
                raw_content
            )
        except AgentTerminalParseError as exc:
            consecutive_invalid += 1
            feedback = (
                "Invalid action rejected: "
                f"{exc} "
                "Return exactly one raw JSON object "
                "with action_type run_command, "
                "complete, or fail. After successful "
                "remediation, retry the original "
                "user-requested operation if it is "
                "still unsatisfied."
            )
            observation = (
                controller_feedback_observation(
                    feedback
                )
            )
            observations.append(observation)
            last_observation = observation

            if (
                consecutive_invalid
                >= active_policy
                .max_consecutive_invalid_actions
            ):
                return _result(
                    "budget_exceeded",
                    reason=(
                        "max_consecutive_invalid_actions"
                    ),
                    summary=feedback,
                )

            continue

        if isinstance(action, FailAction):
            return _result(
                "failed",
                reason=action.reason,
                summary=action.reason,
            )

        if isinstance(action, CompleteAction):
            evidence_ok = True
            feedback_parts: list[str] = []

            if (
                active_policy
                .require_successful_command_before_complete
                and successful_commands < 1
            ):
                evidence_ok = False
                feedback_parts.append(
                    "Completion rejected: at least "
                    "one successful command is "
                    "required."
                )

            if (
                last_command_status is not None
                and _is_negative_status(
                    last_command_status
                )
            ):
                evidence_ok = False
                feedback_parts.append(
                    "Completion rejected: last "
                    "command status is "
                    f"{last_command_status}."
                )

            if evidence_ok:
                return _result(
                    "completed",
                    reason=action.reason,
                    summary=(
                        action.summary
                        or action.reason
                    ),
                )

            consecutive_invalid += 1
            feedback = " ".join(feedback_parts)
            observation = (
                controller_feedback_observation(
                    feedback
                )
            )
            observations.append(observation)
            last_observation = observation

            if (
                consecutive_invalid
                >= active_policy
                .max_consecutive_invalid_actions
            ):
                return _result(
                    "budget_exceeded",
                    reason=(
                        "max_consecutive_invalid_actions"
                    ),
                    summary=feedback,
                )

            continue

        if not isinstance(
            action,
            RunCommandAction,
        ):
            consecutive_invalid += 1
            feedback = (
                "Unsupported action type "
                "rejected by controller. "
                "Use run_command, complete, or fail. "
                "After successful remediation, retry "
                "the original user-requested "
                "operation if it is still unsatisfied."
            )
            observation = (
                controller_feedback_observation(
                    feedback
                )
            )
            observations.append(observation)
            last_observation = observation

            if (
                consecutive_invalid
                >= active_policy
                .max_consecutive_invalid_actions
            ):
                return _result(
                    "budget_exceeded",
                    reason=(
                        "max_consecutive_invalid_actions"
                    ),
                    summary=feedback,
                )

            continue

        fingerprint = command_fingerprint(
            action.argv,
            action.cwd,
        )
        prior_count = fingerprint_counts.get(
            fingerprint,
            0,
        )

        # Deterministic missing-path: identical
        # argv+cwd must not re-run. Feedback only;
        # not a subprocess execution.
        if fingerprint in (
            deterministic_missing_path_fps
        ):
            consecutive_invalid += 1
            observation = rejected_observation(
                argv=list(action.argv),
                cwd=action.cwd,
                rejection_reason=(
                    "identical_deterministic_"
                    "missing_path_retry_blocked"
                ),
                controller_feedback=(
                    _DETERMINISTIC_MISSING_PATH_FEEDBACK
                ),
            )
            observations.append(observation)
            last_observation = observation

            if (
                consecutive_invalid
                >= active_policy
                .max_consecutive_invalid_actions
            ):
                return _result(
                    "budget_exceeded",
                    reason=(
                        "max_consecutive_invalid_actions"
                    ),
                    summary=(
                        _DETERMINISTIC_MISSING_PATH_FEEDBACK
                    ),
                )

            continue

        # Successful-but-empty deterministic discovery
        # (e.g. git ls-files): identical retry is
        # useless and must not re-run the subprocess.
        if fingerprint in (
            deterministic_empty_discovery_fps
        ):
            consecutive_invalid += 1
            observation = rejected_observation(
                argv=list(action.argv),
                cwd=action.cwd,
                rejection_reason=(
                    "identical_empty_discovery_"
                    "retry_blocked"
                ),
                controller_feedback=(
                    _EMPTY_DISCOVERY_FEEDBACK
                ),
            )
            observations.append(observation)
            last_observation = observation

            if (
                consecutive_invalid
                >= active_policy
                .max_consecutive_invalid_actions
            ):
                return _result(
                    "budget_exceeded",
                    reason=(
                        "max_consecutive_invalid_actions"
                    ),
                    summary=_EMPTY_DISCOVERY_FEEDBACK,
                )

            continue

        # Valid executable attempt resets invalid streak.
        consecutive_invalid = 0

        # Consecutive identical argv+cwd attempts:
        # intervening different commands (e.g. install
        # or migrate) allow retrying the original
        # operation. Do not use lifetime totals here.
        trailing_identical = 0
        for prior_fp in reversed(fingerprints_seen):
            if prior_fp == fingerprint:
                trailing_identical += 1
            else:
                break

        if (
            trailing_identical
            >= active_policy
            .max_identical_command_executions
        ):
            return _result(
                "stalled",
                reason="stall_identical_command",
            )

        # Repeated failure: same fingerprint failed
        # twice consecutively → stop before third.
        if (
            len(fingerprints_seen) >= 2
            and fingerprints_seen[-1]
            == fingerprint
            and fingerprints_seen[-2]
            == fingerprint
            and _is_negative_status(
                outcomes_seen[-1]
            )
            and _is_negative_status(
                outcomes_seen[-2]
            )
        ):
            return _result(
                "stalled",
                reason="stall_repeated_failure",
            )

        if (
            commands_executed
            >= active_policy.max_command_executions
        ):
            return _result(
                "budget_exceeded",
                reason="max_command_executions",
            )

        remaining_seconds = (
            _remaining_wall_clock_seconds()
        )

        if (
            remaining_seconds
            < MIN_TIMEOUT_SECONDS
        ):
            return _budget_exceeded_result()

        effective_command_timeout = min(
            active_policy.command_timeout_seconds,
            remaining_seconds,
        )

        try:
            approved_secret_env = (
                resolve_task_command_secret_env(
                    task_id,
                    list(action.argv),
                    action.cwd,
                    required_secret_names=(
                        available_secret_names
                    ),
                )
            )
        except TaskSecretUnavailableError as exc:
            rejected_commands += 1
            consecutive_failures += 1
            observation = rejected_observation(
                argv=list(action.argv),
                cwd=action.cwd,
                rejection_reason=str(exc),
            )
            observations.append(observation)
            last_observation = observation
            last_command_status = "rejected"
            fingerprints_seen.append(fingerprint)
            outcomes_seen.append("rejected")
            fingerprint_counts[fingerprint] = (
                prior_count + 1
            )

            if _detect_oscillation(
                fingerprints_seen,
                outcomes_seen,
            ):
                return _result(
                    "stalled",
                    reason="stall_oscillation",
                )

            if (
                consecutive_failures
                >= active_policy
                .max_consecutive_command_failures
            ):
                return _result(
                    "stalled",
                    reason=(
                        "max_consecutive_command_failures"
                    ),
                )

            continue

        request = TaskCommandRequest(
            task_id=task_id,
            argv=list(action.argv),
            cwd=action.cwd,
            timeout_seconds=(
                effective_command_timeout
            ),
            env=dict(approved_secret_env),
            secret_env_keys=list(
                approved_secret_env.keys()
            ),
            allow_mutating=(
                active_policy.allow_mutating
            ),
            allow_git_mutation=(
                active_policy.allow_git_mutation
            ),
        )

        try:
            command_result = runner(
                project_path=project_path,
                request=request,
                persist=True,
            )
        except (
            TaskCommandPolicyError,
            TaskCommandValidationError,
            TaskCommandPathError,
        ) as exc:
            rejected_commands += 1
            consecutive_failures += 1
            observation = rejected_observation(
                argv=list(action.argv),
                cwd=action.cwd,
                rejection_reason=str(exc),
            )
            observations.append(observation)
            last_observation = observation
            last_command_status = "rejected"
            fingerprints_seen.append(fingerprint)
            outcomes_seen.append("rejected")
            fingerprint_counts[fingerprint] = (
                prior_count + 1
            )

            if _detect_oscillation(
                fingerprints_seen,
                outcomes_seen,
            ):
                return _result(
                    "stalled",
                    reason="stall_oscillation",
                )

            if (
                consecutive_failures
                >= active_policy
                .max_consecutive_command_failures
            ):
                return _result(
                    "stalled",
                    reason=(
                        "max_consecutive_command_failures"
                    ),
                )

            continue

        except TaskCommandSandboxRuntimeError as exc:
            return _result(
                "failed",
                reason=(
                    "infrastructure_failure: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        status = str(
            getattr(
                command_result,
                "status",
                "",
            )
            or ""
        )

        # Runner-owned REJECTED (persisted, no process):
        # replan with observation; do not count as executed.
        if status == "rejected":
            rejected_commands += 1
            consecutive_failures += 1
            rejection_reason = str(
                getattr(
                    command_result,
                    "stderr",
                    "",
                )
                or "Command rejected by policy."
            )
            observation = (
                observation_from_task_command_result(
                    command_result,
                    rejection_reason=rejection_reason,
                )
            )
            observations.append(observation)
            last_observation = observation
            last_command_status = "rejected"
            fingerprints_seen.append(fingerprint)
            outcomes_seen.append("rejected")
            fingerprint_counts[fingerprint] = (
                prior_count + 1
            )

            if _detect_oscillation(
                fingerprints_seen,
                outcomes_seen,
            ):
                return _result(
                    "stalled",
                    reason="stall_oscillation",
                )

            if (
                consecutive_failures
                >= active_policy
                .max_consecutive_command_failures
            ):
                return _result(
                    "stalled",
                    reason=(
                        "max_consecutive_command_failures"
                    ),
                )

            continue

        commands_executed += 1
        observation = (
            observation_from_task_command_result(
                command_result
            )
        )
        observations.append(observation)
        last_observation = observation
        last_command_status = status
        fingerprints_seen.append(fingerprint)
        outcomes_seen.append(status)
        fingerprint_counts[fingerprint] = (
            prior_count + 1
        )

        if _is_success_status(status):
            successful_commands += 1
            consecutive_failures = 0

            if (
                is_deterministic_git_ls_files_discovery(
                    action.argv
                )
                and is_successful_empty_discovery_result(
                    status=status,
                    exit_code=getattr(
                        command_result,
                        "exit_code",
                        None,
                    ),
                    stdout=str(
                        getattr(
                            command_result,
                            "stdout",
                            "",
                        )
                        or ""
                    ),
                )
            ):
                deterministic_empty_discovery_fps.add(
                    fingerprint
                )
        elif _is_negative_status(status):
            if status == "rejected":
                rejected_commands += 1
            else:
                failed_commands += 1

            consecutive_failures += 1

            if is_deterministic_missing_path_failure(
                status=status,
                exit_code=getattr(
                    command_result,
                    "exit_code",
                    None,
                ),
                stderr=str(
                    getattr(
                        command_result,
                        "stderr",
                        "",
                    )
                    or ""
                ),
            ):
                deterministic_missing_path_fps.add(
                    fingerprint
                )
        else:
            failed_commands += 1
            consecutive_failures += 1

        if _detect_oscillation(
            fingerprints_seen,
            outcomes_seen,
        ):
            return _result(
                "stalled",
                reason="stall_oscillation",
            )

        if (
            consecutive_failures
            >= active_policy
            .max_consecutive_command_failures
        ):
            return _result(
                "stalled",
                reason=(
                    "max_consecutive_command_failures"
                ),
            )
