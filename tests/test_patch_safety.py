import json

import pytest

from factory.tools.patch import PatchTool, PatchToolError


def _patch(path: str, content: str):
    return PatchTool.parse_multi_file_response(
        json.dumps(
            {
                "files": [
                    {
                        "path": path,
                        "content": content,
                    }
                ],
                "explanation": "test",
            }
        )
    )


def test_rejects_catastrophic_shrink(tmp_path):
    target = tmp_path / "README.md"
    original = "\n".join(
        f"line {index}: " + ("x" * 40)
        for index in range(120)
    ) + "\n"
    target.write_text(original, encoding="utf-8")

    patch = _patch(
        "README.md",
        "# Tiny replacement\nshort\n",
    )

    with pytest.raises(
        PatchToolError,
        match="Destructive patch rejected",
    ):
        PatchTool.validate_non_destructive_edit(
            str(tmp_path),
            patch,
            prompt="README.md dosyasini guncelle",
        )


def test_append_task_must_preserve_existing_prefix(tmp_path):
    target = tmp_path / "README.md"
    original = "# Project\n\nExisting documentation.\n"
    target.write_text(original, encoding="utf-8")

    patch = _patch(
        "README.md",
        "# Completely rewritten\n",
    )

    with pytest.raises(
        PatchToolError,
        match="Append-style patch rejected",
    ):
        PatchTool.validate_non_destructive_edit(
            str(tmp_path),
            patch,
            prompt=(
                'README.md dosyasinin sonuna '
                '"Agent system test" baslikli bolum ekle.'
            ),
        )


def test_append_task_accepts_preserved_file(tmp_path):
    target = tmp_path / "README.md"
    original = "# Project\n\nExisting documentation.\n"
    target.write_text(original, encoding="utf-8")

    patch = _patch(
        "README.md",
        original + "\n## Agent system test\nOK\n",
    )

    PatchTool.validate_non_destructive_edit(
        str(tmp_path),
        patch,
        prompt=(
            'README.md dosyasinin sonuna '
            '"Agent system test" baslikli bolum ekle.'
        ),
    )
