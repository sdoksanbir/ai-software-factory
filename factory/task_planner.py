import json
import re
from typing import Any

from factory.model_router import route_model
from factory.task_plan_store import save_task_plan
from factory.task_router import route_task


MAX_PLAN_STEPS = 6


_TURKISH_TRANSLATION = str.maketrans({
    0x00E7: "c",
    0x00C7: "c",
    0x011F: "g",
    0x011E: "g",
    0x0131: "i",
    0x0130: "i",
    0x00F6: "o",
    0x00D6: "o",
    0x015F: "s",
    0x015E: "s",
    0x00FC: "u",
    0x00DC: "u",
})


_COMPLEXITY_WORDS = {
    "api",
    "frontend",
    "backend",
    "database",
    "veritabani",
    "endpoint",
    "entegrasyon",
    "integration",
    "test",
    "tests",
}


_COMPLEXITY_CONNECTORS = {
    "ve",
    "ardindan",
    "sonra",
    "ayrica",
}


_WRITE_INTENT_WORDS = {
    "olustur",
    "ekle",
    "degistir",
    "guncelle",
    "sil",
    "duzelt",
    "uygula",
    "yaz",
    "kaydet",
    "create",
    "add",
    "change",
    "update",
    "delete",
    "remove",
    "fix",
    "implement",
    "write",
    "save",
    "rename",
}


def _normalize_for_matching(
    text: str,
) -> str:
    return (
        str(text or "")
        .casefold()
        .translate(_TURKISH_TRANSLATION)
    )


def _prompt_tokens(
    prompt: str,
) -> set[str]:
    normalized = _normalize_for_matching(
        prompt
    )

    return set(
        re.findall(
            r"[a-z0-9_]+",
            normalized,
        )
    )


def should_create_multi_step_plan(
    prompt: str,
) -> bool:
    clean = " ".join(
        str(prompt or "").split()
    ).strip()

    if not clean:
        raise ValueError(
            "prompt must not be blank"
        )

    tokens = _prompt_tokens(clean)

    domain_hits = len(
        tokens & _COMPLEXITY_WORDS
    )

    connector_hits = len(
        tokens & _COMPLEXITY_CONNECTORS
    )

    if domain_hits >= 2:
        return True

    if (
        domain_hits >= 1
        and connector_hits >= 1
    ):
        return True

    if len(clean) >= 180:
        return True

    if clean.count(",") >= 2:
        return True

    return False


def _single_step_kind(
    prompt: str,
) -> str:
    tokens = _prompt_tokens(prompt)

    if tokens & _WRITE_INTENT_WORDS:
        return "write"

    return route_task(prompt).kind


def _single_step_plan(
    prompt: str,
) -> list[dict[str, Any]]:
    return [
        {
            "title": "Gorevi tamamla",
            "instruction": prompt.strip(),
            "kind": _single_step_kind(
                prompt
            ),
            "status": "pending",
            "attempt": 0,
        }
    ]


def _extract_json_object(
    raw: str,
) -> dict[str, Any]:
    text = str(raw or "").strip()

    if not text:
        raise ValueError(
            "Planner returned empty response"
        )

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

    try:
        parsed = json.loads(text)

    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start < 0 or end <= start:
            raise ValueError(
                "Planner response does not "
                "contain JSON"
            )

        parsed = json.loads(
            text[start:end + 1]
        )

    if not isinstance(parsed, dict):
        raise ValueError(
            "Planner response must be "
            "a JSON object"
        )

    return parsed


