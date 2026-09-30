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


def project_name_slug(name: str) -> str:
    """Normalize a display name into a filesystem folder segment."""
    clean = validate_project_name(name)
    slug = re.sub(r"\s+", "-", clean.strip())
    slug = slug.strip(".-")
    if not slug:
        raise ValueError("Gecersiz proje adi.")

    stem = slug.split(".", 1)[0].upper()
    if stem in _RESERVED_WINDOWS_NAMES:
        raise ValueError(
            f"Bu proje adi Windows tarafindan ayrilmistir: {slug}"
        )

    if _INVALID_WINDOWS_CHARS.search(slug):
        raise ValueError(
            'Proje adi su karakterleri iceremez: < > : " / \\ | ? *'
        )

    return slug


def planned_new_project_path(
    parent_path: str,
    project_name: str,
) -> Path:
    parent_text = str(parent_path or "").strip()
    if not parent_text:
        raise ValueError("Ebeveyn klasor yolu bos olamaz.")

    parent = Path(
        os.path.abspath(
            os.path.expanduser(parent_text)
        )
    )

    if not parent.is_dir():
        raise ValueError(
            f"Ebeveyn klasor bulunamadi: {parent}"
        )

    folder_name = project_name_slug(project_name)
    return parent / folder_name


def path_has_git(project_path: str | Path) -> bool:
    root = Path(project_path)
    return (root / ".git").exists()


def normalize_project_path_for_storage(project_path: str) -> str:
    """Absolute, normalized path used when registering a project."""
    text = str(project_path or "").strip()
    if not text:
        raise ValueError("Proje yolu bos olamaz.")

    absolute = os.path.abspath(os.path.expanduser(text))
    normalized = os.path.normpath(absolute)

    try:
        resolved = Path(normalized).resolve()
        storage = str(resolved)
    except OSError:
        storage = normalized

    # Drop trailing separators without turning a drive root into empty.
    if os.name == "nt":
        drive, tail = os.path.splitdrive(storage)
        trimmed = tail.rstrip("\\/")
        if trimmed:
            storage = drive + trimmed
        else:
            storage = drive + "\\"
    else:
        trimmed = storage.rstrip("/")
        storage = trimmed if trimmed else "/"

    return storage


def canonical_project_path_key(project_path: str) -> str:
    """Comparison key: case-insensitive on Windows, trailing-sep insensitive."""
    storage = normalize_project_path_for_storage(project_path)
    if os.name == "nt":
        return os.path.normcase(storage)
    return storage


def project_paths_equivalent(left: str, right: str) -> bool:
    try:
        return (
            canonical_project_path_key(left)
            == canonical_project_path_key(right)
        )
    except ValueError:
        return False


def find_project_by_canonical_path(
    project_path: str,
    rows: list[dict],
) -> dict | None:
    key = canonical_project_path_key(project_path)
    for row in rows:
        row_path = str(row.get("path") or "")
        if not row_path:
            continue
        try:
            if canonical_project_path_key(row_path) == key:
                return row
        except ValueError:
            continue
    return None


def remove_newly_created_project_dir(
    target: Path,
    *,
    expected_parent: Path,
) -> None:
    """Delete only a child directory created by this request.

    Never deletes the parent. Raises RuntimeError if cleanup cannot proceed
    safely or fails.
    """
    try:
        target_resolved = target.resolve()
        parent_resolved = expected_parent.resolve()
    except OSError as exc:
        raise RuntimeError(
            f"Temizlik icin yol cozumlenemedi: {exc}"
        ) from exc

    if not target_resolved.exists():
        return

    if not target_resolved.is_dir():
        raise RuntimeError(
            f"Temizlik hedefi dizin degil: {target_resolved}"
        )

    if target_resolved.parent != parent_resolved:
        raise RuntimeError(
            "Temizlik reddedildi: hedef ebeveyn altinda degil "
            f"({target_resolved})"
        )

    if target_resolved == parent_resolved:
        raise RuntimeError(
            "Temizlik reddedildi: ebeveyn klasor silinemez."
        )

    try:
        shutil.rmtree(target_resolved)
    except OSError as exc:
        raise RuntimeError(
            f"Yeni olusturulan klasor silinemedi: {target_resolved} ({exc})"
        ) from exc


def inspect_project_folder(project_path: str) -> dict:
    text = str(project_path or "").strip()
    if not text:
        raise ValueError("Proje yolu bos olamaz.")

    root = Path(
        os.path.abspath(os.path.expanduser(text))
    )

    if not root.is_dir():
        raise ValueError(
            f"Proje klasoru bulunamadi: {root}"
        )

    characteristics: list[str] = []
    markers = {
        "package.json": "Node.js / npm",
        "pnpm-lock.yaml": "pnpm",
        "yarn.lock": "Yarn",
        "requirements.txt": "Python",
        "pyproject.toml": "Python",
        "Cargo.toml": "Rust",
        "go.mod": "Go",
        "pom.xml": "Java / Maven",
        "build.gradle": "Java / Gradle",
        "Dockerfile": "Docker",
    }
    for filename, label in markers.items():
        if (root / filename).exists():
            characteristics.append(label)

    return {
        "path": normalize_project_path_for_storage(str(root)),
        "exists": True,
        "has_git": path_has_git(root),
        "suggested_name": root.name,
        "characteristics": characteristics,
    }


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


def _write_readme(target: Path, project_name: str) -> None:
    (target / "README.md").write_text(
        f"# {project_name.strip()}\n\n"
        "Created by AI Software Factory.\n",
        encoding="utf-8",
    )


def _write_gitignore(target: Path) -> None:
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


def _bootstrap_git_repo(
    target: Path,
    *,
    initial_commit: bool,
) -> None:
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

    if not initial_commit:
        return

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(target),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if status.returncode != 0:
        return
    if not status.stdout.strip():
        return

    _run_git(["add", "."], cwd=target)
    _run_git(
        ["commit", "-m", "Initial commit"],
        cwd=target,
    )


def create_new_git_project(
    parent_path: str,
    project_name: str,
    *,
    init_git: bool = True,
    create_readme: bool = True,
    create_gitignore: bool = True,
) -> str:
    display_name = validate_project_name(project_name)
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
        if create_readme:
            _write_readme(target, display_name)

        if create_gitignore:
            _write_gitignore(target)

        if init_git:
            _bootstrap_git_repo(
                target,
                initial_commit=create_readme or create_gitignore,
            )

    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise

    return normalize_project_path_for_storage(str(target))


def init_git_in_existing_folder(project_path: str) -> str:
    """Initialize git inside an existing project root (not a parent folder)."""
    text = str(project_path or "").strip()
    if not text:
        raise ValueError("Proje yolu bos olamaz.")

    target = Path(
        os.path.abspath(os.path.expanduser(text))
    )

    if not target.is_dir():
        raise ValueError(
            f"Proje klasoru bulunamadi: {target}"
        )

    if path_has_git(target):
        raise FileExistsError(
            f"Bu klasorde zaten Git deposu var: {target}"
        )

    _bootstrap_git_repo(target, initial_commit=False)
    return normalize_project_path_for_storage(str(target))
