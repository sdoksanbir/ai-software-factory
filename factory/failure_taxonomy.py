"""Lightweight failure reason codes for production steps.

Not an exception hierarchy. Callers keep raising ordinary
exceptions; classify_failure maps them to stable string codes
so reason metadata is not lost across retry/handoff layers.
"""

from __future__ import annotations

from typing import Any

from factory.agents.provider_errors import (
    AgentModelUnavailableError,
    AgentProviderRateLimitError,
    AgentProviderTimeoutError,
    AgentProviderUnavailableError,
)
from factory.review_quality import (
    ReviewVerdictParseError,
)


PROVIDER_UNAVAILABLE = "provider_unavailable"
TIMEOUT = "timeout"
INVALID_RESPONSE = "invalid_response"
EXECUTION_FAILED = "execution_failed"
PATCH_FAILED = "patch_failed"
REVIEW_FAILED = "review_failed"
TEST_FAILED = "test_failed"
MERGE_CONFLICT = "merge_conflict"

FAILURE_REASONS = frozenset(
    {
        PROVIDER_UNAVAILABLE,
        TIMEOUT,
        INVALID_RESPONSE,
        EXECUTION_FAILED,
        PATCH_FAILED,
        REVIEW_FAILED,
        TEST_FAILED,
        MERGE_CONFLICT,
    }
)


def format_failure_message(
    reason: str,
    message: str,
) -> str:
    """Prefix a human message with a stable failure code."""
    code = str(reason or "").strip()
    text = str(message or "").strip()

    if code not in FAILURE_REASONS:
        code = EXECUTION_FAILED

    if not text:
        return code

    if text.startswith(f"{code}:"):
        return text

    return f"{code}: {text}"


def extract_failure_reason(
    message: str | None,
) -> str | None:
    """Parse a leading failure code from a stored error string."""
    text = str(message or "").strip()

    if not text:
        return None

    for code in FAILURE_REASONS:
        prefix = f"{code}:"
        if text.startswith(prefix) or text == code:
            return code

    return None


def classify_failure(
    exc: BaseException | str,
    *,
    step_kind: str | None = None,
    context: str | None = None,
) -> str:
    """Map an exception/message to a stable failure reason code."""
    kind = str(step_kind or "").strip().casefold()
    ctx = str(context or "").strip().casefold()

    if isinstance(exc, BaseException):
        if isinstance(
            exc,
            ReviewVerdictParseError,
        ):
            return INVALID_RESPONSE

        if isinstance(
            exc,
            (
                AgentProviderUnavailableError,
                AgentModelUnavailableError,
                AgentProviderRateLimitError,
            ),
        ):
            return PROVIDER_UNAVAILABLE

        if isinstance(
            exc,
            (
                AgentProviderTimeoutError,
                TimeoutError,
            ),
        ):
            return TIMEOUT

        message = str(exc)
        exc_name = type(exc).__name__
    else:
        message = str(exc)
        exc_name = ""

    blob = " ".join(
        part
        for part in (
            message,
            exc_name,
            kind,
            ctx,
        )
        if part
    ).casefold()

    if (
        "quality gate" in blob
        or "review_verdict" in blob
        or "review blocked" in blob
        or ctx == "review"
    ):
        return REVIEW_FAILED

    if (
        "merge conflict" in blob
        or "merge_conflict" in blob
    ):
        return MERGE_CONFLICT

    if (
        "patch" in blob
        or "apply_patch" in blob
        or "unified diff" in blob
    ):
        return PATCH_FAILED

    if (
        kind == "verify"
        or "test failed" in blob
        or "pytest" in blob
        or ctx == "verify"
    ):
        return TEST_FAILED

    if (
        "timeout" in blob
        or "timed out" in blob
    ):
        return TIMEOUT

    if (
        "unavailable" in blob
        or "connection" in blob
        or "rate limit" in blob
    ):
        return PROVIDER_UNAVAILABLE

    if (
        "invalid json" in blob
        or "json decode" in blob
        or "invalid response" in blob
        or "parse" in blob
        and "review" in blob
    ):
        return INVALID_RESPONSE

    return EXECUTION_FAILED


def failure_metadata(
    exc: BaseException | str,
    *,
    step_kind: str | None = None,
    context: str | None = None,
    attempt: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a small metadata dict that preserves failure reason."""
    reason = classify_failure(
        exc,
        step_kind=step_kind,
        context=context,
    )

    message = (
        str(exc)
        if not isinstance(exc, str)
        else exc
    )

    payload: dict[str, Any] = {
        "failure_reason": reason,
        "failure_message": message,
    }

    if attempt is not None:
        payload["attempt"] = attempt

    if step_kind is not None:
        payload["step_kind"] = step_kind

    if extra:
        payload.update(extra)

    return payload
