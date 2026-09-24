import json
from types import SimpleNamespace

import pytest

from factory.general_agent_contracts import (
    Observation,
    Permission,
)
from factory.general_agent_loop import (
    EvidenceStore,
    EvidenceValidationError,
    NextAction,
    run_agent_loop_preview,
    validate_evidence_bound_action,
)
from factory.general_project_tools import (
    build_full_project_tool_registry,
)


class SequenceModelClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def complete(self, **kwargs):
        if not self.payloads:
            raise AssertionError(
                "Beklenmeyen ekstra model cagrisi"
            )

        item = self.payloads.pop(0)

        if callable(item):
            item = item(kwargs)

        return SimpleNamespace(
            content=json.dumps(item)
        )


def _plan():
    return {
        "goal": "Bu projeye users diye bir app olustur.",
        "summary": "Once kesfet sonra olustur.",
        "success_criteria": [],
        "constraints": [],
        "steps": [
            {
                "step_id": "s1",
                "title": "Kesfet",
                "description": "Koku listele",
                "permission": "read",
                "tool": {
                    "tool_name": "list_files",
                    "arguments": {},
                    "permission": "read",
                    "cwd": None,
                },
                "depends_on": [],
                "verification_criteria": [],
                "status": "pending",
                "max_attempts": 2,
                "attempt": 0,
            },
            {
                "step_id": "s2",
                "title": "Users app olustur",
                "description": "Kanitlanan proje rootunda app olustur",
                "permission": "write",
                "tool": None,
                "depends_on": ["s1"],
                "verification_criteria": [],
                "status": "pending",
                "max_attempts": 2,
                "attempt": 0,
            },
        ],
    }


def _list_obs(
    step_id,
    base,
    entries,
):
    return Observation(
        step_id=step_id,
        tool_name="list_files",
        success=True,
        summary="ok",
        data={
            "base": base,
            "entries": entries,
            "truncated": False,
        },
        error=None,
    )


def test_parent_listing_does_not_inspect_child():
    store = EvidenceStore()

    store.add_observation(
        _list_obs(
            "o1",
            ".",
            [
                {
                    "path": "okulprojesi",
                    "name": "okulprojesi",
                    "type": "directory",
                }
            ],
        )
    )

    assert store.known_directory(
        "okulprojesi"
    )
    assert not store.inspected_directory(
        "okulprojesi"
    )


def test_execute_blocked_before_cwd_inspection(
    tmp_path,
):
    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    store = EvidenceStore()
    store.add_observation(
        _list_obs(
            "o1",
            ".",
            [
                {
                    "path": "okulprojesi",
                    "name": "okulprojesi",
                    "type": "directory",
                }
            ],
        )
    )

    action = NextAction(
        action="tool",
        reason="erken",
        tool={
            "tool_name": "run_process",
            "arguments": {
                "argv": [
                    "python",
                    "-m",
                    "django",
                    "startapp",
                    "users",
                ],
            },
            "permission": (
                registry.get(
                    "run_process"
                ).permission
            ),
            "cwd": "okulprojesi",
        },
        evidence_refs=[],
    )

    with pytest.raises(
        EvidenceValidationError,
        match="bizzat inspect edilmedi",
    ):
        validate_evidence_bound_action(
            action=action,
            evidence_store=store,
        )


