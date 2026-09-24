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

        command_ref = _extract_ref(
            prompt,
            marker='"prefix": [\n      "python",\n      "manage.py"\n    ]',
            key='"command_evidence_id": "',
        )

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
