from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any

from factory.general_agent_contracts import ToolRequest


class CommandGroundingError(RuntimeError):
    pass


_SAFE_PROBE_MARKERS = {
    "help",
    "--help",
    "-h",
    "version",
    "--version",
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


def _join(base: str, child: str) -> str:
    base = _norm(base)
    child = _norm(child)

    if child == ".":
        return base
    if base == ".":
        return child
    return _norm(f"{base}/{child}")


def _argv(request: ToolRequest) -> list[str]:
    raw = request.arguments.get("argv")
    if (
        not isinstance(raw, list)
        or not raw
        or not all(
            isinstance(item, str) and item.strip()
            for item in raw
        )
    ):
        raise CommandGroundingError(
            "run_process argv dolu string listesi olmali."
        )
    return [item.strip() for item in raw]


def _probe_marker_index(argv: list[str]) -> int | None:
    for index, token in enumerate(argv):
        if token.casefold() in _SAFE_PROBE_MARKERS:
            return index
    return None


def _command_prefix(argv: list[str]) -> list[str]:
    index = _probe_marker_index(argv)
    if index is None:
        raise CommandGroundingError(
            "Capability probe help/version marker icermiyor."
        )

    if index != len(argv) - 1:
        raise CommandGroundingError(
            "Capability probe marker son argv token'i olmali."
        )

    prefix = argv[:index]
    if not prefix:
        raise CommandGroundingError(
            "Capability probe command prefix bos olamaz."
        )
    return prefix


def _project_script_paths(
    *,
    prefix: list[str],
    cwd: str,
) -> list[str]:
    result: list[str] = []

    for token in prefix[1:]:
        value = token.replace("\\", "/")
        if value.startswith("-"):
            continue

        suffix = PurePosixPath(value).suffix.casefold()
        if suffix in {
            ".py",
            ".js",
            ".mjs",
            ".cjs",
            ".ts",
            ".sh",
            ".ps1",
            ".cmd",
            ".bat",
        }:
            result.append(_join(cwd, value))

    return result


def validate_safe_capability_probe(
    *,
    request: ToolRequest,
    evidence_store: Any,
) -> list[str]:
    if request.tool_name != "run_process":
        raise CommandGroundingError(
            "Capability probe yalniz run_process olabilir."
        )

    argv = _argv(request)
    prefix = _command_prefix(argv)
    cwd = _norm(request.cwd or ".")

    if not evidence_store.inspected_directory(cwd):
        raise CommandGroundingError(
            "Capability probe cwd bizzat inspect edilmis olmali: "
            f"{cwd}"
        )

    for script_path in _project_script_paths(
        prefix=prefix,
        cwd=cwd,
    ):
        if not evidence_store.known_file(script_path):
            raise CommandGroundingError(
                "Capability probe proje scripti EvidenceStore'da yok: "
                f"{script_path}"
            )

    return prefix


def is_safe_capability_probe(
    *,
    request: ToolRequest,
    evidence_store: Any,
) -> bool:
    try:
        validate_safe_capability_probe(
            request=request,
            evidence_store=evidence_store,
        )
        return True
    except CommandGroundingError:
        return False


def _result_text(result: Any) -> str:
    if isinstance(result, dict):
        chunks: list[str] = []
        for key in (
            "stdout",
            "stderr",
            "output",
            "message",
        ):
            value = result.get(key)
            if value:
                chunks.append(str(value))
        return "\n".join(chunks)

    return str(result or "")


def _result_exit_code(result: Any) -> int | None:
    if not isinstance(result, dict):
        return None

    for key in (
        "returncode",
        "return_code",
        "exit_code",
        "code",
    ):
        value = result.get(key)
        if isinstance(value, int):
            return value

    return None


def _record_id(
    *,
    cwd: str,
    prefix: list[str],
) -> str:
    payload = json.dumps(
        {
            "cwd": cwd,
            "prefix": prefix,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(
        payload.encode("utf-8")
    ).hexdigest()[:12]
    return f"cmd-{digest}"


@dataclass(frozen=True)
class CommandEvidenceRecord:
    command_evidence_id: str
    cwd: str
    prefix: list[str]
    probe_argv: list[str]
    output: str
    source_observation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_evidence_id": self.command_evidence_id,
            "cwd": self.cwd,
            "prefix": list(self.prefix),
            "probe_argv": list(self.probe_argv),
            "output": self.output,
            "source_observation_id": self.source_observation_id,
        }


class CommandEvidenceStore:
    def __init__(self) -> None:
        self._records: dict[
            str,
            CommandEvidenceRecord,
        ] = {}

    def add_probe_result(
        self,
        *,
        request: ToolRequest,
        result: Any,
        source_observation_id: str,
        evidence_store: Any,
    ) -> CommandEvidenceRecord:
        prefix = validate_safe_capability_probe(
            request=request,
            evidence_store=evidence_store,
        )

        exit_code = _result_exit_code(result)
        if exit_code is not None and exit_code != 0:
            raise CommandGroundingError(
                "Capability probe basarisiz exit code dondurdu: "
                f"{exit_code}"
            )

        output = _result_text(result).strip()
        if not output:
            raise CommandGroundingError(
                "Capability probe kullanilabilir cikti uretmedi."
            )

        cwd = _norm(request.cwd or ".")
        record = CommandEvidenceRecord(
            command_evidence_id=_record_id(
                cwd=cwd,
                prefix=prefix,
            ),
            cwd=cwd,
            prefix=list(prefix),
            probe_argv=_argv(request),
            output=output[:50000],
            source_observation_id=source_observation_id,
        )

        self._records[
            record.command_evidence_id
        ] = record

        return record

    def records(self) -> list[CommandEvidenceRecord]:
        return sorted(
            self._records.values(),
            key=lambda item: (
                item.cwd,
                item.prefix,
            ),
        )

    def to_model_payload(self) -> list[dict[str, Any]]:
        return [
            item.to_dict()
            for item in self.records()
        ]

    def get(
        self,
        command_evidence_id: str,
    ) -> CommandEvidenceRecord:
        try:
            return self._records[
                command_evidence_id
            ]
        except KeyError as exc:
            raise CommandGroundingError(
                "Bilinmeyen command_evidence_ref: "
                f"{command_evidence_id}"
            ) from exc

    @staticmethod
    def _token_in_output(
        token: str,
        output: str,
    ) -> bool:
        escaped = re.escape(token)
        pattern = (
            r"(?<![A-Za-z0-9_-])"
            + escaped
            + r"(?![A-Za-z0-9_-])"
        )
        return bool(
            re.search(
                pattern,
                output,
                flags=re.IGNORECASE,
            )
        )

    def validate_mutation_command(
        self,
        *,
        request: ToolRequest,
        command_evidence_refs: list[str],
    ) -> CommandEvidenceRecord:
        if request.tool_name != "run_process":
            raise CommandGroundingError(
                "Command grounding yalniz run_process icin kullanilir."
            )

        if not command_evidence_refs:
            raise CommandGroundingError(
                "run_process mutation command_evidence_refs icermeli."
            )

        candidate = _argv(request)
        cwd = _norm(request.cwd or ".")
        reasons: list[str] = []

        for ref in command_evidence_refs:
            record = self.get(ref)

            if record.cwd != cwd:
                reasons.append(
                    f"{ref}: cwd eslesmiyor"
                )
                continue

            prefix = record.prefix

            if (
                len(candidate) <= len(prefix)
                or candidate[:len(prefix)] != prefix
            ):
                reasons.append(
                    f"{ref}: command prefix eslesmiyor"
                )
                continue

            verb = candidate[len(prefix)]

            if not self._token_in_output(
                verb,
                record.output,
            ):
                reasons.append(
                    f"{ref}: '{verb}' probe ciktisinda yok"
                )
                continue

            return record

        detail = (
            "; ".join(reasons)
            or "uygun command evidence bulunamadi"
        )

        raise CommandGroundingError(
            "run_process komutu capability evidence ile "
            f"kanitlanamadi: {detail}"
        )
