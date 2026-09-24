from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from factory.general_agent_contracts import (
    GeneralTaskPlan,
    PlanStep,
)
from factory.tool_registry import (
    ToolRegistry,
    ToolRegistryError,
)


class GeneralPlannerError(RuntimeError):
    pass


def _extract_json_object(
    raw: str,
) -> dict[str, Any]:
    text = str(raw or "").strip()

    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]

        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start < 0 or end < start:
            raise GeneralPlannerError(
                "Planner gecerli JSON dondurmedi."
            )

        try:
            payload = json.loads(
                text[start : end + 1]
            )
        except json.JSONDecodeError as exc:
            raise GeneralPlannerError(
                "Planner JSON'i ayrıştırılamadı."
            ) from exc

    if not isinstance(payload, dict):
        raise GeneralPlannerError(
            "Planner sonucu JSON object olmali."
        )

    return payload


def _normalize_tool(
    raw: Any,
) -> dict[str, Any] | None:
    if raw is None:
        return None

    if not isinstance(raw, dict):
        raise GeneralPlannerError(
            "Step tool alani object veya null olmali."
        )

    tool_name = str(
        raw.get("tool_name")
        or raw.get("name")
        or ""
    ).strip()

    if not tool_name:
        raise GeneralPlannerError(
            "Tool name bos olamaz."
        )

    arguments = raw.get(
        "arguments",
        {},
    )

    if not isinstance(arguments, dict):
        raise GeneralPlannerError(
            f"{tool_name} arguments object olmali."
        )

    permission = str(
        raw.get("permission")
        or ""
    ).strip().casefold()

    return {
        "tool_name": tool_name,
        "arguments": arguments,
        "permission": permission,
        "cwd": raw.get("cwd"),
    }


def _normalize_plan_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(payload)

    raw_steps = normalized.get("steps")

    if not isinstance(raw_steps, list):
        raise GeneralPlannerError(
            "Planner steps list olmali."
        )

    steps = []

    for index, raw_step in enumerate(
        raw_steps,
        start=1,
    ):
        if not isinstance(raw_step, dict):
            raise GeneralPlannerError(
                f"Step {index} object olmali."
            )

        item = dict(raw_step)

        item.setdefault(
            "step_id",
            f"step-{index}",
        )

        item.setdefault(
            "description",
            str(
                item.get("title")
                or f"Step {index}"
            ),
        )

        if "permission" in item:
            item["permission"] = str(
                item["permission"]
            ).strip().casefold()

        item["tool"] = _normalize_tool(
            item.get("tool")
        )

        steps.append(item)

    normalized["steps"] = steps
    normalized.setdefault(
        "success_criteria",
        [],
    )
    normalized.setdefault(
        "constraints",
        [],
    )

    return normalized


def _slug_criterion_id(
    text: str,
    *,
    fallback_index: int,
) -> str:
    value = text.strip().casefold()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    ).strip("-")

    if not value:
        value = f"criterion-{fallback_index}"

    return value[:80]


def _normalize_verification_criteria(
    payload: dict[str, Any],
) -> dict[str, Any]:
    # Inline verification metinlerini top-level
    # success_criteria kaydina terfi ettir.
    normalized = dict(payload)

    raw_criteria = normalized.get(
        "success_criteria",
        [],
    )

    criteria: list[dict[str, Any]] = []
    known_ids: set[str] = set()
    description_to_id: dict[str, str] = {}

    if isinstance(raw_criteria, list):
        for index, raw in enumerate(
            raw_criteria,
            start=1,
        ):
            if not isinstance(raw, dict):
                continue

            item = dict(raw)

            criterion_id = str(
                item.get(
                    "criterion_id",
                    "",
                )
            ).strip()

            description = str(
                item.get(
                    "description",
                    "",
                )
            ).strip()

            if not criterion_id:
                criterion_id = _slug_criterion_id(
                    description,
                    fallback_index=index,
                )
                item["criterion_id"] = criterion_id

            item.setdefault(
                "required",
                True,
            )

            criteria.append(item)
            known_ids.add(criterion_id)

            if description:
                description_to_id[
                    description
                ] = criterion_id

    steps = []

    for step_index, raw_step in enumerate(
        normalized.get(
            "steps",
            [],
        ),
        start=1,
    ):
        item = dict(raw_step)

        raw_refs = item.get(
            "verification_criteria",
            [],
        )

        if not isinstance(raw_refs, list):
            raw_refs = []

        refs: list[str] = []

        for ref_index, raw_ref in enumerate(
            raw_refs,
            start=1,
        ):
            ref = str(raw_ref).strip()

            if not ref:
                continue

            if ref in known_ids:
                refs.append(ref)
                continue

            if ref in description_to_id:
                refs.append(
                    description_to_id[ref]
                )
                continue

            base_id = _slug_criterion_id(
                ref,
                fallback_index=(
                    step_index * 100
                    + ref_index
                ),
            )

            criterion_id = base_id
            suffix = 2

            while criterion_id in known_ids:
                criterion_id = (
                    f"{base_id}-{suffix}"
                )
                suffix += 1

            criteria.append(
                {
                    "criterion_id": criterion_id,
                    "description": ref,
                    "required": True,
                }
            )

            known_ids.add(criterion_id)
            description_to_id[
                ref
            ] = criterion_id
            refs.append(criterion_id)

        item[
            "verification_criteria"
        ] = refs

        steps.append(item)

    normalized[
        "success_criteria"
    ] = criteria

    normalized[
        "steps"
    ] = steps

    return normalized


