import os
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


class GitWorktreeManager:
    def __init__(self, project_path: str, worktree_root: str):
        self.project_path = os.path.abspath(project_path)
        self.worktree_root = os.path.abspath(worktree_root)
        self.repo_root = self._resolve_repository_root()

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
        
        # Repo adı üzerinden worktree klasör yapısı kurgulanır
        repo_name = os.path.basename(self.repo_root)
        worktree_path = os.path.join(self.worktree_root, repo_name, task_id)
        abs_worktree_path = os.path.abspath(worktree_path)

        # 1. Worktree klasörü veya yolu sistemde halihazırda var mı?
        if os.path.exists(abs_worktree_path):
            raise WorktreeAlreadyExistsError(f"Worktree already exists for {task_id} at: {abs_worktree_path}")

        # Git tarafında worktree listesini kontrol et (çakışma ihtimaline karşı)
        try:
            wt_list = self._run_git_command(["worktree", "list", "--porcelain"])
            if abs_worktree_path.replace("\\", "/") in wt_list.replace("\\", "/"):
                raise WorktreeAlreadyExistsError(f"Git already tracks worktree for {task_id} at: {abs_worktree_path}")
        except GitOperationError:
            pass

        # 2. Branch zaten var mı?
        if self._branch_exists(branch_name):
            raise BranchAlreadyExistsError(f"Branch already exists: {branch_name}. Force creation is not allowed.")

        # 3. Worktree root klasörünün var olduğundan emin ol
        os.makedirs(os.path.dirname(abs_worktree_path), exist_ok=True)

        # 4. Git worktree komutunu çalıştır (Yeni branch ile birlikte)
        # git worktree add -b <branch> <path>
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