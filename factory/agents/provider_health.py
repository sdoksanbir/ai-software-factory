import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from factory.agents.provider_adapter import (
    ProviderDescriptor,
    ProviderTransport,
)


class ProviderHealthStatus(
    str,
    Enum,
):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderHealth:
    provider_name: str
    status: ProviderHealthStatus
    transport: ProviderTransport
    reason: str
    checked_via: str
    executable: str | None = None
    resolved_executable: str | None = None
    features: tuple[str, ...] = ()
    metadata: Mapping[
        str,
        Any,
    ] = field(
        default_factory=dict
    )

    authenticated: bool | None = None
    version: str | None = None
    latency_ms: float | None = None
    error_code: str | None = None

    @property
    def available(
        self,
    ) -> bool:
        return (
            self.status
            == ProviderHealthStatus.AVAILABLE
        )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "provider_name": (
                self.provider_name
            ),
            "status": self.status.value,
            "available": self.available,
            "transport": (
                self.transport.value
            ),
            "reason": self.reason,
            "checked_via": (
                self.checked_via
            ),
            "executable": (
                self.executable
            ),
            "resolved_executable": (
                self.resolved_executable
            ),
            "features": list(
                self.features
            ),
            "metadata": dict(
                self.metadata
            ),
            "authenticated": (
                self.authenticated
            ),
            "version": self.version,
            "latency_ms": (
                self.latency_ms
            ),
            "error_code": (
                self.error_code
            ),
        }


def _known_cli_install_candidates(
    descriptor: ProviderDescriptor,
) -> tuple[Path, ...]:
    local_app_data = (
        os.environ.get(
            "LOCALAPPDATA"
        )
    )

    if not local_app_data:
        return ()

    root = Path(
        local_app_data
    )

    cli_family = str(
        descriptor.metadata.get(
            "cli_family",
            "",
        )
        or ""
    ).strip().lower()

    if (
        descriptor.name
        == "antigravity_cli"
        or cli_family
        == "google_antigravity"
    ):
        return (
            root
            / "agy"
            / "bin"
            / "agy.exe",
        )

    if (
        descriptor.name
        == "codex_cli"
        or cli_family
        == "openai_codex"
    ):
        return (
            root
            / "Programs"
            / "OpenAI"
            / "Codex"
            / "bin"
            / "codex.exe",
        )

    return ()


def resolve_cli_executable(
    descriptor: ProviderDescriptor,
) -> str | None:
    executable = str(
        descriptor.executable
        or ""
    ).strip()

    if not executable:
        return None

    explicit_path = Path(
        executable
    )

    if (
        explicit_path.is_absolute()
        or explicit_path.parent
        != Path(".")
    ):
        if explicit_path.is_file():
            return str(
                explicit_path
            )

    resolved = shutil.which(
        executable
    )

    if resolved:
        return resolved

    for candidate in (
        _known_cli_install_candidates(
            descriptor
        )
    ):
        if candidate.is_file():
            return str(
                candidate
            )

    return None


def probe_provider_descriptor(
    descriptor: ProviderDescriptor,
) -> ProviderHealth:
    features = tuple(
        sorted(
            feature.value
            for feature
            in descriptor.features
        )
    )

    common = {
        "provider_name": (
            descriptor.name
        ),
        "transport": (
            descriptor.transport
        ),
        "executable": (
            descriptor.executable
        ),
        "features": features,
        "metadata": dict(
            descriptor.metadata
        ),
    }

    if (
        descriptor.transport
        == ProviderTransport.CLI
    ):
        resolved = (
            resolve_cli_executable(
                descriptor
            )
        )

        if resolved:
            return ProviderHealth(
                **common,
                status=(
                    ProviderHealthStatus
                    .AVAILABLE
                ),
                reason=(
                    "CLI executable resolved."
                ),
                checked_via=(
                    "cli_executable"
                ),
                resolved_executable=(
                    resolved
                ),
            )

        return ProviderHealth(
            **common,
            status=(
                ProviderHealthStatus
                .UNAVAILABLE
            ),
            reason=(
                "CLI executable could not "
                "be resolved."
            ),
            checked_via=(
                "cli_executable"
            ),
            resolved_executable=None,
        )

    if (
        descriptor.transport
        == ProviderTransport.IN_PROCESS
    ):
        return ProviderHealth(
            **common,
            status=(
                ProviderHealthStatus
                .AVAILABLE
            ),
            reason=(
                "Provider adapter is loaded "
                "in-process."
            ),
            checked_via=(
                "registry"
            ),
        )

    return ProviderHealth(
        **common,
        status=(
            ProviderHealthStatus.UNKNOWN
        ),
        reason=(
            "No passive health probe is "
            "defined for this transport."
        ),
        checked_via=(
            "descriptor"
        ),
    )


def discover_provider(
    descriptor: ProviderDescriptor,
) -> dict[str, Any]:
    health = probe_provider_descriptor(
        descriptor
    )

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
        "health": (
            health.as_dict()
        ),
    }
