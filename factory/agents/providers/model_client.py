from typing import Any

from factory.agents.contracts import (
    AgentRequest,
    AgentResult,
)
from factory.agents.provider_registry import (
    AgentProviderRegistry,
)
from factory.agents.providers.antigravity import (
    AntigravityCliProvider,
)
from factory.agents.providers.ollama import (
    OllamaProvider,
)


class ModelClientProvider:
    provider_name = "model_client"

    def __init__(
        self,
        model_client: Any,
        registry: AgentProviderRegistry | None = None,
    ) -> None:
        self.model_client = model_client

        if registry is not None:
            self.registry = registry
            return

        self.registry = AgentProviderRegistry()

        config = getattr(
            model_client,
            "config",
            None,
        )

        if isinstance(config, dict):
            self.registry.register(
                OllamaProvider(config)
            )

            if self._provider_is_enabled(
                config,
                "antigravity_cli",
            ):
                settings = (
                    self._provider_settings(
                        config,
                        "antigravity_cli",
                    )
                )

                self.registry.register(
                    AntigravityCliProvider(
                        executable=str(
                            settings.get(
                                "executable",
                                "agy",
                            )
                        ),
                        default_timeout=int(
                            settings.get(
                                "default_timeout",
                                120,
                            )
                        ),
                        mode=str(
                            settings.get(
                                "mode",
                                "plan",
                            )
                        ),
                    )
                )

    @staticmethod
    def _provider_settings(
        config: dict[str, Any],
        provider_name: str,
    ) -> dict[str, Any]:
        providers = config.get(
            "providers",
            {},
        )

        if not isinstance(
            providers,
            dict,
        ):
            return {}

        settings = providers.get(
            provider_name,
            {},
        )

        if not isinstance(
            settings,
            dict,
        ):
            return {}

        return settings

    @classmethod
    def _provider_is_enabled(
        cls,
        config: dict[str, Any],
        provider_name: str,
    ) -> bool:
        normalized_provider = (
            provider_name
            .strip()
            .lower()
        )

        settings = cls._provider_settings(
            config,
            normalized_provider,
        )

        explicitly_enabled = (
            settings.get(
                "enabled"
            )
        )

        if explicitly_enabled is True:
            return True

        if explicitly_enabled is False:
            return False

        models = config.get(
            "models",
            {},
        )

        if not isinstance(
            models,
            dict,
        ):
            return False

        for role_config in (
            models.values()
        ):
            if not isinstance(
                role_config,
                dict,
            ):
                continue

            configured_provider = (
                role_config.get(
                    "provider"
                )
            )

            if configured_provider is None:
                continue

            normalized = (
                str(
                    configured_provider
                )
                .strip()
                .lower()
            )

            if (
                normalized
                == normalized_provider
            ):
                return True

        return False

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

        return str(
            provider
        ).strip().lower()

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        configured_provider = (
            self._configured_provider(
                request.model_role
            )
        )

        if (
            configured_provider
            and self.registry.has(
                configured_provider
            )
        ):
            provider = self.registry.get(
                configured_provider
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
