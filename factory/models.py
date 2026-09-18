import os
import yaml
from dataclasses import dataclass
from typing import Optional, Dict, Any
from litellm import completion
import litellm


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
            if params["provider"] != "ollama":
                raise ValueError(
                    "model_name_override yalnizca Ollama "
                    "modellerinde kullanilabilir."
                )

            params = dict(params)
            params["litellm_model"] = (
                f"ollama/{model_name_override}"
            )
        
        # Parametre override imkanı
        temp = temperature if temperature is not None else params["temperature"]
        to = timeout if timeout is not None else params["timeout"]
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # LiteLLM çağrı argümanları
        kwargs = {
            "model": params["litellm_model"],
            "messages": messages,
            "temperature": temp,
            "timeout": to,
        }
        
        if params["provider"] == "ollama" and params["api_base"]:
            kwargs["api_base"] = params["api_base"]

        gen_cfg = self.config.get("generation", {})
        max_retries = gen_cfg.get("max_retries", 1)
        
        last_exception = None
        attempt = 0
        
        while attempt <= max_retries:
            try:
                response = completion(**kwargs)
                
                content = response.choices[0].message.content
                usage = dict(response.usage) if hasattr(response, "usage") and response.usage else None
                
                return ModelResponse(
                    content=content,
                    model=params["litellm_model"],
                    provider=params["provider"],
                    usage=usage
                )
                
            except Exception as e:
                last_exception = e
                attempt += 1
                if attempt > max_retries:
                    break

        # Anlamlı hata yönetimi ve yönlendirme
        err_msg = str(last_exception).lower()
        
        if params["provider"] == "ollama":
            api_base = params.get("api_base", "http://localhost:11434")
            if "connect" in err_msg or "refused" in err_msg or "nodename" in err_msg:
                raise ConnectionError(
                    f"\n[HATA] '{model_role}' çağrısı başarısız:\n"
                    f"Ollama server'a ({api_base}) üzerinden ulaşılamadı. "
                    f"Lütfen Ollama'nın arka planda açık olduğundan emin olun."
                ) from last_exception
            elif "not found" in err_msg or "pull" in err_msg or "does not exist" in err_msg:
                raise ValueError(
                    f"\n[HATA] '{model_role}' çağrısı başarısız:\n"
                    f"Ollama üzerinde '{params['litellm_model']}' modeli bulunamadı. "
                    f"Lütfen terminalde 'ollama run {params['litellm_model'].split('/')}' komutunu çalıştırarak modeli indirin."
                ) from last_exception

        raise RuntimeError(
            f"\n[HATA] '{model_role}' modeli çağrılırken beklenmeyen bir hata oluştu: {last_exception}"
        ) from last_exception