import os
import subprocess
from dataclasses import dataclass


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    success: bool


class SandboxError(Exception):
    """Sandbox çalıştırma sırasında oluşan hatalar."""
    pass


class DockerSandbox:
    def __init__(self, image_name: str = "python:3.11-slim"):
        self.image_name = image_name

    def run_command(self, worktree_path: str, command: str, timeout_seconds: int = 60) -> SandboxResult:
        """
        Worktree yolunu izole bir Docker konteynerine volume olarak bağlar,
        ağ bağlantısını kapatarak verilen komutu (örn. pytest) çalıştırır.
        """
        abs_worktree = os.path.abspath(worktree_path)
        if not os.path.exists(abs_worktree):
            raise SandboxError(f"Worktree path does not exist for sandbox: {abs_worktree}")

        # Docker run komutu:
        # --rm: Çalışma bittikten sonra konteyneri sil
        # --network none: Dış dünya ile ağı tamamen kes (güvenlik için)
        # -v <worktree>:/app: Worktree klasörünü konteyner içindeki /app dizinine bağla
        # -w /app: Çalışma dizini olarak /app'i ayarla
        docker_args = [
            "docker", "run", "--rm",
            "--network", "none",
            "-v", f"{abs_worktree}:/app",
            "-w", "/app",
            self.image_name,
            "sh", "-c", command
        ]

        try:
            result = subprocess.run(
                docker_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                timeout=timeout_seconds
            )
            
            return SandboxResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                success=(result.returncode == 0)
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"Sandbox execution timed out after {timeout_seconds} seconds.",
                success=False
            )
        except FileNotFoundError:
            raise SandboxError("Docker is not installed or not found in system PATH.")
        except Exception as e:
            raise SandboxError(f"Failed to run sandbox container: {str(e)}")