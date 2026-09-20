import subprocess
import time
from dataclasses import replace
from typing import Any

from factory.agents.provider_adapter import (
    ProviderDescriptor,
    ProviderTransport,
)
from factory.agents.provider_health import (
    ProviderHealth,
    ProviderHealthStatus,
    probe_provider_descriptor,
    resolve_cli_executable,
)


DEFAULT_PROBE_TIMEOUT_SECONDS = 5.0


def _first_non_empty_line(
    *values: str | None,
) -> str | None:
    for value in values:
        for line in str(
            value or ""
        ).splitlines():
            normalized = line.strip()

            if normalized:
                return normalized

    return None


def _version_command(
    executable: str,
    descriptor: ProviderDescriptor,
) -> list[str]:
    metadata_command = (
        descriptor.metadata.get(
            "health_probe_command"
        )
    )

    if isinstance(
        metadata_command,
        (list, tuple),
    ):
        arguments = [
            str(item)
            for item
            in metadata_command
            if str(item).strip()
        ]

        if arguments:
            return [
                executable,
                *arguments,
            ]

    return [
        executable,
        "--version",
    ]


def probe_runtime_provider(
    descriptor: ProviderDescriptor,
    *,
    timeout_seconds: float = (
        DEFAULT_PROBE_TIMEOUT_SECONDS
    ),
) -> ProviderHealth:
    started_at = time.perf_counter()

    passive = probe_provider_descriptor(
        descriptor
    )

    if (
        descriptor.transport
        != ProviderTransport.CLI
    ):
        latency_ms = (
            time.perf_counter()
            - started_at
        ) * 1000.0

        return replace(
            passive,
            latency_ms=latency_ms,
        )

    resolved = resolve_cli_executable(
        descriptor
    )

    if not resolved:
        latency_ms = (
            time.perf_counter()
            - started_at
        ) * 1000.0

        return replace(
            passive,
            status=(
                ProviderHealthStatus
                .UNAVAILABLE
            ),
            reason=(
                "CLI executable could not "
                "be resolved for runtime probe."
            ),
            checked_via="runtime_cli",
            resolved_executable=None,
            latency_ms=latency_ms,
            error_code=(
                "EXECUTABLE_NOT_FOUND"
            ),
        )

    command = _version_command(
        resolved,
        descriptor,
    )

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

    except subprocess.TimeoutExpired:
        latency_ms = (
            time.perf_counter()
            - started_at
        ) * 1000.0

        return ProviderHealth(
            provider_name=descriptor.name,
            status=(
                ProviderHealthStatus
                .UNAVAILABLE
            ),
            transport=(
                descriptor.transport
            ),
            reason=(
                "Provider runtime probe "
                "timed out."
            ),
            checked_via=(
                "runtime_cli"
            ),
            executable=(
                descriptor.executable
            ),
            resolved_executable=(
                resolved
            ),
            features=passive.features,
            metadata=dict(
                descriptor.metadata
            ),
            authenticated=None,
            latency_ms=latency_ms,
            error_code="PROBE_TIMEOUT",
        )

    except (
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        latency_ms = (
            time.perf_counter()
            - started_at
        ) * 1000.0

        return ProviderHealth(
            provider_name=descriptor.name,
            status=(
                ProviderHealthStatus
                .UNAVAILABLE
            ),
            transport=(
                descriptor.transport
            ),
            reason=(
                "Provider runtime probe "
                f"failed: {exc}"
            ),
            checked_via=(
                "runtime_cli"
            ),
            executable=(
                descriptor.executable
            ),
            resolved_executable=(
                resolved
            ),
            features=passive.features,
            metadata=dict(
                descriptor.metadata
            ),
            authenticated=None,
            latency_ms=latency_ms,
            error_code="PROBE_ERROR",
        )

    latency_ms = (
        time.perf_counter()
        - started_at
    ) * 1000.0

    version = _first_non_empty_line(
        completed.stdout,
        completed.stderr,
    )

    if completed.returncode != 0:
        return ProviderHealth(
            provider_name=descriptor.name,
            status=(
                ProviderHealthStatus
                .UNAVAILABLE
            ),
            transport=(
                descriptor.transport
            ),
            reason=(
                "Provider runtime probe "
                "returned a non-zero exit "
                f"code: {completed.returncode}"
            ),
            checked_via=(
                "runtime_cli"
            ),
            executable=(
                descriptor.executable
            ),
            resolved_executable=(
                resolved
            ),
            features=passive.features,
            metadata=dict(
                descriptor.metadata
            ),
            authenticated=None,
            version=version,
            latency_ms=latency_ms,
            error_code=(
                "PROBE_NON_ZERO_EXIT"
            ),
        )

    return ProviderHealth(
        provider_name=descriptor.name,
        status=(
            ProviderHealthStatus
            .AVAILABLE
        ),
        transport=descriptor.transport,
        reason=(
            "Provider runtime probe "
            "succeeded."
        ),
        checked_via="runtime_cli",
        executable=(
            descriptor.executable
        ),
        resolved_executable=resolved,
        features=passive.features,
        metadata=dict(
            descriptor.metadata
        ),
        authenticated=None,
        version=version,
        latency_ms=latency_ms,
        error_code=None,
    )


def build_runtime_discovery(
    descriptor: ProviderDescriptor,
    health: ProviderHealth,
) -> dict[str, Any]:
    return {
        "name": descriptor.name,
        "transport": (
            descriptor.transport.value
        ),
        "adapter_version": (
            descriptor.adapter_version
        ),
        "features": list(
            health.features
        ),
        "executable": (
            descriptor.executable
        ),
        "metadata": dict(
            descriptor.metadata
        ),
        "health": health.as_dict(),
    }


def discover_runtime_provider(
    descriptor: ProviderDescriptor,
    *,
    timeout_seconds: float = (
        DEFAULT_PROBE_TIMEOUT_SECONDS
    ),
) -> dict[str, Any]:
    health = probe_runtime_provider(
        descriptor,
        timeout_seconds=(
            timeout_seconds
        ),
    )

    return build_runtime_discovery(
        descriptor,
        health,
    )