def test_execute_allowed_after_inspection_and_file_evidence(
    tmp_path,
):
    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    store = EvidenceStore()

    store.add_observation(
        _list_obs(
            "o1",
            ".",
            [
                {
                    "path": "okulprojesi",
                    "name": "okulprojesi",
                    "type": "directory",
                }
            ],
        )
    )

    store.add_observation(
        _list_obs(
            "o2",
            "okulprojesi",
            [
                {
                    "path": "okulprojesi/manage.py",
                    "name": "manage.py",
                    "type": "file",
                }
            ],
        )
    )

    ref = next(
        x.evidence_id
        for x in store.records()
        if x.path == "okulprojesi/manage.py"
    )

    action = NextAction(
        action="tool",
        reason="hazir",
        tool={
            "tool_name": "run_process",
            "arguments": {
                "argv": [
                    "python",
                    "manage.py",
                    "startapp",
                    "users",
                ],
            },
            "permission": (
                registry.get(
                    "run_process"
                ).permission
            ),
            "cwd": "okulprojesi",
        },
        evidence_refs=[ref],
    )

    validate_evidence_bound_action(
        action=action,
        evidence_store=store,
    )


def test_loop_forces_discovery_before_mutation(
    tmp_path,
):
    project = tmp_path / "okulprojesi"
    project.mkdir()

    (
        project
        / "manage.py"
    ).write_text(
        "import sys\n"
        "if len(sys.argv) > 1 and sys.argv[1] == 'help':\n"
        "    print('Available subcommands:')\n"
        "    print('  check')\n"
        "    print('  startapp')\n"
        "    print('  test')\n",
        encoding="utf-8",
    )

    def _extract_ref(
        prompt,
        *,
        marker,
        key,
    ):
        assert marker in prompt

        before = prompt[
            :prompt.index(marker)
        ]

        start = before.rfind(
            key
        )

        assert start >= 0

        return before[
            start + len(key):
        ].split('"', 1)[0]

    def probe_action(
        kwargs,
    ):
        prompt = kwargs[
            "user_prompt"
        ]

        manage_ref = _extract_ref(
            prompt,
            marker='"path": "okulprojesi/manage.py"',
            key='"evidence_id": "',
        )

        return {
            "action": "execute",
            "reason": (
                "Mutation komutunu uydurmak yerine "
                "mevcut CLI yeteneklerini kesfet."
            ),
            "tool": {
                "tool_name": "run_process",
                "arguments": {
                    "argv": [
                        "python",
                        "manage.py",
                        "help",
                    ],
                    "timeout_seconds": 30,
                },
                "permission": "read",
                "cwd": "okulprojesi",
            },
            "evidence_refs": [
                manage_ref
            ],
            "command_evidence_refs": [],
            "answer": None,
        }

    def grounded_mutation(
        kwargs,
    ):
        prompt = kwargs[
            "user_prompt"
        ]

        manage_ref = _extract_ref(
            prompt,
            marker='"path": "okulprojesi/manage.py"',
            key='"evidence_id": "',
        )

        state_text = prompt.split(
            "STEP RESOLUTION STATE:\n",
            1,
        )[1].split(
            "\n\nBir sonraki tool JSON'unu dondur.",
            1,
        )[0]

        state = json.loads(
            state_text
        )

        matching = [
            item
            for item in state[
                "command_evidence_store"
            ]
            if item.get("prefix")
            == [
                "python",
                "manage.py",
            ]
        ]

        assert len(matching) == 1

        command_ref = matching[0][
            "command_evidence_id"
        ]

        return {
            "action": "execute",
            "reason": (
                "manage.py help ciktisinda startapp "
                "gercekten mevcut."
            ),
            "tool": {
                "tool_name": "run_process",
                "arguments": {
                    "argv": [
                        "python",
                        "manage.py",
                        "startapp",
                        "users",
                    ],
                    "timeout_seconds": 30,
                },
                "permission": "read",
                "cwd": "okulprojesi",
            },
            "evidence_refs": [
                manage_ref
            ],
            "command_evidence_refs": [
                command_ref
            ],
            "answer": None,
        }

    client = SequenceModelClient(
        [
            _plan(),
            {
                "action": "execute",
                "reason": "erken mutation",
                "tool": {
                    "tool_name": "run_process",
                    "arguments": {
                        "argv": [
                            "python",
                            "-m",
                            "django",
                            "startapp",
                            "users",
                        ],
                    },
                    "permission": "read",
                    "cwd": "okulprojesi",
                },
                "evidence_refs": [],
                "command_evidence_refs": [],
                "answer": None,
            },
            {
                "action": "read",
                "reason": "alt klasoru inspect et",
                "tool": {
                    "tool_name": "list_files",
                    "arguments": {
                        "path": "okulprojesi",
                    },
                    "permission": "execute",
                    "cwd": None,
                },
                "evidence_refs": [],
                "command_evidence_refs": [],
                "answer": None,
            },
            probe_action,
            grounded_mutation,
        ]
    )

    registry = (
        build_full_project_tool_registry(
            str(tmp_path)
        )
    )

    result = run_agent_loop_preview(
        prompt="users app olustur",
        model_client=client,
        tool_registry=registry,
        max_read_actions=4,
        max_probe_actions=2,
        max_decisions=8,
    )

    assert (
        result.stop_reason
        == "mutation_action_ready"
    )

    assert result.completed is False

    assert any(
        item.error
        == "EVIDENCE_VALIDATION_BLOCKED"
        for item in result.observations
    )

    assert any(
        item.success
        and item.tool_name == "list_files"
        and item.data.get("base")
        == "okulprojesi"
        for item in result.observations
    )

    assert any(
        item.success
        and item.tool_name == "command_probe"
        for item in result.observations
    )

    assert len(
        result.command_evidence
    ) == 1

    assert (
        result.command_evidence[0]
        .prefix
        == [
            "python",
            "manage.py",
        ]
    )

    assert (
        "startapp"
        in result.command_evidence[0].output
    )

    assert (
        result.pending_action
        is not None
    )

    assert (
        result.pending_action
        .tool
        .permission
        == Permission.EXECUTE
    )

    assert (
        result.pending_action
        .tool
        .cwd
        == "okulprojesi"
    )

    assert (
        result.pending_action
        .tool
        .arguments["argv"]
        == [
            "python",
            "manage.py",
            "startapp",
            "users",
        ]
    )

    assert (
        result.pending_action
        .command_evidence_refs
        == [
            result.command_evidence[0]
            .command_evidence_id
        ]
    )

    assert not (
        project
        / "users"
    ).exists()


