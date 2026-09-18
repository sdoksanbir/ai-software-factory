from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


FAST_MODEL = "llama3.1:8b"
CODER_MODEL = "qwen2.5-coder:14b"

# Bu modeller otomatik routing tarafindan secilmez.
UNSAFE_AUTO_MODELS = {
    "qwen2.5-coder:32b",
}


@dataclass(frozen=True)
class ModelRoute:
    model: str
    profile: str
    reason: str
    code_score: int


_CODE_PATTERNS = (
    r"\bpython\b",
    r"\btypescript\b",
    r"\bjavascript\b",
    r"\breact\b",
    r"\belectron\b",
    r"\bfastapi\b",
    r"\bsql\b",
    r"\bapi\b",
    r"\bfunction\b",
    r"\bclass\b",
    r"\bcomponent\b",
    r"\bendpoint\b",
    r"\bbug\b",
    r"\bdebug\b",
    r"\brefactor\b",
    r"\btest\b",
    r"\bbuild\b",
    r"\bcompile\b",
    r"\bpatch\b",
    r"\brepository\b",
    r"\brepo\b",
    r"\bgit\b",
    r"\bdocker\b",
    r"\bfrontend\b",
    r"\bbackend\b",
    r"\bcode\b",
    r"\bkod\b",
    r"\bfonksiyon\b",
    r"\bdosya\b",
    r"\bhata\b",
    r"\btestler\b",
    r"\bduzelt\b",
    r"\bolustur\b",
    r"\bekle\b",
    r"\bsil\b",
    r"\bdegistir\b",
    r"\.py\b",
    r"\.ts\b",
    r"\.tsx\b",
    r"\.js\b",
    r"\.jsx\b",
    r"\.json\b",
    r"\.css\b",
    r"\.html\b",
)


def _normalize_models(
    models: Iterable[str] | None,
) -> list[str]:
    if models is None:
        return []

    result: list[str] = []

    for model in models:
        name = str(model).strip()

        if not name:
            continue

        if name in UNSAFE_AUTO_MODELS:
            continue

        if name not in result:
            result.append(name)

    return result


def _code_score(prompt: str) -> int:
    normalized = prompt.casefold()

    score = 0

    for pattern in _CODE_PATTERNS:
        if re.search(pattern, normalized):
            score += 1

    # Kod bloklari veya shell benzeri komutlar kuvvetli sinyaldir.
    if "```" in prompt:
        score += 2

    if "/" in prompt or "\\" in prompt:
        score += 1

    return score


def _pick_available(
    preferred: str,
    fallback: str,
    available_models: list[str],
) -> str:
    # Liste verilmediyse router sadece politika karari verir.
    if not available_models:
        return preferred

    if preferred in available_models:
        return preferred

    if fallback in available_models:
        return fallback

    coder_candidates = [
        model
        for model in available_models
        if "coder" in model.casefold()
        and "32b" not in model.casefold()
    ]

    if coder_candidates:
        return coder_candidates[0]

    return available_models[0]


def route_model(
    prompt: str,
    available_models: Iterable[str] | None = None,
) -> ModelRoute:
    clean_prompt = prompt.strip()

    if not clean_prompt:
        raise ValueError("prompt bos olamaz")

    models = _normalize_models(
        available_models,
    )

    score = _code_score(clean_prompt)

    if score >= 1:
        selected = _pick_available(
            CODER_MODEL,
            FAST_MODEL,
            models,
        )

        return ModelRoute(
            model=selected,
            profile="coder_local",
            reason=(
                "Kodlama veya repository degisikligi "
                "sinyali algilandi."
            ),
            code_score=score,
        )

    selected = _pick_available(
        FAST_MODEL,
        CODER_MODEL,
        models,
    )

    return ModelRoute(
        model=selected,
        profile="fast_local",
        reason=(
            "Genel veya hafif gorev; hizli yerel "
            "model yeterli."
        ),
        code_score=score,
    )
