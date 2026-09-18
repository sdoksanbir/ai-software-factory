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
    def apply_multi_file_patch(worktree_path: str, patch: MultiFilePatch) -> List[str]:
        written_files = []

        for file_change in patch.files:
            written_path = PatchTool.apply_file_patch(
                worktree_path,
                file_change.path,
                file_change.content
            )
            written_files.append(written_path)

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