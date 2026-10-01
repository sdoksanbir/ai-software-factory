"""Fail-closed Agent Terminal action parser.

Accepts raw JSON objects only. No markdown fences,
prose extraction, or shell heuristics.
"""

from __future__ import annotations

import json
from typing import Any

from factory.agent_terminal_models import (
    CompleteAction,
    FailAction,
    RunCommandAction,
    TerminalAction,
)
from factory.task_command_models import (
    MAX_ARG_COUNT,
    MAX_ARG_LENGTH,
)


class AgentTerminalParseError(ValueError):
    """Model output rejected by fail-closed parser."""


MAX_REASON_CHARS = 1000
MAX_SUMMARY_CHARS = 8000
MAX_CWD_CHARS = 1000

_FORBIDDEN_ACTION_FIELDS = frozenset(
    {
        "allow_mutating",
        "allow_git_mutation",
        "permission_level",
        "execution_boundary",
        "network_policy",
        "timeout_seconds",
        "timeout",
        "shell",
        "command",
        "env",
        "secret_env_keys",
        "docker",
        "docker_args",
        "dependency_volume",
        "persist",
        "host",
        "execution_boundary_override",
    }
)

_RUN_COMMAND_FIELDS = frozenset(
    {
        "action_type",
        "argv",
        "cwd",
        "reason",
    }
)
_COMPLETE_FIELDS = frozenset(
    {
        "action_type",
        "reason",
        "summary",
    }
)
_FAIL_FIELDS = frozenset(
    {
        "action_type",
        "reason",
    }
)


def _reject(message: str) -> None:
    raise AgentTerminalParseError(message)


def _require_raw_json_object(
    raw: str,
) -> dict[str, Any]:
    text = str(raw or "")

    if not text.strip():
        _reject("Model output empty.")

    # Fail closed: any fencing / prose wrapper.
    if "```" in text:
        _reject(
            "Markdown fenced JSON rejected."
        )

    stripped = text.strip()

    if not (
        stripped.startswith("{")
        and stripped.endswith("}")
    ):
        _reject(
            "Model output must be a raw JSON object."
        )

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        _reject(
            f"Malformed JSON: {exc.msg}."
        )

    if not isinstance(parsed, dict):
        _reject(
            "Model output must be a JSON object."
        )

    return parsed


def _check_forbidden_fields(
    payload: dict[str, Any],
) -> None:
    present = sorted(
        key
        for key in payload
        if key in _FORBIDDEN_ACTION_FIELDS
    )

    if present:
        _reject(
            "Forbidden action field(s): "
            + ", ".join(present)
        )


def _require_reason(
    value: Any,
) -> str:
    if not isinstance(value, str):
        _reject("reason must be a string.")

    reason = value.strip()

    if not reason:
        _reject("reason must be non-empty.")

    if len(reason) > MAX_REASON_CHARS:
        _reject(
            f"reason exceeds {MAX_REASON_CHARS} chars."
        )

    return reason


def _optional_summary(
    value: Any,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        _reject("summary must be a string or null.")

    summary = value.strip()

    if not summary:
        return None

    if len(summary) > MAX_SUMMARY_CHARS:
        _reject(
            f"summary exceeds {MAX_SUMMARY_CHARS} chars."
        )

    return summary


def _optional_cwd(
    value: Any,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        _reject("cwd must be a string or null.")

    cwd = value.strip()

    if not cwd:
        return None

    if len(cwd) > MAX_CWD_CHARS:
        _reject(
            f"cwd exceeds {MAX_CWD_CHARS} chars."
        )

    # Absolute / escape attempts are still finally
    # jails by TaskCommandRunner; reject obvious
    # absolute Windows/Unix forms early.
    if (
        cwd.startswith("/")
        or cwd.startswith("\\")
        or (len(cwd) >= 2 and cwd[1] == ":")
    ):
        _reject(
            "cwd must be a relative project path."
        )

    if ".." in cwd.replace("\\", "/").split("/"):
        _reject(
            "cwd must not contain parent segments."
        )

    return cwd


def _require_argv(
    value: Any,
) -> tuple[str, ...]:
    if isinstance(value, str):
        _reject("argv must be a list, not a string.")

    if not isinstance(value, list):
        _reject("argv must be a list of strings.")

    if not value:
        _reject("argv must be non-empty.")

    if len(value) > MAX_ARG_COUNT:
        _reject(
            f"argv exceeds {MAX_ARG_COUNT} entries."
        )

    argv: list[str] = []

    for index, entry in enumerate(value):
        if not isinstance(entry, str):
            _reject(
                "argv entries must be strings "
                f"(index {index})."
            )

        if not entry:
            _reject(
                "argv entries must be non-empty "
                f"(index {index})."
            )

        if len(entry) > MAX_ARG_LENGTH:
            _reject(
                "argv entry exceeds "
                f"{MAX_ARG_LENGTH} chars "
                f"(index {index})."
            )

        argv.append(entry)

    return tuple(argv)


def _reject_extra_fields(
    payload: dict[str, Any],
    allowed: frozenset[str],
) -> None:
    extra = sorted(
        key
        for key in payload
        if key not in allowed
    )

    if extra:
        _reject(
            "Unknown action field(s): "
            + ", ".join(extra)
        )


def parse_terminal_action(
    raw: str,
) -> TerminalAction:
    """Parse one model decision into a typed action.

    Raises AgentTerminalParseError on any defect.
    Does not execute anything.
    """
    payload = _require_raw_json_object(raw)
    _check_forbidden_fields(payload)

    action_type = payload.get("action_type")

    if not isinstance(action_type, str):
        _reject(
            "action_type is required and must be a string."
        )

    if action_type == "run_command":
        _reject_extra_fields(
            payload,
            _RUN_COMMAND_FIELDS,
        )

        if "argv" not in payload:
            _reject("argv is required.")

        if "reason" not in payload:
            _reject("reason is required.")

        return RunCommandAction(
            argv=_require_argv(
                payload["argv"]
            ),
            cwd=_optional_cwd(
                payload.get("cwd")
            ),
            reason=_require_reason(
                payload["reason"]
            ),
        )

    if action_type == "complete":
        _reject_extra_fields(
            payload,
            _COMPLETE_FIELDS,
        )

        if "reason" not in payload:
            _reject("reason is required.")

        return CompleteAction(
            reason=_require_reason(
                payload["reason"]
            ),
            summary=_optional_summary(
                payload.get("summary")
            ),
        )

    if action_type == "fail":
        _reject_extra_fields(
            payload,
            _FAIL_FIELDS,
        )

        if "reason" not in payload:
            _reject("reason is required.")

        return FailAction(
            reason=_require_reason(
                payload["reason"]
            ),
        )

    _reject(
        f"Unknown action_type: {action_type!r}."
    )
    raise AssertionError("unreachable")
