"""Shared WRITE worktree/branch ownership verification.

Proves that claimed runtime/SQLite metadata matches the production WRITE
convention before approval merge or reject cleanup may touch Git state.

Expected WRITE naming (mirrors create_worktree callers):

    branch = agent/<task_id.lower()>
    worktree_path = <worktree_root>/<repo_name>/<task_id.lower()>
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import pathlib

from factory.execute_recovery import _path_contained
from factory.tools.git_ops import (
    GitOperationError,
    GitWorktreeManager,
)


class WriteOwnershipError(RuntimeError):
    """Claimed WRITE worktree/branch ownership could not be proven."""


@dataclass(frozen=True)
class WritePathPlan:
    task_id: str
    branch: str
    worktree_path: str
    worktree_root: str
    canonical_repo_root: str


@dataclass(frozen=True)
class _WorktreeListEntry:
    path: str
    branch: str | None
    head: str | None
    detached: bool = False
    prunable: bool = False


def derive_write_path_plan(
    git_manager: GitWorktreeManager,
    task_id: str,
) -> WritePathPlan:
    """Mirror production WRITE create_worktree naming (task_id.lower())."""
    clean_id = (task_id or "").strip().lower()
    if not clean_id:
        raise WriteOwnershipError(
            "WRITE worktree task_id bos olamaz."
        )

    canonical = os.path.abspath(git_manager.repo_root)
    worktree_root = os.path.abspath(git_manager.worktree_root)
    repo_name = os.path.basename(canonical)
    branch = f"agent/{clean_id}"
    worktree_path = os.path.abspath(
        os.path.join(worktree_root, repo_name, clean_id)
    )
    return WritePathPlan(
        task_id=clean_id,
        branch=branch,
        worktree_path=worktree_path,
        worktree_root=worktree_root,
        canonical_repo_root=canonical,
    )


def norm_path_key(path: str) -> str:
    return os.path.normcase(
        os.path.abspath(path)
    ).replace("\\", "/")


def paths_equal(left: str, right: str) -> bool:
    return norm_path_key(left) == norm_path_key(right)


def is_symlink_entry(path: str) -> bool:
    try:
        if os.path.islink(path):
            return True
        return pathlib.Path(path).is_symlink()
    except OSError:
        return True


def has_symlink_or_junction_escape(
    path: str,
    worktree_root: str,
) -> bool:
    """True when leaf/parent symlink/junction could escape ownership."""
    abs_path = os.path.abspath(path)
    abs_root = os.path.abspath(worktree_root)

    if not _path_contained(abs_path, abs_root):
        return True

    current = pathlib.Path(abs_path)
    root_path = pathlib.Path(abs_root)
    while True:
        if is_symlink_entry(str(current)):
            return True
        if norm_path_key(str(current)) == norm_path_key(
            str(root_path)
        ):
            break
        parent = current.parent
        if parent == current:
            break
        try:
            current.relative_to(root_path)
        except ValueError:
            return True
        current = parent

    try:
        real_path = os.path.realpath(abs_path)
        real_root = os.path.realpath(abs_root)
    except OSError:
        return True

    if not _path_contained(real_path, real_root):
        return True
    return False


def _parse_worktree_list_porcelain(
    listing: str,
) -> list[_WorktreeListEntry]:
    """Parse ``git worktree list --porcelain`` into exact path/branch blocks."""
    entries: list[_WorktreeListEntry] = []
    path: str | None = None
    branch: str | None = None
    head: str | None = None
    detached = False
    prunable = False

    def _flush() -> None:
        nonlocal path, branch, head, detached, prunable
        if path is None:
            return
        entries.append(
            _WorktreeListEntry(
                path=os.path.abspath(path.replace("/", os.sep)),
                branch=branch,
                head=head,
                detached=detached,
                prunable=prunable,
            )
        )
        path = None
        branch = None
        head = None
        detached = False
        prunable = False

    for raw_line in listing.splitlines():
        line = raw_line.strip()
        if not line:
            _flush()
            continue
        if line.startswith("worktree "):
            _flush()
            path = line[len("worktree "):].strip()
        elif line.startswith("HEAD "):
            head = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                branch = ref[len(prefix):]
            else:
                branch = ref
        elif line == "detached":
            detached = True
        elif line.startswith("prunable"):
            prunable = True

    _flush()
    return entries


def list_registered_worktrees(
    git_manager: GitWorktreeManager,
) -> list[_WorktreeListEntry]:
    try:
        listing = git_manager._run_git_command(
            ["worktree", "list", "--porcelain"],
            cwd=git_manager.repo_root,
        )
    except GitOperationError as exc:
        raise WriteOwnershipError(
            f"Unable to list registered worktrees: {exc}"
        ) from exc
    return _parse_worktree_list_porcelain(listing)


def find_registered_worktree(
    git_manager: GitWorktreeManager,
    worktree_path: str,
) -> _WorktreeListEntry | None:
    needle = norm_path_key(worktree_path)
    for entry in list_registered_worktrees(git_manager):
        if norm_path_key(entry.path) == needle:
            return entry
    return None


def verify_write_metadata_ownership(
    *,
    task_id: str,
    claimed_branch: str | None,
    claimed_worktree_path: str | None,
    git_manager: GitWorktreeManager,
) -> WritePathPlan:
    """Prove claimed metadata matches expected WRITE convention.

    Does not require live Git registration (startup recovery may clean
    orphan directories / leftover branches after metadata proof).
    """
    if not claimed_branch or not str(claimed_branch).strip():
        raise WriteOwnershipError("stored branch missing")
    if (
        not claimed_worktree_path
        or not str(claimed_worktree_path).strip()
    ):
        raise WriteOwnershipError("stored worktree_path missing")

    plan = derive_write_path_plan(git_manager, task_id)

    if str(claimed_branch).strip() != plan.branch:
        raise WriteOwnershipError(
            "stored branch does not match expected WRITE convention: "
            f"{claimed_branch!r} != {plan.branch!r}"
        )

    if not paths_equal(str(claimed_worktree_path), plan.worktree_path):
        raise WriteOwnershipError(
            "stored worktree_path does not match expected WRITE "
            f"convention: {claimed_worktree_path!r} != "
            f"{plan.worktree_path!r}"
        )

    if not _path_contained(plan.worktree_path, plan.worktree_root):
        raise WriteOwnershipError(
            "expected worktree_path escapes worktree_root"
        )

    if not paths_equal(
        git_manager.repo_root,
        plan.canonical_repo_root,
    ):
        raise WriteOwnershipError("git_manager repo_root mismatch")

    return plan


def verify_registered_write_association(
    git_manager: GitWorktreeManager,
    plan: WritePathPlan,
) -> _WorktreeListEntry:
    """Require an exact registered worktree path bound to expected branch."""
    entry = find_registered_worktree(
        git_manager,
        plan.worktree_path,
    )
    if entry is None:
        raise WriteOwnershipError(
            "expected WRITE worktree is not registered in this repository"
        )

    if entry.detached or not entry.branch:
        raise WriteOwnershipError(
            "registered WRITE worktree is detached or missing branch ref"
        )

    if entry.branch != plan.branch:
        raise WriteOwnershipError(
            "registered worktree branch does not match expected WRITE "
            f"branch: {entry.branch!r} != {plan.branch!r}"
        )

    return entry


def verify_write_worktree_ownership(
    *,
    task_id: str,
    claimed_branch: str | None,
    claimed_worktree_path: str | None,
    git_manager: GitWorktreeManager,
    require_registered_association: bool = True,
    require_no_symlink_escape: bool = True,
) -> WritePathPlan:
    """Full WRITE ownership proof used by approval / reject API paths."""
    plan = verify_write_metadata_ownership(
        task_id=task_id,
        claimed_branch=claimed_branch,
        claimed_worktree_path=claimed_worktree_path,
        git_manager=git_manager,
    )

    if require_no_symlink_escape and os.path.lexists(plan.worktree_path):
        if has_symlink_or_junction_escape(
            plan.worktree_path,
            plan.worktree_root,
        ):
            raise WriteOwnershipError(
                "WRITE worktree path has symlink/junction escape risk"
            )

    if require_registered_association:
        verify_registered_write_association(git_manager, plan)

    return plan
