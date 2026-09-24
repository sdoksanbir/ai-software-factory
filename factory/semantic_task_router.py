from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from factory.task_router import route_task


VALID_KINDS = {
    "read",
    "write",
    "execute",
}

VALID_INTENTS = {
    "explain_or_inspect",
    "code_change",
    "create_virtualenv",
    "ensure_pip",
    "package_install",
    "framework_scaffold",
    "run_tests",
    "run_build",
    "unknown",
}


@dataclass(frozen=True)
class SemanticTaskRoute:
    kind: str
    intent: str
    target: str | None
    framework: str | None
    confidence: float
    reason: str
    source: str = "semantic"


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()

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
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(
            r"\{[\s\S]*\}",
            text,
        )
        if match is None:
            raise ValueError(
                "Semantic router JSON cevabi bulunamadi."
            )
        value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise ValueError(
            "Semantic router cevabi JSON nesnesi olmali."
        )

    return value


def _clean_target(
    value: Any,
) -> str | None:
    if value is None:
        return None

    target = str(value).strip()

    if not target:
        return None

    if len(target) > 120:
        return None

    return target


def _validate_payload(
    payload: dict[str, Any],
) -> SemanticTaskRoute:
    kind = str(
        payload.get("kind", "")
    ).strip().casefold()

    intent = str(
        payload.get("intent", "unknown")
    ).strip().casefold()

    target = _clean_target(
        payload.get("target")
    )

    framework = _clean_target(
        payload.get("framework")
    )

    try:
        confidence = float(
            payload.get("confidence", 0.0)
        )
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = max(
        0.0,
        min(1.0, confidence),
    )

    reason = str(
        payload.get(
            "reason",
            "Semantic intent siniflandirmasi.",
        )
    ).strip()

    if kind not in VALID_KINDS:
        raise ValueError(
            f"Desteklenmeyen semantic kind: {kind!r}"
        )

    if intent not in VALID_INTENTS:
        intent = "unknown"

    if confidence < 0.70:
        raise ValueError(
            "Semantic router confidence esigin altinda."
        )

    return SemanticTaskRoute(
        kind=kind,
        intent=intent,
        target=target,
        framework=framework,
        confidence=confidence,
        reason=reason,
        source="semantic",
    )


def route_task_semantic(
    prompt: str,
    *,
    model_client: Any,
) -> SemanticTaskRoute:
    deterministic = route_task(prompt)

    system_prompt = (
        "Sen bir yazilim gorev intent routerisin. "
        "Kullanicinin NE YAPILMASINI istedigini siniflandir. "
        "Yalnizca gecerli JSON nesnesi dondur. "
        "Markdown kullanma. "
        "kind yalnizca read, write veya execute olabilir. "
        "READ: bilgi isteme, aciklama, inceleme, listeleme, soru sorma. "
        "WRITE: repository dosyasi/kodu/README/config icerigini "
        "olusturma, degistirme, silme veya refactor etme. "
        "EXECUTE: proje ortaminda gercek bir eylem calistirma; "
        "paket kurma, venv olusturma, pip hazirlama, test/build calistirma. "
        "Bir urun veya kutuphane adi tek basina sinifi belirlemez; "
        "fiilin ve tum cumlenin anlamina bak. "
        "Ornekler: "
        "'Django nedir?' => read/explain_or_inspect. "
        "'Django'nun en son surumunu kur' => execute/package_install, target django. "
        "'requirements.txt icine django ekle' => write/code_change. "
        "'venv olustur' => execute/create_virtualenv. "
        "'pip kur' => execute/ensure_pip. "
        "'testleri calistir' => execute/run_tests. "
        "'Bu klasorde okulprojesi adinda yeni bir Django projesi olustur' "
        "=> execute/framework_scaffold, framework django, target okulprojesi. "
        "Bir framework projesi olusturma istegini package_install olarak "
        "siniflandirma; paket kurmak ile proje scaffold etmek farkli eylemlerdir. "
        "Komut/shell metni URETME. "
        "JSON semasi: "
        '{"kind":"read|write|execute",'
        '"intent":"explain_or_inspect|code_change|create_virtualenv|'
        'ensure_pip|package_install|framework_scaffold|run_tests|run_build|unknown",'
        '"target":"hedef veya null",'
        '"framework":"framework veya null",'
        '"confidence":0.0,'
        '"reason":"kisa neden"}.'
    )

    user_prompt = (
        "KULLANICI GOREVI:\n"
        f"{prompt}\n\n"
        "Yalnizca JSON dondur."
    )

    try:
        response = model_client.complete(
            model_role="fast_local",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            timeout=45,
        )

        payload = _extract_json_object(
            response.content
        )

        return _validate_payload(
            payload
        )

    except Exception as exc:
        return SemanticTaskRoute(
            kind=deterministic.kind,
            intent="unknown",
            target=None,
            framework=None,
            confidence=1.0,
            reason=(
                "Semantic router kullanilamadi; "
                "deterministic fallback kullanildi. "
                f"Neden: {type(exc).__name__}"
            ),
            source="deterministic_fallback",
        )
