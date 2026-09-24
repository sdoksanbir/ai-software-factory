import json

import pytest

from factory.capability_resolver import (
    CapabilityInventory,
    CapabilityResolution,
    CapabilityResolverError,
    build_capability_inventory,
    extract_capability_tokens,
    materialize_grounded_action,
    parse_capability_resolution,
    resolve_capability_selection,
)
from factory.command_grounding import (
    CommandEvidenceRecord,
    CommandEvidenceStore,
)
from factory.general_agent_loop import (
    EvidenceStore,
    run_agent_loop_preview,
)
from factory.general_agent_contracts import Permission
from factory.general_project_tools import (
    build_full_project_tool_registry,
)
from factory.tool_registry import ToolDefinition, ToolRegistry


class _FakeModel:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        class _Resp:
            def __init__(self, content):
                self.content = content

        return _Resp(json.dumps(self.payload))


class _SequenceModel:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if not self.payloads:
            raise AssertionError("extra model call")
        item = self.payloads.pop(0)
        if callable(item):
            item = item(kwargs)

        class _Resp:
            def __init__(self, content):
                self.content = content

        return _Resp(json.dumps(item))


def _command_store(
    *,
    prefix,
    output,
    cwd="pkg",
    runtime_ref="rt-1",
    command_evidence_id="cmd-test",
):
    store = CommandEvidenceStore()
    record = CommandEvidenceRecord(
        command_evidence_id=command_evidence_id,
        cwd=cwd,
        prefix=list(prefix),
        probe_argv=list(prefix) + ["--help"],
        output=output,
        source_observation_id="obs-1",
        runtime_ref=runtime_ref,
    )
    store._records[record.command_evidence_id] = record
    return store


def _evidence_with_file(path="pkg/tool.py"):
    store = EvidenceStore()
    store._upsert(
        "file",
        path,
        "read_file",
        "obs-file",
    )
    return store


def _registry():
    return ToolRegistry(
        [
            ToolDefinition(
                name="run_process",
                description="run",
                permission=Permission.EXECUTE,
                input_schema={
                    "type": "object",
                    "properties": {},
                },
            )
        ]
    )


def test_generic_help_builds_inventory():
    store = _command_store(
        prefix=["python", "tool.py"],
        output=(
            "Commands:\n"
            "  build\n"
            "  test\n"
            "  deploy\n"
        ),
    )
    inventory = build_capability_inventory(store)
    assert [o.token for o in inventory.options] == [
        "build",
        "test",
        "deploy",
    ]
    assert inventory.options[0].capability_ref == "cap-001"


def test_bracket_heading_not_capability():
    tokens = extract_capability_tokens(
        "Available subcommands:\n\n"
        "[auth]\n"
        "    check\n"
        "    migrate\n"
        "[django]\n"
        "    startapp\n"
    )
    assert [t for t, _ in tokens] == [
        "check",
        "migrate",
        "startapp",
    ]


def test_help_option_lines_not_capability():
    tokens = extract_capability_tokens(
        "Options:\n"
        "  -h, --help     show help\n"
        "  --version      show version\n"
        "Commands:\n"
        "  build\n"
    )
    assert [t for t, _ in tokens] == ["build"]


def test_duplicate_tokens_deduped():
    store = _command_store(
        prefix=["python", "tool.py"],
        output=(
            "Commands:\n"
            "  build\n"
            "  build\n"
            "  test\n"
            "  Build\n"
        ),
    )
    inventory = build_capability_inventory(store)
    assert [o.token for o in inventory.options] == [
        "build",
        "test",
    ]


def test_two_column_help_extracts_first_token():
    tokens = extract_capability_tokens(
        "build    Build the project\n"
        "test     Run tests\n"
    )
    assert [t for t, _ in tokens] == [
        "build",
        "test",
    ]


def test_parse_rejects_tool_and_token_fields():
    with pytest.raises(
        CapabilityResolverError,
        match="uretemez",
    ):
        parse_capability_resolution(
            {
                "decision": "select",
                "capability_ref": "cap-001",
                "arguments": [],
                "reason": "ok",
                "tool_name": "run_process",
                "cwd": "pkg",
            }
        )

    with pytest.raises(
        CapabilityResolverError,
        match="uretemez",
    ):
        parse_capability_resolution(
            {
                "decision": "select",
                "capability_ref": "cap-001",
                "arguments": [],
                "reason": "ok",
                "capability": "build",
            }
        )

    with pytest.raises(
        CapabilityResolverError,
        match="uretemez",
    ):
        parse_capability_resolution(
            {
                "decision": "select",
                "capability_ref": "cap-001",
                "arguments": [],
                "reason": "ok",
                "command_evidence_ref": "cmd-1",
            }
        )


def test_parse_accepts_capability_ref_selection():
    resolution = parse_capability_resolution(
        {
            "decision": "select",
            "capability_ref": "cap-018",
            "arguments": ["users"],
            "reason": "amaca uygun",
        }
    )
    assert isinstance(resolution, CapabilityResolution)
    assert resolution.capability_ref == "cap-018"
    assert resolution.arguments == ["users"]


