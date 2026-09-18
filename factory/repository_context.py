from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "ai-worktrees",
}

SKIP_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
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

ARCHITECTURE_ANCHORS = (
    "config.yaml",
    "api/app.py",
    "factory/orchestrator.py",
    "factory/task_router.py",
    "factory/model_router.py",
    "factory/read_task_runner.py",
    "factory/database.py",
    "factory/pipeline.py",
    "factory/control_center.py",
    "frontend/src/api.ts",
    "frontend/src/App.tsx",
    "frontend/package.json",
)

MAX_MAP_FILES = 140
MAX_SELECTED_FILES = 12
MAX_FILE_CHARS = 3200
MAX_CONTEXT_CHARS = 30000


@dataclass(frozen=True)
class RankedFile:
    path: Path
    relative: str
    score: int
    reasons: tuple[str, ...]


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


def normalize_text(
    value: str,
) -> str:
    return (
        value
        .translate(TRANSLATION_TABLE)
        .casefold()
    )


def _is_skipped_part(
    part: str,
) -> bool:
    value = normalize_text(part)

    if value in SKIP_DIRS:
        return True

    if value.startswith(".venv"):
        return True

    if value.startswith("venv"):
        return True

    if value == "site-packages":
        return True

    if value.endswith(".egg-info"):
        return True

    return False


def _is_allowed_file(
    path: Path,
    root: Path,
) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False

    if any(
        _is_skipped_part(part)
        for part in relative.parts
    ):
        return False

    if path.name in SKIP_FILES:
        return False

    return (
        path.is_file()
        and path.suffix.lower()
        in TEXT_SUFFIXES
    )


def scan_repository(
    project_path: str,
) -> list[Path]:
    root = Path(project_path).resolve()

    if not root.exists():
        raise FileNotFoundError(
            f"Repository bulunamadi: {root}"
        )

    files: list[Path] = []

    for path in root.rglob("*"):
        try:
            if _is_allowed_file(
                path,
                root,
            ):
                files.append(path)
        except OSError:
            continue

    return files


def _prompt_tokens(
    prompt: str,
) -> set[str]:
    normalized = normalize_text(prompt)

    raw_tokens = re.findall(
        r"[a-z0-9_.\-/]+",
        normalized,
    )

    ignored = {
        "bu",
        "bir",
        "ve",
        "ile",
        "icin",
        "olan",
        "olarak",
        "nedir",
        "nasil",
        "kisa",
        "sekilde",
        "mevcut",
        "proje",
        "projeyi",
        "projenin",
        "bana",
        "gorev",
    }

    return {
        token
        for token in raw_tokens
        if len(token) >= 3
        and token not in ignored
    }


def _is_general_overview(
    prompt: str,
) -> bool:
    value = normalize_text(prompt)

    markers = (
        "projeyi ozetle",
        "projenin mevcut yapisini",
        "projenin yapisini",
        "genel yapisini",
        "mimarisini",
        "proje mimarisi",
        "repository yapisi",
        "repo yapisi",
        "genel bakis",
    )

    return any(
        marker in value
        for marker in markers
    )


def _base_architecture_score(
    relative: str,
) -> int:
    normalized = normalize_text(relative)

    try:
        index = ARCHITECTURE_ANCHORS.index(
            relative
        )
        return 500 - (index * 10)
    except ValueError:
        pass

    if normalized.startswith("factory/"):
        return 120

    if normalized.startswith("api/"):
        return 115

    if normalized.startswith("frontend/src/"):
        return 105

    if normalized.startswith("tests/"):
        return 25

    if normalized.endswith(".md"):
        return 10

    return 50


def _safe_preview(
    path: Path,
    limit: int = 9000,
) -> str:
    try:
        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )[:limit]
    except OSError:
        return ""