def _defer_dependent_tool_calls(
    payload: dict[str, Any],
) -> dict[str, Any]:
    # Ilk statik plan observation sonucunu henuz bilmez.
    # Bu nedenle onceki step'lere bagimli tool cagirilari
    # somutlastirilmaz. Agent Loop observation sonrasi
    # bu step icin gercek tool request'i yeniden uretecek.
    normalized = dict(payload)

    steps = []

    for raw_step in normalized.get(
        "steps",
        [],
    ):
        item = dict(raw_step)

        depends_on = item.get(
            "depends_on",
            [],
        )

        if (
            isinstance(depends_on, list)
            and depends_on
            and item.get("tool") is not None
        ):
            item["tool"] = None

        steps.append(item)

    normalized["steps"] = steps

    return normalized


def _canonicalize_permissions(
    payload: dict[str, Any],
    registry: ToolRegistry,
) -> dict[str, Any]:
    # Tool permission modeli degil registry belirler.
    normalized = dict(payload)

    raw_steps = normalized.get(
        "steps",
        [],
    )

    canonical_steps = []

    for raw_step in raw_steps:
        item = dict(raw_step)

        tool = item.get(
            "tool"
        )

        if isinstance(
            tool,
            dict,
        ):
            tool_name = str(
                tool.get(
                    "tool_name",
                    ""
                )
            ).strip()

            if not tool_name:
                raise GeneralPlannerError(
                    "Tool name bos olamaz."
                )

            try:
                definition = registry.get(
                    tool_name
                )
            except ToolRegistryError as exc:
                raise GeneralPlannerError(
                    "Planner bilinmeyen tool uretti: "
                    f"{tool_name}"
                ) from exc

            permission = (
                definition
                .permission
                .value
            )

            canonical_tool = dict(
                tool
            )

            canonical_tool[
                "permission"
            ] = permission

            item[
                "tool"
            ] = canonical_tool

            item[
                "permission"
            ] = permission

        canonical_steps.append(
            item
        )

    normalized[
        "steps"
    ] = canonical_steps

    return normalized


def _validate_tool_references(
    plan: GeneralTaskPlan,
    registry: ToolRegistry,
) -> None:
    for step in plan.steps:
        if step.tool is None:
            continue

        try:
            registry.validate_request(
                step.tool
            )
        except ToolRegistryError as exc:
            raise GeneralPlannerError(
                f"Planner gecersiz tool request uretti "
                f"({step.step_id}): {exc}"
            ) from exc


