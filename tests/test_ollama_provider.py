from types import SimpleNamespace

from factory.agents.contracts import (
    AgentRequest,
)
from factory.agents.providers.ollama import (
    OllamaProvider,
)


def _config():
    return {
        "models": {
            "fast_local": {
                "provider": "ollama",
                "model": "llama3.1:8b",
                "api_base": (
                    "http://127.0.0.1:11434"
                ),
                "temperature": 0.1,
                "timeout_seconds": 120,
            }
        }
    }


def _response(content="ok"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content
                )
            )
        ],
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 5,
        },
    )


def test_ollama_provider_uses_role_config():
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _response("hello")

    provider = OllamaProvider(
        _config(),
        completion_fn=fake_completion,
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="user",
            model_role="fast_local",
        )
    )

    assert result.content == "hello"
    assert result.provider == "ollama"
    assert result.model == "llama3.1:8b"

    assert calls[0]["model"] == (
        "ollama/llama3.1:8b"
    )
    assert calls[0]["temperature"] == 0.1
    assert calls[0]["timeout"] == 120
    assert calls[0]["api_base"] == (
        "http://127.0.0.1:11434"
    )


def test_ollama_provider_allows_model_override():
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _response()

    provider = OllamaProvider(
        _config(),
        completion_fn=fake_completion,
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="user",
            model_role="fast_local",
            model_name="qwen2.5-coder:14b",
            temperature=0.0,
            timeout=45,
        )
    )

    assert result.model == (
        "qwen2.5-coder:14b"
    )
    assert calls[0]["model"] == (
        "ollama/qwen2.5-coder:14b"
    )
    assert calls[0]["temperature"] == 0.0
    assert calls[0]["timeout"] == 45


def test_ollama_provider_rejects_non_ollama_role():
    config = _config()

    config["models"]["cloud_senior"] = {
        "provider": "openai",
        "model": "some-model",
    }

    provider = OllamaProvider(
        config,
        completion_fn=lambda **kwargs: _response(),
    )

    try:
        provider.complete(
            AgentRequest(
                system_prompt="system",
                user_prompt="user",
                model_role="cloud_senior",
            )
        )
    except ValueError as exc:
        assert "not configured for Ollama" in str(
            exc
        )
    else:
        raise AssertionError(
            "Expected ValueError"
        )


def test_ollama_provider_retries():
    config = _config()
    config["generation"] = {
        "max_retries": 1,
    }

    attempts = []

    def flaky_completion(**kwargs):
        attempts.append(kwargs)

        if len(attempts) == 1:
            raise RuntimeError(
                "temporary failure"
            )

        return _response("retry-ok")

    provider = OllamaProvider(
        config,
        completion_fn=flaky_completion,
    )

    result = provider.complete(
        AgentRequest(
            system_prompt="system",
            user_prompt="user",
            model_role="fast_local",
        )
    )

    assert result.content == "retry-ok"
    assert len(attempts) == 2


def test_ollama_provider_maps_connection_error():
    config = _config()
    config["generation"] = {
        "max_retries": 0,
    }

    def fail(**kwargs):
        raise RuntimeError(
            "connection refused"
        )

    provider = OllamaProvider(
        config,
        completion_fn=fail,
    )

    try:
        provider.complete(
            AgentRequest(
                system_prompt="system",
                user_prompt="user",
                model_role="fast_local",
            )
        )
    except ConnectionError as exc:
        assert "Ollama server" in str(exc)
    else:
        raise AssertionError(
            "Expected ConnectionError"
        )


def test_ollama_provider_maps_missing_model():
    config = _config()
    config["generation"] = {
        "max_retries": 0,
    }

    def fail(**kwargs):
        raise RuntimeError(
            "model not found"
        )

    provider = OllamaProvider(
        config,
        completion_fn=fail,
    )

    try:
        provider.complete(
            AgentRequest(
                system_prompt="system",
                user_prompt="user",
                model_role="fast_local",
                model_name=(
                    "qwen2.5-coder:14b"
                ),
            )
        )
    except ValueError as exc:
        message = str(exc)

        assert (
            "qwen2.5-coder:14b"
            in message
        )
        assert (
            "ollama pull"
            in message
        )
    else:
        raise AssertionError(
            "Expected ValueError"
        )
