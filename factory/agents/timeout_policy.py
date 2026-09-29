from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from factory.agents.contracts import AgentRequest

DEFAULT_AGENT_TIMEOUT = 120


def resolve_agent_timeout(
    timeout: int | None,
    *,
    config: Mapping[str, Any] | None = None,
    model_role: str | None = None,
) -> int:
    """Resolve the logical agent request timeout.

    Precedence:
    1. explicit timeout
    2. config models[role].timeout_seconds
    3. DEFAULT_AGENT_TIMEOUT (120)

    Does not enforce the timeout; transport
    providers apply the resolved value.
    """
    if timeout is not None:
        resolved = int(timeout)

        if resolved < 1:
            raise ValueError(
                "Agent request timeout "
                "must be >= 1."
            )

        return resolved

    if (
        isinstance(config, Mapping)
        and model_role
    ):
        models = config.get("models", {})

        if isinstance(models, Mapping):
            role_config = models.get(
                model_role,
                {},
            )

            if isinstance(role_config, Mapping):
                role_timeout = role_config.get(
                    "timeout_seconds"
                )

                if role_timeout is not None:
                    resolved = int(
                        role_timeout
                    )

                    if resolved < 1:
                        raise ValueError(
                            "Configured role "
                            "timeout_seconds "
                            "must be >= 1."
                        )

                    return resolved

    return DEFAULT_AGENT_TIMEOUT


def ensure_agent_request_timeout(
    request: AgentRequest,
    *,
    config: Mapping[str, Any] | None = None,
) -> AgentRequest:
    """Return a request with an explicit timeout."""
    resolved = resolve_agent_timeout(
        request.timeout,
        config=config,
        model_role=request.model_role,
    )

    if request.timeout == resolved:
        return request

    return replace(
        request,
        timeout=resolved,
    )
