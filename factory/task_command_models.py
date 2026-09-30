"""Production task command contracts for guarded execution.

Independent of experimental general_agent_* stack.
Not yet wired into TaskExecutionService.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class PermissionLevel(str, Enum):
    EXECUTE_SAFE = "EXECUTE_SAFE"
    EXECUTE_MUTATING = "EXECUTE_MUTATING"
    DANGEROUS = "DANGEROUS"


class ExecutionBoundary(str, Enum):
    HOST_SAFE = "HOST_SAFE"
    PROJECT_CODE_SANDBOX = "PROJECT_CODE_SANDBOX"


class NetworkPolicy(str, Enum):
    NETWORK_NONE = "NETWORK_NONE"
    NETWORK_PACKAGE_INSTALL = "NETWORK_PACKAGE_INSTALL"


class CommandStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


DEFAULT_TIMEOUT_SECONDS = 120
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 300
MAX_CAPTURE_CHARS = 100_000
MAX_ARG_COUNT = 64
MAX_ARG_LENGTH = 2000
REDACTION_MASK = "******"

# Case-insensitive substrings for request.env secret detection.
SENSITIVE_ENV_KEY_MARKERS = (
    "PASSWORD",
    "PASSWD",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "APIKEY",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "AUTH",
)


@dataclass(frozen=True)
class TaskCommandRequest:
    task_id: str
    argv: list[str]
    cwd: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    env: dict[str, str] | None = None
    secret_env_keys: list[str] = field(
        default_factory=list
    )
    # Explicit backend gate for EXECUTE_MUTATING.
    # DANGEROUS is never allowed, even when True.
    allow_mutating: bool = False


@dataclass(frozen=True)
class TaskCommandResult:
    command_id: str
    task_id: str
    argv: list[str]
    cwd: str
    permission_level: str
    started_at: str
    finished_at: str
    duration_ms: int
    exit_code: int | None
    stdout: str
    stderr: str
    status: str
    secret_env_keys: list[str] = field(
        default_factory=list
    )
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    execution_boundary: str = ""
    network_policy: str = (
        NetworkPolicy.NETWORK_NONE.value
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskCommandError(RuntimeError):
    """Base error for guarded task commands."""


class TaskCommandPolicyError(TaskCommandError):
    """Command rejected by permission / policy checks."""


class TaskCommandPathError(TaskCommandError):
    """CWD or path jail violation."""


class TaskCommandValidationError(TaskCommandError):
    """Invalid request shape (argv, timeout, env)."""


class TaskCommandSandboxRuntimeError(TaskCommandError):
    """Sandbox runtime unavailable or unsupported."""


def normalize_secret_env_keys(
    keys: list[str] | set[str] | tuple[str, ...] | None,
) -> list[str]:
    if not keys:
        return []

    seen: set[str] = set()
    ordered: list[str] = []

    for raw in keys:
        key = str(raw or "").strip()

        if not key or key in seen:
            continue

        seen.add(key)
        ordered.append(key)

    return ordered


def is_sensitive_env_key(key: str) -> bool:
    folded = str(key or "").casefold()

    if not folded:
        return False

    return any(
        marker.casefold() in folded
        for marker in SENSITIVE_ENV_KEY_MARKERS
    )


def detect_sensitive_env_keys(
    env: dict[str, str] | None,
) -> list[str]:
    if not env:
        return []

    return normalize_secret_env_keys(
        [
            key
            for key in env
            if is_sensitive_env_key(key)
        ]
    )


def resolve_secret_env_keys(
    env: dict[str, str] | None,
    explicit_keys: list[str] | set[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Merge explicit secret keys with auto-detected sensitive names."""
    return normalize_secret_env_keys(
        [
            *(explicit_keys or []),
            *detect_sensitive_env_keys(env),
        ]
    )


def collect_secret_values(
    env: dict[str, str] | None,
    secret_env_keys: list[str] | set[str] | tuple[str, ...] | None,
) -> list[str]:
    keys = normalize_secret_env_keys(
        secret_env_keys
    )

    if not env or not keys:
        return []

    values: list[str] = []
    seen: set[str] = set()

    # Case-insensitive lookup for Windows-style env maps.
    folded_map = {
        key.casefold(): value
        for key, value in env.items()
    }

    for key in keys:
        value = env.get(key)

        if value is None:
            value = folded_map.get(
                key.casefold()
            )

        if value is None:
            continue

        text = str(value)

        if not text or text in seen:
            continue

        seen.add(text)
        values.append(text)

    return values


def redact_text(
    text: str,
    secret_values: list[str] | None,
) -> str:
    if not text or not secret_values:
        return text or ""

    redacted = text

    # Longer secrets first to avoid partial overlap issues.
    for secret in sorted(
        secret_values,
        key=len,
        reverse=True,
    ):
        if secret:
            redacted = redacted.replace(
                secret,
                REDACTION_MASK,
            )

    return redacted


def truncate_capture(
    text: str,
    *,
    limit: int | None = None,
) -> tuple[str, bool]:
    value = text or ""
    max_chars = (
        MAX_CAPTURE_CHARS
        if limit is None
        else limit
    )

    if len(value) <= max_chars:
        return value, False

    return value[:max_chars], True