def _normalize_model_steps(
    payload: dict[str, Any],
) -> tuple[
    str | None,
    list[dict[str, Any]],
]:
    raw_steps = payload.get("steps")

    if not isinstance(raw_steps, list):
        raise ValueError(
            "Planner response must "
            "contain steps"
        )

    if len(raw_steps) < 2:
        raise ValueError(
            "Multi-step plan must contain "
            "at least two steps"
        )

    if len(raw_steps) > MAX_PLAN_STEPS:
        raise ValueError(
            "Planner produced more than "
            f"{MAX_PLAN_STEPS} steps"
        )

    normalized = []

    for raw_step in raw_steps:
        if not isinstance(
            raw_step,
            dict,
        ):
            raise ValueError(
                "Each planner step must "
                "be an object"
            )

        title = str(
            raw_step.get("title") or ""
        ).strip()

        instruction = str(
            raw_step.get("instruction")
            or ""
        ).strip()

        kind = str(
            raw_step.get("kind") or ""
        ).strip().lower()

        if not title:
            raise ValueError(
                "Planner step title is blank"
            )

        if not instruction:
            raise ValueError(
                "Planner step instruction "
                "is blank"
            )

        if kind not in {
            "read",
            "write",
            "verify",
        }:
            raise ValueError(
                "Invalid planner step kind: "
                f"{kind}"
            )

        normalized.append(
            {
                "title": title,
                "instruction": instruction,
                "kind": kind,
                "status": "pending",
                "attempt": 0,
            }
        )

    summary = payload.get("summary")

    if summary is not None:
        summary = (
            str(summary).strip()
            or None
        )

    return summary, normalized


def build_task_plan(
    prompt: str,
    *,
    model_client: Any,
    model_name: str | None = None,
) -> dict[str, Any]:
    clean_prompt = str(
        prompt or ""
    ).strip()

    if not clean_prompt:
        raise ValueError(
            "prompt must not be blank"
        )

    if not should_create_multi_step_plan(
        clean_prompt
    ):
        return {
            "summary": "Tek adimli gorev",
            "steps": _single_step_plan(
                clean_prompt
            ),
            "planner_mode": "single_step",
        }

    selected_model = (
        model_name
        or route_model(
            clean_prompt
        ).model
    )

    response = model_client.complete(
        model_role="coder_local",
        system_prompt=(
            "Sen bir yazilim gorev "
            "planlayicisisin. "
            "Kod yazma veya dosya degistirme. "
            "Yalnizca uygulanabilir bir gorev "
            "plani uret. "
            "Yanitin sadece gecerli JSON olmali. "
            "Markdown kullanma. "
            "En az 2, en fazla 6 adim uret. "
            "Her adim tek bir net amaca "
            "sahip olmali. "
            "kind sadece read, write veya "
            "verify olabilir. "
            "read mevcut sistemi incelemek "
            "icindir. "
            "write dosya veya kod degisikligi "
            "icindir. "
            "verify test veya final dogrulama "
            "icindir. "
            "Gereksiz adim olusturma. "
            "Ayni isi birden fazla adima bolme. "
            "JSON semasi: "
            '{"summary":"kisa ozet",'
            '"steps":['
            '{"title":"kisa baslik",'
            '"instruction":"net gorev",'
            '"kind":"read|write|verify"}'
            "]}"
        ),
        user_prompt=(
            "KULLANICI GOREVI:\n"
            f"{clean_prompt}\n\n"
            "Bu gorevi uygulanabilir ve "
            "sirali adimlara ayir."
        ),
        temperature=0.0,
        model_name_override=selected_model,
    )

    payload = _extract_json_object(
        response.content
    )

    summary, steps = (
        _normalize_model_steps(
            payload
        )
    )

    return {
        "summary": summary,
        "steps": steps,
        "planner_mode": "multi_step",
    }


def create_and_save_task_plan(
    task_id: str,
    prompt: str,
    *,
    model_client: Any,
    model_name: str | None = None,
    db_path=None,
) -> dict[str, Any]:
    plan = build_task_plan(
        prompt,
        model_client=model_client,
        model_name=model_name,
    )

    save_kwargs = {}

    if db_path is not None:
        save_kwargs["db_path"] = db_path

    saved = save_task_plan(
        task_id,
        plan["steps"],
        summary=plan["summary"],
        **save_kwargs,
    )

    saved["planner_mode"] = (
        plan["planner_mode"]
    )

    return saved
