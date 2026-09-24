import pytest

from factory.command_grounding import (
    CommandEvidenceStore,
    CommandGroundingError,
    is_safe_capability_probe,
)
from factory.general_agent_contracts import (
    Permission,
    ToolRequest,
)


class FakeEvidenceStore:
    def __init__(
        self,
        *,
        inspected_dirs=None,
        files=None,
    ):
        self.inspected_dirs = set(
            inspected_dirs or {"."}
        )
        self.files = set(
            files or set()
        )

    def inspected_directory(self, path):
        return path in self.inspected_dirs

    def known_file(self, path):
        return path in self.files


def _request(argv, *, cwd=None):
    return ToolRequest(
        tool_name="run_process",
        arguments={"argv": argv},
        permission=Permission.EXECUTE,
        cwd=cwd,
    )


def test_manage_py_help_is_safe_probe_when_grounded():
    evidence = FakeEvidenceStore(
        inspected_dirs={".", "okulprojesi"},
        files={"okulprojesi/manage.py"},
    )

    request = _request(
        [
            "python",
            "manage.py",
            "help",
        ],
        cwd="okulprojesi",
    )

    assert is_safe_capability_probe(
        request=request,
        evidence_store=evidence,
    )


def test_manage_py_probe_blocked_without_file_evidence():
    evidence = FakeEvidenceStore(
        inspected_dirs={".", "okulprojesi"},
        files=set(),
    )

    request = _request(
        [
            "python",
            "manage.py",
            "help",
        ],
        cwd="okulprojesi",
    )

    assert not is_safe_capability_probe(
        request=request,
        evidence_store=evidence,
    )


def test_mutation_needs_matching_command_evidence():
    evidence = FakeEvidenceStore(
        inspected_dirs={".", "okulprojesi"},
        files={"okulprojesi/manage.py"},
    )

    store = CommandEvidenceStore()

    probe = _request(
        [
            "python",
            "manage.py",
            "help",
        ],
        cwd="okulprojesi",
    )

    record = store.add_probe_result(
        request=probe,
        result={
            "returncode": 0,
            "stdout": (
                "Available subcommands:\n"
                "  check\n"
                "  startapp\n"
                "  test\n"
            ),
            "stderr": "",
        },
        source_observation_id="o1",
        evidence_store=evidence,
    )

    mutation = _request(
        [
            "python",
            "manage.py",
            "startapp",
            "users",
        ],
        cwd="okulprojesi",
    )

    matched = store.validate_mutation_command(
        request=mutation,
        command_evidence_refs=[
            record.command_evidence_id
        ],
    )

    assert (
        matched.command_evidence_id
        == record.command_evidence_id
    )


def test_flask_hallucination_not_grounded_by_manage_py_help():
    evidence = FakeEvidenceStore(
        inspected_dirs={".", "okulprojesi"},
        files={"okulprojesi/manage.py"},
    )

    store = CommandEvidenceStore()

    record = store.add_probe_result(
        request=_request(
            [
                "python",
                "manage.py",
                "help",
            ],
            cwd="okulprojesi",
        ),
        result={
            "returncode": 0,
            "stdout": "Available subcommands:\n  startapp\n",
        },
        source_observation_id="o1",
        evidence_store=evidence,
    )

    hallucinated = _request(
        [
            "python",
            "-m",
            "flask",
            "create-app",
            "users",
        ],
        cwd="okulprojesi",
    )

    with pytest.raises(
        CommandGroundingError,
        match="command prefix eslesmiyor",
    ):
        store.validate_mutation_command(
            request=hallucinated,
            command_evidence_refs=[
                record.command_evidence_id
            ],
        )


def test_unknown_subcommand_not_grounded():
    evidence = FakeEvidenceStore(
        inspected_dirs={".", "okulprojesi"},
        files={"okulprojesi/manage.py"},
    )

    store = CommandEvidenceStore()

    record = store.add_probe_result(
        request=_request(
            [
                "python",
                "manage.py",
                "help",
            ],
            cwd="okulprojesi",
        ),
        result={
            "returncode": 0,
            "stdout": "Available subcommands:\n  startapp\n",
        },
        source_observation_id="o1",
        evidence_store=evidence,
    )

    unknown = _request(
        [
            "python",
            "manage.py",
            "createapp",
            "users",
        ],
        cwd="okulprojesi",
    )

    with pytest.raises(
        CommandGroundingError,
        match="probe ciktisinda yok",
    ):
        store.validate_mutation_command(
            request=unknown,
            command_evidence_refs=[
                record.command_evidence_id
            ],
        )


def test_help_marker_must_be_last_token():
    evidence = FakeEvidenceStore(
        inspected_dirs={"."},
        files=set(),
    )

    request = _request(
        [
            "git",
            "help",
            "commit",
        ]
    )

    assert not is_safe_capability_probe(
        request=request,
        evidence_store=evidence,
    )
