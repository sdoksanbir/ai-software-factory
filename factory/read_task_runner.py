from __future__ import annotations

from pathlib import Path
from typing import Any

from factory.model_router import ModelRoute


SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    "AI-Worktrees",
}

TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
}

SKIP_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}

MAX_TREE_FILES = 250
MAX_CONTEXT_FILES = 35
MAX_FILE_CHARS = 6000
MAX_CONTEXT_CHARS = 55000


def _safe_relative(
    path: Path,
    root: Path,
) -> str:
    return path.relative_to(root).as_posix()


def _is_allowed(
    path: Path,
    root: Path,
) -> bool:
    relative = path.relative_to(root)

    if any(
        part in SKIP_DIRS
        for part in relative.parts
    ):
        return False

    if path.name in SKIP_FILES:
        return False

    return (
        path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
    )


def build_read_context(
    project_path: str,
) -> str:
    root = Path(project_path).resolve()

    if not root.exists():
        raise FileNotFoundError(
            f"Proje bulunamadi: {root}"
        )

    files: list[Path] = []

    for path in root.rglob("*"):
        try:
            if _is_allowed(path, root):
                files.append(path)
        except (OSError, ValueError):
            continue

    files.sort(
        key=lambda item: (
            len(item.relative_to(root).parts),
            item.as_posix().casefold(),
        )
    )

    tree = [
        _safe_relative(path, root)
        for path in files[:MAX_TREE_FILES]
    ]

    preferred_names = {
        "README.md",
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "config.yaml",
        "vite.config.ts",
        "tsconfig.json",
    }

    preferred = [
        path
        for path in files
        if path.name in preferred_names
    ]

    remaining = [
        path
        for path in files
        if path not in preferred
    ]

    selected = (
        preferred + remaining
    )[:MAX_CONTEXT_FILES]

    sections = [
        "PROJECT FILE TREE:",
        *tree,
        "",
        "SELECTED FILE CONTENTS:",
    ]

    used_chars = sum(
        len(item) + 1
        for item in sections
    )

    for path in selected:
        if used_chars >= MAX_CONTEXT_CHARS:
            break

        try:
            content = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        content = content[:MAX_FILE_CHARS]

        header = (
            "\n--- FILE: "
            + _safe_relative(path, root)
            + " ---\n"
        )

        remaining_chars = (
            MAX_CONTEXT_CHARS - used_chars
        )

        piece = (
            header + content
        )[:remaining_chars]

        sections.append(piece)
        used_chars += len(piece)

    return "\n".join(sections)


def run_read_task(
    project_path: str,
    prompt: str,
    model_route: ModelRoute,
    model_client: Any,
) -> str:
    context = build_read_context(
        project_path
    )

    system_prompt = (
        "Sen salt-okuma modunda calisan bir "
        "yazilim proje analiz ajanisin. "
        "Kullaniciya normal, okunabilir metinle cevap ver. "
        "JSON patch uretme. "
        "Dosya degisikligi onerisi yapabilirsin ancak "
        "hicbir dosyayi degistirme. "
        "Yalnizca verilen repository baglamina dayan. "
        "Bilmedigin bir noktada tahmin etme."
    )

    user_prompt = (
        "KULLANICI GOREVI:\n"
        f"{prompt}\n\n"
        "REPOSITORY BAGLAMI:\n"
        f"{context}\n\n"
        "Gorevi dogrudan cevapla."
    )

    response = model_client.complete(
        model_role="fast_local",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.2,
        model_name_override=model_route.model,
    )

    return response.content.strip()
