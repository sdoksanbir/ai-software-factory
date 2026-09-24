from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from factory.command_grounding import (
    CommandEvidenceRecord,
    CommandEvidenceStore,
    CommandGroundingError,
    is_project_script_path,
)
from factory.general_agent_contracts import ToolRequest
from factory.tool_registry import ToolRegistry


class CapabilityResolverError(RuntimeError):
    pass


class CapabilityOption(BaseModel):
    capability_ref: str
    command_evidence_ref: str
    token: str
    source_line: str | None = None


class CapabilityInventory(BaseModel):
    options: list[CapabilityOption] = Field(
        default_factory=list
    )

    def get(
        self,
        capability_ref: str,
    ) -> CapabilityOption:
        for option in self.options:
            if option.capability_ref == capability_ref:
                return option
        raise CapabilityResolverError(
            f"Bilinmeyen capability_ref: {capability_ref}"
        )

    def by_token(
        self,
        token: str,
    ) -> CapabilityOption | None:
        wanted = token.casefold()
        for option in self.options:
            if option.token.casefold() == wanted:
                return option
        return None


class CapabilityResolution(BaseModel):
    """Model yalniz inventory ID secer; token/ToolRequest uretmez."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["select", "fail"]
    capability_ref: str | None = None
    arguments: list[str] = Field(
        default_factory=list
    )
    reason: str = Field(min_length=1)


@dataclass(frozen=True)
class MaterializedCapabilityAction:
    tool: ToolRequest
    evidence_refs: list[str]
    command_evidence_refs: list[str]
    runtime_ref: str | None
    reason: str


_COMMAND_TOKEN_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]*$"
)
_BRACKET_HEADING_RE = re.compile(
    r"^\[.*\]$"
)
_FORBIDDEN_RESOLUTION_FIELDS = frozenset(
    {
        "tool_name",
        "tool",
        "cwd",
        "permission",
        "runtime_ref",
        "evidence_refs",
        "command_evidence_refs",
        "argv",
        "capability",
        "command_evidence_ref",
        "token",
    }
)


def _norm_path(path: str) -> str:
    return str(path or ".").replace("\\", "/").strip() or "."


def _join_cwd(cwd: str, token: str) -> str:
    value = token.replace("\\", "/")
    base = _norm_path(cwd)
    if base in {".", ""}:
        return value.lstrip("./")
    if value.startswith("/"):
        return value
    return f"{base}/{value.lstrip('./')}"


def _is_command_token(token: str) -> bool:
    if not token:
        return False
    if token.startswith("-"):
        return False
    if any(
        ch in token
        for ch in "/\\|$;&<>(){}[]\"'`="
    ):
        return False
    if "." in token:
        return False
    return bool(_COMMAND_TOKEN_RE.fullmatch(token))


def _strip_list_marker(text: str) -> str:
    stripped = text.strip()
    for marker in ("* ", "• ", "· ", "- ", "+ "):
        if not stripped.startswith(marker):
            continue
        rest = stripped[len(marker):].lstrip()
        # "-h" / "--help" option satiri; bullet degil.
        if rest.startswith("-"):
            return stripped
        return rest
    return stripped


def _is_heading_line(stripped: str) -> bool:
    if _BRACKET_HEADING_RE.fullmatch(stripped):
        return True
    lowered = stripped.casefold()
    if lowered.startswith("usage:"):
        return True
    if stripped.endswith(":"):
        body = stripped[:-1].strip()
        if not body:
            return True
        if " " in body:
            return True
        first = body.split()[0]
        if not _is_command_token(first):
            return True
        if body.casefold() in {
            "commands",
            "command",
            "options",
            "option",
            "arguments",
            "usage",
            "subcommands",
            "examples",
            "description",
        }:
            return True
    return False


def extract_capability_tokens(
    output: str,
) -> list[tuple[str, str]]:
    """Help output → (token, source_line) listesi; sirali, ham."""
    found: list[tuple[str, str]] = []
    for raw in str(output or "").splitlines():
        source_line = raw.rstrip()
        stripped = source_line.strip()
        if not stripped:
            continue
        if _is_heading_line(stripped):
            continue

        working = _strip_list_marker(stripped)
        if working.startswith("-"):
            continue

        first = re.split(r"[\s,]+", working, maxsplit=1)[0]
        first = first.strip(".,;:")
        if not _is_command_token(first):
            continue
        found.append((first, stripped))
    return found


def build_capability_inventory(
    command_evidence_store: CommandEvidenceStore,
) -> CapabilityInventory:
    options: list[CapabilityOption] = []
    seen: set[str] = set()
    counter = 0

    for record in command_evidence_store.records():
        for token, source_line in extract_capability_tokens(
            record.output
        ):
            key = token.casefold()
            if key in seen:
                continue
            seen.add(key)
            counter += 1
            options.append(
                CapabilityOption(
                    capability_ref=f"cap-{counter:03d}",
                    command_evidence_ref=(
                        record.command_evidence_id
                    ),
                    token=token,
                    source_line=source_line,
                )
            )

    return CapabilityInventory(options=options)


def format_capability_inventory(
    inventory: CapabilityInventory,
) -> str:
    lines: list[str] = []
    for option in inventory.options:
        if (
            option.source_line
            and option.source_line.strip() != option.token
        ):
            lines.append(
                f"{option.capability_ref} | {option.token} | "
                f"{option.source_line.strip()}"
            )
        else:
            lines.append(
                f"{option.capability_ref} | {option.token}"
            )
    return "\n".join(lines)


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        raise CapabilityResolverError(
            "Capability resolver bos cevap dondurdu."
        )

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise CapabilityResolverError(
                "Capability resolver JSON object dondurmedi."
            )
        try:
            payload = json.loads(
                text[start:end + 1]
            )
        except json.JSONDecodeError as exc:
            raise CapabilityResolverError(
                "Capability resolver JSON'i ayrıştırılamadı."
            ) from exc

    if not isinstance(payload, dict):
        raise CapabilityResolverError(
            "Capability resolver JSON object olmali."
        )
    return payload


def parse_capability_resolution(
    payload: dict[str, Any],
) -> CapabilityResolution:
    present = sorted(
        key
        for key in _FORBIDDEN_RESOLUTION_FIELDS
        if key in payload
    )
    if present:
        raise CapabilityResolverError(
            "Capability resolver ToolRequest/token alanlari "
            f"uretemez: {', '.join(present)}"
        )

    try:
        return CapabilityResolution.model_validate(
            payload
        )
    except Exception as exc:
        raise CapabilityResolverError(
            f"Gecersiz CapabilityResolution: {exc}"
        ) from exc


def _step_title_description(
    target_step: Any,
) -> tuple[str, str]:
    if target_step is None:
        return "", ""

    if hasattr(target_step, "model_dump"):
        data = target_step.model_dump(mode="json")
    elif isinstance(target_step, dict):
        data = target_step
    else:
        data = {
            "title": getattr(
                target_step, "title", ""
            ),
            "description": getattr(
                target_step,
                "description",
                "",
            ),
        }

    title = str(
        data.get("title")
        or data.get("name")
        or ""
    ).strip()
    description = str(
        data.get("description")
        or data.get("summary")
        or ""
    ).strip()
    return title, description


def resolve_capability_selection(
    *,
    goal: str,
    target_step: Any,
    command_evidence_store: CommandEvidenceStore,
    model_client: Any,
    inventory: CapabilityInventory | None = None,
    model_role: str = "capability_resolver",
    timeout: int = 60,
    prior_fail_reason: str | None = None,
) -> CapabilityResolution:
    built = inventory or build_capability_inventory(
        command_evidence_store
    )
    if not built.options:
        return CapabilityResolution(
            decision="fail",
            reason=(
                "Capability inventory bos; "
                "secilebilir command token yok."
            ),
        )

    title, description = _step_title_description(
        target_step
    )
    inventory_text = format_capability_inventory(built)

    system_prompt = (
        "Sen CAPABILITY RESOLVER'sin.\n"
        "Asagida deterministic CapabilityInventory verilir.\n"
        "Yalnizca semantik secim JSON'u dondur.\n\n"
        "URETME: tool_name, cwd, permission, runtime_ref, argv, "
        "command_evidence_ref, capability token, evidence_refs.\n\n"
        "Kurallar:\n"
        "1. Kullanicinin dili ile capability adlarinin dili "
        "farkli olabilir. Lexical equality arama.\n"
        "2. Kullanicinin istedigi islemin ANLAMINA en uygun "
        "capability'yi sec.\n"
        "3. Sadece verilen capability_ref degerlerinden birini "
        "kullan.\n"
        "4. arguments yalniz kullaniciya ozel ek argumanlardir; "
        "capability token'ini arguments icine koyma.\n"
        "5. Eslesen capability yoksa decision=fail dondur.\n"
        "6. Cikti tek JSON object olmali.\n\n"
        "GECERLI OUTPUT:\n"
        + json.dumps(
            {
                "decision": "select",
                "capability_ref": "cap-001",
                "arguments": ["target-name"],
                "reason": (
                    "Secilen capability create-item "
                    "amacini karsiliyor."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    retry_block = ""
    if prior_fail_reason:
        retry_block = (
            "\n\nONCEKI DENEME:\n"
            f"{prior_fail_reason}\n"
            "Onceki secimde eslesme bulunamadi.\n"
            "Mevcut secenekleri tekrar degerlendir.\n"
            "Kelime eslesmesi degil semantik amac eslesmesi yap.\n"
        )

    user_prompt = (
        "CAPABILITY RESOLUTION STATE:\n"
        f"GOAL:\n{goal}\n\n"
        f"STEP TITLE:\n{title}\n\n"
        f"STEP DESCRIPTION:\n{description}\n\n"
        "AVAILABLE CAPABILITIES:\n"
        f"{inventory_text}"
        f"{retry_block}\n\n"
        "CapabilityResolution JSON'unu dondur."
    )

    try:
        response = model_client.complete(
            model_role=model_role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            timeout=timeout,
        )
    except Exception as exc:
        raise CapabilityResolverError(
            "Capability resolver model cagrisi basarisiz: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    payload = _extract_json_object(
        getattr(response, "content", "")
    )
    return parse_capability_resolution(payload)


def _source_script_paths(
    record: CommandEvidenceRecord,
) -> list[str]:
    paths: list[str] = []
    for token in record.prefix[1:]:
        value = str(token).strip()
        if not value or value.startswith("-"):
            continue
        path = _join_cwd(record.cwd, value)
        if is_project_script_path(path):
            paths.append(_norm_path(path))
    return paths


def _source_file_evidence_refs(
    *,
    record: CommandEvidenceRecord,
    evidence_store: Any,
) -> list[str]:
    script_paths = set(_source_script_paths(record))
    if not script_paths:
        raise CapabilityResolverError(
            "CommandEvidence prefix icinde proje script "
            "yolu bulunamadi."
        )

    refs: list[str] = []
    for item in evidence_store.records():
        if item.kind != "file":
            continue
        if _norm_path(item.path) in script_paths:
            refs.append(item.evidence_id)

    if not refs:
        raise CapabilityResolverError(
            "Capability kaynak script icin FILE "
            "evidence_ref bulunamadi: "
            + ", ".join(sorted(script_paths))
        )
    return refs


def materialize_grounded_action(
    *,
    resolution: CapabilityResolution,
    command_evidence_store: CommandEvidenceStore,
    evidence_store: Any,
    tool_registry: ToolRegistry,
    inventory: CapabilityInventory | None = None,
) -> MaterializedCapabilityAction | None:
    """CapabilityResolution → deterministic grounded mutation."""
    if resolution.decision == "fail":
        return None

    if not resolution.capability_ref:
        raise CapabilityResolverError(
            "select icin capability_ref zorunlu."
        )

    built = inventory or build_capability_inventory(
        command_evidence_store
    )
    option = built.get(resolution.capability_ref)

    try:
        record = command_evidence_store.get(
            option.command_evidence_ref
        )
    except CommandGroundingError as exc:
        raise CapabilityResolverError(str(exc)) from exc

    extra_args = [
        str(item).strip()
        for item in resolution.arguments
        if str(item).strip()
    ]
    argv = (
        list(record.prefix)
        + [option.token]
        + extra_args
    )

    try:
        definition = tool_registry.get("run_process")
    except Exception as exc:
        raise CapabilityResolverError(
            "run_process tool kayitli degil."
        ) from exc

    file_refs = _source_file_evidence_refs(
        record=record,
        evidence_store=evidence_store,
    )

    request = ToolRequest(
        tool_name="run_process",
        arguments={"argv": argv},
        permission=definition.permission,
        cwd=record.cwd if record.cwd != "." else None,
    )

    return MaterializedCapabilityAction(
        tool=request,
        evidence_refs=file_refs,
        command_evidence_refs=[
            record.command_evidence_id
        ],
        runtime_ref=record.runtime_ref,
        reason=resolution.reason,
    )
