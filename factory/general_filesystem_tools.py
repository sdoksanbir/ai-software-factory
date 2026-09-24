from __future__ import annotations

from pathlib import Path
from typing import Any
import fnmatch

from factory.tool_registry import (
    ToolRegistry,
    build_contract_registry,
)


DEFAULT_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "coverage",
}

MAX_READ_BYTES = 1_000_000
MAX_WRITE_BYTES = 1_000_000
MAX_LIST_ITEMS = 500
MAX_FIND_RESULTS = 200


class FilesystemToolError(RuntimeError):
    pass


class UnsafeProjectPathError(
    FilesystemToolError
):
    pass


class FileTooLargeError(
    FilesystemToolError
):
    pass


class ProtectedProjectPathError(
    FilesystemToolError
):
    pass


def _project_root(
    project_path: str,
) -> Path:
    root = Path(
        project_path
    ).expanduser().resolve()

    if not root.exists():
        raise FilesystemToolError(
            f"Proje yolu bulunamadi: {root}"
        )

    if not root.is_dir():
        raise FilesystemToolError(
            f"Proje yolu klasor degil: {root}"
        )

    return root


def _resolve_inside(
    root: Path,
    raw_path: str | None,
) -> Path:
    value = (
        (raw_path or ".").strip()
        or "."
    )

    candidate_input = Path(value)

    if candidate_input.is_absolute():
        candidate = (
            candidate_input
            .expanduser()
            .resolve()
        )
    else:
        candidate = (
            root
            / candidate_input
        ).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeProjectPathError(
            "Proje kokunun disina erisim reddedildi: "
            f"{value}"
        ) from exc

    return candidate


def _relative(
    root: Path,
    path: Path,
) -> str:
    if path == root:
        return "."

    return (
        path.relative_to(root)
        .as_posix()
    )


def _is_skipped(
    root: Path,
    path: Path,
) -> bool:
    try:
        parts = path.relative_to(
            root
        ).parts
    except ValueError:
        return True

    return any(
        part in DEFAULT_SKIP_DIRS
        for part in parts
    )


def _assert_writable_path(
    root: Path,
    path: Path,
) -> None:
    try:
        parts = path.relative_to(
            root
        ).parts
    except ValueError as exc:
        raise UnsafeProjectPathError(
            "Proje kokunun disina yazma reddedildi."
        ) from exc

    protected = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
    }

    if any(
        part in protected
        for part in parts
    ):
        raise ProtectedProjectPathError(
            "Korunan proje yoluna yazma reddedildi: "
            + path.relative_to(root).as_posix()
        )


def _resolve_with_cwd(
    root: Path,
    *,
    cwd: str | None,
    path: str,
) -> Path:
    if cwd:
        base = _resolve_inside(
            root,
            cwd,
        )

        if not base.is_dir():
            raise FilesystemToolError(
                f"cwd klasor degil: {cwd}"
            )

        relative_base = _relative(
            root,
            base,
        )

        if relative_base == ".":
            combined = Path(path)
        else:
            combined = (
                Path(relative_base)
                / path
            )

        return _resolve_inside(
            root,
            str(combined),
        )

    return _resolve_inside(
        root,
        path,
    )


def _list_files_handler(
    root: Path,
):
    def handler(
        arguments: dict[str, Any],
        cwd: str | None,
    ) -> dict[str, Any]:
        base_raw = (
            cwd
            if cwd is not None
            else arguments.get(
                "path",
                ".",
            )
        )

        base = _resolve_inside(
            root,
            str(base_raw),
        )

        if not base.exists():
            raise FilesystemToolError(
                f"Yol bulunamadi: {_relative(root, base)}"
            )

        if not base.is_dir():
            raise FilesystemToolError(
                f"Yol klasor degil: {_relative(root, base)}"
            )

        entries = []

        for item in sorted(
            base.iterdir(),
            key=lambda value: (
                not value.is_dir(),
                value.name.casefold(),
            ),
        ):
            resolved = item.resolve()

            if _is_skipped(
                root,
                resolved,
            ):
                continue

            try:
                resolved.relative_to(root)
            except ValueError:
                continue

            entries.append(
                {
                    "path": _relative(
                        root,
                        resolved,
                    ),
                    "name": item.name,
                    "type": (
                        "directory"
                        if item.is_dir()
                        else "file"
                    ),
                }
            )

            if len(entries) >= MAX_LIST_ITEMS:
                break

        return {
            "base": _relative(
                root,
                base,
            ),
            "entries": entries,
            "truncated": (
                len(entries)
                >= MAX_LIST_ITEMS
            ),
        }

    return handler


