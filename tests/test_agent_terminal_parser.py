"""Fail-closed Agent Terminal parser tests."""

from __future__ import annotations

import pytest

from factory.agent_terminal_models import (
    CompleteAction,
    FailAction,
    RunCommandAction,
)
from factory.agent_terminal_parser import (
    AgentTerminalParseError,
    parse_terminal_action,
)
from factory.task_command_models import (
    MAX_ARG_COUNT,
    MAX_ARG_LENGTH,
)


def test_valid_run_command():
    action = parse_terminal_action(
        '{"action_type":"run_command",'
        '"argv":["python","--version"],'
        '"cwd":null,'
        '"reason":"inspect"}'
    )
    assert isinstance(action, RunCommandAction)
    assert action.argv == ("python", "--version")
    assert action.cwd is None
    assert action.reason == "inspect"


def test_valid_complete():
    action = parse_terminal_action(
        '{"action_type":"complete",'
        '"reason":"done",'
        '"summary":"ok"}'
    )
    assert isinstance(action, CompleteAction)
    assert action.summary == "ok"


def test_valid_fail():
    action = parse_terminal_action(
        '{"action_type":"fail","reason":"blocked"}'
    )
    assert isinstance(action, FailAction)
    assert action.reason == "blocked"


def test_fenced_json_rejected():
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            "```json\n"
            '{"action_type":"fail","reason":"x"}\n'
            "```"
        )


def test_prose_rejected():
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            'Here you go:\n'
            '{"action_type":"fail","reason":"x"}'
        )


def test_unknown_action_rejected():
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            '{"action_type":"shell","reason":"x"}'
        )


def test_extra_field_rejected():
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            '{"action_type":"fail",'
            '"reason":"x","extra":1}'
        )


@pytest.mark.parametrize(
    "field",
    [
        "allow_mutating",
        "network_policy",
        "permission_level",
        "env",
        "secret_env_keys",
        "timeout_seconds",
        "shell",
        "command",
    ],
)
def test_forbidden_authority_fields_rejected(field):
    payload = (
        '{"action_type":"run_command",'
        '"argv":["python","--version"],'
        '"cwd":null,'
        '"reason":"x",'
        f'"{field}":true}}'
    )
    with pytest.raises(AgentTerminalParseError) as exc:
        parse_terminal_action(payload)
    assert field in str(exc.value)


def test_argv_string_rejected():
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            '{"action_type":"run_command",'
            '"argv":"python --version",'
            '"reason":"x"}'
        )


def test_argv_empty_rejected():
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            '{"action_type":"run_command",'
            '"argv":[],'
            '"reason":"x"}'
        )


def test_non_string_argv_rejected():
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            '{"action_type":"run_command",'
            '"argv":["python",1],'
            '"reason":"x"}'
        )


def test_too_many_argv_rejected():
    argv = ",".join(
        f'"a{i}"' for i in range(MAX_ARG_COUNT + 1)
    )
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            '{"action_type":"run_command",'
            f'"argv":[{argv}],'
            '"reason":"x"}'
        )


def test_overlong_arg_rejected():
    long_arg = "x" * (MAX_ARG_LENGTH + 1)
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            '{"action_type":"run_command",'
            f'"argv":["{long_arg}"],'
            '"reason":"x"}'
        )


def test_absolute_cwd_rejected():
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            '{"action_type":"run_command",'
            '"argv":["python"],'
            '"cwd":"/etc",'
            '"reason":"x"}'
        )


def test_parent_cwd_rejected():
    with pytest.raises(AgentTerminalParseError):
        parse_terminal_action(
            '{"action_type":"run_command",'
            '"argv":["python"],'
            '"cwd":"../outside",'
            '"reason":"x"}'
        )
