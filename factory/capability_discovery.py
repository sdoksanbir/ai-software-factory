from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any

from factory.command_grounding import (
    CommandGroundingError,
    build_safe_capability_probe_request,
    logical_runtime_for_script_path,
)
from factory.general_agent_contracts import ToolRequest

_LOGICAL_ARGV0_BY_FAMILY = {
    "python": "python",
    "node": "node",
}


@dataclass(frozen=True)
class CapabilityCandidate:
    candidate_id: str
    source_evidence_ref: str
    script_path: str
    cwd: str
    runtime_family: str
    logical_prefix: list[str]
    signals: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_evidence_ref": self.source_evidence_ref,
            "script_path": self.script_path,
            "cwd": self.cwd,
            "runtime_family": self.runtime_family,
            "logical_prefix": list(self.logical_prefix),
            "signals": list(self.signals),
        }


def _norm(raw: str | None) -> str:
    value = str(raw or ".").strip().replace("\\", "/")
    if value in {"", "."}:
        return "."

    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise CommandGroundingError(
            f"Guvenli olmayan proje yolu: {value}"
        )
    return str(path)


def _candidate_id(
    *,
    script_path: str,
    runtime_family: str,
    logical_prefix: list[str],
) -> str:
    payload = json.dumps(
        {
            "script_path": script_path,
            "runtime_family": runtime_family,
            "logical_prefix": logical_prefix,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(
        payload.encode("utf-8")
    ).hexdigest()[:12]
    return f"cap-{digest}"


def detect_python_entry_signals(
    source: str,
) -> tuple[str, ...]:
    signals: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()

    has_main_guard = False
    uses_sys_argv = False
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(
                    node.module.split(".", 1)[0]
                )
        elif isinstance(node, ast.Compare):
            if _is_name_main_compare(node):
                has_main_guard = True
        elif isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "sys"
                and node.attr == "argv"
            ):
                uses_sys_argv = True

    if has_main_guard:
        signals.append("python_main_guard")
    if uses_sys_argv:
        signals.append("sys_argv")
    for name in (
        "argparse",
        "click",
        "typer",
        "fire",
    ):
        if name in imports:
            signals.append(f"import:{name}")

    return tuple(dict.fromkeys(signals))


def _is_name_main_compare(node: ast.Compare) -> bool:
    if not isinstance(node.left, ast.Name):
        return False
    if node.left.id != "__name__":
        return False
    if len(node.ops) != 1 or not isinstance(
        node.ops[0],
        ast.Eq,
    ):
        return False
    if len(node.comparators) != 1:
        return False
    comparator = node.comparators[0]
    return (
        isinstance(comparator, ast.Constant)
        and comparator.value == "__main__"
    )


def detect_node_entry_signals(
    source: str,
) -> tuple[str, ...]:
    signals: list[str] = []
    head = source.lstrip()[:120]
    if head.startswith("#!") and "node" in head.casefold():
        signals.append("node_shebang")

    if re.search(
        r"\bprocess\.argv\b",
        source,
    ):
        signals.append("process_argv")

    for name in (
        "commander",
        "yargs",
    ):
        pattern = (
            rf"""(?:require\(['"]{name}['"]\)"""
            rf"""|from\s+['"]{name}['"])"""
        )
        if re.search(pattern, source):
            signals.append(f"import:{name}")

    return tuple(dict.fromkeys(signals))


def detect_entry_signals(
    *,
    script_path: str,
    source: str,
) -> tuple[str, ...]:
    family = logical_runtime_for_script_path(
        script_path
    )
    if family == "python":
        return detect_python_entry_signals(source)
    if family == "node":
        return detect_node_entry_signals(source)
    return ()


def detect_package_json_bin_targets(
    source: str,
    *,
    package_dir: str,
) -> tuple[str, ...]:
    try:
        payload = json.loads(source)
    except json.JSONDecodeError:
        return ()

    if not isinstance(payload, dict):
        return ()

    targets: list[str] = []
    raw_bin = payload.get("bin")
    if isinstance(raw_bin, str) and raw_bin.strip():
        targets.append(raw_bin.strip())
    elif isinstance(raw_bin, dict):
        for value in raw_bin.values():
            if isinstance(value, str) and value.strip():
                targets.append(value.strip())

    scripts = payload.get("scripts")
    if isinstance(scripts, dict):
        # scripts are npm command strings, not file candidates
        pass

    normalized: list[str] = []
    base = _norm(package_dir)
    for target in targets:
        rel = target.replace("\\", "/").lstrip("./")
        if base == ".":
            normalized.append(_norm(rel))
        else:
            normalized.append(_norm(f"{base}/{rel}"))

    return tuple(dict.fromkeys(normalized))


class CapabilityCandidateStore:
    """File evidence'dan ayri entry-point / capability adaylari."""

    def __init__(self) -> None:
        self._candidates: dict[
            str,
            CapabilityCandidate,
        ] = {}
        self._assessed_paths: set[str] = set()
        self._rejected_paths: set[str] = set()
        self._bin_targets: set[str] = set()

    def assessed(self, script_path: str) -> bool:
        path = _norm(script_path)
        return (
            path in self._assessed_paths
            or path in self._rejected_paths
            or path in self._candidates
        )

    def is_candidate(self, script_path: str) -> bool:
        path = _norm(script_path)
        return any(
            item.script_path == path
            for item in self._candidates.values()
        )

    def records(self) -> list[CapabilityCandidate]:
        return sorted(
            self._candidates.values(),
            key=lambda item: (
                item.script_path.count("/"),
                item.script_path.casefold(),
            ),
        )

    def to_model_payload(self) -> list[dict[str, Any]]:
        return [
            item.to_dict()
            for item in self.records()
        ]

    def note_package_json(
        self,
        *,
        path: str,
        content: str,
    ) -> None:
        package_dir = str(
            PurePosixPath(_norm(path)).parent
        )
        if package_dir in {"", "."}:
            package_dir = "."
        for target in detect_package_json_bin_targets(
            content,
            package_dir=package_dir,
        ):
            self._bin_targets.add(target)

    def assess_file(
        self,
        *,
        script_path: str,
        content: str,
        source_evidence_ref: str,
    ) -> CapabilityCandidate | None:
        path = _norm(script_path)
        if path in self._candidates:
            return self._candidates[path]
        if path in self._rejected_paths:
            return None

        family = logical_runtime_for_script_path(path)
        if family is None:
            self._assessed_paths.add(path)
            self._rejected_paths.add(path)
            return None

        signals = list(
            detect_entry_signals(
                script_path=path,
                source=content,
            )
        )

        if path in self._bin_targets:
            signals.append("package_json_bin")

        unique_signals = tuple(
            dict.fromkeys(signals)
        )
        self._assessed_paths.add(path)

        if not unique_signals:
            self._rejected_paths.add(path)
            return None

        parent = str(PurePosixPath(path).parent)
        cwd = "." if parent in {"", "."} else parent
        relative = PurePosixPath(path).name
        argv0 = _LOGICAL_ARGV0_BY_FAMILY[family]
        prefix = [argv0, relative]
        candidate = CapabilityCandidate(
            candidate_id=_candidate_id(
                script_path=path,
                runtime_family=family,
                logical_prefix=prefix,
            ),
            source_evidence_ref=source_evidence_ref,
            script_path=path,
            cwd=cwd,
            runtime_family=family,
            logical_prefix=prefix,
            signals=unique_signals,
        )
        self._candidates[path] = candidate
        return candidate

    def next_probe_request(
        self,
        *,
        evidence_store: Any,
        runtime_evidence_store: Any,
        command_evidence_store: Any,
        permission: Any,
        attempted_probes: set[str],
        fingerprint_fn,
    ) -> tuple[
        CapabilityCandidate,
        ToolRequest,
    ] | None:
        # Basarili CommandEvidence varken yeni auto-probe yok.
        if command_evidence_store.records():
            return None

        for candidate in self.records():
            if not runtime_evidence_store.candidates_for(
                candidate.runtime_family
            ):
                continue

            if command_evidence_store.has_prefix(
                cwd=candidate.cwd,
                prefix=candidate.logical_prefix,
            ):
                continue

            try:
                request = build_safe_capability_probe_request(
                    script_path=candidate.script_path,
                    evidence_store=evidence_store,
                    permission=permission,
                )
            except CommandGroundingError:
                continue

            fingerprint = fingerprint_fn(request)
            if fingerprint in attempted_probes:
                continue

            return candidate, request

        return None
