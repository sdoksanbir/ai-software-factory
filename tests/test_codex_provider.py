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
from factory.agents.providers.codex import (
    CodexCliProvider,
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
        "metadata": {},
    }

    values.update(
        overrides
    )

    return AgentRequest(
        **values
    )


def _jsonl(
    *events,
):
    return "\n".join(
        json.dumps(event)
        for event in events
    )


def _success_stdout():
    return _jsonl(
        {
            "type": "thread.started",
            "thread_id": "thread-1",
        },
        {
            "type": "turn.started",
        },
        {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "agent_message",
                "text": "CODEX_OK",
            },
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 14896,
                "cached_input_tokens": 9984,
                "cache_write_input_tokens": 0,
                "output_tokens": 7,
                "reasoning_output_tokens": 0,
            },
        },
    )


def test_descriptor_declares_codex_cli_features():
    provider = (
        CodexCliProvider()
    )

    descriptor = (
        provider.describe()
    )

    assert (
        descriptor.name
        == "codex_cli"
    )

    assert (
        descriptor.transport
        == ProviderTransport.CLI
    )

    assert (
        descriptor.executable
        == "codex"
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

    assert (
        descriptor.metadata[
            "sandbox"
        ]
        == "read-only"
    )


def test_provider_executes_jsonl_ephemeral_read_only():
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
            stdout=_success_stdout(),
            stderr="",
        )

    provider = CodexCliProvider(
        run_fn=fake_run,
    )

    result = provider.complete(
        _request()
    )

    assert (
        result.content
        == "CODEX_OK"
    )

    assert (
        result.provider
        == "codex_cli"
    )

    assert (
        result.metadata[
            "thread_id"
        ]
        == "thread-1"
    )

    assert (
        result.metadata[
            "input_tokens"
        ]
        == 14896
    )

    assert (
        result.metadata[
            "cached_input_tokens"
        ]
        == 9984
    )

    command, kwargs = calls[0]

    assert command[:2] == [
        "codex",
        "exec",
    ]

    assert "--json" in command
    assert "--ephemeral" in command

    assert (
        command[
            command.index(
                "--sandbox"
            )
            + 1
        ]
        == "read-only"
    )

    prompt = command[-1]

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
        == 60
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
            stdout=_success_stdout(),
            stderr="",
        )

    provider = CodexCliProvider(
        run_fn=fake_run,
    )

    result = provider.complete(
        _request(
            model_name="gpt-5.4",
        )
    )

    command = captured[
        "command"
    ]

    assert (
        command[
            command.index(
                "--model"
            )
            + 1
        ]
        == "gpt-5.4"
    )

    assert (
        result.model
        == "gpt-5.4"
    )


def test_provider_passes_worktree_directory():
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
            stdout=_success_stdout(),
            stderr="",
        )

    provider = CodexCliProvider(
        run_fn=fake_run,
    )

    provider.complete(
        _request(
            metadata={
                "worktree_path": (
                    r"C:\AI-Worktrees"
                    r"\task-1234"
                ),
            },
        )
    )

    command = captured[
        "command"
    ]

    assert (
        command[
            command.index(
                "--cd"
            )
            + 1
        ]
        == (
            r"C:\AI-Worktrees"
            r"\task-1234"
        )
    )


def test_working_directory_takes_priority():
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
            stdout=_success_stdout(),
            stderr="",
        )

    provider = CodexCliProvider(
        run_fn=fake_run,
    )

    provider.complete(
        _request(
            metadata={
                "working_directory": (
                    r"C:\preferred"
                ),
                "worktree_path": (
                    r"C:\fallback"
                ),
            },
        )
    )

    command = captured[
        "command"
    ]

    assert (
        command[
            command.index(
                "--cd"
            )
            + 1
        ]
        == r"C:\preferred"
    )


def test_workspace_write_can_be_configured():
    provider = CodexCliProvider(
        sandbox="workspace-write",
        run_fn=lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=0,
                stdout=_success_stdout(),
                stderr="",
            )
        ),
    )

    result = provider.complete(
        _request()
    )

    assert (
        result.metadata[
            "sandbox"
        ]
        == "workspace-write"
    )