def build_general_task_plan(
    prompt: str,
    *,
    model_client: Any,
    tool_registry: ToolRegistry,
    model_role: str = "fast_local",
    timeout: int = 60,
) -> GeneralTaskPlan:
    clean_prompt = str(
        prompt or ""
    ).strip()

    if not clean_prompt:
        raise GeneralPlannerError(
            "Kullanici gorevi bos olamaz."
        )

    tools = tool_registry.describe_for_model()

    system_prompt = (
        "Sen genel amacli bir AI ajan planlayicisisin. "
        "Gorevin kullanici istegini sabit intent isimlerine "
        "siniflandirmak DEGIL; hedefi gerceklestirmek icin "
        "genel araclarla uygulanabilir bir plan uretmektir. "
        "Yalnizca gecerli JSON dondur. Markdown kullanma.\n\n"
        "TEMEL KURALLAR:\n"
        "1. Bilmedigin proje yapisini ASLA varsayma. "
        "Konum, framework root, dosya veya mevcut durum "
        "bilinmiyorsa once READ tool ile kesfet.\n"
        "2. Kullanici 'bu projeye app ekle' diyorsa mevcut "
        "framework projesinin nerede oldugunu bulmadan "
        "create/start komutu planlama.\n"
        "3. Tool listesinde olmayan arac uydurma.\n"
        "4. Ham shell string uretme. run_process gerekiyorsa "
        "arguments.argv bir string listesi olmali.\n"
        "5. READ/WRITE/EXECUTE tum gorevin turu DEGIL; "
        "her step'in permission degeridir.\n"
        "6. Action sonrasinda sonucu kanitlayacak "
        "dogrulama adimi planla.\n"
        "7. Bir tool cwd'si onceki observation sonucuna "
        "bagliysa yol uydurma. O step'te tool=null birakabilir "
        "ve description icinde onceki observation'dan "
        "netlestirilecegini belirt.\n"
        "8. Kullanici sadece bilgi soruyorsa tool=null olan "
        "bir model/sentez step'i kullanabilirsin.\n"
        "9. Destructive islem planlama; gerekiyorsa constraint "
        "olarak belirt.\n"
        "10. Cikti tek ve eksiksiz bir JSON object olmali; aciklama veya "
        "Markdown ekleme.\n\n"
        "GECERLI JSON OUTPUT ORNEGI:\n"
        + json.dumps(
            {
                "goal": "asil hedef",
                "summary": "plan ozeti",
                "success_criteria": [
                    {
                        "criterion_id": "criterion-1",
                        "description": "basari kosulu",
                        "required": True,
                    }
                ],
                "constraints": [],
                "steps": [
                    {
                        "step_id": "step-1",
                        "title": "Projeyi kesfet",
                        "description": "Proje kokunu listele.",
                        "permission": "read",
                        "tool": {
                            "tool_name": "list_files",
                            "arguments": {"path": "."},
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
                        "step_id": "step-2",
                        "title": "Sonraki adimi uygula",
                        "description": (
                            "Onceki observation sonucuna gore tool "
                            "Agent Loop tarafindan netlestirilecek."
                        ),
                        "permission": "execute",
                        "tool": None,
                        "depends_on": ["step-1"],
                        "verification_criteria": ["criterion-1"],
                        "status": "pending",
                        "max_attempts": 2,
                        "attempt": 0,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n\n"
        "MEVCUT TOOL KATALOGU:\n"
        + json.dumps(
            tools,
            ensure_ascii=False,
            indent=2,
        )
    )

    user_prompt = (
        "KULLANICI GOREVI:\n"
        f"{clean_prompt}\n\n"
        "Bu gorevi gerceklestirmek icin genel ve uygulanabilir "
        "plan uret. Sadece JSON dondur."
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
        raise GeneralPlannerError(
            "Planner model cagrisi basarisiz: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    payload = _extract_json_object(
        getattr(
            response,
            "content",
            "",
        )
    )

    normalized = _normalize_plan_payload(
        payload
    )

    normalized = _normalize_verification_criteria(
        normalized
    )

    normalized = _defer_dependent_tool_calls(
        normalized
    )

    normalized = _canonicalize_permissions(
        normalized,
        tool_registry,
    )

    try:
        plan = GeneralTaskPlan.model_validate(
            normalized
        )
    except ValidationError as exc:
        raise GeneralPlannerError(
            "Planner GeneralTaskPlan semasina uymadi: "
            f"{exc}"
        ) from exc

    _validate_tool_references(
        plan,
        tool_registry,
    )

    return plan


def plan_uses_tool(
    plan: GeneralTaskPlan,
    tool_name: str,
) -> bool:
    return any(
        step.tool is not None
        and step.tool.tool_name == tool_name
        for step in plan.steps
    )


def first_tool_step(
    plan: GeneralTaskPlan,
) -> PlanStep | None:
    for step in plan.steps:
        if step.tool is not None:
            return step

    return None
