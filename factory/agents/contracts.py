from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class AgentRequest:
    system_prompt: str
    user_prompt: str
    model_role: str = "fast_local"
    temperature: float | None = None
    timeout: int | None = None
    model_name: str | None = None
    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class AgentResult:
    content: str
    provider: str
    model: str | None = None
    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )


@runtime_checkable
class AgentProvider(Protocol):
    provider_name: str

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        ...
