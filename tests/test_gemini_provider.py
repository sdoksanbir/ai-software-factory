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
from factory.agents.providers.gemini import (
    GeminiCliProvider,
)


def make_request(
    *,
    system_prompt="You are a coding agent.",
    user_prompt="Return OK.",
    model_name=None,
    timeout=None,
    metadata=None,
):
    return AgentRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model_role="fast_local",
        model_name=model_name,
        timeout=timeout,
        metadata=dict(
            metadata or {}
        ),
    )


def test_rejects_empty_executable():
    with pytest.raises(
        ValueError,
        match="executable",
    ):
        GeminiCliProvider(
            executable=""
        )


def test_rejects_invalid_timeout():
    with pytest.raises(
        ValueError,
        match="default_timeout",
    ):
        GeminiCliProvider(
            default_timeout=0
        )


def test_rejects_invalid_approval_mode():
    with pytest.raises(
        ValueError,
        match="approval mode",
    ):
        GeminiCliProvider(
            approval_mode="invalid"
        )


def test_descriptor_matches_provider_standard():
    provider = GeminiCliProvider()

    descriptor = provider.describe()

    assert descriptor.name == "gemini_cli"

    assert (
        descriptor.transport
        == ProviderTransport.CLI
    )

    assert descriptor.executable == "gemini"

    assert (
        ProviderFeature.SYSTEM_PROMPT
        in descriptor.features
    )

    assert (
        ProviderFeature.MODEL_OVERRIDE
        in descriptor.features
    )

    assert (
        ProviderFeature.TIMEOUT
        in descriptor.features
    )

    assert (
        ProviderFeature.USAGE_METADATA
        in descriptor.features
    )

    assert (
        descriptor.metadata[
            "cli_family"
        ]
        == "google_gemini"
    )

    assert (
        descriptor.metadata[
            "output_format"
        ]
        == "json"
    )

    assert (
        descriptor.metadata[
            "approval_mode"
        ]
        == "plan"
    )


def test_build_command_uses_headless_json_mode():
    provider = GeminiCliProvider(
        executable="gemini",
        approval_mode="plan",
    )

    request = make_request(
        model_name="gemini-2.5-pro",
        timeout=45,
        metadata={
            "working_directory": (
                r"C:\Projects\Demo"
            )
        },
    )

    (
        command,
        timeout,
        cwd,
    ) = provider._build_command(
        request
    )

    assert command[0] == "gemini"

    assert "--prompt" in command

    prompt_index = (
        command.index(
            "--prompt"
        )
        + 1
    )

    assert (
        "SYSTEM INSTRUCTIONS:"
        in command[prompt_index]
    )

    assert (
        "You are a coding agent."
        in command[prompt_index]
    )

    assert (
        "USER REQUEST:"
        in command[prompt_index]
    )

    assert (
        "Return OK."
        in command[prompt_index]
    )

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
                "--approval-mode"
            )
            + 1
        ]
        == "plan"
    )

    assert (
        command[
            command.index(
                "--model"
            )
            + 1
        ]
        == "gemini-2.5-pro"
    )

    assert timeout == 45

    assert (
        cwd
        == r"C:\Projects\Demo"
    )