def test_preview_does_not_execute_mutation(
    tmp_path,
):
    project = tmp_path / "okulprojesi"
    project.mkdir()

    assert not (
        project
        / "users"
    ).exists()


def _tool_action(
    *,
    tool_name,
    arguments,
    cwd,
    reason,
    evidence_refs=None,
    command_evidence_refs=None,
):
    return {
        "action": "tool",
        "reason": reason,
        "tool": {
            "tool_name": tool_name,
            "arguments": arguments,
            "permission": "read",
            "cwd": cwd,
        },
        "evidence_refs": evidence_refs or [],
        "command_evidence_refs": (
            command_evidence_refs or []
        ),
        "answer": None,
    }


def _extract_evidence_ref(prompt, path):
    marker = f'"path": "{path}"'
    assert marker in prompt
    before = prompt[:prompt.index(marker)]
    key = '"evidence_id": "'
    start = before.rfind(key)
    assert start >= 0
    return before[start + len(key):].split('"', 1)[0]


def _extract_command_ref(prompt, prefix):
    state_text = prompt.split(
        "STEP RESOLUTION STATE:\n",
        1,
    )[1].split(
        "\n\nBir sonraki tool JSON'unu dondur.",
        1,
    )[0]
    state = json.loads(state_text)
    matching = [
        item
        for item in state[
            "command_evidence_store"
        ]
        if item.get("prefix") == prefix
    ]
    assert len(matching) == 1
    return matching[0]["command_evidence_id"]


def _python_help_script():
    return (
        "import sys\n"
        "if any(a in {'--help', '-h', 'help'} for a in sys.argv[1:]):\n"
        "    print('Available commands:')\n"
        "    print('  build')\n"
        "    print('  check')\n"
        "    sys.exit(0)\n"
        "print('unexpected')\n"
        "sys.exit(1)\n"
    )