def test_unknown_capability_ref_rejected():
    store = _command_store(
        prefix=["python", "tool.py"],
        output="Commands:\n  build\n",
    )
    inventory = build_capability_inventory(store)
    with pytest.raises(
        CapabilityResolverError,
        match="Bilinmeyen capability_ref",
    ):
        materialize_grounded_action(
            resolution=CapabilityResolution(
                decision="select",
                capability_ref="cap-999",
                arguments=[],
                reason="yok",
            ),
            command_evidence_store=store,
            evidence_store=_evidence_with_file(),
            tool_registry=_registry(),
            inventory=inventory,
        )


def test_materialize_from_capability_ref():
    store = _command_store(
        prefix=["python", "manage.py"],
        output=(
            "Available subcommands:\n\n"
            "[django]\n"
            "    migrate\n"
            "    startapp\n"
        ),
        cwd="okulprojesi",
    )
    inventory = build_capability_inventory(store)
    option = inventory.by_token("startapp")
    assert option is not None

    materialized = materialize_grounded_action(
        resolution=CapabilityResolution(
            decision="select",
            capability_ref=option.capability_ref,
            arguments=["users"],
            reason="eslesiyor",
        ),
        command_evidence_store=store,
        evidence_store=_evidence_with_file(
            "okulprojesi/manage.py"
        ),
        tool_registry=_registry(),
        inventory=inventory,
    )

    assert materialized is not None
    assert materialized.tool.arguments["argv"] == [
        "python",
        "manage.py",
        "startapp",
        "users",
    ]
    assert materialized.tool.cwd == "okulprojesi"
    assert materialized.runtime_ref == "rt-1"
    assert materialized.command_evidence_refs == [
        "cmd-test"
    ]
    assert len(materialized.evidence_refs) == 1


def test_materialize_binds_only_source_script_evidence():
    store = _command_store(
        prefix=["python", "tool.py"],
        output="Commands:\n  build\n",
        cwd="pkg",
    )
    evidence = EvidenceStore()
    evidence._upsert(
        "file",
        "pkg/tool.py",
        "read_file",
        "obs-1",
    )
    evidence._upsert(
        "file",
        "pkg/README.md",
        "read_file",
        "obs-2",
    )
    evidence._upsert(
        "file",
        "pkg/util.py",
        "read_file",
        "obs-3",
    )
    inventory = build_capability_inventory(store)
    option = inventory.by_token("build")
    materialized = materialize_grounded_action(
        resolution=CapabilityResolution(
            decision="select",
            capability_ref=option.capability_ref,
            arguments=[],
            reason="ok",
        ),
        command_evidence_store=store,
        evidence_store=evidence,
        tool_registry=_registry(),
        inventory=inventory,
    )
    assert len(materialized.evidence_refs) == 1
    assert materialized.evidence_refs[0].startswith(
        "file:"
    ) or "tool.py" in str(
        [
            item.path
            for item in evidence.records()
            if item.evidence_id
            in materialized.evidence_refs
        ]
    )


def test_resolve_uses_compact_inventory_prompt():
    store = _command_store(
        prefix=["python", "tool.py"],
        output="Commands:\n  build\n  check\n",
    )
    inventory = build_capability_inventory(store)
    option = inventory.by_token("build")
    client = _FakeModel(
        {
            "decision": "select",
            "capability_ref": option.capability_ref,
            "arguments": [],
            "reason": "hedef build",
        }
    )

    class _Step:
        def model_dump(self, mode="json"):
            return {
                "title": "derle",
                "description": "paketi derle",
                "permission": "mutate",
                "tool": {"tool_name": "run_process"},
            }

    resolution = resolve_capability_selection(
        goal="paketi derle",
        target_step=_Step(),
        command_evidence_store=store,
        model_client=client,
        inventory=inventory,
    )

    assert resolution.decision == "select"
    assert resolution.capability_ref == option.capability_ref
    call = client.calls[0]
    assert call["model_role"] == "capability_resolver"
    prompt = call["user_prompt"]
    assert "AVAILABLE CAPABILITIES:" in prompt
    assert "cap-001 | build" in prompt
    assert "command_evidence_store" not in prompt
    assert '"permission"' not in prompt
    assert "run_process" not in prompt
    assert "Lexical equality arama" in call[
        "system_prompt"
    ]
    assert "create-item" in call["system_prompt"]


def test_empty_inventory_fails_without_model():
    store = _command_store(
        prefix=["python", "tool.py"],
        output="usage: tool.py [-h]\n",
    )
    client = _FakeModel({"decision": "fail", "reason": "x"})
    resolution = resolve_capability_selection(
        goal="x",
        target_step={"title": "t", "description": "d"},
        command_evidence_store=store,
        model_client=client,
    )
    assert resolution.decision == "fail"
    assert client.calls == []