def test_complete_parses_success_json():
    captured = {}

    payload = {
        "session_id": "session-123",
        "response": "GEMINI_OK\n",
        "stats": {
            "models": {
                "gemini-test": {
                    "tokens": {
                        "input": 10,
                        "output": 3,
                    }
                }
            }
        },
        "warnings": [
            "test-warning"
        ],
    }

    def fake_run(
        command,
        **kwargs,
    ):
        captured["command"] = command
        captured["kwargs"] = kwargs

        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                payload
            ),
            stderr="",
        )

    provider = GeminiCliProvider(
        run_fn=fake_run
    )

    result = provider.complete(
        make_request(
            model_name="gemini-test",
            metadata={
                "worktree_path": (
                    r"C:\AI-Worktrees\TASK-1"
                )
            },
        )
    )

    assert result.content == "GEMINI_OK"

    assert (
        result.provider
        == "gemini_cli"
    )

    assert (
        result.model
        == "gemini-test"
    )

    assert (
        result.metadata[
            "session_id"
        ]
        == "session-123"
    )

    assert (
        result.metadata[
            "approval_mode"
        ]
        == "plan"
    )

    assert (
        result.metadata[
            "warnings"
        ]
        == ["test-warning"]
    )

    assert (
        result.metadata[
            "stats"
        ]
        == payload["stats"]
    )

    assert (
        captured["kwargs"]["cwd"]
        == r"C:\AI-Worktrees\TASK-1"
    )

    assert (
        captured["kwargs"][
            "timeout"
        ]
        == 120
    )


def test_invalid_json_is_rejected():
    provider = GeminiCliProvider(
        run_fn=lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=0,
                stdout="not-json",
                stderr="",
            )
        )
    )

    with pytest.raises(
        RuntimeError,
        match="invalid JSON",
    ):
        provider.complete(
            make_request()
        )


def test_missing_response_is_rejected():
    provider = GeminiCliProvider(
        run_fn=lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "stats": {},
                    }
                ),
                stderr="",
            )
        )
    )

    with pytest.raises(
        RuntimeError,
        match="missing string field",
    ):
        provider.complete(
            make_request()
        )


def test_authentication_error_is_mapped():
    provider = GeminiCliProvider(
        run_fn=lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=1,
                stdout=json.dumps(
                    {
                        "error": {
                            "message": (
                                "Authentication "
                                "required"
                            )
                        }
                    }
                ),
                stderr="",
            )
        )
    )

    with pytest.raises(
        AgentProviderUnavailableError,
    ):
        provider.complete(
            make_request()
        )


def test_rate_limit_error_is_mapped():
    provider = GeminiCliProvider(
        run_fn=lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=1,
                stdout=json.dumps(
                    {
                        "error": {
                            "message": (
                                "Resource exhausted: "
                                "quota exceeded"
                            )
                        }
                    }
                ),
                stderr="",
            )
        )
    )

    with pytest.raises(
        AgentProviderRateLimitError,
    ):
        provider.complete(
            make_request()
        )


def test_model_error_is_mapped():
    provider = GeminiCliProvider(
        run_fn=lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=1,
                stdout=json.dumps(
                    {
                        "error": {
                            "message": (
                                "Model not found"
                            )
                        }
                    }
                ),
                stderr="",
            )
        )
    )

    with pytest.raises(
        AgentModelUnavailableError,
    ):
        provider.complete(
            make_request()
        )


def test_subprocess_timeout_is_mapped():
    def fake_run(
        *args,
        **kwargs,
    ):
        raise subprocess.TimeoutExpired(
            cmd=["gemini"],
            timeout=10,
        )

    provider = GeminiCliProvider(
        run_fn=fake_run
    )

    with pytest.raises(
        AgentProviderTimeoutError,
    ):
        provider.complete(
            make_request(
                timeout=10
            )
        )


def test_missing_executable_is_mapped():
    def fake_run(
        *args,
        **kwargs,
    ):
        raise FileNotFoundError(
            "gemini not found"
        )

    provider = GeminiCliProvider(
        run_fn=fake_run
    )

    with pytest.raises(
        AgentProviderUnavailableError,
    ):
        provider.complete(
            make_request()
        )


def test_ineligible_tier_error_is_mapped():
    provider = GeminiCliProvider(
        run_fn=lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=(
                    "Error authenticating: "
                    "IneligibleTierError: "
                    "reasonCode: UNSUPPORTED_CLIENT. "
                    "This client is no longer supported."
                ),
            )
        )
    )

    with pytest.raises(
        AgentProviderUnavailableError,
        match="authentication",
    ):
        provider.complete(
            make_request()
        )
