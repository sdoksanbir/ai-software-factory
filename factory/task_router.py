from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TaskRoute:
    kind: str
    reason: str


TRANSLATION_TABLE = str.maketrans(
    {
        "\u0131": "i",
        "\u0130": "i",
        "\u015f": "s",
        "\u015e": "s",
        "\u011f": "g",
        "\u011e": "g",
        "\u00fc": "u",
        "\u00dc": "u",
        "\u00f6": "o",
        "\u00d6": "o",
        "\u00e7": "c",
        "\u00c7": "c",
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
    if _matches(clean, WRITE_PATTERNS):
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