def _node_help_script():
    return (
        "const args = process.argv.slice(2);\n"
        "if (args.some((a) => ['--help', '-h', 'help'].includes(a))) {\n"
        "  console.log('Available commands:');\n"
        "  console.log('  build');\n"
        "  console.log('  check');\n"
        "  process.exit(0);\n"
        "}\n"
        "console.log('unexpected');\n"
        "process.exit(1);\n"
    )


def _python_fail_probe_script():
    return (
        "import sys\n"
        "sys.exit(2)\n"
    )


def test_repeated_ungrounded_mutation_discovers_then_fails(
    tmp_path,
):
    """Scenario C: script exists, probe fails, no inventing, controlled fail."""
    package = tmp_path / "pkg"
    package.mkdir()
    script = package / "tool.py"
    script.write_text(
        _python_fail_probe_script(),
        encoding="utf-8",
    )

    mutation = _tool_action(
        tool_name="run_process",
        arguments={
            "argv": [
                "python",
                "tool.py",
                "build",
            ],
        },
        cwd="pkg",
        reason="ayni dogrulanmamis komut",
    )

    client = SequenceModelClient(
        [
            _plan(),
            mutation,
            mutation,
            mutation,
            mutation,
        ]
    )

    result = run_agent_loop_preview(
        prompt="paketi derle",
        model_client=client,
        tool_registry=(
            build_full_project_tool_registry(
                str(tmp_path)
            )
        ),
        max_read_actions=4,
        max_probe_actions=2,
        max_decisions=8,
    )

    assert (
        result.stop_reason
        == "insufficient_evidence"
    )
    assert result.completed is False
    assert (
        result.pending_action is not None
    )
    assert (
        result.pending_action.action
        == "fail"
    )
    assert (
        result.pending_action.tool
        is None
    )
    assert result.command_evidence == []
    assert any(
        item.success
        and item.tool_name == "list_files"
        and item.data.get("base") == "pkg"
        for item in result.observations
    )
    assert any(
        item.tool_name == "command_probe"
        for item in result.observations
    )
    assert any(
        item.error
        in {
            "COMMAND_PROBE_REJECTED",
        }
        or (
            item.tool_name == "command_probe"
            and not item.success
        )
        for item in result.observations
    )
    assert any(
        item.error
        == "REPEATED_UNGROUNDED_MUTATION"
        for item in result.observations
    )
    assert (
        script.read_text(encoding="utf-8")
        == _python_fail_probe_script()
    )


def test_repeated_write_discovers_then_fails_without_writing(
    tmp_path,
):
    """Scenario A: no executable script evidence → no probe → fail."""
    widget = tmp_path / "widget"
    widget.mkdir()
    note = widget / "note.txt"
    note.write_text(
        "keep\n",
        encoding="utf-8",
    )

    mutation = _tool_action(
        tool_name="write_file",
        arguments={
            "path": "widget/out.txt",
            "content": "created",
        },
        cwd="widget",
        reason="ayni dogrulanmamis yazma",
    )

    client = SequenceModelClient(
        [
            _plan(),
            mutation,
            mutation,
            mutation,
        ]
    )

    result = run_agent_loop_preview(
        prompt="widget icine dosya yaz",
        model_client=client,
        tool_registry=(
            build_full_project_tool_registry(
                str(tmp_path)
            )
        ),
        max_read_actions=4,
        max_probe_actions=2,
        max_decisions=6,
    )

    assert (
        result.stop_reason
        == "insufficient_evidence"
    )
    assert not (
        widget / "out.txt"
    ).exists()
    assert not any(
        item.tool_name == "command_probe"
        for item in result.observations
    )
    assert any(
        item.success
        and item.tool_name == "list_files"
        and item.data.get("base") == "widget"
        for item in result.observations
    )
    assert any(
        item.success
        and item.tool_name == "read_file"
        and item.data.get("path")
        == "widget/note.txt"
        for item in result.observations
    )
    assert any(
        item.error
        == "REPEATED_UNGROUNDED_MUTATION"
        for item in result.observations
    )
    assert (
        note.read_text(encoding="utf-8")
        == "keep\n"
    )


