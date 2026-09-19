from typing import Any

from factory.agents.contracts import (
    AgentProvider,
    AgentRequest,
    AgentResult,
)


class ModelClientProvider:
    provider_name = "model_client"

    def __init__(
        self,
        model_client: Any,
    ) -> None:
        self.model_client = model_client

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        response = self.model_client.complete(
            model_role=request.model_role,
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            temperature=request.temperature,
            timeout=request.timeout,
            model_name_override=request.model_name,
        )

        return AgentResult(
            content=response.content,
            provider=self.provider_name,
            model=request.model_name,
            metadata={
                "model_role": request.model_role,
            },
        )


assert isinstance(
    ModelClientProvider,
    type,
)
