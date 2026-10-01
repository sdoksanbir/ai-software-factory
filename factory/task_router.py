from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TaskRoute:
    kind: str
    reason: str


TRANSLATION_TABLE = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
)


EXECUTE_PATTERNS = (
    # pip-install-execute-v1
    r"\bpip\b.*\b(kur|kurulum|yukle|install|setup|gerceklestir)\w*\b",
    r"\b(kur|kurulum|yukle|install|setup|gerceklestir)\w*\b.*\bpip\b",
    r"\bvenv\b.*\b(kur|olustur|hazirla)\b",
    r"\b(kur|olustur|hazirla)\b.*\bvenv\b",
    r"\bsanal ortam\b.*\b(kur|olustur|hazirla)\b",
    r"\b(kur|olustur|hazirla)\b.*\bsanal ortam\b",
    r"\bvirtual environment\b.*\b(create|setup|set up)\b",
    r"\b(create|setup|set up)\b.*\bvirtual environment\b",
    # Narrow run intents (not bare calistir).
    r"\b(testleri|testler|test|pytest|lint)\b.*\bcalistir\b",
    r"\bcalistir\b.*\b(testleri|testler|test|pytest|lint)\b",
    r"\bpython\b.*\bcalistir\b",
    r"\bcalistir\b.*\bpython\b",
    r"\bbuild\s+al\b",
)


WRITE_PATTERNS = (
    r"\bolustur\b",
    r"\bekle\b",
    r"\bduzelt\b",
    r"\bdegistir\b",
    r"\bguncelle\b",
    r"\bsil\b",
    r"\brefactor\b",
    r"\bimplement\b",
    r"\bcreate\b",
    r"\badd\b",
    r"\bfix\b",
    r"\bmodify\b",
    r"\bupdate\b",
    r"\bremove\b",
    r"\bdelete\b",
    r"\byaz\b",
    r"\btest ekle\b",
    r"\btestlerini ekle\b",
)


# Ambiguous creation verbs. Never treat these as WRITE alone.
_AMBIGUOUS_CREATION_VERBS = (
    r"\byap\b",
    r"\bhazirla\b",
    r"\btasarla\b",
)


# Strong implementation/UI artifact objects for compound WRITE.
_ARTIFACT_OBJECT_PATTERNS = (
    r"\bhtml\b",
    r"\bcss\b",
    r"\bscss\b",
    r"\breact\b",
    r"\bcomponent\b",
    r"\bbilesen\b",
    r"\bprototip\w*\b",
    r"\bweb\s+sayfa\w*\b",
    r"\bsayfa\w*\b",
    r"\bekran\w*\b",
    r"\bdashboard\b",
    r"\barayuz\w*\b",
    r"\bui\b",
    r"\btemplate\b",
)


# "dashboard analizi yap" is analysis, not artifact creation.
_ANALYSIS_YAP_SUPPRESS = re.compile(
    r"\banaliz\w*\s+yap\b"
)


READ_PATTERNS = (
    r"\bozetle\b",
    r"\bacikla\b",
    r"\bincele\b",
    r"\banaliz et\b",
    r"\blistele\b",
    r"\bgoster\b",
    r"\bne yapiyor\b",
    r"\bsummarize\b",
    r"\bexplain\b",
    r"\breview\b",
    r"\banalyze\b",
    r"\blist\b",
    r"\bshow\b",
)


def normalize_text(
    text: str,
) -> str:
    return (
        text
        .translate(TRANSLATION_TABLE)
        .casefold()
    )


def _matches(
    prompt: str,
    patterns: tuple[str, ...],
) -> bool:
    text = normalize_text(prompt)

    return any(
        re.search(pattern, text)
        for pattern in patterns
    )


def _has_artifact_creation_intent(
    prompt: str,
) -> bool:
    """Compound WRITE: artifact object + ambiguous creation verb.

    Bare yap/hazirla/tasarla alone never qualify.
    Analysis phrases like "dashboard analizi yap" are excluded.
    Object/action order may be either way.
    """
    text = normalize_text(prompt)

    if _ANALYSIS_YAP_SUPPRESS.search(text):
        return False

    has_artifact = any(
        re.search(pattern, text)
        for pattern in _ARTIFACT_OBJECT_PATTERNS
    )

    if not has_artifact:
        return False

    return any(
        re.search(pattern, text)
        for pattern in _AMBIGUOUS_CREATION_VERBS
    )


def route_task(
    prompt: str,
) -> TaskRoute:
    clean = prompt.strip()

    if not clean:
        raise ValueError(
            "prompt bos olamaz"
        )

    # Yerel proje ortaminda gercek bir eylem isteyen
    # gorevler READ/WRITE hattina gonderilmez.
    if _matches(clean, EXECUTE_PATTERNS):
        return TaskRoute(
            kind="execute",
            reason=(
                "Proje ortaminda gercek bir yerel "
                "eylem istegi algilandi."
            ),
        )

    # Acik bir degisiklik talebi varsa WRITE,
    # READ sinyalinden daha onceliklidir.
    if (
        _matches(clean, WRITE_PATTERNS)
        or _has_artifact_creation_intent(clean)
    ):
        return TaskRoute(
            kind="write",
            reason=(
                "Dosya veya kod degisikligi isteyen "
                "bir eylem algilandi."
            ),
        )

    if _matches(clean, READ_PATTERNS):
        return TaskRoute(
            kind="read",
            reason=(
                "Salt-okuma, analiz veya aciklama "
                "istegi algilandi."
            ),
        )

    # Belirsiz gorevlerde guvenli varsayim:
    # otomatik dosya degisikligi yapma.
    return TaskRoute(
        kind="read",
        reason=(
            "Acik bir dosya degisikligi talebi "
            "bulunmadigi icin salt-okuma secildi."
        ),
    )