def test_failed_capability_probe_does_not_create_command_evidence(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()
    (
        package / "tool.py"
    ).write_text(
        _python_fail_probe_script(),
        encoding="utf-8",
    )

    def mutation_with_file_ref(kwargs):
        prompt = kwargs["user_prompt"]
        evidence_ref = _extract_evidence_ref(
            prompt,
            "pkg/tool.py",
        )
        return _tool_action(
            tool_name="run_process",
            arguments={
                "argv": [
                    "python",
                    "tool.py",
                    "build",
                ],
            },
            cwd="pkg",
            reason="kanitsiz ayni komut",
            evidence_refs=[evidence_ref],
        )

    client = SequenceModelClient(
        [
            _plan(),
            _tool_action(
                tool_name="list_files",
                arguments={"path": "pkg"},
                cwd=None,
                reason="paketi listele",
            ),
            mutation_with_file_ref,
            mutation_with_file_ref,
            mutation_with_file_ref,
        ]
    )

    result = run_agent_loop_preview(
        prompt="paketi derle",
        model_client=client,
        tool_registry=(
            build_full_project_tool_registry(
                str(tmp_path)
            )
        ),
        max_read_actions=4,
        max_probe_actions=2,
        max_decisions=8,
    )

    assert (
        result.stop_reason
        == "insufficient_evidence"
    )
    assert result.command_evidence == []
    assert any(
        item.tool_name == "command_probe"
        for item in result.observations
    )
    assert any(
        item.error == "COMMAND_GROUNDING_BLOCKED"
        for item in result.observations
    )
    assert any(
        item.error
        == "REPEATED_UNGROUNDED_MUTATION"
        for item in result.observations
    )
    assert (
        result.pending_action is not None
        and result.pending_action.action
        == "fail"
    )


def test_python_script_capability_probe_then_grounded_mutation(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()
    script = package / "tool.py"
    script.write_text(
        _python_help_script(),
        encoding="utf-8",
    )

    wrong_write = _tool_action(
        tool_name="write_file",
        arguments={
            "path": "pkg/out.txt",
            "content": "created",
        },
        cwd="pkg",
        reason="kanitsiz write",
    )

    def grounded_mutation(kwargs):
        prompt = kwargs["user_prompt"]
        evidence_ref = _extract_evidence_ref(
            prompt,
            "pkg/tool.py",
        )
        command_ref = _extract_command_ref(
            prompt,
            ["python", "tool.py"],
        )
        return _tool_action(
            tool_name="run_process",
            arguments={
                "argv": [
                    "python",
                    "tool.py",
                    "build",
                ],
                "timeout_seconds": 30,
            },
            cwd="pkg",
            reason="probe ciktisinda build var",
            evidence_refs=[evidence_ref],
            command_evidence_refs=[command_ref],
        )

    client = SequenceModelClient(
        [
            _plan(),
            wrong_write,
            wrong_write,
            grounded_mutation,
        ]
    )

    result = run_agent_loop_preview(
        prompt="paketi derle",
        model_client=client,
        tool_registry=(
            build_full_project_tool_registry(
                str(tmp_path)
            )
        ),
        max_read_actions=4,
        max_probe_actions=2,
        max_decisions=8,
    )

    assert (
        result.stop_reason
        == "mutation_action_ready"
    )
    assert result.completed is False
    assert len(result.command_evidence) == 1
    assert (
        result.command_evidence[0].prefix
        == ["python", "tool.py"]
    )
    assert (
        "build"
        in result.command_evidence[0].output
    )
    assert any(
        item.success
        and item.tool_name == "command_probe"
        for item in result.observations
    )
    assert (
        result.pending_action is not None
    )
    assert (
        result.pending_action.tool.arguments[
            "argv"
        ]
        == ["python", "tool.py", "build"]
    )
    assert not (
        package / "out.txt"
    ).exists()
    # Logical argv preserved; physical path only in runtime binding.
    assert all(
        not str(item).lower().endswith(
            "python.exe"
        )
        for item in result.command_evidence[0].prefix
    )


def test_node_script_capability_probe_then_grounded_mutation(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()
    script = package / "run.mjs"
    script.write_text(
        _node_help_script(),
        encoding="utf-8",
    )

    wrong = _tool_action(
        tool_name="run_process",
        arguments={
            "argv": [
                "node",
                "run.mjs",
                "build",
            ],
        },
        cwd="pkg",
        reason="kanitsiz mutation",
    )

    def grounded_mutation(kwargs):
        prompt = kwargs["user_prompt"]
        evidence_ref = _extract_evidence_ref(
            prompt,
            "pkg/run.mjs",
        )
        command_ref = _extract_command_ref(
            prompt,
            ["node", "run.mjs"],
        )
        return _tool_action(
            tool_name="run_process",
            arguments={
                "argv": [
                    "node",
                    "run.mjs",
                    "build",
                ],
                "timeout_seconds": 30,
            },
            cwd="pkg",
            reason="probe ciktisinda build var",
            evidence_refs=[evidence_ref],
            command_evidence_refs=[command_ref],
        )

    client = SequenceModelClient(
        [
            _plan(),
            wrong,
            wrong,
            grounded_mutation,
        ]
    )

    result = run_agent_loop_preview(
        prompt="paketi derle",
        model_client=client,
        tool_registry=(
            build_full_project_tool_registry(
                str(tmp_path)
            )
        ),
        max_read_actions=4,
        max_probe_actions=2,
        max_decisions=8,
    )

    assert (
        result.stop_reason
        == "mutation_action_ready"
    )
    assert len(result.command_evidence) == 1
    assert (
        result.command_evidence[0].prefix
        == ["node", "run.mjs"]
    )
    assert (
        result.pending_action.tool.arguments[
            "argv"
        ]
        == ["node", "run.mjs", "build"]
    )
    assert script.read_text(encoding="utf-8") == (
        _node_help_script()
    )


def _empty_tool_action():
    return {
        "action": "tool",
        "reason": "gecersiz tool",
        "tool": {
            "tool_name": "",
            "arguments": {},
            "permission": "read",
            "cwd": None,
        },
        "evidence_refs": [],
        "command_evidence_refs": [],
        "answer": None,
    }


def test_invalid_empty_tool_name_recovers_via_discovery(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()
    script = package / "tool.py"
    script.write_text(
        _python_help_script(),
        encoding="utf-8",
    )

    def grounded_mutation(kwargs):
        prompt = kwargs["user_prompt"]
        evidence_ref = _extract_evidence_ref(
            prompt,
            "pkg/tool.py",
        )
        command_ref = _extract_command_ref(
            prompt,
            ["python", "tool.py"],
        )
        return _tool_action(
            tool_name="run_process",
            arguments={
                "argv": [
                    "python",
                    "tool.py",
                    "build",
                ],
                "timeout_seconds": 30,
            },
            cwd="pkg",
            reason="probe ciktisinda build var",
            evidence_refs=[evidence_ref],
            command_evidence_refs=[command_ref],
        )

    client = SequenceModelClient(
        [
            _plan(),
            _empty_tool_action(),
            _empty_tool_action(),
            grounded_mutation,
        ]
    )

    result = run_agent_loop_preview(
        prompt="paketi derle",
        model_client=client,
        tool_registry=(
            build_full_project_tool_registry(
                str(tmp_path)
            )
        ),
        max_read_actions=4,
        max_probe_actions=2,
        max_decisions=8,
    )

    assert (
        result.stop_reason
        == "mutation_action_ready"
    )
    assert any(
        item.error == "MODEL_ACTION_INVALID"
        and item.data.get("stage")
        == "deferred_step"
        for item in result.observations
    )
    assert any(
        item.success
        and item.tool_name == "command_probe"
        for item in result.observations
    )
    assert len(result.command_evidence) == 1
    assert (
        result.command_evidence[0].prefix
        == ["python", "tool.py"]
    )
    assert (
        result.pending_action is not None
    )
    assert (
        result.pending_action.tool.arguments[
            "argv"
        ]
        == ["python", "tool.py", "build"]
    )
    assert not (
        package / "out.txt"
    ).exists()
    assert (
        script.read_text(encoding="utf-8")
        == _python_help_script()
    )


def test_repeated_invalid_model_action_stops_without_exception(
    tmp_path,
):
    widget = tmp_path / "widget"
    widget.mkdir()
    note = widget / "note.txt"
    note.write_text(
        "keep\n",
        encoding="utf-8",
    )

    client = SequenceModelClient(
        [
            _plan(),
            _empty_tool_action(),
            _empty_tool_action(),
            _empty_tool_action(),
            _empty_tool_action(),
            _empty_tool_action(),
        ]
    )

    result = run_agent_loop_preview(
        prompt="widget incele",
        model_client=client,
        tool_registry=(
            build_full_project_tool_registry(
                str(tmp_path)
            )
        ),
        max_read_actions=4,
        max_probe_actions=2,
        max_decisions=8,
    )

    assert result.stop_reason in {
        "invalid_model_action",
        "max_decisions",
    }
    assert result.completed is False
    assert result.command_evidence == []
    assert any(
        item.error == "MODEL_ACTION_INVALID"
        for item in result.observations
    )
    assert not (
        widget / "out.txt"
    ).exists()
    assert (
        note.read_text(encoding="utf-8")
        == "keep\n"
    )


def test_max_probe_actions_returns_runtime_evidence(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()
    script = package / "tool.py"
    script.write_text(
        _python_help_script(),
        encoding="utf-8",
    )

    def probe_action(kwargs):
        prompt = kwargs["user_prompt"]
        evidence_ref = _extract_evidence_ref(
            prompt,
            "pkg/tool.py",
        )
        return _tool_action(
            tool_name="run_process",
            arguments={
                "argv": [
                    "python",
                    "tool.py",
                    "--help",
                ],
                "timeout_seconds": 30,
            },
            cwd="pkg",
            reason="capability probe",
            evidence_refs=[evidence_ref],
        )

    client = SequenceModelClient(
        [
            _plan(),
            _tool_action(
                tool_name="list_files",
                arguments={"path": "pkg"},
                cwd=None,
                reason="paketi listele",
            ),
            probe_action,
            probe_action,
        ]
    )

    result = run_agent_loop_preview(
        prompt="paketi derle",
        model_client=client,
        tool_registry=(
            build_full_project_tool_registry(
                str(tmp_path)
            )
        ),
        max_read_actions=4,
        max_probe_actions=1,
        max_decisions=8,
    )

    assert (
        result.stop_reason
        == "max_probe_actions"
    )
    assert result.completed is False
    assert isinstance(
        result.runtime_evidence,
        list,
    )
    assert (
        result.pending_action is not None
    )
    assert (
        result.pending_action.tool.tool_name
        == "run_process"
    )
    assert (
        result.pending_action.tool.arguments[
            "argv"
        ]
        == ["python", "tool.py", "--help"]
    )
    assert (
        script.read_text(encoding="utf-8")
        == _python_help_script()
    )
    assert not (
        package / "out.txt"
    ).exists()
