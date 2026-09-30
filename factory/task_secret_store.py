"""Controller-owned ephemeral task secret store.

Process-memory only. Server restart loses all task
secrets — acceptable for V1. Never persist values to
SQLite, files, or logs.
"""

from __future__ import annotations

import re
import threading
from typing import Mapping

# Strict secret name: lowercase identifier.
SECRET_NAME_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]{0,63}$"
)
MAX_SECRETS_PER_TASK = 8
MAX_SECRET_VALUE_LENGTH = 2048

USER_PASSWORD_SECRET_NAME = "user_password"


class TaskSecretStoreError(ValueError):
    """Invalid secret registration request."""


class _TaskSecretStore:
    """Thread-safe in-memory map: task_id → name → value."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._secrets: dict[
            str, dict[str, str]
        ] = {}

    def set_task_secrets(
        self,
        task_id: str,
        secrets: Mapping[str, str],
    ) -> None:
        tid = str(task_id or "").strip()

        if not tid:
            raise TaskSecretStoreError(
                "task_id is required."
            )

        normalized = _normalize_secrets(secrets)

        with self._lock:
            if not normalized:
                self._secrets.pop(tid, None)
                return

            self._secrets[tid] = dict(normalized)

    def has_task_secret(
        self,
        task_id: str,
        name: str,
    ) -> bool:
        tid = str(task_id or "").strip()
        key = str(name or "").strip()

        with self._lock:
            bucket = self._secrets.get(tid)

            if not bucket:
                return False

            return key in bucket

    def get_task_secret(
        self,
        task_id: str,
        name: str,
    ) -> str | None:
        tid = str(task_id or "").strip()
        key = str(name or "").strip()

        with self._lock:
            bucket = self._secrets.get(tid)

            if not bucket:
                return None

            return bucket.get(key)

    def list_task_secret_names(
        self,
        task_id: str,
    ) -> list[str]:
        tid = str(task_id or "").strip()

        with self._lock:
            bucket = self._secrets.get(tid)

            if not bucket:
                return []

            return sorted(bucket.keys())

    def clear_task_secrets(
        self,
        task_id: str,
    ) -> None:
        tid = str(task_id or "").strip()

        with self._lock:
            self._secrets.pop(tid, None)

    def reset_for_tests(self) -> None:
        """Clear entire store. Tests / restart simulation."""
        with self._lock:
            self._secrets.clear()

    def __repr__(self) -> str:
        with self._lock:
            task_count = len(self._secrets)
            name_counts = {
                tid: sorted(bucket.keys())
                for tid, bucket in self._secrets.items()
            }

        return (
            f"<TaskSecretStore tasks={task_count} "
            f"names={name_counts}>"
        )


def _normalize_secrets(
    secrets: Mapping[str, str] | None,
) -> dict[str, str]:
    if not secrets:
        return {}

    if len(secrets) > MAX_SECRETS_PER_TASK:
        raise TaskSecretStoreError(
            "Too many secrets for one task "
            f"(max {MAX_SECRETS_PER_TASK})."
        )

    normalized: dict[str, str] = {}

    for raw_name, raw_value in secrets.items():
        name = str(raw_name or "").strip()
        value = str(raw_value or "")

        if not name:
            raise TaskSecretStoreError(
                "Secret name must be non-empty."
            )

        if not SECRET_NAME_PATTERN.fullmatch(name):
            raise TaskSecretStoreError(
                "Secret name must match "
                f"{SECRET_NAME_PATTERN.pattern}."
            )

        if name in normalized:
            raise TaskSecretStoreError(
                f"Duplicate secret name: {name}."
            )

        if not value:
            raise TaskSecretStoreError(
                "Secret value must be non-empty."
            )

        if len(value) > MAX_SECRET_VALUE_LENGTH:
            raise TaskSecretStoreError(
                "Secret value exceeds "
                f"{MAX_SECRET_VALUE_LENGTH} chars."
            )

        normalized[name] = value

    return normalized


def validate_secret_items(
    items: list[Mapping[str, str]] | None,
) -> dict[str, str]:
    """Validate API-shaped secret list → name map."""
    if not items:
        return {}

    as_map: dict[str, str] = {}

    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise TaskSecretStoreError(
                f"Secret entry {index} must be an object."
            )

        name = str(item.get("name", "")).strip()
        value = str(item.get("value", ""))

        if name in as_map:
            raise TaskSecretStoreError(
                f"Duplicate secret name: {name}."
            )

        as_map[name] = value

    return _normalize_secrets(as_map)


def scrub_prompt_with_secrets(
    prompt: str,
    secrets: Mapping[str, str] | None,
) -> str:
    """Replace exact known secret values with placeholders.

    Only scrub values that arrived via structured secrets.
    Longer values first to avoid partial overlaps.
    """
    text = str(prompt or "")

    if not secrets or not text:
        return text

    scrubbed = text

    for name, value in sorted(
        secrets.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        if not value:
            continue

        placeholder = f"[SECRET:{name}]"
        scrubbed = scrubbed.replace(
            value,
            placeholder,
        )

    return scrubbed


# Process-global store. Restart → empty.
_STORE = _TaskSecretStore()


def set_task_secrets(
    task_id: str,
    secrets: Mapping[str, str],
) -> None:
    _STORE.set_task_secrets(task_id, secrets)


def has_task_secret(
    task_id: str,
    name: str,
) -> bool:
    return _STORE.has_task_secret(task_id, name)


def get_task_secret(
    task_id: str,
    name: str,
) -> str | None:
    return _STORE.get_task_secret(task_id, name)


def list_task_secret_names(
    task_id: str,
) -> list[str]:
    return _STORE.list_task_secret_names(task_id)


def clear_task_secrets(task_id: str) -> None:
    _STORE.clear_task_secrets(task_id)


def reset_task_secret_store_for_tests() -> None:
    """Simulate process restart for tests."""
    _STORE.reset_for_tests()