def _find_files_handler(
    root: Path,
):
    def handler(
        arguments: dict[str, Any],
        cwd: str | None,
    ) -> dict[str, Any]:
        pattern = str(
            arguments["pattern"]
        ).strip()

        if not pattern:
            raise FilesystemToolError(
                "Arama deseni bos olamaz."
            )

        base = _resolve_inside(
            root,
            cwd or ".",
        )

        if not base.is_dir():
            raise FilesystemToolError(
                "Arama baslangic yolu klasor olmali."
            )

        matches: list[str] = []

        for path in base.rglob("*"):
            try:
                if not path.is_file():
                    continue

                resolved = path.resolve()

                if _is_skipped(
                    root,
                    resolved,
                ):
                    continue

                relative = _relative(
                    root,
                    resolved,
                )

                if (
                    fnmatch.fnmatch(
                        path.name,
                        pattern,
                    )
                    or fnmatch.fnmatch(
                        relative,
                        pattern,
                    )
                ):
                    matches.append(
                        relative
                    )

                if (
                    len(matches)
                    >= MAX_FIND_RESULTS
                ):
                    break
            except (
                OSError,
                ValueError,
            ):
                continue

        matches.sort()

        return {
            "pattern": pattern,
            "matches": matches,
            "count": len(matches),
            "truncated": (
                len(matches)
                >= MAX_FIND_RESULTS
            ),
        }

    return handler


def _read_file_handler(
    root: Path,
):
    def handler(
        arguments: dict[str, Any],
        cwd: str | None,
    ) -> dict[str, Any]:
        requested = str(
            arguments["path"]
        )

        path = _resolve_with_cwd(
            root,
            cwd=cwd,
            path=requested,
        )

        if not path.exists():
            raise FilesystemToolError(
                f"Dosya bulunamadi: {requested}"
            )

        if not path.is_file():
            raise FilesystemToolError(
                f"Yol dosya degil: {requested}"
            )

        size = path.stat().st_size

        if size > MAX_READ_BYTES:
            raise FileTooLargeError(
                "Dosya okuma sinirini asiyor: "
                f"{size} byte"
            )

        content = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        return {
            "path": _relative(
                root,
                path,
            ),
            "size_bytes": size,
            "content": content,
        }

    return handler


def _write_file_handler(
    root: Path,
):
    def handler(
        arguments: dict[str, Any],
        cwd: str | None,
    ) -> dict[str, Any]:
        requested = str(
            arguments["path"]
        )

        content = str(
            arguments["content"]
        )

        encoded = content.encode(
            "utf-8"
        )

        if len(encoded) > MAX_WRITE_BYTES:
            raise FileTooLargeError(
                "Dosya yazma sinirini asiyor: "
                f"{len(encoded)} byte"
            )

        path = _resolve_with_cwd(
            root,
            cwd=cwd,
            path=requested,
        )

        _assert_writable_path(
            root,
            path,
        )

        parent = path.parent

        _assert_writable_path(
            root,
            parent,
        )

        parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        existed_before = (
            path.exists()
        )

        if existed_before and not path.is_file():
            raise FilesystemToolError(
                f"Hedef dosya degil: {requested}"
            )

        temp_path = path.with_name(
            path.name + ".ai-factory-tmp"
        )

        _assert_writable_path(
            root,
            temp_path,
        )

        try:
            temp_path.write_text(
                content,
                encoding="utf-8",
            )

            temp_path.replace(
                path
            )
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass

        return {
            "path": _relative(
                root,
                path,
            ),
            "created": (
                not existed_before
            ),
            "overwritten": (
                existed_before
            ),
            "size_bytes": len(
                encoded
            ),
        }

    return handler


def _file_exists_handler(
    root: Path,
):
    def handler(
        arguments: dict[str, Any],
        cwd: str | None,
    ) -> dict[str, Any]:
        requested = str(
            arguments["path"]
        )

        candidate = _resolve_with_cwd(
            root,
            cwd=cwd,
            path=requested,
        )

        exists = candidate.exists()

        return {
            "path": _relative(
                root,
                candidate,
            ),
            "exists": exists,
            "type": (
                "directory"
                if exists
                and candidate.is_dir()
                else (
                    "file"
                    if exists
                    and candidate.is_file()
                    else None
                )
            ),
        }

    return handler


def build_filesystem_tool_registry(
    project_path: str,
) -> ToolRegistry:
    root = _project_root(
        project_path
    )

    registry = (
        build_contract_registry()
    )

    registry.bind_handler(
        "list_files",
        _list_files_handler(root),
    )
    registry.bind_handler(
        "find_files",
        _find_files_handler(root),
    )
    registry.bind_handler(
        "read_file",
        _read_file_handler(root),
    )
    registry.bind_handler(
        "file_exists",
        _file_exists_handler(root),
    )
    registry.bind_handler(
        "write_file",
        _write_file_handler(root),
    )

    return registry