def _python_help_script():
    return (
        "import sys\n"
        "if __name__ == '__main__':\n"
        "    if any(a in {'--help', '-h', 'help'} "
        "for a in sys.argv[1:]):\n"
        "        print('Available commands:')\n"
        "        print('  build')\n"
        "        print('  check')\n"
        "        sys.exit(0)\n"
        "    print('unexpected')\n"
        "    sys.exit(1)\n"
    )


def _plan():
    return {
        "goal": "paketi derle",
        "summary": "kesfet sonra derle",
        "success_criteria": [],
        "constraints": [],
        "steps": [
            {
                "step_id": "s1",
                "title": "kesfet",
                "description": "projeyi incele",
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
                "title": "derle",
                "description": "paketi derle",
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


def _extract_cap_ref(prompt, token):
    block = prompt.split(
        "AVAILABLE CAPABILITIES:\n",
        1,
    )[1]
    for marker in (
        "\n\nONCEKI DENEME:",
        "\n\nCapabilityResolution JSON'unu dondur.",
    ):
        if marker in block:
            block = block.split(marker, 1)[0]
            break
    for line in block.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[1] == token:
            return parts[0]
    raise AssertionError(token)


def test_first_semantic_fail_then_select(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "tool.py").write_text(
        _python_help_script(),
        encoding="utf-8",
    )

    def grounded(kwargs):
        prompt = kwargs["user_prompt"]
        assert "ONCEKI DENEME:" in prompt
        ref = _extract_cap_ref(prompt, "build")
        return {
            "decision": "select",
            "capability_ref": ref,
            "arguments": [],
            "reason": "ikinci denemede eslesti",
        }

    client = _SequenceModel(
        [
            _plan(),
            {
                "action": "tool",
                "reason": "kanitsiz",
                "tool": {
                    "tool_name": "write_file",
                    "arguments": {
                        "path": "pkg/out.txt",
                        "content": "x",
                    },
                    "permission": "read",
                    "cwd": "pkg",
                },
                "evidence_refs": [],
                "command_evidence_refs": [],
                "answer": None,
            },
            {
                "decision": "fail",
                "reason": "eslesme yok",
            },
            grounded,
        ]
    )

    result = run_agent_loop_preview(
        prompt="paketi derle",
        model_client=client,
        tool_registry=build_full_project_tool_registry(
            str(tmp_path)
        ),
        max_read_actions=8,
        max_probe_actions=2,
        max_decisions=10,
        max_semantic_resolution_attempts=2,
    )

    assert result.stop_reason == "mutation_action_ready"
    assert result.pending_action.tool.arguments[
        "argv"
    ] == ["python", "tool.py", "build"]
    assert any(
        item.error == "CAPABILITY_SEMANTIC_FAIL"
        for item in result.observations
    )
    assert not (package / "out.txt").exists()


def test_two_semantic_fails_capability_no_match(
    tmp_path,
):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "tool.py").write_text(
        _python_help_script(),
        encoding="utf-8",
    )
    (package / "README.md").write_text(
        "docs\n",
        encoding="utf-8",
    )

    client = _SequenceModel(
        [
            _plan(),
            {
                "action": "tool",
                "reason": "kanitsiz",
                "tool": {
                    "tool_name": "write_file",
                    "arguments": {
                        "path": "pkg/out.txt",
                        "content": "x",
                    },
                    "permission": "read",
                    "cwd": "pkg",
                },
                "evidence_refs": [],
                "command_evidence_refs": [],
                "answer": None,
            },
            {
                "decision": "fail",
                "reason": "yok-1",
            },
            {
                "decision": "fail",
                "reason": "yok-2",
            },
        ]
    )

    result = run_agent_loop_preview(
        prompt="paketi derle",
        model_client=client,
        tool_registry=build_full_project_tool_registry(
            str(tmp_path)
        ),
        max_read_actions=8,
        max_probe_actions=2,
        max_decisions=10,
        max_semantic_resolution_attempts=2,
    )

    assert result.stop_reason == "capability_no_match"
    assert len(result.command_evidence) == 1
    assert result.completed is False
    semantic_fails = [
        item
        for item in result.observations
        if item.error == "CAPABILITY_SEMANTIC_FAIL"
    ]
    assert len(semantic_fails) == 2
    assert not any(
        item.success
        and item.tool_name == "read_file"
        and item.data.get("path") == "pkg/README.md"
        for item in result.observations
        if any(
            obs.tool_name == "command_probe"
            and obs.success
            for obs in result.observations
        )
    )
    # After evidence: no extra probes / README discovery.
    saw_probe = False
    post_reads = []
    post_probes = 0
    for item in result.observations:
        if (
            item.tool_name == "command_probe"
            and item.success
        ):
            if saw_probe:
                post_probes += 1
            saw_probe = True
            continue
        if (
            saw_probe
            and item.success
            and item.tool_name == "read_file"
        ):
            post_reads.append(item.data.get("path"))
    assert post_probes == 0
    assert "pkg/README.md" not in post_reads
