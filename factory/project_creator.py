from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def validate_project_name(name: str) -> str:
    clean = str(name or "").strip()

    if not clean:
        raise ValueError("Proje adi bos olamaz.")

    if clean in {".", ".."}:
        raise ValueError("Gecersiz proje adi.")

    if _INVALID_WINDOWS_CHARS.search(clean):
        raise ValueError(
            'Proje adi su karakterleri iceremez: < > : " / \\ | ? *'
        )

    if clean.endswith((" ", ".")):
        raise ValueError(
            "Proje adi bosluk veya nokta ile bitemez."
        )

    stem = clean.split(".", 1)[0].upper()
    if stem in _RESERVED_WINDOWS_NAMES:
        raise ValueError(
            f"Bu proje adi Windows tarafindan ayrilmistir: {clean}"
        )

    return clean


def planned_new_project_path(
    parent_path: str,
    project_name: str,
) -> Path:
    parent_text = str(parent_path or "").strip()
    if not parent_text:
        raise ValueError("Ana klasor yolu bos olamaz.")

    parent = Path(
        os.path.abspath(
            os.path.expanduser(parent_text)
        )
    )

    if not parent.is_dir():
        raise ValueError(
            f"Ana klasor bulunamadi: {parent}"
        )

    name = validate_project_name(project_name)
    return parent / name


def _run_git(
    args: list[str],
    *,
    cwd: Path,
) -> None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Git bulunamadi. Git kurulu ve PATH icinde olmali."
        ) from exc

    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"git {' '.join(args)} basarisiz oldu"
        )
        raise RuntimeError(detail)


def create_new_git_project(
    parent_path: str,
    project_name: str,
) -> str:
    target = planned_new_project_path(
        parent_path,
        project_name,
    )

    if target.exists():
        raise FileExistsError(
            f"Hedef klasor zaten mevcut: {target}"
        )

    target.mkdir(parents=False, exist_ok=False)

    try:
        (target / "README.md").write_text(
            f"# {project_name.strip()}\n\n"
            "Created by AI Software Factory.\n",
            encoding="utf-8",
        )

        (target / ".gitignore").write_text(
            "\n".join(
                [
                    ".venv/",
                    "venv/",
                    "__pycache__/",
                    "*.py[cod]",
                    "node_modules/",
                    "dist/",
                    "build/",
                    ".env",
                    ".DS_Store",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        _run_git(["init"], cwd=target)
        _run_git(["branch", "-M", "main"], cwd=target)
        _run_git(
            [
                "config",
                "user.name",
                "AI Software Factory",
            ],
            cwd=target,
        )
        _run_git(
            [
                "config",
                "user.email",
                "local@ai-software-factory",
            ],
            cwd=target,
        )
        _run_git(["add", "."], cwd=target)
        _run_git(
            ["commit", "-m", "Initial commit"],
            cwd=target,
        )

    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise

    return str(target.resolve())
