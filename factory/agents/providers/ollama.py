from collections.abc import Callable, Mapping
from typing import Any

from litellm import completion

from factory.agents.contracts import (
    AgentRequest,
    AgentResult,
)
from factory.agents.provider_errors import (
    AgentModelUnavailableError,
    AgentProviderUnavailableError,
)


class OllamaProvider:
    provider_name = "ollama"

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        completion_fn: Callable[..., Any] = completion,
    ) -> None:
        self.config = config
        self.completion_fn = completion_fn

    def _resolve_role(
        self,
        model_role: str,
    ) -> dict[str, Any]:
        models = self.config.get("models", {})

        if model_role not in models:
            raise KeyError(
                f"Unknown model role: {model_role}"
            )

        role = models[model_role]

        if role.get("provider") != "ollama":
            raise ValueError(
                f"Model role '{model_role}' is not "
                "configured for Ollama."
            )

        return {
            "model": role.get("model"),
            "api_base": role.get("api_base"),
            "temperature": role.get(
                "temperature",
                0.1,
            ),
            "timeout": role.get(
                "timeout_seconds",
                120,
            ),
        }

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        params = self._resolve_role(
            request.model_role
        )

        model_name = (
            request.model_name
            or params["model"]
        )

        if not model_name:
            raise ValueError(
                "Ollama model name is missing."
            )

        temperature = (
            request.temperature
            if request.temperature is not None
            else params["temperature"]
        )

        timeout = (
            request.timeout
            if request.timeout is not None
            else params["timeout"]
        )

        kwargs = {
            "model": f"ollama/{model_name}",
            "messages": [
                {
                    "role": "system",
                    "content": request.system_prompt,
                },
                {
                    "role": "user",
                    "content": request.user_prompt,
                },
            ],
            "temperature": temperature,
            "timeout": timeout,
        }

        if params["api_base"]:
            kwargs["api_base"] = params["api_base"]

        generation = self.config.get(
            "generation",
            {},
        )

        max_retries = int(
            generation.get(
                "max_retries",
                1,
            )
        )

        last_exception = None
        response = None

        for _attempt in range(
            max_retries + 1
        ):
            try:
                response = self.completion_fn(
                    **kwargs
                )
                break
            except Exception as exc:
                last_exception = exc

        if response is None:
            error_text = str(
                last_exception
            ).lower()

            api_base = (
                params["api_base"]
                or "http://localhost:11434"
            )

            if (
                "connect" in error_text
                or "refused" in error_text
                or "nodename" in error_text
            ):
                raise AgentProviderUnavailableError(
                    "Ollama server could not be "
                    f"reached at {api_base}."
                ) from last_exception

            if (
                "not found" in error_text
                or "pull" in error_text
                or "does not exist" in error_text
            ):
                raise AgentModelUnavailableError(
                    "Ollama model was not found: "
                    f"{model_name}. "
                    "Install it with: "
                    f"ollama pull {model_name}"
                ) from last_exception

            raise RuntimeError(
                "Unexpected Ollama provider error: "
                f"{last_exception}"
            ) from last_exception

        usage = None

        if (
            hasattr(response, "usage")
            and response.usage
        ):
            try:
                usage = dict(response.usage)
            except Exception:
                usage = None

        return AgentResult(
            content=(
                response
                .choices[0]
                .message
                .content
            ),
            provider=self.provider_name,
            model=model_name,
            metadata={
                "model_role": request.model_role,
                "usage": usage,
            },
        )
