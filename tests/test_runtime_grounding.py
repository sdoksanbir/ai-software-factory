from pathlib import Path
import sys

from factory.runtime_grounding import (
    RuntimeEvidenceStore,
    discover_runtime_candidates,
)


def _project_python_path(
    root: Path,
) -> Path:
    if sys.platform.startswith(
        "win"
    ):
        return (
            root
            / ".venv"
            / "Scripts"
            / "python.exe"
        )

    return (
        root
        / ".venv"
        / "bin"
        / "python"
    )


def test_discovers_current_python_runtime(
    tmp_path,
):
    candidates = (
        discover_runtime_candidates(
            tmp_path
        )
    )

    python_candidates = [
        item
        for item in candidates
        if item.family
        == "python"
    ]

    assert python_candidates

    assert any(
        Path(
            item.executable
        ).resolve()
        == Path(
            sys.executable
        ).resolve()
        for item in python_candidates
    )


def test_project_local_runtime_is_preferred(
    tmp_path,
):
    executable = (
        _project_python_path(
            tmp_path
        )
    )

    executable.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    executable.write_bytes(
        b"placeholder"
    )

    candidates = (
        discover_runtime_candidates(
            tmp_path
        )
    )

    python_candidates = [
        item
        for item in candidates
        if item.family
        == "python"
    ]

    assert python_candidates

    assert (
        Path(
            python_candidates[0]
            .executable
        ).resolve()
        == executable.resolve()
    )

    assert (
        python_candidates[0]
        .project_local
        is True
    )


def test_discovers_nested_project_venv(
    tmp_path,
):
    nested = (
        tmp_path
        / "okulprojesi"
    )

    nested.mkdir()

    if sys.platform.startswith(
        "win"
    ):
        executable = (
            nested
            / "venv"
            / "Scripts"
            / "python.exe"
        )
    else:
        executable = (
            nested
            / "venv"
            / "bin"
            / "python"
        )

    executable.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    executable.write_bytes(
        b"placeholder"
    )

    store = (
        RuntimeEvidenceStore
        .discover(
            tmp_path
        )
    )

    assert any(
        Path(
            item.executable
        ).resolve()
        == executable.resolve()
        and item.project_local
        for item in store.records()
    )


def test_runtime_ids_are_stable(
    tmp_path,
):
    first = (
        RuntimeEvidenceStore
        .discover(
            tmp_path
        )
    )

    second = (
        RuntimeEvidenceStore
        .discover(
            tmp_path
        )
    )

    assert [
        item.runtime_id
        for item in first.records()
    ] == [
        item.runtime_id
        for item in second.records()
    ]


def test_store_can_validate_known_executable(
    tmp_path,
):
    store = (
        RuntimeEvidenceStore
        .discover(
            tmp_path
        )
    )

    assert store.executable_known(
        sys.executable
    )
