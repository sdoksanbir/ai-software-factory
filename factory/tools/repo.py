import os
import pathlib
from typing import List


class RepoToolError(Exception):
    """Repo araçları çalışırken oluşan hatalar."""
    pass


class RepoTool:
    @staticmethod
    def _validate_path(base_path: str, target_path: str) -> str:
        """Path traversal saldırılarını önlemek için dosyanın worktree içinde olduğunu doğrular."""
        base = pathlib.Path(base_path).resolve()
        target = pathlib.Path(target_path).resolve()
        
        try:
            target.relative_to(base)
        except ValueError:
            raise RepoToolError(f"Access denied: Path is outside the worktree root -> {target_path}")
        
        return str(target)

    @staticmethod
    def list_files(worktree_path: str, ignore_dirs: List[str] = None) -> List[str]:
        """Worktree içindeki tüm dosyaları göreceli yollarıyla listeler (.git, node_modules vb. hariç tutar)."""
        if ignore_dirs is None:
            ignore_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv", "test_worktrees"}

        abs_base = os.path.abspath(worktree_path)
        if not os.path.exists(abs_base):
            raise RepoToolError(f"Worktree path does not exist: {abs_base}")

        file_list = []
        for root, dirs, files in os.walk(abs_base):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, abs_base)
                file_list.append(rel_path)
                
        return file_list

    @staticmethod
    def read_file(worktree_path: str, file_path: str, max_lines: int = 2000) -> str:
        """Güvenli bir şekilde belirtilen dosyayı okur ve içeriğini döner."""
        abs_base = os.path.abspath(worktree_path)
        target_path = os.path.abspath(os.path.join(abs_base, file_path))
        
        safe_path = RepoTool._validate_path(abs_base, target_path)
        
        if not os.path.exists(safe_path) or not os.path.isfile(safe_path):
            raise RepoToolError(f"File not found or is not a file: {file_path}")

        try:
            with open(safe_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                
            if len(lines) > max_lines:
                return "".join(lines[:max_lines]) + f"\n... [Truncated: File exceeds {max_lines} lines]"
                
            return "".join(lines)
        except Exception as e:
            raise RepoToolError(f"Failed to read file {file_path}: {str(e)}")

    @staticmethod
    def search_code(worktree_path: str, keyword: str, file_extension: str = None) -> List[str]:
        """Worktree içinde basit bir metin/kod araması yapar."""
        abs_base = os.path.abspath(worktree_path)
        results = []
        
        files = RepoTool.list_files(abs_base)
        for rel_path in files:
            if file_extension and not rel_path.endswith(file_extension):
                continue
                
            full_path = os.path.join(abs_base, rel_path)
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, 1):
                        if keyword in line:
                            results.append(f"{rel_path}:{line_no}: {line.strip()}")
            except Exception:
                continue
                
        return results