def rank_repository_files(
    project_path: str,
    prompt: str,
) -> list[RankedFile]:
    root = Path(project_path).resolve()
    files = scan_repository(
        project_path
    )

    tokens = _prompt_tokens(prompt)
    prompt_normalized = normalize_text(
        prompt
    )

    asks_tests = any(
        marker in prompt_normalized
        for marker in (
            "test",
            "pytest",
            "unit test",
        )
    )

    asks_docs = any(
        marker in prompt_normalized
        for marker in (
            "readme",
            "dokuman",
            "documentation",
        )
    )

    overview = _is_general_overview(
        prompt
    )

    ranked: list[RankedFile] = []

    for path in files:
        relative = (
            path
            .relative_to(root)
            .as_posix()
        )

        relative_normalized = (
            normalize_text(relative)
        )

        score = _base_architecture_score(
            relative
        )

        reasons: list[str] = []

        # Promptta tam dosya/path geciyorsa en yuksek oncelik.
        if (
            relative_normalized
            in prompt_normalized
        ):
            score += 2000
            reasons.append(
                "explicit-path"
            )

        filename = normalize_text(
            path.name
        )

        stem = normalize_text(
            path.stem
        )

        for token in tokens:
            if token == filename:
                score += 900
                reasons.append(
                    f"filename:{token}"
                )

            elif token in filename:
                score += 350
                reasons.append(
                    f"filename-part:{token}"
                )

            elif token in relative_normalized:
                score += 180
                reasons.append(
                    f"path:{token}"
                )

            elif token in stem:
                score += 220
                reasons.append(
                    f"stem:{token}"
                )

        # Genel proje ozetinde mimari anchor dosyalari
        # ekstra onceliklidir.
        if (
            overview
            and relative
            in ARCHITECTURE_ANCHORS
        ):
            score += 700
            reasons.append(
                "architecture-overview"
            )

        # Kullanici istemediyse testleri geri plana at.
        if (
            relative_normalized
            .startswith("tests/")
            and not asks_tests
        ):
            score -= 250

        # Kullanici istemediyse README/dokumanlari geri plana at.
        if (
            path.suffix.lower() == ".md"
            and not asks_docs
        ):
            score -= 450

        # Icerik bazli ucuz relevance kontrolu.
        if tokens:
            preview = normalize_text(
                _safe_preview(path)
            )

            content_hits = 0

            for token in tokens:
                occurrences = min(
                    preview.count(token),
                    5,
                )

                content_hits += occurrences

            if content_hits:
                score += min(
                    content_hits * 18,
                    220,
                )

                reasons.append(
                    f"content:{content_hits}"
                )

        ranked.append(
            RankedFile(
                path=path,
                relative=relative,
                score=score,
                reasons=tuple(reasons),
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.score,
            len(
                item.relative.split("/")
            ),
            item.relative.casefold(),
        )
    )

    return ranked


def _balanced_overview_selection(
    ranked: list[RankedFile],
) -> list[RankedFile]:
    by_relative = {
        item.relative: item
        for item in ranked
    }

    selected: list[RankedFile] = []

    # Genel mimari sorusunda kritik katmanlari
    # bilincli olarak dengeli ekle.
    for relative in ARCHITECTURE_ANCHORS:
        item = by_relative.get(
            relative
        )

        if item is not None:
            selected.append(item)

    for item in ranked:
        if item in selected:
            continue

        selected.append(item)

        if (
            len(selected)
            >= MAX_SELECTED_FILES
        ):
            break

    return selected[
        :MAX_SELECTED_FILES
    ]


def select_context_files(
    project_path: str,
    prompt: str,
) -> list[RankedFile]:
    ranked = rank_repository_files(
        project_path,
        prompt,
    )

    if _is_general_overview(prompt):
        return _balanced_overview_selection(
            ranked
        )

    return ranked[
        :MAX_SELECTED_FILES
    ]


def build_repository_map(
    project_path: str,
) -> str:
    root = Path(project_path).resolve()

    files = scan_repository(
        project_path
    )

    relatives = sorted(
        (
            path.relative_to(root).as_posix()
            for path in files
        ),
        key=lambda value: (
            len(value.split("/")),
            value.casefold(),
        ),
    )

    visible = relatives[
        :MAX_MAP_FILES
    ]

    lines = [
        "REPOSITORY_MAP:",
        *visible,
    ]

    remaining = (
        len(relatives)
        - len(visible)
    )

    if remaining > 0:
        lines.append(
            f"... {remaining} additional files omitted"
        )

    return "\n".join(lines)


def build_smart_read_context(
    project_path: str,
    prompt: str,
) -> str:
    root = Path(project_path).resolve()

    selected = select_context_files(
        project_path,
        prompt,
    )

    sections = [
        f"PROJECT_ROOT: {root}",
        "",
        build_repository_map(
            project_path
        ),
        "",
        "SELECTED_FILES_BY_RELEVANCE:",
    ]

    for index, item in enumerate(
        selected,
        start=1,
    ):
        sections.append(
            (
                f"{index}. {item.relative} "
                f"(score={item.score})"
            )
        )

    sections.extend(
        [
            "",
            "SELECTED_FILE_CONTENTS:",
        ]
    )

    used_chars = sum(
        len(item) + 1
        for item in sections
    )

    for item in selected:
        if (
            used_chars
            >= MAX_CONTEXT_CHARS
        ):
            break

        content = _safe_preview(
            item.path,
            MAX_FILE_CHARS,
        )

        header = (
            "\n--- PROJECT FILE: "
            + item.relative
            + " ---\n"
        )

        remaining = (
            MAX_CONTEXT_CHARS
            - used_chars
        )

        piece = (
            header + content
        )[:remaining]

        sections.append(piece)
        used_chars += len(piece)

    return "\n".join(
        sections
    )
