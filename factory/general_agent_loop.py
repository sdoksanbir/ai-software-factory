"""EXPERIMENTAL — General agent prototype.

Not used by the production API structured execution path.
Do not import from production modules.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from factory.general_agent_contracts import (
    GeneralTaskPlan,
    Observation,
    Permission,
    ToolRequest,
)
from factory.general_task_planner import (
    GeneralPlannerError,
    build_general_task_plan,
)
from factory.tool_registry import (
    ToolRegistry,
    ToolRegistryError,
)
from factory.command_grounding import (
    CommandEvidenceStore,
    CommandGroundingError,
    is_safe_capability_probe,
    logical_runtime_for_script_path,
)
from factory.capability_discovery import (
    CapabilityCandidateStore,
)
from factory.capability_resolver import (
    CapabilityResolverError,
    build_capability_inventory,
    materialize_grounded_action,
    resolve_capability_selection,
)
from factory.runtime_grounding import (
    RuntimeEvidenceStore,
    RuntimeGroundingError,
    bind_runtime_request,
)


class AgentLoopError(RuntimeError):
    pass


class EvidenceValidationError(AgentLoopError):
    pass


def _norm(raw: str | None) -> str:
    value = str(raw or ".").strip().replace("\\", "/")
    if value in {"", "."}:
        return "."

    path = PurePosixPath(value)

    if path.is_absolute() or ".." in path.parts:
        raise EvidenceValidationError(
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


def _parent(path: str) -> str:
    p = _norm(path)
    if p == ".":
        return "."

    value = str(PurePosixPath(p).parent)
    return "." if value in {"", "."} else _norm(value)


def _within(path: str, base: str) -> bool:
    path = _norm(path)
    base = _norm(base)

    return (
        base == "."
        or path == base
        or path.startswith(base + "/")
    )


def _eid(kind: str, path: str) -> str:
    digest = hashlib.sha1(
        f"{kind}:{path}".encode("utf-8")
    ).hexdigest()[:10]

    return f"ev-{kind}-{digest}"


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    kind: Literal["directory", "file", "path"]
    path: str
    source_tool: str
    source_observation_id: str
    inspected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "path": self.path,
            "source_tool": self.source_tool,
            "source_observation_id": self.source_observation_id,
            "inspected": self.inspected,
        }


class EvidenceStore:
    def __init__(self) -> None:
        self._records: dict[
            tuple[str, str],
            EvidenceRecord,
        ] = {}

        self._inspected_dirs: set[str] = {"."}

        self._upsert(
            "directory",
            ".",
            "project_root",
            "project-root",
            inspected=True,
        )

    def _upsert(
        self,
        kind: Literal["directory", "file", "path"],
        path: str,
        source_tool: str,
        source_observation_id: str,
        inspected: bool = False,
    ) -> EvidenceRecord:
        path = _norm(path)

        if (
            kind == "directory"
            and path in self._inspected_dirs
        ):
            inspected = True

        key = (kind, path)
        old = self._records.get(key)

        if old is not None:
            if inspected and not old.inspected:
                old = EvidenceRecord(
                    evidence_id=old.evidence_id,
                    kind=old.kind,
                    path=old.path,
                    source_tool=source_tool,
                    source_observation_id=source_observation_id,
                    inspected=True,
                )
                self._records[key] = old
            return old

        item = EvidenceRecord(
            evidence_id=_eid(kind, path),
            kind=kind,
            path=path,
            source_tool=source_tool,
            source_observation_id=source_observation_id,
            inspected=inspected,
        )

        self._records[key] = item
        return item

    def add_observation(
        self,
        observation: Observation,
    ) -> None:
        if not observation.success:
            return

        data = (
            observation.data
            if isinstance(observation.data, dict)
            else {}
        )

        if observation.tool_name == "list_files":
            base = _norm(data.get("base", "."))
            self._inspected_dirs.add(base)

            self._upsert(
                "directory",
                base,
                observation.tool_name,
                observation.step_id,
                inspected=True,
            )

            for entry in data.get("entries", []):
                if not isinstance(entry, dict):
                    continue

                path = entry.get("path")
                if not path:
                    continue

                raw_type = str(
                    entry.get("type", "")
                ).casefold()

                kind = (
                    "directory"
                    if raw_type == "directory"
                    else "file"
                    if raw_type == "file"
                    else "path"
                )

                self._upsert(
                    kind,
                    str(path),
                    observation.tool_name,
                    observation.step_id,
                )

            return

        if observation.tool_name == "find_files":
            for match in data.get("matches", []):
                if isinstance(match, str):
                    self._upsert(
                        "file",
                        match,
                        observation.tool_name,
                        observation.step_id,
                    )
            return

        if observation.tool_name == "read_file":
            path = data.get("path")
            if isinstance(path, str):
                self._upsert(
                    "file",
                    path,
                    observation.tool_name,
                    observation.step_id,
                )
            return

        if (
            observation.tool_name == "file_exists"
            and data.get("exists")
        ):
            path = data.get("path")
            if isinstance(path, str):
                self._upsert(
                    "path",
                    path,
                    observation.tool_name,
                    observation.step_id,
                )

    def records(self) -> list[EvidenceRecord]:
        return sorted(
            self._records.values(),
            key=lambda x: (x.path, x.kind),
        )

    def to_model_payload(self) -> list[dict[str, Any]]:
        return [x.to_dict() for x in self.records()]

    def get(self, evidence_id: str) -> EvidenceRecord:
        for item in self._records.values():
            if item.evidence_id == evidence_id:
                return item

        raise EvidenceValidationError(
            f"Bilinmeyen evidence_ref: {evidence_id}"
        )

    def known_directory(self, path: str) -> bool:
        path = _norm(path)
        return any(
            x.kind == "directory"
            and x.path == path
            for x in self._records.values()
        )

    def inspected_directory(self, path: str) -> bool:
        return _norm(path) in self._inspected_dirs

    def known_file(self, path: str) -> bool:
        path = _norm(path)
        return any(
            x.kind == "file"
            and x.path == path
            for x in self._records.values()
        )


class NextAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "tool",
        "complete",
        "fail",
    ]

    reason: str = Field(min_length=1)
    tool: ToolRequest | None = None
    evidence_refs: list[str] = Field(
        default_factory=list
    )
    command_evidence_refs: list[str] = Field(
        default_factory=list
    )
    runtime_ref: str | None = None
    answer: str | None = None


@dataclass
class AgentLoopPreviewResult:
    plan: GeneralTaskPlan
    observations: list[Observation]
    evidence: list[EvidenceRecord]
    command_evidence: list[Any]
    runtime_evidence: list[Any]
    pending_action: NextAction | None
    completed: bool
    final_answer: str | None
    stop_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.model_dump(mode="json"),
            "observations": [
                x.model_dump(mode="json")
                for x in self.observations
            ],
            "evidence": [
                x.to_dict()
                for x in self.evidence
            ],
            "command_evidence": [
                x.to_dict()
                for x in self.command_evidence
            ],
            "runtime_evidence": [
                x.to_dict()
                for x in self.runtime_evidence
            ],
            "pending_action": (
                self.pending_action.model_dump(
                    mode="json"
                )
                if self.pending_action
                else None
            ),
            "completed": self.completed,
            "final_answer": self.final_answer,
            "stop_reason": self.stop_reason,
        }


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()

    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if (
            lines
            and lines[-1].strip().startswith("```")
        ):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise AgentLoopError(
                "Agent gecerli JSON dondurmedi."
            )

        try:
            payload = json.loads(
                text[start : end + 1]
            )
        except json.JSONDecodeError as exc:
            preview = text[:4000]
            raise AgentLoopError(
                "Agent JSON'i ayrıştırılamadı. "
                "Ham model cevabı:\n"
                + preview
            ) from exc

    if not isinstance(payload, dict):
        raise AgentLoopError(
            "Agent JSON object olmali."
        )

    return payload


def _canonicalize_action(
    payload: dict[str, Any],
    registry: ToolRegistry,
) -> NextAction:
    action = str(
        payload.get("action", "")
    ).strip().casefold()

    raw_tool = payload.get("tool")

    if (
        action
        in {"read", "write", "execute", "destructive"}
        and isinstance(raw_tool, dict)
    ):
        action = "tool"

    reason = str(
        payload.get("reason", "")
    ).strip()

    refs = payload.get(
        "evidence_refs",
        [],
    )

    if not isinstance(refs, list):
        raise AgentLoopError(
            "evidence_refs liste olmali."
        )

    refs = [
        str(x).strip()
        for x in refs
        if str(x).strip()
    ]

    raw_command_refs = payload.get(
        "command_evidence_refs",
        [],
    )

    if not isinstance(
        raw_command_refs,
        list,
    ):
        raise AgentLoopError(
            "command_evidence_refs liste olmali."
        )

    command_refs = [
        str(x).strip()
        for x in raw_command_refs
        if str(x).strip()
    ]

    runtime_ref = payload.get(
        "runtime_ref"
    )

    if runtime_ref is not None:
        runtime_ref = str(
            runtime_ref
        ).strip() or None

    answer = payload.get("answer")
    if answer is not None:
        answer = str(answer)

    if action in {"complete", "fail"}:
        return NextAction(
            action=action,
            reason=reason or action,
            tool=None,
            evidence_refs=refs,
            command_evidence_refs=command_refs,
            runtime_ref=runtime_ref,
            answer=answer,
        )

    if action != "tool":
        raise AgentLoopError(
            f"Bilinmeyen next action: {action}"
        )

    if not isinstance(raw_tool, dict):
        raise AgentLoopError(
            "tool action icin tool object gerekli."
        )

    name = str(
        raw_tool.get("tool_name", "")
    ).strip()

    if not name:
        raise AgentLoopError(
            "tool_name bos olamaz."
        )

    try:
        definition = registry.get(name)
    except ToolRegistryError as exc:
        raise AgentLoopError(
            f"Agent bilinmeyen tool secti: {name}"
        ) from exc

    arguments = raw_tool.get(
        "arguments",
        {},
    )

    if not isinstance(arguments, dict):
        raise AgentLoopError(
            "tool.arguments object olmali."
        )

    cwd = raw_tool.get("cwd")

    if cwd is not None:
        cwd = _norm(str(cwd))

    request = ToolRequest(
        tool_name=name,
        arguments=arguments,
        permission=definition.permission,
        cwd=cwd,
    )

    try:
        registry.validate_request(request)
    except ToolRegistryError as exc:
        raise AgentLoopError(
            f"Agent gecersiz tool request uretti: {exc}"
        ) from exc

    return NextAction(
        action="tool",
        reason=reason or "Tool kullan.",
        tool=request,
        evidence_refs=refs,
        command_evidence_refs=command_refs,
        runtime_ref=runtime_ref,
        answer=answer,
    )


def _first_deferred_step(
    plan: GeneralTaskPlan,
):
    return next(
        (
            step
            for step in plan.steps
            if step.tool is None
        ),
        None,
    )


def _model_call(
    *,
    model_client: Any,
    model_role: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int,
    error_prefix: str,
) -> dict[str, Any]:
    try:
        response = model_client.complete(
            model_role=model_role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            timeout=timeout,
        )
    except Exception as exc:
        raise AgentLoopError(
            f"{error_prefix}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    return _extract_json_object(
        getattr(response, "content", "")
    )


def resolve_deferred_step_action(
    *,
    goal: str,
    plan: GeneralTaskPlan,
    target_step: Any,
    observations: list[Observation],
    evidence_store: EvidenceStore,
    command_evidence_store: CommandEvidenceStore,
    runtime_evidence_store: RuntimeEvidenceStore,
    model_client: Any,
    tool_registry: ToolRegistry,
    capability_store: CapabilityCandidateStore | None = None,
    resolve_with_capability: bool = False,
    model_role: str = "fast_local",
    timeout: int = 60,
) -> NextAction:
    capability_rules = ""
    if resolve_with_capability:
        capability_rules = (
            "RESOLVE_WITH_CAPABILITY MODU:\n"
            "Command Evidence MEVCUT. "
            "Yeni filesystem discovery yapma. "
            "Yeni capability probe isteme. "
            "list_files/read_file/find_files secme. "
            "Mevcut Evidence Store, Runtime Evidence ve "
            "Command Evidence ile grounded mutation sec "
            "(command_evidence_refs zorunlu). "
            "Command output icindeki gercek capability "
            "tokenlarini kullan; framework veya komut uydurma. "
            "Mevcut capability goal icin uygun degilse fail dondur.\n\n"
        )

    system_prompt = (
        "Sen genel amacli STEP RESOLVER'sin. "
        "Sadece TARGET STEP icin bir sonraki tool'u sec. "
        "Tum gorevi yeniden planlama. Yalnizca JSON dondur.\n\n"
        + capability_rules
        + "ZORUNLU KURALLAR:\n"
        "1. Evidence Store disinda path/cwd uydurma.\n"
        "2. Parent listede gorulen bir klasor mutation cwd icin "
        "yeterli degildir. Mutation cwd kullanmadan once o klasor "
        "READ ile bizzat inspect edilmis olmali: inspected=true.\n"
        "3. Kanit yetersizse WRITE/EXECUTE secme; READ yap. "
        "Ama Command Evidence varken READ/discovery secme.\n"
        "4. Mutation tool icin evidence_refs zorunlu.\n"
        "5. EXECUTE icin cwd altindan en az bir FILE evidence_ref ver.\n"
        "6. run_process MUTATION icin command_evidence_refs zorunlu. "
        "Uygun command evidence yoksa mutation uydurma; ayni command "
        "ailesiyle help/--help/-h/version/--version probe yap.\n"
        "7. Capability probe sadece komut yeteneklerini kesfetmek icindir.\n"
        "8. Tool permission'ini Registry belirler.\n"
        "9. run_process shell string degil argv listesi kullanir.\n"
        "10. python/python3/node gibi runtime-backed komutlarda mutlak "
        "interpreter yolu uydurma. argv[0] icin mantiksal ad kullan "
        "(ornegin python). Tek project-local runtime varsa sistem onu "
        "otomatik baglar; secim belirsizse runtime_ref kullan.\n"
        "11. Bir runtime ile capability probe basarisiz olduysa o runtime "
        "icin command evidence yoktur; mutation yapma.\n"
        "12. PlanStep.permission final effect / approval sinifidir; "
        "bir sonraki tool secimini BELIRLEMEZ. Tool permission'ini "
        "ToolRegistry belirler. permission=write olsa bile "
        "write_file zorunlu degildir; grounded run_process "
        "veya baska uygun tool secilebilir.\n"
        "13. Evidence yetersizken ayni mutation'i tekrar deneme. "
        "Command Evidence yokken: inspect edilmemis klasor veya "
        "okunmamis bilinen dosya varsa once READ; bilinen entry-point "
        "ve runtime varsa safe capability probe. Command Evidence "
        "varsa discovery yapma; grounded mutation veya fail.\n"
        "14. complete deme; tool veya fail dondur.\n"
        "15. evidence_refs, command_evidence_refs, runtime_ref ve answer "
        "tool nesnesinin ICINDE DEGIL; en dis JSON nesnesinde tool ile "
        "AYNI SEVIYEDE olmalidir.\n"
        "16. Cikti tek ve eksiksiz bir JSON object olmali; aciklama veya "
        "Markdown ekleme.\n\n"
        "GECERLI JSON OUTPUT ORNEGI:\n"
        + json.dumps(
            {
                "action": "tool",
                "reason": "neden",
                "tool": {
                    "tool_name": "list_files",
                    "arguments": {"path": "."},
                    "permission": "read",
                    "cwd": None,
                },
                "evidence_refs": [],
                "command_evidence_refs": [],
                "runtime_ref": None,
                "answer": None,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n\n"
        "TOOL KATALOGU:\n"
        + json.dumps(
            tool_registry.describe_for_model(),
            ensure_ascii=False,
            indent=2,
        )
    )

    state = {
        "goal": goal,
        "target_step": target_step.model_dump(
            mode="json"
        ),
        "success_criteria": [
            x.model_dump(mode="json")
            for x in plan.success_criteria
        ],
        "resolve_with_capability": (
            resolve_with_capability
        ),
        "evidence_store": (
            evidence_store.to_model_payload()
        ),
        "command_evidence_store": (
            command_evidence_store.to_model_payload()
        ),
        "runtime_evidence_store": (
            runtime_evidence_store.to_model_payload()
        ),
        "capability_candidates": (
            capability_store.to_model_payload()
            if capability_store is not None
            else []
        ),
        "recent_observations": [
            x.model_dump(mode="json")
            for x in observations[-8:]
        ],
    }

    user_suffix = (
        "\n\nCommand Evidence mevcut. "
        "Grounded mutation JSON'unu dondur."
        if resolve_with_capability
        else "\n\nBir sonraki tool JSON'unu dondur."
    )

    payload = _model_call(
        model_client=model_client,
        model_role=model_role,
        system_prompt=system_prompt,
        user_prompt=(
            "STEP RESOLUTION STATE:\n"
            + json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
            )
            + user_suffix
        ),
        timeout=timeout,
        error_prefix=(
            "Step resolver model cagrisi basarisiz"
        ),
    )

    action = _canonicalize_action(
        payload,
        tool_registry,
    )

    if action.action == "complete":
        raise AgentLoopError(
            "Step resolver complete donduremez."
        )

    return action


def decide_next_action(
    *,
    goal: str,
    plan: GeneralTaskPlan,
    observations: list[Observation],
    model_client: Any,
    tool_registry: ToolRegistry,
    evidence_store: EvidenceStore | None = None,
    model_role: str = "fast_local",
    timeout: int = 60,
) -> NextAction:
    if evidence_store is None:
        evidence_store = EvidenceStore()

    system_prompt = (
        "Sen genel amacli agent karar vericisisin. "
        "Evidence Store disinda path/cwd uydurma. "
        "Basari kanitlanmadan complete deme. "
        "Evidence yetersizken ayni mutation'i tekrar deneme. "
        "Inspect edilmemis klasor veya okunmamis bilinen dosya varsa "
        "once READ yap; bilinen proje scripti ve uygun runtime varsa "
        "safe capability probe yap; boyle bir alan kalmadiysa fail dondur. "
        "Olmayan framework veya komut uydurma. "
        "Tool permission'ini Registry belirler. "
        "Yalnizca JSON dondur. "
        "evidence_refs, command_evidence_refs, runtime_ref ve answer "
        "tool nesnesinin icinde degil; en dis JSON nesnesinde tool ile "
        "ayni seviyede olmalidir.\n\n"
        "GECERLI JSON OUTPUT ORNEGI:\n"
        + json.dumps(
            {
                "action": "tool",
                "reason": "neden",
                "tool": {
                    "tool_name": "list_files",
                    "arguments": {"path": "."},
                    "permission": "read",
                    "cwd": None,
                },
                "evidence_refs": [],
                "command_evidence_refs": [],
                "runtime_ref": None,
                "answer": None,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n\n"
        "TOOL KATALOGU:\n"
        + json.dumps(
            tool_registry.describe_for_model(),
            ensure_ascii=False,
            indent=2,
        )
    )

    payload = _model_call(
        model_client=model_client,
        model_role=model_role,
        system_prompt=system_prompt,
        user_prompt=json.dumps(
            {
                "goal": goal,
                "plan": plan.model_dump(
                    mode="json"
                ),
                "evidence_store": (
                    evidence_store.to_model_payload()
                ),
                "recent_observations": [
                    x.model_dump(mode="json")
                    for x in observations[-8:]
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        timeout=timeout,
        error_prefix=(
            "Next-action model cagrisi basarisiz"
        ),
    )

    return _canonicalize_action(
        payload,
        tool_registry,
    )


def _effective_path(
    request: ToolRequest,
    raw_path: str,
) -> str:
    return _join(
        request.cwd or ".",
        raw_path,
    )


def validate_evidence_bound_action(
    *,
    action: NextAction,
    evidence_store: EvidenceStore,
) -> None:
    if action.action != "tool":
        return

    request = action.tool

    if request is None:
        raise EvidenceValidationError(
            "Tool action tool request icermiyor."
        )

    cwd = _norm(
        request.cwd or "."
    )

    if not evidence_store.known_directory(cwd):
        raise EvidenceValidationError(
            f"cwd EvidenceStore'da yok: {cwd}"
        )

    if request.permission == Permission.READ:
        if request.tool_name == "list_files":
            raw = request.arguments.get(
                "path",
                ".",
            )
            if isinstance(raw, str):
                target = _effective_path(
                    request,
                    raw,
                )
                if not evidence_store.known_directory(
                    target
                ):
                    raise EvidenceValidationError(
                        "list_files bilinmeyen klasoru "
                        f"inspect edemez: {target}"
                    )

        elif request.tool_name == "read_file":
            raw = request.arguments.get("path")
            if isinstance(raw, str):
                target = _effective_path(
                    request,
                    raw,
                )
                if not evidence_store.known_file(
                    target
                ):
                    raise EvidenceValidationError(
                        f"read_file bilinmeyen dosya: {target}"
                    )

        elif request.tool_name == "file_exists":
            raw = request.arguments.get("path")
            if isinstance(raw, str):
                target = _effective_path(
                    request,
                    raw,
                )
                if not evidence_store.known_directory(
                    _parent(target)
                ):
                    raise EvidenceValidationError(
                        "file_exists target parent "
                        "EvidenceStore'da yok."
                    )

        return

    if not evidence_store.inspected_directory(cwd):
        raise EvidenceValidationError(
            "Mutation cwd parent listede gorunmus olsa bile "
            f"bizzat inspect edilmedi: {cwd}"
        )

    if not action.evidence_refs:
        raise EvidenceValidationError(
            "Mutation action evidence_refs icermeli."
        )

    records = [
        evidence_store.get(ref)
        for ref in action.evidence_refs
    ]

    if request.permission == Permission.EXECUTE:
        if not any(
            x.kind == "file"
            and _within(x.path, cwd)
            for x in records
        ):
            raise EvidenceValidationError(
                "EXECUTE icin inspected cwd altindan "
                "en az bir FILE evidence_ref gerekli."
            )

    if request.permission == Permission.WRITE:
        raw = request.arguments.get("path")
        if isinstance(raw, str):
            target = _effective_path(
                request,
                raw,
            )
            if not evidence_store.inspected_directory(
                _parent(target)
            ):
                raise EvidenceValidationError(
                    "WRITE hedefinin parent klasoru "
                    "inspect edilmedi."
                )

    if request.permission == Permission.DESTRUCTIVE:
        raise EvidenceValidationError(
            "Preview modunda DESTRUCTIVE action hazirlanmaz."
        )


def _fingerprint(
    request: ToolRequest,
) -> str:
    return json.dumps(
        {
            "tool_name": request.tool_name,
            "arguments": request.arguments,
            "cwd": request.cwd,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _mutation_identity(
    action: NextAction,
) -> str:
    request = action.tool
    if request is None:
        raise EvidenceValidationError(
            "Tool action tool request icermiyor."
        )

    return _fingerprint(request)


def _remember_read_file(
    observation: Observation,
    read_file_paths: set[str],
) -> None:
    if (
        not observation.success
        or observation.tool_name != "read_file"
    ):
        return

    raw = observation.data.get("path")
    if isinstance(raw, str) and raw.strip():
        read_file_paths.add(_norm(raw))


def _forced_capability_probe_action(
    *,
    evidence_store: EvidenceStore,
    tool_registry: ToolRegistry,
    runtime_evidence_store: RuntimeEvidenceStore,
    command_evidence_store: CommandEvidenceStore,
    capability_store: CapabilityCandidateStore,
    attempted_discoveries: set[str],
    attempted_probes: set[str],
) -> NextAction | None:
    if "run_process" not in set(tool_registry.names()):
        return None

    probe = capability_store.next_probe_request(
        evidence_store=evidence_store,
        runtime_evidence_store=runtime_evidence_store,
        command_evidence_store=command_evidence_store,
        permission=tool_registry.get(
            "run_process"
        ).permission,
        attempted_probes=attempted_probes,
        fingerprint_fn=_fingerprint,
    )
    if probe is None:
        return None

    candidate, probe_request = probe
    fingerprint = _fingerprint(probe_request)
    attempted_discoveries.add(fingerprint)
    attempted_probes.add(fingerprint)
    return NextAction(
        action="tool",
        reason=(
            "Entry-point candidate bulundu. "
            "Capability probe yapiliyor."
        ),
        tool=probe_request,
        evidence_refs=(
            [candidate.source_evidence_ref]
            if candidate.source_evidence_ref
            else []
        ),
    )


def _next_discovery_action(
    *,
    evidence_store: EvidenceStore,
    tool_registry: ToolRegistry,
    read_fingerprints: set[str],
    read_file_paths: set[str],
    attempted_discoveries: set[str],
    runtime_evidence_store: RuntimeEvidenceStore,
    command_evidence_store: CommandEvidenceStore,
    capability_store: CapabilityCandidateStore,
    attempted_probes: set[str],
) -> NextAction | None:
    """Deterministik discovery state machine.

    FILESYSTEM_DISCOVERY → CAPABILITY_PROBE (aday varsa)
    → CAPABILITY_DISCOVERY (okunmamis script)
    → genel read fallback.

    Unprobed candidate varken baska candidate-source
    file okunmaz. CommandEvidence varken auto-probe yok.
    """
    known_tools = set(
        tool_registry.names()
    )

    # Phase: FILESYSTEM_DISCOVERY — uninspected directories
    directories = sorted(
        (
            record.path
            for record in evidence_store.records()
            if record.kind == "directory"
            and not evidence_store.inspected_directory(
                record.path
            )
        ),
        key=lambda path: (
            path.count("/"),
            path.casefold(),
        ),
    )

    for path in directories:
        if "list_files" not in known_tools:
            break

        request = ToolRequest(
            tool_name="list_files",
            arguments={"path": path},
            permission=tool_registry.get(
                "list_files"
            ).permission,
            cwd=None,
        )
        fingerprint = _fingerprint(request)
        if (
            fingerprint in read_fingerprints
            or fingerprint in attempted_discoveries
        ):
            continue

        action = NextAction(
            action="tool",
            reason=(
                "Mutation icin kanit yetersiz. "
                "Once bilinmeyen alan okunuyor."
            ),
            tool=request,
            evidence_refs=[],
        )

        try:
            validate_evidence_bound_action(
                action=action,
                evidence_store=evidence_store,
            )
        except EvidenceValidationError:
            continue

        attempted_discoveries.add(
            fingerprint
        )
        return action

    # Phase: CAPABILITY_PROBE — pending entry-point first.
    # Cuts filesystem/capability reads while a candidate waits.
    probe_action = _forced_capability_probe_action(
        evidence_store=evidence_store,
        tool_registry=tool_registry,
        runtime_evidence_store=runtime_evidence_store,
        command_evidence_store=command_evidence_store,
        capability_store=capability_store,
        attempted_discoveries=attempted_discoveries,
        attempted_probes=attempted_probes,
    )
    if probe_action is not None:
        return probe_action

    # Phase: CAPABILITY_DISCOVERY — read one unread script to classify
    if (
        not command_evidence_store.records()
        and "read_file" in known_tools
    ):
        script_files = sorted(
            (
                record.path
                for record in evidence_store.records()
                if record.kind == "file"
                and logical_runtime_for_script_path(
                    record.path
                )
                is not None
                and not capability_store.assessed(
                    record.path
                )
                and _norm(record.path)
                not in read_file_paths
            ),
            key=lambda path: (
                path.count("/"),
                path.casefold(),
            ),
        )

        for path in script_files:
            request = ToolRequest(
                tool_name="read_file",
                arguments={"path": path},
                permission=tool_registry.get(
                    "read_file"
                ).permission,
                cwd=None,
            )
            fingerprint = _fingerprint(request)
            if (
                fingerprint in read_fingerprints
                or fingerprint in attempted_discoveries
            ):
                continue

            action = NextAction(
                action="tool",
                reason=(
                    "Capability adayi degerlendirmek "
                    "icin bilinen script okunuyor."
                ),
                tool=request,
                evidence_refs=[],
            )

            try:
                validate_evidence_bound_action(
                    action=action,
                    evidence_store=evidence_store,
                )
            except EvidenceValidationError:
                continue

            attempted_discoveries.add(
                fingerprint
            )
            return action

        package_json_files = sorted(
            (
                record.path
                for record in evidence_store.records()
                if record.kind == "file"
                and PurePosixPath(record.path).name.casefold()
                == "package.json"
                and _norm(record.path)
                not in read_file_paths
            ),
            key=lambda path: (
                path.count("/"),
                path.casefold(),
            ),
        )

        for path in package_json_files:
            request = ToolRequest(
                tool_name="read_file",
                arguments={"path": path},
                permission=tool_registry.get(
                    "read_file"
                ).permission,
                cwd=None,
            )
            fingerprint = _fingerprint(request)
            if (
                fingerprint in read_fingerprints
                or fingerprint in attempted_discoveries
            ):
                continue

            action = NextAction(
                action="tool",
                reason=(
                    "package.json bin hedefleri "
                    "icin dosya okunuyor."
                ),
                tool=request,
                evidence_refs=[],
            )

            try:
                validate_evidence_bound_action(
                    action=action,
                    evidence_store=evidence_store,
                )
            except EvidenceValidationError:
                continue

            attempted_discoveries.add(
                fingerprint
            )
            return action

    # Fallback filesystem reads for non-script unknowns
    files = sorted(
        (
            record.path
            for record in evidence_store.records()
            if record.kind == "file"
            and _norm(record.path)
            not in read_file_paths
        ),
        key=lambda path: (
            path.count("/"),
            path.casefold(),
        ),
    )

    for path in files:
        if "read_file" not in known_tools:
            break

        request = ToolRequest(
            tool_name="read_file",
            arguments={"path": path},
            permission=tool_registry.get(
                "read_file"
            ).permission,
            cwd=None,
        )
        fingerprint = _fingerprint(request)
        if (
            fingerprint in read_fingerprints
            or fingerprint in attempted_discoveries
        ):
            continue

        action = NextAction(
            action="tool",
            reason=(
                "Mutation icin kanit yetersiz. "
                "Once bilinmeyen alan okunuyor."
            ),
            tool=request,
            evidence_refs=[],
        )

        try:
            validate_evidence_bound_action(
                action=action,
                evidence_store=evidence_store,
            )
        except EvidenceValidationError:
            continue

        attempted_discoveries.add(
            fingerprint
        )
        return action

    return None


def _assess_read_for_capability(
    *,
    observation: Observation,
    evidence_store: EvidenceStore,
    capability_store: CapabilityCandidateStore,
) -> None:
    if (
        not observation.success
        or observation.tool_name != "read_file"
    ):
        return

    data = observation.data
    if not isinstance(data, dict):
        return

    path = data.get("path")
    content = data.get("content")
    if not isinstance(path, str) or not isinstance(
        content,
        str,
    ):
        return

    path = _norm(path)
    if PurePosixPath(path).name.casefold() == "package.json":
        capability_store.note_package_json(
            path=path,
            content=content,
        )
        return

    evidence_ref = ""
    for record in evidence_store.records():
        if (
            record.kind == "file"
            and record.path == path
        ):
            evidence_ref = record.evidence_id
            break

    capability_store.assess_file(
        script_path=path,
        content=content,
        source_evidence_ref=evidence_ref,
    )


def _execute_read(
    request: ToolRequest,
    registry: ToolRegistry,
    index: int,
) -> Observation:
    try:
        result = registry.execute(
            request
        )
    except Exception as exc:
        return Observation(
            step_id=f"observation-{index}",
            tool_name=request.tool_name,
            success=False,
            summary=f"{request.tool_name} basarisiz: {exc}",
            data={},
            error=f"{type(exc).__name__}: {exc}",
        )

    return Observation(
        step_id=f"observation-{index}",
        tool_name=request.tool_name,
        success=True,
        summary=f"{request.tool_name} tamamlandi.",
        data=(
            result
            if isinstance(result, dict)
            else {"result": result}
        ),
        error=None,
    )


def _control(
    index: int,
    error: str,
    summary: str,
    data: dict[str, Any],
) -> Observation:
    return Observation(
        step_id=f"observation-{index}",
        tool_name="agent_guard",
        success=False,
        summary=summary,
        data=data,
        error=error,
    )


def _plan_requires_mutation(
    plan: GeneralTaskPlan,
) -> bool:
    return any(
        step.permission
        in {
            Permission.WRITE,
            Permission.EXECUTE,
            Permission.DESTRUCTIVE,
        }
        for step in plan.steps
    )



def _bind_action_runtime(
    *,
    action: NextAction,
    runtime_evidence_store: RuntimeEvidenceStore,
) -> NextAction:
    if (
        action.action != "tool"
        or action.tool is None
        or action.tool.tool_name
        != "run_process"
    ):
        return action

    binding = bind_runtime_request(
        request=action.tool,
        store=runtime_evidence_store,
        runtime_ref=action.runtime_ref,
    )

    if binding is None:
        return action

    return action.model_copy(
        update={
            "tool": binding.request,
            "runtime_ref": (
                binding.runtime.runtime_id
            ),
        }
    )


def run_agent_loop_preview(
    *,
    prompt: str,
    model_client: Any,
    tool_registry: ToolRegistry,
    project_root: str | None = None,
    max_read_actions: int = 8,
    max_probe_actions: int = 4,
    max_decisions: int = 16,
    max_capability_resolution_attempts: int = 3,
    max_semantic_resolution_attempts: int = 2,
    capability_resolver_model_role: str = (
        "capability_resolver"
    ),
) -> AgentLoopPreviewResult:
    if max_read_actions < 1:
        raise ValueError(
            "max_read_actions en az 1 olmali."
        )

    if max_probe_actions < 1:
        raise ValueError(
            "max_probe_actions en az 1 olmali."
        )

    if max_decisions < 1:
        raise ValueError(
            "max_decisions en az 1 olmali."
        )

    if max_capability_resolution_attempts < 1:
        raise ValueError(
            "max_capability_resolution_attempts en az 1 olmali."
        )

    if max_semantic_resolution_attempts < 1:
        raise ValueError(
            "max_semantic_resolution_attempts en az 1 olmali."
        )

    try:
        plan = build_general_task_plan(
            prompt,
            model_client=model_client,
            tool_registry=tool_registry,
        )
    except GeneralPlannerError as exc:
        raise AgentLoopError(
            str(exc)
        ) from exc

    observations: list[Observation] = []
    evidence_store = EvidenceStore()
    command_evidence_store = CommandEvidenceStore()
    runtime_evidence_store = RuntimeEvidenceStore.discover(
        project_root
        or Path.cwd()
    )
    read_fingerprints: set[str] = set()
    read_file_paths: set[str] = set()
    attempted_discoveries: set[str] = set()
    attempted_probes: set[str] = set()
    blocked_mutations: set[str] = set()
    forced_action: NextAction | None = None
    invalid_model_actions = 0
    capability_resolution_attempts = 0
    semantic_resolution_attempts = 0
    prior_semantic_fail_reason: str | None = None
    capability_store = CapabilityCandidateStore()
    read_count = 0
    probe_count = 0
    decisions = 0

    # At most one initial concrete READ.
    for step_id in plan.ready_step_ids():
        step = next(
            x
            for x in plan.steps
            if x.step_id == step_id
        )

        if (
            step.tool is None
            or step.tool.permission != Permission.READ
        ):
            continue

        initial = NextAction(
            action="tool",
            reason=step.description,
            tool=step.tool,
            evidence_refs=[],
        )

        validate_evidence_bound_action(
            action=initial,
            evidence_store=evidence_store,
        )

        obs = _execute_read(
            step.tool,
            tool_registry,
            1,
        )

        observations.append(obs)
        read_count += 1

        if obs.success:
            read_fingerprints.add(
                _fingerprint(step.tool)
            )
            evidence_store.add_observation(
                obs
            )
            _remember_read_file(
                obs,
                read_file_paths,
            )
            _assess_read_for_capability(
                observation=obs,
                evidence_store=evidence_store,
                capability_store=capability_store,
            )
            # Candidate oluştuysa model'e gitmeden CAPABILITY_PROBE.
            forced_probe = _forced_capability_probe_action(
                evidence_store=evidence_store,
                tool_registry=tool_registry,
                runtime_evidence_store=(
                    runtime_evidence_store
                ),
                command_evidence_store=(
                    command_evidence_store
                ),
                capability_store=capability_store,
                attempted_discoveries=(
                    attempted_discoveries
                ),
                attempted_probes=attempted_probes,
            )
            if forced_probe is not None:
                forced_action = forced_probe

        break

    def _insufficient_evidence_result() -> AgentLoopPreviewResult:
        answer = (
            "Mutation icin yeterli kanit yok ve "
            "kesfedilecek bilinmeyen alan kalmadi."
        )
        return AgentLoopPreviewResult(
            plan=plan,
            observations=observations,
            evidence=evidence_store.records(),
            command_evidence=(
                command_evidence_store.records()
            ),
            runtime_evidence=(
                runtime_evidence_store.records()
            ),
            pending_action=NextAction(
                action="fail",
                reason=answer,
                answer=answer,
            ),
            completed=False,
            final_answer=answer,
            stop_reason="insufficient_evidence",
        )

    def _invalid_model_action_result(
        message: str,
    ) -> AgentLoopPreviewResult:
        answer = (
            "Model gecersiz action uretti ve "
            "kesfedilecek bilinmeyen alan kalmadi."
        )
        return AgentLoopPreviewResult(
            plan=plan,
            observations=observations,
            evidence=evidence_store.records(),
            command_evidence=(
                command_evidence_store.records()
            ),
            runtime_evidence=(
                runtime_evidence_store.records()
            ),
            pending_action=NextAction(
                action="fail",
                reason=message or answer,
                answer=answer,
            ),
            completed=False,
            final_answer=answer,
            stop_reason="invalid_model_action",
        )

    def _capability_resolution_failed_result(
        message: str | None = None,
    ) -> AgentLoopPreviewResult:
        answer = (
            message
            or (
                "Command Evidence mevcut ancak model "
                "gecerli grounded mutation uretemedi."
            )
        )
        return AgentLoopPreviewResult(
            plan=plan,
            observations=observations,
            evidence=evidence_store.records(),
            command_evidence=(
                command_evidence_store.records()
            ),
            runtime_evidence=(
                runtime_evidence_store.records()
            ),
            pending_action=NextAction(
                action="fail",
                reason=answer,
                answer=answer,
            ),
            completed=False,
            final_answer=answer,
            stop_reason="capability_resolution_failed",
        )

    def _capability_no_match_result(
        message: str | None = None,
    ) -> AgentLoopPreviewResult:
        answer = (
            message
            or (
                "Capability inventory mevcut ancak "
                "kullanici hedefiyle eslesen capability "
                "secilemedi."
            )
        )
        return AgentLoopPreviewResult(
            plan=plan,
            observations=observations,
            evidence=evidence_store.records(),
            command_evidence=(
                command_evidence_store.records()
            ),
            runtime_evidence=(
                runtime_evidence_store.records()
            ),
            pending_action=NextAction(
                action="fail",
                reason=answer,
                answer=answer,
            ),
            completed=False,
            final_answer=answer,
            stop_reason="capability_no_match",
        )

    def _on_blocked_mutation(
        *,
        blocked_action: NextAction,
        error_code: str,
        message: str,
        data: dict[str, Any],
    ) -> NextAction | None | Literal["fail", "capability_fail"]:
        identity = _mutation_identity(
            blocked_action
        )
        repeated = identity in blocked_mutations
        blocked_mutations.add(identity)

        observations.append(
            _control(
                len(observations) + 1,
                error_code,
                message,
                data,
            )
        )

        # Invariant: usable CommandEvidence varken
        # filesystem/capability discovery'ye donulmez.
        if command_evidence_store.records():
            capability_resolution_attempts += 1
            if (
                capability_resolution_attempts
                >= max_capability_resolution_attempts
            ):
                observations.append(
                    _control(
                        len(observations) + 1,
                        "REPEATED_UNGROUNDED_MUTATION",
                        "Command Evidence varken bounded "
                        "resolution tukendi. Filesystem "
                        "discovery yapilmayacak.",
                        data,
                    )
                )
                return "capability_fail"
            if repeated:
                observations.append(
                    _control(
                        len(observations) + 1,
                        "REPEATED_UNGROUNDED_MUTATION",
                        "Command Evidence varken ayni "
                        "mutation tekrar engellendi. "
                        "Filesystem discovery yapilmayacak.",
                        data,
                    )
                )
            return None

        discovery = _next_discovery_action(
            evidence_store=evidence_store,
            tool_registry=tool_registry,
            read_fingerprints=read_fingerprints,
            read_file_paths=read_file_paths,
            attempted_discoveries=(
                attempted_discoveries
            ),
            runtime_evidence_store=(
                runtime_evidence_store
            ),
            command_evidence_store=(
                command_evidence_store
            ),
            capability_store=capability_store,
            attempted_probes=attempted_probes,
        )

        if repeated:
            if discovery is None:
                summary = (
                    "Ayni mutation kanit yetersizken "
                    "tekrarlandi. Kesfedilecek "
                    "bilinmeyen alan kalmadi."
                )
            else:
                summary = (
                    "Ayni mutation kanit yetersizken "
                    "tekrarlandi. Once bilinmeyen "
                    "alan okunuyor."
                )

            observations.append(
                _control(
                    len(observations) + 1,
                    "REPEATED_UNGROUNDED_MUTATION",
                    summary,
                    data,
                )
            )

        if discovery is not None:
            return discovery

        if repeated:
            return "fail"

        return None

    while True:
        if forced_action is not None:
            action = forced_action
            forced_action = None
        else:
            if decisions >= max_decisions:
                return AgentLoopPreviewResult(
                    plan=plan,
                    observations=observations,
                    evidence=evidence_store.records(),
                    command_evidence=(
                        command_evidence_store.records()
                    ),
                    runtime_evidence=(
                        runtime_evidence_store.records()
                    ),
                    pending_action=None,
                    completed=False,
                    final_answer=None,
                    stop_reason="max_decisions",
                )

            deferred = _first_deferred_step(
                plan
            )
            decision_stage = (
                "deferred_step"
                if deferred is not None
                else "next_action"
            )

            try:
                has_command_evidence = bool(
                    command_evidence_store.records()
                )
                if (
                    deferred is not None
                    and has_command_evidence
                ):
                    # RESOLVE_WITH_CAPABILITY:
                    # inventory deterministic; model sadece ref secer.
                    inventory = build_capability_inventory(
                        command_evidence_store
                    )
                    if not inventory.options:
                        return _capability_no_match_result(
                            "Capability inventory bos; "
                            "secilebilir command token yok."
                        )

                    resolution = resolve_capability_selection(
                        goal=plan.goal,
                        target_step=deferred,
                        command_evidence_store=(
                            command_evidence_store
                        ),
                        model_client=model_client,
                        inventory=inventory,
                        model_role=(
                            capability_resolver_model_role
                        ),
                        prior_fail_reason=(
                            prior_semantic_fail_reason
                        ),
                    )
                    if resolution.decision == "fail":
                        decisions += 1
                        semantic_resolution_attempts += 1
                        observations.append(
                            _control(
                                len(observations) + 1,
                                "CAPABILITY_SEMANTIC_FAIL",
                                resolution.reason,
                                {
                                    "attempt": (
                                        semantic_resolution_attempts
                                    ),
                                    "max_attempts": (
                                        max_semantic_resolution_attempts
                                    ),
                                    "inventory_size": len(
                                        inventory.options
                                    ),
                                },
                            )
                        )
                        prior_semantic_fail_reason = (
                            resolution.reason
                        )
                        if (
                            semantic_resolution_attempts
                            >= max_semantic_resolution_attempts
                        ):
                            return _capability_no_match_result(
                                resolution.reason
                            )
                        continue

                    materialized = (
                        materialize_grounded_action(
                            resolution=resolution,
                            command_evidence_store=(
                                command_evidence_store
                            ),
                            evidence_store=evidence_store,
                            tool_registry=tool_registry,
                            inventory=inventory,
                        )
                    )
                    if materialized is None:
                        raise CapabilityResolverError(
                            "Capability select materialize "
                            "edilemedi."
                        )
                    action = NextAction(
                        action="tool",
                        reason=materialized.reason,
                        tool=materialized.tool,
                        evidence_refs=(
                            materialized.evidence_refs
                        ),
                        command_evidence_refs=(
                            materialized.command_evidence_refs
                        ),
                        runtime_ref=(
                            materialized.runtime_ref
                        ),
                    )
                elif deferred is not None:
                    action = resolve_deferred_step_action(
                        goal=plan.goal,
                        plan=plan,
                        target_step=deferred,
                        observations=observations,
                        evidence_store=evidence_store,
                        command_evidence_store=command_evidence_store,
                        runtime_evidence_store=runtime_evidence_store,
                        model_client=model_client,
                        tool_registry=tool_registry,
                        capability_store=capability_store,
                        resolve_with_capability=False,
                    )
                else:
                    action = decide_next_action(
                        goal=plan.goal,
                        plan=plan,
                        observations=observations,
                        model_client=model_client,
                        tool_registry=tool_registry,
                        evidence_store=evidence_store,
                    )
            except (
                AgentLoopError,
                CapabilityResolverError,
            ) as exc:
                decisions += 1
                invalid_model_actions += 1
                observations.append(
                    _control(
                        len(observations) + 1,
                        "MODEL_ACTION_INVALID",
                        str(exc),
                        {
                            "stage": decision_stage,
                            "resolve_with_capability": bool(
                                command_evidence_store.records()
                            ),
                        },
                    )
                )

                # Invariant: CommandEvidence varken
                # FILESYSTEM/CAPABILITY discovery'ye donme.
                if command_evidence_store.records():
                    capability_resolution_attempts += 1
                    if (
                        capability_resolution_attempts
                        >= max_capability_resolution_attempts
                    ):
                        return _capability_resolution_failed_result(
                            str(exc)
                        )
                    continue

                discovery = _next_discovery_action(
                    evidence_store=evidence_store,
                    tool_registry=tool_registry,
                    read_fingerprints=read_fingerprints,
                    read_file_paths=read_file_paths,
                    attempted_discoveries=(
                        attempted_discoveries
                    ),
                    runtime_evidence_store=(
                        runtime_evidence_store
                    ),
                    command_evidence_store=(
                        command_evidence_store
                    ),
                    capability_store=capability_store,
                    attempted_probes=attempted_probes,
                )

                if discovery is not None:
                    forced_action = discovery
                    continue

                return _invalid_model_action_result(
                    str(exc)
                )

            decisions += 1

        if action.action == "fail":
            return AgentLoopPreviewResult(
                plan=plan,
                observations=observations,
                evidence=evidence_store.records(),
                command_evidence=command_evidence_store.records(),
                runtime_evidence=runtime_evidence_store.records(),
                pending_action=action,
                completed=False,
                final_answer=action.answer,
                stop_reason="agent_failed",
            )

        if action.action == "complete":
            if _plan_requires_mutation(plan):
                observations.append(
                    _control(
                        len(observations) + 1,
                        "PREMATURE_COMPLETION_BLOCKED",
                        "Mutation gerektiren plan mutation "
                        "calistirilmadan tamamlanamaz.",
                        {},
                    )
                )
                continue

            return AgentLoopPreviewResult(
                plan=plan,
                observations=observations,
                evidence=evidence_store.records(),
                command_evidence=command_evidence_store.records(),
                runtime_evidence=runtime_evidence_store.records(),
                pending_action=None,
                completed=True,
                final_answer=action.answer,
                stop_reason="completed",
            )

        if action.tool is None:
            raise AgentLoopError(
                "tool action tool request icermiyor."
            )

        # RESOLVE_WITH_CAPABILITY: CommandEvidence varken
        # filesystem/capability discovery tool'larini reddet.
        if command_evidence_store.records():
            is_discovery_tool = (
                action.tool.permission == Permission.READ
                or (
                    action.tool.tool_name == "run_process"
                    and is_safe_capability_probe(
                        request=action.tool,
                        evidence_store=evidence_store,
                    )
                )
            )
            if is_discovery_tool:
                capability_resolution_attempts += 1
                observations.append(
                    _control(
                        len(observations) + 1,
                        "CAPABILITY_RESOLUTION_BLOCKED",
                        "Command Evidence varken filesystem "
                        "veya capability discovery yapilamaz.",
                        {
                            "tool_name": action.tool.tool_name,
                            "arguments": action.tool.arguments,
                            "cwd": action.tool.cwd,
                        },
                    )
                )
                if (
                    capability_resolution_attempts
                    >= max_capability_resolution_attempts
                ):
                    return _capability_resolution_failed_result()
                continue

        if action.tool.permission == Permission.READ:
            try:
                validate_evidence_bound_action(
                    action=action,
                    evidence_store=evidence_store,
                )
            except EvidenceValidationError as exc:
                observations.append(
                    _control(
                        len(observations) + 1,
                        "EVIDENCE_VALIDATION_BLOCKED",
                        str(exc),
                        {
                            "tool_name": action.tool.tool_name,
                            "arguments": action.tool.arguments,
                            "cwd": action.tool.cwd,
                            "evidence_refs": action.evidence_refs,
                        },
                    )
                )
                continue

        else:
            if (
                action.tool.tool_name == "run_process"
                and is_safe_capability_probe(
                    request=action.tool,
                    evidence_store=evidence_store,
                )
            ):
                logical_probe_action = action

                try:
                    bound_probe_action = _bind_action_runtime(
                        action=action,
                        runtime_evidence_store=runtime_evidence_store,
                    )
                except RuntimeGroundingError as exc:
                    observations.append(
                        _control(
                            len(observations) + 1,
                            "RUNTIME_GROUNDING_BLOCKED",
                            str(exc),
                            {
                                "arguments": logical_probe_action.tool.arguments,
                                "cwd": logical_probe_action.tool.cwd,
                                "runtime_ref": logical_probe_action.runtime_ref,
                            },
                        )
                    )
                    continue

                if probe_count >= max_probe_actions:
                    return AgentLoopPreviewResult(
                        plan=plan,
                        observations=observations,
                        evidence=evidence_store.records(),
                        command_evidence=command_evidence_store.records(),
                        runtime_evidence=runtime_evidence_store.records(),
                        pending_action=logical_probe_action,
                        completed=False,
                        final_answer=None,
                        stop_reason="max_probe_actions",
                    )

                probe_observation = _execute_read(
                    bound_probe_action.tool,
                    tool_registry,
                    len(observations) + 1,
                )

                raw_result = probe_observation.data
                probe_observation.tool_name = "command_probe"
                probe_observation.data = {
                    "request": {
                        "tool_name": logical_probe_action.tool.tool_name,
                        "arguments": logical_probe_action.tool.arguments,
                        "cwd": logical_probe_action.tool.cwd,
                        "runtime_ref": bound_probe_action.runtime_ref,
                    },
                    "result": raw_result,
                }

                observations.append(
                    probe_observation
                )
                probe_count += 1

                if probe_observation.success:
                    try:
                        command_evidence_store.add_probe_result(
                            request=logical_probe_action.tool,
                            result=raw_result,
                            source_observation_id=probe_observation.step_id,
                            evidence_store=evidence_store,
                            runtime_ref=bound_probe_action.runtime_ref,
                        )
                        # Basarili CommandEvidence → RESOLVE (model).
                        continue
                    except CommandGroundingError as exc:
                        observations.append(
                            _control(
                                len(observations) + 1,
                                "COMMAND_PROBE_REJECTED",
                                str(exc),
                                {},
                            )
                        )

                # Probe basarisiz: sonraki discovery (varsa) deterministic.
                next_discovery = _next_discovery_action(
                    evidence_store=evidence_store,
                    tool_registry=tool_registry,
                    read_fingerprints=read_fingerprints,
                    read_file_paths=read_file_paths,
                    attempted_discoveries=(
                        attempted_discoveries
                    ),
                    runtime_evidence_store=(
                        runtime_evidence_store
                    ),
                    command_evidence_store=(
                        command_evidence_store
                    ),
                    capability_store=capability_store,
                    attempted_probes=attempted_probes,
                )
                if next_discovery is not None:
                    forced_action = next_discovery
                continue

            try:
                validate_evidence_bound_action(
                    action=action,
                    evidence_store=evidence_store,
                )
            except EvidenceValidationError as exc:
                outcome = _on_blocked_mutation(
                    blocked_action=action,
                    error_code=(
                        "EVIDENCE_VALIDATION_BLOCKED"
                    ),
                    message=str(exc),
                    data={
                        "tool_name": action.tool.tool_name,
                        "arguments": action.tool.arguments,
                        "cwd": action.tool.cwd,
                        "evidence_refs": action.evidence_refs,
                    },
                )
                if outcome == "fail":
                    return _insufficient_evidence_result()
                if outcome == "capability_fail":
                    return _capability_resolution_failed_result(
                        str(exc)
                    )
                if isinstance(outcome, NextAction):
                    forced_action = outcome
                continue

            if action.tool.tool_name == "run_process":
                logical_mutation_action = action

                try:
                    runtime_binding = bind_runtime_request(
                        request=logical_mutation_action.tool,
                        store=runtime_evidence_store,
                        runtime_ref=logical_mutation_action.runtime_ref,
                    )
                except RuntimeGroundingError as exc:
                    observations.append(
                        _control(
                            len(observations) + 1,
                            "RUNTIME_GROUNDING_BLOCKED",
                            str(exc),
                            {
                                "arguments": logical_mutation_action.tool.arguments,
                                "cwd": logical_mutation_action.tool.cwd,
                                "runtime_ref": logical_mutation_action.runtime_ref,
                            },
                        )
                    )
                    continue

                selected_runtime_ref = (
                    runtime_binding.runtime.runtime_id
                    if runtime_binding is not None
                    else None
                )

                try:
                    command_evidence_store.validate_mutation_command(
                        request=logical_mutation_action.tool,
                        command_evidence_refs=(
                            logical_mutation_action.command_evidence_refs
                        ),
                        runtime_ref=selected_runtime_ref,
                    )
                except CommandGroundingError as exc:
                    outcome = _on_blocked_mutation(
                        blocked_action=logical_mutation_action,
                        error_code=(
                            "COMMAND_GROUNDING_BLOCKED"
                        ),
                        message=str(exc),
                        data={
                            "tool_name": (
                                logical_mutation_action.tool.tool_name
                            ),
                            "arguments": (
                                logical_mutation_action.tool.arguments
                            ),
                            "cwd": logical_mutation_action.tool.cwd,
                            "runtime_ref": selected_runtime_ref,
                            "command_evidence_refs": (
                                logical_mutation_action.command_evidence_refs
                            ),
                        },
                    )
                    if outcome == "fail":
                        return _insufficient_evidence_result()
                    if outcome == "capability_fail":
                        return _capability_resolution_failed_result(
                            str(exc)
                        )
                    if isinstance(outcome, NextAction):
                        forced_action = outcome
                    continue

                action = logical_mutation_action.model_copy(
                    update={
                        "runtime_ref": selected_runtime_ref,
                    }
                )

            return AgentLoopPreviewResult(
                plan=plan,
                observations=observations,
                evidence=evidence_store.records(),
                command_evidence=command_evidence_store.records(),
                runtime_evidence=runtime_evidence_store.records(),
                pending_action=action,
                completed=False,
                final_answer=None,
                stop_reason="mutation_action_ready",
            )

        fp = _fingerprint(
            action.tool
        )

        if fp in read_fingerprints:
            observations.append(
                _control(
                    len(observations) + 1,
                    "DUPLICATE_SUCCESSFUL_READ",
                    "Ayni basarili READ tekrar calistirilmadi.",
                    {},
                )
            )
            continue

        if read_count >= max_read_actions:
            return AgentLoopPreviewResult(
                plan=plan,
                observations=observations,
                evidence=evidence_store.records(),
                command_evidence=command_evidence_store.records(),
                runtime_evidence=runtime_evidence_store.records(),
                pending_action=action,
                completed=False,
                final_answer=None,
                stop_reason="max_read_actions",
            )

        obs = _execute_read(
            action.tool,
            tool_registry,
            len(observations) + 1,
        )

        observations.append(obs)
        read_count += 1

        if obs.success:
            read_fingerprints.add(fp)
            evidence_store.add_observation(
                obs
            )
            _remember_read_file(
                obs,
                read_file_paths,
            )
            _assess_read_for_capability(
                observation=obs,
                evidence_store=evidence_store,
                capability_store=capability_store,
            )
            # Classify sonrasi candidate varsa CAPABILITY_PROBE.
            forced_probe = _forced_capability_probe_action(
                evidence_store=evidence_store,
                tool_registry=tool_registry,
                runtime_evidence_store=(
                    runtime_evidence_store
                ),
                command_evidence_store=(
                    command_evidence_store
                ),
                capability_store=capability_store,
                attempted_discoveries=(
                    attempted_discoveries
                ),
                attempted_probes=attempted_probes,
            )
            if forced_probe is not None:
                forced_action = forced_probe
                continue

            # Candidate yoksa sonraki discovery'yi model'siz surdur.
            next_discovery = _next_discovery_action(
                evidence_store=evidence_store,
                tool_registry=tool_registry,
                read_fingerprints=read_fingerprints,
                read_file_paths=read_file_paths,
                attempted_discoveries=(
                    attempted_discoveries
                ),
                runtime_evidence_store=(
                    runtime_evidence_store
                ),
                command_evidence_store=(
                    command_evidence_store
                ),
                capability_store=capability_store,
                attempted_probes=attempted_probes,
            )
            if next_discovery is not None:
                forced_action = next_discovery
                continue
