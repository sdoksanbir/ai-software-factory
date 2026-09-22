import os
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class GitWorktreeResult:
    task_id: str
    branch: str
    path: str
    repository_root: str


class GitOperationError(Exception):
    """Git komutları veya worktree işlemleri sırasında oluşan hatalar için temel exception."""
    pass


class NotAGitRepositoryError(GitOperationError):
    """Verilen yol bir git repository olmadığında fırlatılır."""
    pass


class BranchAlreadyExistsError(GitOperationError):
    """Oluşturulmak istenen branch zaten mevcut olduğunda fırlatılır."""
    pass


class WorktreeAlreadyExistsError(GitOperationError):
    """Aynı task için worktree klasörü veya kaydı zaten varsa fırlatılır."""
    pass


class UnsafeWorktreePathError(GitOperationError):
    """Worktree root ana repository'nin içinde veya kendisi olduğunda fırlatılır."""
    pass


class GitWorktreeManager:
    def __init__(self, project_path: str, worktree_root: str):
        self.project_path = os.path.abspath(project_path)
        self.worktree_root = os.path.abspath(worktree_root)
        self.repo_root = self._resolve_repository_root()
        self._validate_worktree_safety()

    def _validate_worktree_safety(self) -> None:
        """Worktree root'un ana repository'nin içinde olup olmadığını pathlib ile denetler."""
        repo_path = pathlib.Path(self.repo_root).resolve()
        wt_path = pathlib.Path(self.worktree_root).resolve()
        
        try:
            wt_path.relative_to(repo_path)
            raise UnsafeWorktreePathError(
                f"Worktree root cannot be inside the main repository:\n{self.worktree_root}"
            )
        except ValueError:
            pass

    def _run_git_command(self, args: list[str], cwd: Optional[str] = None) -> str:
        """Yardımcı metod: subprocess ile git komutlarını çalıştırır ve çıktıyı döner."""
        target_cwd = cwd if cwd else self.repo_root
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=target_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.strip() or e.stdout.strip()
            raise GitOperationError(f"Git command failed ('git {' '.join(args)}'): {err_msg}") from e
        except FileNotFoundError as e:
            raise GitOperationError("Git is not installed or not found in system PATH.") from e

    def _resolve_repository_root(self) -> str:
        """Verilen project_path veya alt klasörünün gerçek git kök dizinini (toplevel) bulur."""
        if not os.path.exists(self.project_path):
            raise NotAGitRepositoryError(f"Project path does not exist: {self.project_path}")
        
        try:
            root = self._run_git_command(["rev-parse", "--show-toplevel"], cwd=self.project_path)
            return os.path.abspath(root)
        except GitOperationError as e:
            raise NotAGitRepositoryError(f"Not a Git repository: {self.project_path}") from e

    def validate_repository(self) -> bool:
        """Verilen yolun geçerli bir git repository olduğunu doğrular."""
        try:
            root = self._run_git_command(["rev-parse", "--show-toplevel"])
            return os.path.isdir(root)
        except Exception:
            return False

    def _branch_exists(self, branch_name: str) -> bool:
        """Verilen branch adının lokalde var olup olmadığını kontrol eder."""
        try:
            output = self._run_git_command(["branch", "--list", branch_name])
            return bool(output.strip())
        except Exception:
            return False

    def create_worktree(self, task_id: str) -> GitWorktreeResult:
        """
        Verilen task_id için izole bir branch ve ana repo dışında worktree oluşturur.
        """
        if not self.validate_repository():
            raise NotAGitRepositoryError(f"Invalid repository root: {self.repo_root}")

        branch_name = f"agent/{task_id}"
        
        repo_name = os.path.basename(self.repo_root)
        worktree_path = os.path.join(self.worktree_root, repo_name, task_id)
        abs_worktree_path = os.path.abspath(worktree_path)

        if os.path.exists(abs_worktree_path):
            raise WorktreeAlreadyExistsError(f"Worktree already exists for {task_id} at: {abs_worktree_path}")

        try:
            wt_list = self._run_git_command(["worktree", "list", "--porcelain"])
            if abs_worktree_path.replace("\\", "/") in wt_list.replace("\\", "/"):
                raise WorktreeAlreadyExistsError(f"Git already tracks worktree for {task_id} at: {abs_worktree_path}")
        except GitOperationError:
            pass

        if self._branch_exists(branch_name):
            raise BranchAlreadyExistsError(f"Branch already exists: {branch_name}. Force creation is not allowed.")

        os.makedirs(os.path.dirname(abs_worktree_path), exist_ok=True)

        self._run_git_command(["worktree", "add", "-b", branch_name, abs_worktree_path])

        return GitWorktreeResult(
            task_id=task_id,
            branch=branch_name,
            path=abs_worktree_path,
            repository_root=self.repo_root
        )

    def get_status(self, worktree_path: str) -> str:
        """Verilen worktree yolundaki git status durumunu porcelain formatında döner."""
        abs_path = os.path.abspath(worktree_path)
        if not os.path.exists(abs_path):
            raise GitOperationError(f"Worktree path does not exist: {abs_path}")
        
        return self._run_git_command(["status", "--porcelain"], cwd=abs_path)

    def get_diff(self, worktree_path: str) -> str:
        """
        Verilen worktree yolundaki tracked (değişen/silinen) ve 
        untracked (yeni eklenen) tüm uncommitted değişikliklerin diff çıktısını döner.
        """
        abs_path = os.path.abspath(worktree_path)
        if not os.path.exists(abs_path):
            raise GitOperationError(f"Worktree path does not exist: {abs_path}")

        diff_parts = []

        # 1. Tracked dosyalardaki değişiklikler (modified, deleted)
        tracked_diff = self._run_git_command(["diff"], cwd=abs_path)
        if tracked_diff:
            diff_parts.append(tracked_diff)

        # 2. Untracked (yeni eklenen) dosyalar için staging area'yı bozmadan diff simülasyonu
        try:
            untracked_output = self._run_git_command(["ls-files", "--others", "--exclude-standard"], cwd=abs_path)
            if untracked_output:
                for rel_path in untracked_output.splitlines():
                    rel_path = rel_path.strip()
                    if not rel_path:
                        continue

                    full_path = os.path.abspath(os.path.join(abs_path, rel_path))
                    
                    # Path traversal koruması (worktree dışına çıkılmasını engelle)
                    if not full_path.startswith(abs_path):
                        continue

                    if os.path.isfile(full_path):
                        # Binary dosya tespiti
                        is_binary = False
                        try:
                            with open(full_path, "rb") as f:
                                chunk = f.read(8000)
                                if b"\x00" in chunk:
                                    is_binary = True
                        except Exception:
                            is_binary = True

                        if is_binary:
                            binary_diff = f"--- /dev/null\n+++ b/{rel_path}\nBinary file /dev/null and b/{rel_path} differ"
                            diff_parts.append(binary_diff)
                        else:
                            try:
                                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                    lines = f.readlines()
                                file_diff = [
                                    f"--- /dev/null",
                                    f"+++ b/{rel_path}",
                                    f"@@ -0,0 +1,{len(lines)} @@"
                                ]
                                for line in lines:
                                    file_diff.append("+" + (line if line.endswith("\n") else line + "\n"))
                                diff_parts.append("\n".join(file_diff))
                            except Exception:
                                pass
        except Exception:
            pass

        return "\n".join(diff_parts).strip()

    def commit_all(self, worktree_path: str, message: str) -> str:
        """Worktree içindeki tüm değişiklikleri commit eder ve commit hash döner."""
        abs_path = os.path.abspath(worktree_path)

        if not os.path.exists(abs_path):
            raise GitOperationError(f"Worktree path does not exist: {abs_path}")

        status = self.get_status(abs_path)
        if not status.strip():
            raise GitOperationError("No changes to commit.")

        self._run_git_command(["add", "-A"], cwd=abs_path)
        self._run_git_command(["commit", "-m", message], cwd=abs_path)

        return self._run_git_command(["rev-parse", "HEAD"], cwd=abs_path)


    def merge_branch(self, branch_name: str) -> str:
        """Verilen branch'i ana repository'de aktif branch'e birleştirir."""
        if not self._branch_exists(branch_name):
            raise GitOperationError(f"Branch does not exist: {branch_name}")

        main_status = self._run_git_command(
            ["status", "--porcelain"],
            cwd=self.repo_root
        )

        if main_status.strip():
            raise GitOperationError(
                "Main repository has uncommitted changes. Merge cancelled."
            )

        self._run_git_command(
            ["merge", "--no-ff", branch_name, "-m", f"Merge {branch_name}"],
            cwd=self.repo_root
        )

        return self._run_git_command(
            ["rev-parse", "HEAD"],
            cwd=self.repo_root
        )


    def abort_merge(self) -> None:
        # Ana repository'de devam eden merge islemini guvenli sekilde geri alir.
        self._run_git_command(
            ["merge", "--abort"],
            cwd=self.repo_root,
        )

    def remove_worktree(self, worktree_path: str, force: bool = False) -> None:
        """Git worktree kaydını ve klasörünü kaldırır."""
        abs_path = os.path.abspath(worktree_path)

        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(abs_path)

        self._run_git_command(args, cwd=self.repo_root)


    def delete_branch(self, branch_name: str, force: bool = False) -> None:
        """Yerel branch'i siler."""
        if not self._branch_exists(branch_name):
            return

        flag = "-D" if force else "-d"
        self._run_git_command(
            ["branch", flag, branch_name],
            cwd=self.repo_root
        )
