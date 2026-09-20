import json
import subprocess
from types import SimpleNamespace

import pytest

from factory.agents.contracts import (
    AgentRequest,
)
from factory.agents.provider_adapter import (
    ProviderFeature,
    ProviderTransport,
)
from factory.agents.provider_errors import (
    AgentModelUnavailableError,
    AgentProviderRateLimitError,
    AgentProviderTimeoutError,
    AgentProviderUnavailableError,
)
from factory.agents.providers.antigravity import (
    AntigravityCliProvider,
)


def _request(
    **overrides,
):
    values = {
        "system_prompt": (
            "You are a coding agent."
        ),
        "user_prompt": (
            "Inspect the repository."
        ),
        "model_role": "cloud_senior",
        "model_name": None,
        "timeout": 60,
    }

    values.update(
        overrides
    )

    return AgentRequest(
        **values
    )


def _success_payload():
    return {
        "conversation_id": "conv-1",
        "status": "SUCCESS",
        "response": "AGY_OK\n",
        "duration_seconds": 3.88,
        "num_turns": 1,
        "usage": {
            "input_tokens": 12529,
            "output_tokens": 745,
            "thinking_tokens": 741,
            "cache_read_tokens": 0,
            "total_tokens": 13274,
        },
    }


def test_descriptor_declares_cli_features():
    provider = (
        AntigravityCliProvider()
    )

    descriptor = (
        provider.describe()
    )

    assert (
        descriptor.name
        == "antigravity_cli"
    )

    assert (
        descriptor.transport
        == ProviderTransport.CLI
    )

    assert (
        descriptor.executable
        == "agy"
    )

    assert descriptor.supports(
        ProviderFeature.SYSTEM_PROMPT
    )

    assert descriptor.supports(
        ProviderFeature.MODEL_OVERRIDE
    )

    assert descriptor.supports(
        ProviderFeature.TIMEOUT
    )

    assert descriptor.supports(
        ProviderFeature.USAGE_METADATA
    )


def test_provider_executes_json_print_mode():
    calls = []

    def fake_run(
        command,
        **kwargs,
    ):
        calls.append(
            (
                command,
                kwargs,
            )
        )

        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                _success_payload()
            ),
            stderr="",
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    result = provider.complete(
        _request()
    )

    assert (
        result.content
        == "AGY_OK"
    )

    assert (
        result.provider
        == "antigravity_cli"
    )

    assert (
        result.metadata[
            "conversation_id"
        ]
        == "conv-1"
    )

    assert (
        result.metadata[
            "total_tokens"
        ]
        == 13274
    )

    command, kwargs = calls[0]

    assert command[0] == "agy"

    assert (
        command[
            command.index(
                "--output-format"
            )
            + 1
        ]
        == "json"
    )

    assert (
        command[
            command.index(
                "--mode"
            )
            + 1
        ]
        == "plan"
    )

    assert (
        command[
            command.index(
                "--print-timeout"
            )
            + 1
        ]
        == "60s"
    )

    prompt = command[
        command.index(
            "--print"
        )
        + 1
    ]

    assert (
        "SYSTEM INSTRUCTIONS"
        in prompt
    )

    assert (
        "You are a coding agent."
        in prompt
    )

    assert (
        "Inspect the repository."
        in prompt
    )

    assert (
        kwargs["timeout"]
        == 70
    )

    assert (
        kwargs["check"]
        is False
    )


def test_provider_passes_model_override():
    captured = {}

    def fake_run(
        command,
        **kwargs,
    ):
        captured["command"] = (
            command
        )

        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                _success_payload()
            ),
            stderr="",
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    result = provider.complete(
        _request(
            model_name=(
                "gemini-2.5-pro"
            ),
        )
    )

    command = captured[
        "command"
    ]

    assert "--model" in command

    assert (
        command[
            command.index(
                "--model"
            )
            + 1
        ]
        == "gemini-2.5-pro"
    )

    assert (
        result.model
        == "gemini-2.5-pro"
    )


def test_provider_omits_model_when_not_overridden():
    captured = {}

    def fake_run(
        command,
        **kwargs,
    ):
        captured["command"] = (
            command
        )

        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                _success_payload()
            ),
            stderr="",
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    provider.complete(
        _request(
            model_name=None,
        )
    )

    assert (
        "--model"
        not in captured["command"]
    )


def test_missing_executable_maps_to_provider_unavailable():
    def fake_run(
        *args,
        **kwargs,
    ):
        raise FileNotFoundError(
            "agy"
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        AgentProviderUnavailableError,
        match="executable was not found",
    ):
        provider.complete(
            _request()
        )


def test_process_timeout_maps_to_provider_timeout():
    def fake_run(
        *args,
        **kwargs,
    ):
        raise subprocess.TimeoutExpired(
            cmd="agy",
            timeout=60,
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        AgentProviderTimeoutError,
    ):
        provider.complete(
            _request()
        )


@pytest.mark.parametrize(
    (
        "message",
        "error_type",
    ),
    [
        (
            "Authentication required",
            AgentProviderUnavailableError,
        ),
        (
            "429 rate limit exceeded",
            AgentProviderRateLimitError,
        ),
        (
            "model not found",
            AgentModelUnavailableError,
        ),
        (
            "request timeout",
            AgentProviderTimeoutError,
        ),
    ],
)
def test_nonzero_exit_maps_known_errors(
    message,
    error_type,
):
    def fake_run(
        *args,
        **kwargs,
    ):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=message,
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        error_type
    ):
        provider.complete(
            _request()
        )


def test_unknown_nonzero_exit_is_not_silently_fallbackable():
    def fake_run(
        *args,
        **kwargs,
    ):
        return SimpleNamespace(
            returncode=2,
            stdout="",
            stderr=(
                "unexpected internal "
                "failure"
            ),
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        RuntimeError,
        match="Antigravity CLI failed",
    ):
        provider.complete(
            _request()
        )


def test_invalid_json_is_rejected():
    def fake_run(
        *args,
        **kwargs,
    ):
        return SimpleNamespace(
            returncode=0,
            stdout="not-json",
            stderr="",
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        RuntimeError,
        match="invalid JSON",
    ):
        provider.complete(
            _request()
        )


def test_json_error_payload_is_mapped():
    payload = {
        "conversation_id": "conv-error",
        "status": "ERROR",
        "error": {
            "message": (
                "Authentication required"
            ),
        },
    }

    def fake_run(
        *args,
        **kwargs,
    ):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                payload
            ),
            stderr="",
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        AgentProviderUnavailableError,
    ):
        provider.complete(
            _request()
        )


def test_success_requires_response_string():
    payload = {
        "status": "SUCCESS",
        "response": None,
    }

    def fake_run(
        *args,
        **kwargs,
    ):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                payload
            ),
            stderr="",
        )

    provider = AntigravityCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        RuntimeError,
        match="missing string field",
    ):
        provider.complete(
            _request()
        )


def test_invalid_provider_configuration_is_rejected():
    with pytest.raises(
        ValueError,
        match="default_timeout",
    ):
        AntigravityCliProvider(
            default_timeout=0
        )

    with pytest.raises(
        ValueError,
        match="Unsupported",
    ):
        AntigravityCliProvider(
            mode="yolo"
        )
