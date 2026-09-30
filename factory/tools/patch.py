import os
import json
import pathlib
import stat
from typing import List

from factory.schemas import MultiFilePatch


class PatchToolError(Exception):
    """Patch uygulama hataları."""
    pass


class PatchTool:
    @staticmethod
    def parse_multi_file_response(content: str) -> MultiFilePatch:
        cleaned = PatchTool._clean_markdown_fences(content).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise PatchToolError(
                f"Model response is not valid JSON: {e}"
            ) from e

        try:
            return MultiFilePatch.model_validate(data)
        except Exception as e:
            raise PatchToolError(
                f"Model response does not match multi-file schema: {e}"
            ) from e

    @staticmethod
    def _clean_markdown_fences(content: str) -> str:
        """Modelin eklediği ```python ... ``` tarzı markdown bloklarını temizler."""
        lines = content.strip().splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]

        return "\n".join(lines) + "\n"

    @staticmethod
    def _ensure_under_root(
        path: pathlib.Path,
        root: pathlib.Path,
        *,
        label: str,
    ) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PatchToolError(
                "Access denied: Path is outside worktree -> "
                f"{label}"
            ) from exc

    @staticmethod
    def normalize_relative_path(raw: str) -> str:
        text = (raw or "").strip()

        if not text:
            raise PatchToolError("Empty path rejected")

        if (
            os.path.isabs(text)
            or pathlib.PureWindowsPath(text).is_absolute()
            or pathlib.PurePosixPath(
                text.replace("\\", "/")
            ).is_absolute()
        ):
            raise PatchToolError(
                f"Absolute path rejected: {raw}"
            )

        parts: list[str] = []

        for part in pathlib.PurePosixPath(
            text.replace("\\", "/")
        ).parts:
            if part in ("", "."):
                continue

            if part == "..":
                raise PatchToolError(
                    f"Path traversal rejected: {raw}"
                )

            if part.casefold() == ".git":
                raise PatchToolError(
                    f".git path rejected: {raw}"
                )

            parts.append(part)

        if not parts:
            raise PatchToolError(
                "Project root path rejected"
            )

        return "/".join(parts)

    @staticmethod
    def resolve_safe_target(
        worktree_path: str,
        relative_path: str,
        *,
        must_exist: bool,
        for_delete: bool = False,
    ) -> pathlib.Path:
        """Resolve a project-relative mutation path.

        V1 policy: reject ANY symlink component (file or
        directory) so lexical scope cannot be bypassed via
        in-tree aliases. Also reject paths that would leave
        the worktree.
        """
        root = pathlib.Path(worktree_path).resolve()
        rel = PatchTool.normalize_relative_path(
            relative_path
        )
        parts = pathlib.PurePosixPath(rel).parts
        current = root

        for index, part in enumerate(parts):
            is_final = index == len(parts) - 1
            next_path = current / part

            if next_path.is_symlink():
                raise PatchToolError(
                    "Symlink path rejected for mutation: "
                    f"{relative_path}"
                )

            if next_path.exists():
                resolved = next_path.resolve()
                PatchTool._ensure_under_root(
                    resolved,
                    root,
                    label=relative_path,
                )

                if not is_final:
                    if not resolved.is_dir():
                        raise PatchToolError(
                            "Invalid path component "
                            f"(not a directory): {relative_path}"
                        )
                    current = resolved
                    continue

                if for_delete or must_exist:
                    if resolved.is_dir():
                        raise PatchToolError(
                            "Directory deletion is unsupported "
                            "in V1; emit explicit file delete "
                            f"entries instead: {relative_path}"
                        )

                    if not resolved.is_file():
                        raise PatchToolError(
                            "Delete target is not a regular "
                            f"file: {relative_path}"
                        )

                    return resolved

                if not resolved.is_file():
                    raise PatchToolError(
                        "Target path is not a file: "
                        f"{relative_path}"
                    )

                return resolved

            # Component does not exist.
            if must_exist or for_delete:
                raise PatchToolError(
                    "Delete target does not exist: "
                    f"{relative_path}"
                )

            remainder = pathlib.Path(*parts[index:])
            candidate = current / remainder
            PatchTool._ensure_under_root(
                candidate,
                root,
                label=relative_path,
            )

            parent = candidate.parent

            if parent.is_symlink():
                raise PatchToolError(
                    "Symlink path rejected for mutation: "
                    f"{relative_path}"
                )

            if parent.exists():
                parent_resolved = parent.resolve()
                PatchTool._ensure_under_root(
                    parent_resolved,
                    root,
                    label=relative_path,
                )

            return candidate

        raise PatchToolError(
            f"Unable to resolve path: {relative_path}"
        )

    @staticmethod
    def validate_non_destructive_edit(
        worktree_path: str,
        patch: MultiFilePatch,
        *,
        prompt: str = "",
    ) -> None:
        # DESTRUCTIVE_PATCH_GUARD_V2
        abs_base = pathlib.Path(worktree_path).resolve()
        prompt_folded = prompt.casefold()

        append_markers = (
            "sonuna",
            "sona ekle",
            "append",
            "at the end",
            "end of the file",
        )
        prepend_markers = (
            "basina",
            "başına",
            "prepend",
            "at the beginning",
            "beginning of the file",
        )

        append_intent = any(
            item in prompt_folded
            for item in append_markers
        )
        prepend_intent = any(
            item in prompt_folded
            for item in prepend_markers
        )

        for file_change in patch.files:
            if getattr(
                file_change,
                "operation",
                "write",
            ) == "delete":
                continue

            target_path = PatchTool.resolve_safe_target(
                str(abs_base),
                file_change.path,
                must_exist=False,
                for_delete=False,
            )

            if not target_path.exists() or not target_path.is_file():
                continue

            try:
                original = target_path.read_text(
                    encoding="utf-8",
                    errors="strict",
                )
            except (OSError, UnicodeError):
                continue

            proposed = PatchTool._clean_markdown_fences(
                file_change.content
            )

            original_norm = (
                original.replace("\\r\\n", "\\n")
                .replace("\\r", "\\n")
            )
            proposed_norm = (
                proposed.replace("\\r\\n", "\\n")
                .replace("\\r", "\\n")
            )

            if original_norm == proposed_norm:
                continue

            original_lines = max(
                1,
                len(original_norm.splitlines()),
            )
            proposed_lines = max(
                1,
                len(proposed_norm.splitlines()),
            )
            original_chars = max(
                1,
                len(original_norm),
            )
            proposed_chars = max(
                1,
                len(proposed_norm),
            )

            line_ratio = proposed_lines / original_lines
            char_ratio = proposed_chars / original_chars

            if (
                original_lines >= 80
                and original_chars >= 2000
                and line_ratio < 0.40
                and char_ratio < 0.55
            ):
                raise PatchToolError(
                    "Destructive patch rejected for "
                    f"{file_change.path}: existing file would shrink "
                    f"from {original_lines} to {proposed_lines} lines "
                    f"({line_ratio:.1%}) and from {original_chars} to "
                    f"{proposed_chars} chars ({char_ratio:.1%}). "
                    "Preserve unrelated existing content and return the "
                    "complete updated file."
                )

            if append_intent:
                original_body = original_norm.rstrip("\\n")
                proposed_body = proposed_norm.rstrip("\\n")

                if (
                    original_body
                    and not proposed_body.startswith(original_body)
                ):
                    raise PatchToolError(
                        "Append-style patch rejected for "
                        f"{file_change.path}: task asks to append content "
                        "but the proposed file does not preserve the "
                        "existing content as its prefix. Return the full "
                        "existing file plus only the requested addition."
                    )

            if prepend_intent:
                original_body = original_norm.lstrip("\\n")
                proposed_body = proposed_norm.lstrip("\\n")

                if (
                    original_body
                    and not proposed_body.endswith(original_body)
                ):
                    raise PatchToolError(
                        "Prepend-style patch rejected for "
                        f"{file_change.path}: task asks to prepend content "
                        "but the proposed file does not preserve the "
                        "existing content as its suffix."
                    )

    @staticmethod
    def _restore_item(
        *,
        target_path: pathlib.Path,
        existed: bool,
        original_bytes: bytes | None,
        original_mode: int | None,
    ) -> None:
        if existed and original_bytes is not None:
            target_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            target_path.write_bytes(original_bytes)

            if original_mode is not None:
                os.chmod(
                    target_path,
                    stat.S_IMODE(original_mode),
                )
            return

        if target_path.exists() and target_path.is_file():
            target_path.unlink()

    @staticmethod
    def apply_multi_file_patch(
        worktree_path: str,
        patch: MultiFilePatch,
    ) -> List[str]:
        abs_base = pathlib.Path(worktree_path).resolve()

        prepared = []
        seen_targets = set()

        # Validate every item before mutating anything.
        for file_change in patch.files:
            operation = getattr(
                file_change,
                "operation",
                "write",
            )

            if operation not in {"write", "delete"}:
                raise PatchToolError(
                    f"Unknown patch operation: {operation}"
                )

            target_path = PatchTool.resolve_safe_target(
                str(abs_base),
                file_change.path,
                must_exist=(operation == "delete"),
                for_delete=(operation == "delete"),
            )

            target_key = str(target_path).casefold()

            if target_key in seen_targets:
                raise PatchToolError(
                    "Duplicate target path in patch: "
                    f"{file_change.path}"
                )

            seen_targets.add(target_key)

            existed = target_path.exists()
            original_bytes = None
            original_mode = None

            if existed:
                original_bytes = target_path.read_bytes()
                original_mode = target_path.stat().st_mode

            cleaned_content = ""

            if operation == "write":
                cleaned_content = (
                    PatchTool._clean_markdown_fences(
                        file_change.content
                    )
                )

            prepared.append(
                (
                    operation,
                    target_path,
                    cleaned_content,
                    existed,
                    original_bytes,
                    original_mode,
                )
            )

        changed_files: list[str] = []
        applied: list[
            tuple[
                str,
                pathlib.Path,
                bool,
                bytes | None,
                int | None,
            ]
        ] = []

        try:
            for (
                operation,
                target_path,
                cleaned_content,
                existed,
                original_bytes,
                original_mode,
            ) in prepared:
                # Register BEFORE mutation so a partial write
                # failure still restores this current item.
                applied.append(
                    (
                        operation,
                        target_path,
                        existed,
                        original_bytes,
                        original_mode,
                    )
                )

                if operation == "write":
                    target_path.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )
                    parent_resolved = (
                        target_path.parent.resolve()
                    )
                    PatchTool._ensure_under_root(
                        parent_resolved,
                        abs_base,
                        label=str(target_path),
                    )
                    target_path.write_text(
                        cleaned_content,
                        encoding="utf-8",
                    )
                elif operation == "delete":
                    if (
                        not target_path.exists()
                        or not target_path.is_file()
                    ):
                        raise PatchToolError(
                            "Delete target missing at apply "
                            f"time: {target_path}"
                        )
                    target_path.unlink()
                else:
                    raise PatchToolError(
                        f"Unknown patch operation: {operation}"
                    )

                changed_files.append(str(target_path))

        except Exception as e:
            rollback_errors: list[str] = []

            for (
                operation,
                target_path,
                existed,
                original_bytes,
                original_mode,
            ) in reversed(applied):
                try:
                    PatchTool._restore_item(
                        target_path=target_path,
                        existed=existed,
                        original_bytes=original_bytes,
                        original_mode=original_mode,
                    )
                except Exception as restore_exc:
                    rollback_errors.append(
                        f"{target_path}: {restore_exc}"
                    )

            if rollback_errors:
                raise PatchToolError(
                    "Multi-file patch failed and rollback "
                    f"was incomplete: {e}. "
                    "Rollback errors: "
                    + "; ".join(rollback_errors)
                ) from e

            raise PatchToolError(
                "Multi-file patch failed and was "
                f"rolled back: {e}"
            ) from e

        return changed_files

    @staticmethod
    def apply_file_patch(
        worktree_path: str,
        file_path: str,
        content: str,
    ) -> str:
        """Belirtilen dosyaya temizlenmiş içeriği yazar (yoksa oluşturur)."""
        target_path = PatchTool.resolve_safe_target(
            worktree_path,
            file_path,
            must_exist=False,
            for_delete=False,
        )

        target_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        cleaned_content = PatchTool._clean_markdown_fences(
            content
        )

        try:
            target_path.write_text(
                cleaned_content,
                encoding="utf-8",
            )
            return str(target_path)
        except Exception as e:
            raise PatchToolError(
                f"Failed to write patch to {file_path}: {str(e)}"
            ) from e
