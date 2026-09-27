import os
import yaml
from dataclasses import dataclass
from typing import Optional, Dict, Any
from litellm import completion
import litellm
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ModelResponse:
    content: str
    model: str
    provider: str
    usage: Optional[Dict[str, Any]] = None


class ModelClient:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        
        # LiteLLM log kirliliğini ve uyarıları minimumda tut
        litellm.drop_params = True

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(
                f"Config dosyası bulunamadı: '{self.config_path}'. "
                f"Lütfen ana dizinde config.yaml olduğundan emin olun."
            )
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            raise ValueError(f"config.yaml okunurken YAML ayrıştırma hatası oluştu: {e}")

    def _resolve_model_params(self, model_role: str) -> Dict[str, Any]:
        models_config = self.config.get("models", {})
        if model_role not in models_config:
            available_roles = list(models_config.keys())
            raise KeyError(
                f"Geçersiz model rolü: '{model_role}'. "
                f"config.yaml içinde tanımlı roller: {available_roles}"
            )
        
        role_cfg = models_config[model_role]
        provider = role_cfg.get("provider")
        model_name = role_cfg.get("model")
        api_base = role_cfg.get("api_base")
        
        # LiteLLM için provider/model formatı (Örn: ollama/qwen2.5-coder:14b)
        if provider == "ollama":
            litellm_model = f"ollama/{model_name}"
        elif provider == "openrouter":
            litellm_model = f"openrouter/{model_name}"
        else:
            litellm_model = model_name

        # Cloud kontrolü
        if provider != "ollama":
            cloud_cfg = self.config.get("cloud", {})
            if not cloud_cfg.get("enabled", False):
                raise PermissionError(
                    f"Cloud sağlayıcısı ('{provider}') isteniyor ancak "
                    f"config.yaml içindeki cloud.enabled ayarı kapalı (false)."
                )

        return {
            "litellm_model": litellm_model,
            "provider": provider,
            "api_base": api_base,
            "temperature": role_cfg.get("temperature", 0.1),
            "timeout": role_cfg.get("timeout_seconds", 120)
        }

    def _resolve_fallback_params(
        self,
        model_role: str,
    ) -> Optional[Dict[str, Any]]:
        models_config = self.config.get("models", {})
        role_cfg = models_config.get(model_role, {})
        fallback_cfg = role_cfg.get("fallback")

        if not isinstance(fallback_cfg, dict):
            return None

        provider = fallback_cfg.get("provider")
        model_name = fallback_cfg.get("model")
        api_base = fallback_cfg.get("api_base")

        if not provider or not model_name:
            return None

        if provider == "ollama":
            litellm_model = f"ollama/{model_name}"
        elif provider == "openrouter":
            litellm_model = f"openrouter/{model_name}"
        else:
            litellm_model = model_name

        if provider != "ollama":
            cloud_cfg = self.config.get("cloud", {})
            if not cloud_cfg.get("enabled", False):
                return None

        return {
            "litellm_model": litellm_model,
            "provider": provider,
            "api_base": api_base,
            "temperature": fallback_cfg.get(
                "temperature",
                role_cfg.get("temperature", 0.1),
            ),
            "timeout": fallback_cfg.get(
                "timeout_seconds",
                role_cfg.get("timeout_seconds", 120),
            ),
        }

    @staticmethod
    def _should_use_fallback(exc: Exception) -> bool:
        err = str(exc).lower()
        fallback_signals = (
            "rate limit",
            "ratelimit",
            "429",
            "free-models-per-day",
            "timeout",
            "timed out",
            "connection",
            "connect",
            "refused",
            "service unavailable",
            "502",
            "503",
            "504",
            "api key",
            "openrouter_api_key",
            "ortam degiskeni bulunamadi",
            "unauthorized",
            "401",
            "403",
        )
        return any(
            signal in err
            for signal in fallback_signals
        )

    def _call_provider(
        self,
        *,
        params: Dict[str, Any],
        messages: list[Dict[str, str]],
        temperature: float,
        timeout: int,
        max_retries: int,
    ) -> ModelResponse:
        kwargs = {
            "model": params["litellm_model"],
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout,
        }

        if (
            params["provider"] == "ollama"
            and params.get("api_base")
        ):
            kwargs["api_base"] = params["api_base"]

        if params["provider"] == "openrouter":
            openrouter_api_key = os.getenv(
                "OPENROUTER_API_KEY",
                "",
            ).strip()

            if not openrouter_api_key:
                raise RuntimeError(
                    "OPENROUTER_API_KEY ortam degiskeni bulunamadi."
                )

            kwargs["api_key"] = openrouter_api_key

        last_exception = None

        for _attempt in range(max_retries + 1):
            try:
                response = completion(**kwargs)

                content = response.choices[0].message.content
                usage = (
                    dict(response.usage)
                    if hasattr(response, "usage")
                    and response.usage
                    else None
                )

                actual_model = (
                    getattr(response, "model", None)
                    or params["litellm_model"]
                )

                return ModelResponse(
                    content=content,
                    model=actual_model,
                    provider=params["provider"],
                    usage=usage,
                )

            except Exception as exc:
                last_exception = exc

        assert last_exception is not None
        raise last_exception

    def complete(
        self,
        model_role: str,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        model_name_override: Optional[str] = None,
    ) -> ModelResponse:

        params = self._resolve_model_params(model_role)

        if model_name_override:
            if params["provider"] == "ollama":
                params = dict(params)
                params["litellm_model"] = (
                    f"ollama/{model_name_override}"
                )
            elif params["provider"] == "openrouter":
                pass
            else:
                raise ValueError(
                    "model_name_override bu provider icin desteklenmiyor: "
                    + str(params["provider"])
                )

        temp = (
            temperature
            if temperature is not None
            else params["temperature"]
        )
        to = (
            timeout
            if timeout is not None
            else params["timeout"]
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        gen_cfg = self.config.get("generation", {})
        max_retries = int(
            gen_cfg.get("max_retries", 1)
        )

        try:
            return self._call_provider(
                params=params,
                messages=messages,
                temperature=temp,
                timeout=to,
                max_retries=max_retries,
            )

        except Exception as primary_exception:
            fallback_params = self._resolve_fallback_params(
                model_role
            )

            if (
                fallback_params is not None
                and self._should_use_fallback(
                    primary_exception
                )
            ):
                print(
                    "[MODEL FALLBACK] "
                    f"{params['provider']} "
                    f"{params['litellm_model']} -> "
                    f"{fallback_params['provider']} "
                    f"{fallback_params['litellm_model']}"
                )

                fallback_temp = (
                    temperature
                    if temperature is not None
                    else fallback_params["temperature"]
                )
                fallback_timeout = (
                    timeout
                    if timeout is not None
                    else fallback_params["timeout"]
                )

                try:
                    return self._call_provider(
                        params=fallback_params,
                        messages=messages,
                        temperature=fallback_temp,
                        timeout=fallback_timeout,
                        max_retries=max_retries,
                    )

                except Exception as fallback_exception:
                    raise RuntimeError(
                        "\n[HATA] Primary ve fallback model "
                        "cagrilari basarisiz oldu.\n"
                        f"Primary ({params['provider']}): "
                        f"{primary_exception}\n"
                        f"Fallback "
                        f"({fallback_params['provider']}): "
                        f"{fallback_exception}"
                    ) from fallback_exception

            err_msg = str(primary_exception).lower()

            if params["provider"] == "ollama":
                api_base = params.get(
                    "api_base",
                    "http://127.0.0.1:11434",
                )

                if (
                    "connect" in err_msg
                    or "refused" in err_msg
                    or "nodename" in err_msg
                ):
                    raise ConnectionError(
                        f"\n[HATA] '{model_role}' cagrisi "
                        f"basarisiz:\n"
                        f"Ollama server'a ({api_base}) "
                        "ulasilamadi."
                    ) from primary_exception

                if (
                    "not found" in err_msg
                    or "pull" in err_msg
                    or "does not exist" in err_msg
                ):
                    raise ValueError(
                        f"\n[HATA] '{model_role}' cagrisi "
                        f"basarisiz:\n"
                        f"Ollama uzerinde "
                        f"'{params['litellm_model']}' "
                        "modeli bulunamadi."
                    ) from primary_exception

            raise RuntimeError(
                f"\n[HATA] '{model_role}' modeli "
                "cagrilirken beklenmeyen bir hata olustu: "
                f"{primary_exception}"
            ) from primary_exception