def test_missing_executable_maps_to_unavailable():
    def fake_run(
        *args,
        **kwargs,
    ):
        raise FileNotFoundError(
            "codex"
        )

    provider = CodexCliProvider(
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
            cmd="codex",
            timeout=60,
        )

    provider = CodexCliProvider(
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
            "authentication required",
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
            "request timed out",
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

    provider = CodexCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        error_type
    ):
        provider.complete(
            _request()
        )


def test_unknown_nonzero_exit_is_not_fallbackable():
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

    provider = CodexCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        RuntimeError,
        match="Codex CLI failed",
    ):
        provider.complete(
            _request()
        )


def test_invalid_jsonl_is_rejected():
    def fake_run(
        *args,
        **kwargs,
    ):
        return SimpleNamespace(
            returncode=0,
            stdout="not-json",
            stderr="",
        )

    provider = CodexCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        RuntimeError,
        match="invalid JSONL",
    ):
        provider.complete(
            _request()
        )


def test_error_event_is_mapped():
    stdout = _jsonl(
        {
            "type": "thread.started",
            "thread_id": "thread-error",
        },
        {
            "type": "turn.failed",
            "error": {
                "message": (
                    "429 rate limit exceeded"
                ),
            },
        },
    )

    def fake_run(
        *args,
        **kwargs,
    ):
        return SimpleNamespace(
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    provider = CodexCliProvider(
        run_fn=fake_run,
    )

    with pytest.raises(
        AgentProviderRateLimitError,
    ):
        provider.complete(
            _request()
        )


def test_last_agent_message_is_final_result():
    stdout = _jsonl(
        {
            "type": "thread.started",
            "thread_id": "thread-2",
        },
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": "first",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": "final",
            },
        },
        {
            "type": "turn.completed",
            "usage": {},
        },
    )

    provider = CodexCliProvider(
        run_fn=lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=0,
                stdout=stdout,
                stderr="",
            )
        ),
    )

    result = provider.complete(
        _request()
    )

    assert result.content == "final"


def test_success_requires_agent_message():
    stdout = _jsonl(
        {
            "type": "thread.started",
            "thread_id": "thread-empty",
        },
        {
            "type": "turn.completed",
            "usage": {},
        },
    )

    provider = CodexCliProvider(
        run_fn=lambda *args, **kwargs: (
            SimpleNamespace(
                returncode=0,
                stdout=stdout,
                stderr="",
            )
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="without an agent_message",
    ):
        provider.complete(
            _request()
        )


def test_invalid_configuration_is_rejected():
    with pytest.raises(
        ValueError,
        match="default_timeout",
    ):
        CodexCliProvider(
            default_timeout=0
        )

    with pytest.raises(
        ValueError,
        match="Unsupported Codex sandbox",
    ):
        CodexCliProvider(
            sandbox="invalid"
        )


def test_provider_retries_official_windows_install_path(
    monkeypatch,
):
    calls = []

    fallback_path = (
        r"C:\Users\test\AppData\Local"
        r"\Programs\OpenAI\Codex"
        r"\bin\codex.exe"
    )

    def fake_run(
        command,
        **kwargs,
    ):
        calls.append(
            list(command)
        )

        if (
            command[0]
            == "codex"
        ):
            raise FileNotFoundError(
                "codex"
            )

        return SimpleNamespace(
            returncode=0,
            stdout=_success_stdout(),
            stderr="",
        )

    provider = CodexCliProvider(
        run_fn=fake_run,
    )

    monkeypatch.setattr(
        provider,
        "_installed_executable_fallback",
        lambda: fallback_path,
    )

    result = provider.complete(
        _request()
    )

    assert (
        result.content
        == "CODEX_OK"
    )

    assert len(calls) == 2

    assert (
        calls[0][0]
        == "codex"
    )

    assert (
        calls[1][0]
        == fallback_path
    )
