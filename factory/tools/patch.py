import os
import json
import pathlib
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
        
        # Eğer ilk satır ``` ile başlıyorsa ve son satır ``` ise bunları soy
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
            
        return "\n".join(lines) + "\n"

    @staticmethod
    def validate_non_destructive_edit(
        worktree_path: str,
        patch: MultiFilePatch,
        *,
        prompt: str = "",
    ) -> None:
        # DESTRUCTIVE_PATCH_GUARD_V2
        # Model tam dosya icerigi dondurdugu icin, mevcut buyuk bir dosyanin
        # neredeyse tamamen silinmesini yazmadan once engelle.
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
            target_path = pathlib.Path(
                os.path.abspath(
                    os.path.join(
                        str(abs_base),
                        file_change.path,
                    )
                )
            )

            try:
                target_path.relative_to(abs_base)
            except ValueError:
                raise PatchToolError(
                    "Access denied: Path is outside worktree -> "
                    f"{file_change.path}"
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

            # Genel felaket korumasi: buyuk bir mevcut dosya hem satir
            # hem karakter olarak dramatik bicimde kuculuyorsa reddet.
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

            # Prompt acikca sona ekleme istiyorsa mevcut dosya aynen
            # korunmali, sadece sonuna yeni icerik eklenmelidir.
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
    def apply_multi_file_patch(worktree_path: str, patch: MultiFilePatch) -> List[str]:
        abs_base = pathlib.Path(worktree_path).resolve()

        prepared = []
        seen_targets = set()

        # First validate every file before writing anything.
        for file_change in patch.files:
            target_path = pathlib.Path(
                os.path.abspath(
                    os.path.join(str(abs_base), file_change.path)
                )
            )

            try:
                target_path.relative_to(abs_base)
            except ValueError:
                raise PatchToolError(
                    f"Access denied: Path is outside worktree -> {file_change.path}"
                )

            target_key = str(target_path).lower()
            if target_key in seen_targets:
                raise PatchToolError(
                    f"Duplicate target path in patch: {file_change.path}"
                )

            seen_targets.add(target_key)

            if target_path.exists() and not target_path.is_file():
                raise PatchToolError(
                    f"Target path is not a file: {file_change.path}"
                )

            existed = target_path.exists()
            original_bytes = target_path.read_bytes() if existed else None

            cleaned_content = PatchTool._clean_markdown_fences(
                file_change.content
            )

            prepared.append(
                (
                    target_path,
                    cleaned_content,
                    existed,
                    original_bytes
                )
            )

        written_files = []

        try:
            for target_path, cleaned_content, _, _ in prepared:
                target_path.parent.mkdir(
                    parents=True,
                    exist_ok=True
                )

                target_path.write_text(
                    cleaned_content,
                    encoding="utf-8"
                )

                written_files.append(str(target_path))

        except Exception as e:
            # Restore every file to its original state.
            for target_path, _, existed, original_bytes in reversed(prepared):
                try:
                    if existed:
                        target_path.parent.mkdir(
                            parents=True,
                            exist_ok=True
                        )
                        target_path.write_bytes(original_bytes)
                    elif target_path.exists():
                        target_path.unlink()
                except Exception:
                    pass

            raise PatchToolError(
                f"Multi-file patch failed and was rolled back: {e}"
            ) from e

        return written_files

    @staticmethod
    def apply_file_patch(worktree_path: str, file_path: str, content: str) -> str:
        """Belirtilen dosyaya temizlenmiş içeriği yazar (yoksa oluşturur)."""
        abs_base = os.path.abspath(worktree_path)
        target_path = os.path.abspath(os.path.join(abs_base, file_path))
        
        # Güvenlik kontrolü: Dosya worktree dışına çıkmasın
        try:
            pathlib.Path(target_path).relative_to(pathlib.Path(abs_base).resolve())
        except ValueError:
            raise PatchToolError(f"Access denied: Path is outside worktree -> {file_path}")

        # Klasör yoksa oluştur
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        # Markdown kalıntılarını temizle
        cleaned_content = PatchTool._clean_markdown_fences(content)

        try:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(cleaned_content)
            return target_path
        except Exception as e:
            raise PatchToolError(f"Failed to write patch to {file_path}: {str(e)}")