import hashlib
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


@dataclass(frozen=True)
class GitLocalChangesSnapshot:
    """Factory-owned stash snapshot of local working-tree changes."""

    commit_sha: str
    label: str


@dataclass(frozen=True)
class GitWorkingTreePathFingerprint:
    """Per-path fingerprint used by rollback concurrency guards."""

    path: str
    porcelain_status: str
    kind: str
    content_sha256: Optional[str]
    symlink_target: Optional[str]
    index_stages: tuple[str, ...]


@dataclass(frozen=True)
class GitWorkingTreeGuard:
    """
    Exact working-tree/index fingerprint captured before destructive rollback.

    Equality is content-based: concurrent edits to an already-owned path must
    change this guard and refuse reset --hard.
    """

    head_sha: str
    entries: tuple[GitWorkingTreePathFingerprint, ...]


class GitOperationError(Exception):
    """Git komutları veya worktree işlemleri sırasında oluşan hatalar için temel exception."""
    pass


class UnsafeRollbackError(GitOperationError):
    """
    Destructive rollback refused because the working tree contains paths
    that Factory cannot prove it owns (concurrent user/editor changes).
    """
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

    def _run_git_command_result(
        self,
        args: list[str],
        cwd: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Run a git command without treating exit code 1 as a hard raise."""
        target_cwd = cwd if cwd else self.repo_root
        try:
            return subprocess.run(
                ["git"] + args,
                cwd=target_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                check=False,
            )
        except FileNotFoundError as e:
            raise GitOperationError(
                "Git is not installed or not found in system PATH."
            ) from e

    def _run_git_command(self, args: list[str], cwd: Optional[str] = None) -> str:
        """Yardımcı metod: subprocess ile git komutlarını çalıştırır ve çıktıyı döner."""
        result = self._run_git_command_result(args, cwd=cwd)

        if result.returncode != 0:
            err_msg = (
                (result.stderr or "").strip()
                or (result.stdout or "").strip()
            )
            raise GitOperationError(
                f"Git command failed ('git {' '.join(args)}'): {err_msg}"
            )

        return (result.stdout or "").strip()

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
            wt_list = self._run_git_command(
                ["worktree", "list", "--porcelain"]
            )
        except GitOperationError:
            wt_list = ""

        if abs_worktree_path.replace("\\", "/") in (
            wt_list.replace("\\", "/")
        ):
            raise WorktreeAlreadyExistsError(
                f"Git already tracks worktree for {task_id} at: "
                f"{abs_worktree_path}"
            )

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

    def create_execute_worktree(self, task_id: str) -> GitWorktreeResult:
        """Create a disposable EXECUTE worktree on branch execute/<task_id>.

        Distinct from WRITE create_worktree (agent/<task_id>). Never used
        for approval merge.
        """
        if not self.validate_repository():
            raise NotAGitRepositoryError(
                f"Invalid repository root: {self.repo_root}"
            )

        clean_id = (task_id or "").strip()
        if not clean_id:
            raise GitOperationError(
                "EXECUTE worktree task_id bos olamaz."
            )

        branch_name = f"execute/{clean_id}"
        repo_name = os.path.basename(self.repo_root)
        worktree_path = os.path.join(
            self.worktree_root,
            repo_name,
            f"execute-{clean_id}",
        )
        abs_worktree_path = os.path.abspath(worktree_path)

        if os.path.exists(abs_worktree_path):
            raise WorktreeAlreadyExistsError(
                "Execute worktree already exists for "
                f"{clean_id} at: {abs_worktree_path}"
            )

        try:
            wt_list = self._run_git_command(
                ["worktree", "list", "--porcelain"]
            )
        except GitOperationError:
            wt_list = ""

        if abs_worktree_path.replace("\\", "/") in (
            wt_list.replace("\\", "/")
        ):
            raise WorktreeAlreadyExistsError(
                "Git already tracks execute worktree for "
                f"{clean_id} at: {abs_worktree_path}"
            )

        if self._branch_exists(branch_name):
            raise BranchAlreadyExistsError(
                f"Execute branch already exists: {branch_name}. "
                "Force creation is not allowed."
            )

        os.makedirs(
            os.path.dirname(abs_worktree_path),
            exist_ok=True,
        )

        self._run_git_command(
            [
                "worktree",
                "add",
                "-b",
                branch_name,
                abs_worktree_path,
            ]
        )

        return GitWorktreeResult(
            task_id=clean_id,
            branch=branch_name,
            path=abs_worktree_path,
            repository_root=self.repo_root,
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


    def get_head(
        self,
        ref: str = "HEAD",
        cwd: Optional[str] = None,
    ) -> str:
        """Resolve a ref to a full commit hash."""
        return self._run_git_command(
            ["rev-parse", ref],
            cwd=cwd if cwd else self.repo_root,
        )

    def get_repository_head(self) -> str:
        """Return the current HEAD commit of the main repository."""
        return self.get_head("HEAD")

    def get_branch_head(self, branch_name: str) -> str:
        """Return the tip commit of a local branch."""
        if not self._branch_exists(branch_name):
            raise GitOperationError(
                f"Branch does not exist: {branch_name}"
            )

        return self.get_head(branch_name)

    def is_ancestor(
        self,
        maybe_ancestor: str,
        maybe_descendant: str,
    ) -> bool:
        """
        Return whether maybe_ancestor is an ancestor of maybe_descendant
        (inclusive of equal commits).

        Exit-code semantics from `git merge-base --is-ancestor`:
          0 → True (is ancestor)
          1 → False (definitely not ancestor)
          other → raise GitOperationError (fail closed)
        """
        result = self._run_git_command_result(
            [
                "merge-base",
                "--is-ancestor",
                maybe_ancestor,
                maybe_descendant,
            ],
            cwd=self.repo_root,
        )

        if result.returncode == 0:
            return True

        if result.returncode == 1:
            return False

        err_msg = (
            (result.stderr or "").strip()
            or (result.stdout or "").strip()
            or f"exit code {result.returncode}"
        )
        raise GitOperationError(
            "Git ancestry check failed "
            f"('git merge-base --is-ancestor {maybe_ancestor} "
            f"{maybe_descendant}'): {err_msg}"
        )

    def get_repository_status(self) -> str:
        """Return porcelain status of the main repository working tree."""
        return self._run_git_command(
            ["status", "--porcelain"],
            cwd=self.repo_root,
        )

    def _normalize_repo_rel_path(self, raw_path: str) -> str:
        path = (raw_path or "").strip().strip('"').replace("\\", "/")
        if not path or path.startswith("/") or path.startswith("~"):
            raise GitOperationError(
                f"Unsafe repository path rejected: {raw_path!r}"
            )
        parts = pathlib.PurePosixPath(path).parts
        if any(part == ".." for part in parts):
            raise GitOperationError(
                f"Path traversal rejected: {raw_path!r}"
            )
        return path

    def _validated_repo_path(self, rel_path: str) -> pathlib.Path:
        """
        Map a repo-relative path to an absolute path without following a leaf
        symlink.

        - Parent directories are resolved and must remain inside the repo.
        - The leaf component is kept lexical so Path.is_symlink() observes the
          real leaf (not its target).
        """
        normalized = self._normalize_repo_rel_path(rel_path)
        repo = pathlib.Path(self.repo_root).resolve()
        parts = pathlib.PurePosixPath(normalized).parts
        if not parts:
            raise GitOperationError(
                f"Unsafe repository path rejected: {rel_path!r}"
            )

        candidate = repo.joinpath(*parts)
        try:
            parent = candidate.parent.resolve()
        except OSError as exc:
            raise GitOperationError(
                f"Cannot resolve parent for path: {rel_path!r}"
            ) from exc

        try:
            parent.relative_to(repo)
        except ValueError as exc:
            raise GitOperationError(
                f"Path escapes repository root: {rel_path!r}"
            ) from exc

        # Resolved parent + lexical leaf name — never resolve() the leaf.
        return parent / candidate.name

    def _rev_exists(self, rev: str) -> bool:
        result = self._run_git_command_result(
            ["rev-parse", "--verify", rev],
            cwd=self.repo_root,
        )
        return result.returncode == 0

    def _diff_name_only(self, old_rev: str, new_rev: str) -> set[str]:
        output = self._run_git_command(
            ["diff", "--name-only", f"{old_rev}..{new_rev}"],
            cwd=self.repo_root,
        )
        paths: set[str] = set()
        for line in output.splitlines():
            line = line.strip()
            if line:
                paths.add(self._normalize_repo_rel_path(line))
        return paths

    def _ls_tree_names(self, treeish: str) -> set[str]:
        output = self._run_git_command(
            ["ls-tree", "-r", "--name-only", treeish],
            cwd=self.repo_root,
        )
        paths: set[str] = set()
        for line in output.splitlines():
            line = line.strip()
            if line:
                paths.add(self._normalize_repo_rel_path(line))
        return paths

    def list_dirty_paths(self) -> set[str]:
        """Parse porcelain status into a set of repo-relative dirty paths."""
        paths: set[str] = set()
        for line in self.get_repository_status().splitlines():
            if len(line) < 4:
                continue
            entry = line[3:]
            if " -> " in entry:
                left, right = entry.split(" -> ", 1)
                paths.add(self._normalize_repo_rel_path(left))
                paths.add(self._normalize_repo_rel_path(right))
            else:
                paths.add(self._normalize_repo_rel_path(entry))
        return paths

    def list_snapshot_owned_paths(
        self,
        snapshot: GitLocalChangesSnapshot,
    ) -> set[str]:
        """
        Paths proven to belong to a Factory stash snapshot.

        Tracked: diff between stash base parent (^1) and WIP / index (^2).
        Untracked: tree of the --include-untracked parent (^3) when present.
        """
        sha = snapshot.commit_sha
        if not self._rev_exists(sha):
            raise GitOperationError(
                f"Snapshot commit not found: {sha}"
            )
        if not self._rev_exists(f"{sha}^1"):
            raise GitOperationError(
                f"Snapshot base parent missing: {sha}^1"
            )

        paths = self._diff_name_only(f"{sha}^1", sha)
        if self._rev_exists(f"{sha}^2"):
            paths |= self._diff_name_only(f"{sha}^1", f"{sha}^2")
        if self._rev_exists(f"{sha}^3"):
            paths |= self._ls_tree_names(f"{sha}^3")
        return paths

    def list_commit_range_paths(
        self,
        old_sha: str,
        new_sha: str,
    ) -> set[str]:
        """Paths changed between two commits (e.g. pre/post merge)."""
        return self._diff_name_only(old_sha, new_sha)

    def _list_stash_entries(self) -> list[tuple[str, str, str]]:
        """Return (commit_sha, stash_ref, subject) for each stash entry."""
        output = self._run_git_command(
            ["stash", "list", "--format=%H%x00%gd%x00%gs"],
            cwd=self.repo_root,
        )
        entries: list[tuple[str, str, str]] = []
        if not output.strip():
            return entries
        for line in output.splitlines():
            parts = line.split("\x00")
            if len(parts) < 3:
                continue
            sha, ref, subject = parts[0].strip(), parts[1].strip(), parts[2]
            if sha and ref:
                entries.append((sha, ref, subject))
        return entries

    def _stash_sha_set(self) -> set[str]:
        return {sha for sha, _ref, _subject in self._list_stash_entries()}

    def _stash_subject_has_label(self, subject: str, label: str) -> bool:
        """Match exact Factory label in `git stash push -m` subject."""
        subject = (subject or "").strip()
        label = (label or "").strip()
        if not label:
            return False
        if subject == label:
            return True
        # Typical subject: "On main: factory-approval-..."
        if ": " in subject and subject.rsplit(": ", 1)[-1] == label:
            return True
        return False

    def _identify_factory_stash_sha(
        self,
        *,
        label: str,
        before_shas: set[str],
    ) -> str:
        """
        Locate the Factory stash by unique label + new SHA.

        Never assumes refs/stash is Factory-owned.
        """
        matches: list[str] = []
        for sha, _ref, subject in self._list_stash_entries():
            if sha in before_shas:
                continue
            if self._stash_subject_has_label(subject, label):
                matches.append(sha)

        if len(matches) == 0:
            raise GitOperationError(
                "Factory stash not found after push for label "
                f"{label!r}; refusing to claim refs/stash"
            )
        if len(matches) > 1:
            raise GitOperationError(
                "Multiple Factory stash entries matched label "
                f"{label!r}: {matches}"
            )
        return matches[0]

    def _find_stash_ref_by_sha(self, commit_sha: str) -> str:
        """
        Resolve a Factory snapshot SHA to its current stash@{n} ref.

        Never assume stash@{0} — only match the tracked commit SHA.
        """
        needle = (commit_sha or "").strip()
        if not needle:
            raise GitOperationError(
                "Cannot locate stash snapshot: empty commit SHA"
            )

        for sha, ref, _subject in self._list_stash_entries():
            if sha == needle:
                return ref

        raise GitOperationError(
            f"Stash snapshot not found in stash list: {needle}"
        )

    def _after_stash_push_hook(self) -> None:
        """
        Test injection point after `stash push`, before Factory identity
        resolution. Production no-op.
        """
        return None

    def _verify_clean_after_preserve(self) -> str:
        """
        Hook point after stash push: return porcelain status.

        Tests may monkeypatch this to simulate a post-stash dirty failure
        while the real stash already exists.
        """
        return self.get_repository_status()

    def _ls_files_stage_by_path(self) -> dict[str, tuple[str, ...]]:
        output = self._run_git_command(
            ["ls-files", "--stage"],
            cwd=self.repo_root,
        )
        mapping: dict[str, list[str]] = {}
        for line in output.splitlines():
            if not line.strip():
                continue
            # "mode sha stage\tpath" — path may contain spaces after tab.
            if "\t" in line:
                meta, path = line.split("\t", 1)
            else:
                parts = line.split(None, 3)
                if len(parts) < 4:
                    continue
                path = parts[3]
            try:
                norm = self._normalize_repo_rel_path(path)
            except GitOperationError:
                continue
            mapping.setdefault(norm, []).append(line)
        return {path: tuple(rows) for path, rows in mapping.items()}

    def _fingerprint_path(
        self,
        rel_path: str,
        porcelain_status: str,
        stage_map: dict[str, tuple[str, ...]],
    ) -> GitWorkingTreePathFingerprint:
        norm = self._normalize_repo_rel_path(rel_path)
        stages = stage_map.get(norm, ())
        repo = pathlib.Path(self.repo_root).resolve()
        full = pathlib.Path(
            os.path.normpath(str(repo / pathlib.PurePosixPath(norm)))
        )

        # Bound check without requiring the leaf to exist.
        try:
            anchor = full.parent.resolve() if not full.exists() else (
                full.parent.resolve()
            )
            anchor.relative_to(repo)
        except Exception as exc:
            raise GitOperationError(
                f"Path escapes repository root: {rel_path!r}"
            ) from exc

        content_sha256: Optional[str] = None
        symlink_target: Optional[str] = None
        kind = "missing"

        if full.is_symlink():
            kind = "symlink"
            symlink_target = os.readlink(full)
        elif full.is_file():
            kind = "file"
            digest = hashlib.sha256()
            digest.update(full.read_bytes())
            content_sha256 = digest.hexdigest()
        elif full.is_dir():
            kind = "directory"
        elif "D" in (porcelain_status or ""):
            kind = "deleted"
        else:
            kind = "missing"

        return GitWorkingTreePathFingerprint(
            path=norm,
            porcelain_status=porcelain_status,
            kind=kind,
            content_sha256=content_sha256,
            symlink_target=symlink_target,
            index_stages=stages,
        )

    def capture_working_tree_guard(self) -> GitWorkingTreeGuard:
        """
        Capture an exact fingerprint of the current dirty working tree/index.

        Used after restore conflict and re-checked immediately before any
        destructive rollback.
        """
        head_sha = self.get_repository_head()
        stage_map = self._ls_files_stage_by_path()
        fingerprints: dict[str, GitWorkingTreePathFingerprint] = {}

        for line in self.get_repository_status().splitlines():
            if len(line) < 4:
                continue
            porcelain_status = line[:2]
            entry = line[3:]
            if " -> " in entry:
                left, right = entry.split(" -> ", 1)
                path_items = [left, right]
            else:
                path_items = [entry]

            for raw_path in path_items:
                fp = self._fingerprint_path(
                    raw_path,
                    porcelain_status,
                    stage_map,
                )
                fingerprints[fp.path] = fp

        ordered = tuple(
            fingerprints[path]
            for path in sorted(fingerprints.keys())
        )
        return GitWorkingTreeGuard(
            head_sha=head_sha,
            entries=ordered,
        )

    def _show_blob_bytes(self, rev_path: str) -> bytes:
        try:
            binary = subprocess.run(
                ["git", "show", rev_path],
                cwd=self.repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError as e:
            raise GitOperationError(
                "Git is not installed or not found in system PATH."
            ) from e
        if binary.returncode != 0:
            err = (binary.stderr or b"").decode(
                "utf-8",
                errors="replace",
            ).strip()
            raise GitOperationError(
                f"Git show failed for {rev_path!r}: {err}"
            )
        return binary.stdout

    def _remove_verified_snapshot_untracked(
        self,
        snapshot: GitLocalChangesSnapshot,
    ) -> None:
        """
        Delete only untracked files proven to match snapshot^3 blobs.

        Never runs `git clean`. Skips symlinks and content mismatches.
        """
        sha = snapshot.commit_sha
        if not self._rev_exists(f"{sha}^3"):
            return

        for rel in sorted(self._ls_tree_names(f"{sha}^3")):
            full = self._validated_repo_path(rel)
            if full.is_symlink():
                raise UnsafeRollbackError(
                    "Refusing to remove symlink during snapshot cleanup: "
                    f"{rel}"
                )
            if not full.is_file():
                continue
            expected = self._show_blob_bytes(f"{sha}^3:{rel}")
            actual = full.read_bytes()
            if actual != expected:
                raise UnsafeRollbackError(
                    "Refusing to remove untracked path with unexpected "
                    f"content: {rel}"
                )
            full.unlink()

    def preserve_local_changes(
        self,
        label: str,
    ) -> GitLocalChangesSnapshot:
        """
        Temporarily stash tracked + untracked local changes on the main repo.

        Identifies the Factory stash by unique label + SHA set difference —
        never by assuming refs/stash is Factory-owned.

        Atomic UX: on post-stash verification failure, restore the working
        tree (and drop the snapshot when restore succeeds) before raising.
        """
        status = self.get_repository_status()
        if not status.strip():
            raise GitOperationError(
                "No local changes to preserve"
            )

        before_shas = self._stash_sha_set()

        self._run_git_command(
            [
                "stash",
                "push",
                "--include-untracked",
                "-m",
                label,
            ],
            cwd=self.repo_root,
        )

        # Allow tests to inject an intervening stash before identity resolve.
        self._after_stash_push_hook()

        try:
            commit_sha = self._identify_factory_stash_sha(
                label=label,
                before_shas=before_shas,
            )
        except GitOperationError as identify_exc:
            raise GitOperationError(
                "Failed to identify Factory stash after push for label "
                f"{label!r}: {identify_exc}"
            ) from identify_exc

        snapshot = GitLocalChangesSnapshot(
            commit_sha=commit_sha,
            label=label,
        )

        remaining = self._verify_clean_after_preserve()
        if remaining.strip():
            restore_error = None
            try:
                self.restore_local_changes(
                    snapshot,
                    restore_index=True,
                )
            except Exception as exc:
                restore_error = exc

            if restore_error is not None:
                raise GitOperationError(
                    "Repository still dirty after preserving local "
                    f"changes ({remaining.strip()}), and restoring the "
                    f"working tree failed: {restore_error}. "
                    f"Factory snapshot retained for recovery: "
                    f"{commit_sha} ({label})"
                ) from restore_error

            try:
                self.drop_local_changes_snapshot(snapshot)
            except Exception as drop_exc:
                raise GitOperationError(
                    "Repository still dirty after preserving local "
                    f"changes; working tree was restored but snapshot "
                    f"cleanup failed for {commit_sha}: {drop_exc}"
                ) from drop_exc

            raise GitOperationError(
                "Repository still dirty after preserving local changes; "
                "user working tree was restored: "
                f"{remaining.strip()}"
            )

        return snapshot

    def restore_local_changes(
        self,
        snapshot: GitLocalChangesSnapshot,
        *,
        restore_index: bool = True,
    ) -> None:
        """
        Re-apply a Factory stash snapshot onto the current HEAD.

        Uses --index by default so staged vs unstaged state is preserved.
        Does not drop the snapshot; caller must drop explicitly after success.
        """
        stash_ref = self._find_stash_ref_by_sha(
            snapshot.commit_sha
        )
        args = ["stash", "apply"]
        if restore_index:
            args.append("--index")
        args.append(stash_ref)
        self._run_git_command(args, cwd=self.repo_root)

    def drop_local_changes_snapshot(
        self,
        snapshot: GitLocalChangesSnapshot,
    ) -> None:
        """Drop only the Factory-owned stash entry identified by SHA."""
        stash_ref = self._find_stash_ref_by_sha(
            snapshot.commit_sha
        )
        self._run_git_command(
            ["stash", "drop", stash_ref],
            cwd=self.repo_root,
        )

    def reset_repository_to(
        self,
        commit_sha: str,
        *,
        expected_current_head: str,
        owned_paths: set[str],
        expected_guard: GitWorkingTreeGuard,
        snapshot: Optional[GitLocalChangesSnapshot] = None,
    ) -> None:
        """
        Hard-reset the main repository to commit_sha after ownership + guard
        checks.

        Fail closed if:
        - HEAD is not exactly expected_current_head
        - any dirty path is outside owned_paths (snapshot ∪ merge)
        - current working-tree/index fingerprint != expected_guard

        Never runs `git clean -fd`. Untracked cleanup is limited to
        snapshot-owned blobs with exact content verification.
        """
        current = self.get_repository_head()
        if current != expected_current_head:
            raise GitOperationError(
                "Refusing hard reset: HEAD is "
                f"{current}, expected {expected_current_head}"
            )

        dirty = self.list_dirty_paths()
        owned = {
            self._normalize_repo_rel_path(path)
            for path in owned_paths
        }
        unexpected = dirty - owned
        if unexpected:
            raise UnsafeRollbackError(
                "UNEXPECTED_CONCURRENT_CHANGES: "
                + ", ".join(sorted(unexpected))
            )

        current_guard = self.capture_working_tree_guard()
        if current_guard != expected_guard:
            raise UnsafeRollbackError(
                "UNEXPECTED_CONCURRENT_CHANGES: working-tree guard "
                "mismatch (owned path content or index changed)"
            )

        # Final HEAD check immediately before destructive reset.
        if self.get_repository_head() != expected_current_head:
            raise GitOperationError(
                "Refusing hard reset: HEAD changed during guard verification"
            )

        self._run_git_command(
            ["reset", "--hard", commit_sha],
            cwd=self.repo_root,
        )

        if snapshot is not None:
            self._remove_verified_snapshot_untracked(snapshot)

    def merge_branch(self, branch_name: str) -> str:
        """Verilen branch'i ana repository'de aktif branch'e birleştirir."""
        if not self._branch_exists(branch_name):
            raise GitOperationError(f"Branch does not exist: {branch_name}")

        main_status = self.get_repository_status()

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
