from __future__ import annotations

import json
from typing import Any

from factory.tools.patch import (
    PatchTool,
    PatchToolError,
)


def _extract_json_object(
    raw_text: str,
) -> dict[str, Any]:
    text = raw_text.strip()

    if not text:
        raise PatchToolError(
            "Model bos yanit dondurdu."
        )

    # Markdown JSON fence temizligi
    if text.startswith("```"):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    decoder = json.JSONDecoder()

    # Once tum metni JSON olarak dene.
    try:
        value = json.loads(text)

        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    # Basinda/sonunda aciklama varsa ilk gecerli
    # JSON object'i bul.
    for index, char in enumerate(text):
        if char != "{":
            continue

        try:
            value, _ = decoder.raw_decode(
                text[index:]
            )
        except json.JSONDecodeError:
            continue

        if isinstance(value, dict):
            return value

    preview = text[:700]

    raise PatchToolError(
        "Model yanitinda gecerli JSON object "
        "bulunamadi. Yanit baslangici:\n"
        f"{preview}"
    )


def _normalize_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    # Model bazen tek dosyayi dogrudan dondurebilir:
    # {"path": "...", "content": "..."}
    if (
        "files" not in payload
        and isinstance(payload.get("path"), str)
        and "content" in payload
    ):
        payload = {
            "files": [
                {
                    "path": payload["path"],
                    "content": payload["content"],
                }
            ],
            "explanation": payload.get(
                "explanation",
                "",
            ),
        }

    files = payload.get("files")

    # Tek object gelirse listeye cevir.
    if isinstance(files, dict):
        payload = dict(payload)
        payload["files"] = [files]

    return payload


def parse_model_patch_response(
    raw_text: str,
):
    payload = _extract_json_object(
        raw_text
    )

    payload = _normalize_payload(
        payload
    )

    normalized = json.dumps(
        payload,
        ensure_ascii=False,
    )

    try:
        return PatchTool.parse_multi_file_response(
            normalized
        )
    except PatchToolError as exc:
        preview = raw_text.strip()[:700]

        raise PatchToolError(
            f"{exc}\n\n"
            "Model yanit baslangici:\n"
            f"{preview}"
        ) from exc
