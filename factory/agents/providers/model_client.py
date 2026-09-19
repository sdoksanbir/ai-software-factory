from typing import Any

from factory.agents.contracts import (
    AgentProvider,
    AgentRequest,
    AgentResult,
)
from factory.agents.providers.ollama import (
    OllamaProvider,
)


class ModelClientProvider:
    provider_name = "model_client"

    def __init__(
        self,
        model_client: Any,
    ) -> None:
        self.model_client = model_client

    def _configured_provider(
        self,
        model_role: str,
    ) -> str | None:
        config = getattr(
            self.model_client,
            "config",
            None,
        )

        if not isinstance(config, dict):
            return None

        models = config.get(
            "models",
            {},
        )

        if not isinstance(models, dict):
            return None

        role_config = models.get(
            model_role
        )

        if not isinstance(
            role_config,
            dict,
        ):
            return None

        provider = role_config.get(
            "provider"
        )

        if provider is None:
            return None

        return str(provider)

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        configured_provider = (
            self._configured_provider(
                request.model_role
            )
        )

        if configured_provider == "ollama":
            provider = OllamaProvider(
                self.model_client.config
            )

            return provider.complete(
                request
            )

        # Compatibility path for providers that
        # have not been migrated yet.
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
