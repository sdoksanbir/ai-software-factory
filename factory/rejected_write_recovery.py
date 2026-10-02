"""Startup recovery for stale REJECTED WRITE worktree/branch artifacts.

Ownership is proven only by DB-backed rejected WRITE tasks whose stored
branch/worktree_path exactly match the production WRITE convention.
Global ``agent/*`` sweeps are intentionally forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
import shutil
from typing import Any, Callable

from factory.execute_recovery import (
    _list_prunable_worktree_paths,
    _path_contained,
    _worktree_registered,
)
from factory.tools.git_ops import (
    GitOperationError,
    GitWorktreeManager,
)
from factory.write_worktree_ownership import (
    WriteOwnershipError,
    WritePathPlan,
    derive_write_path_plan,
    has_symlink_or_junction_escape,
    is_symlink_entry,
    norm_path_key,
    verify_write_metadata_ownership,
)

# Re-export for existing imports/tests.
__all__ = (
    "RejectedWriteCleanupError",
    "RecoveryAction",
    "WritePathPlan",
    "RejectedWriteRecoveryResult",
    "derive_write_path_plan",
    "verify_rejected_write_ownership",
    "recover_rejected_write_artifacts",
    "recover_rejected_write_artifacts_on_startup",
)


class RejectedWriteCleanupError(RuntimeError):
    """Exact rejected-WRITE artifact cleanup failed."""


class RecoveryAction(str, Enum):
    NONE = "none"
    RECOVERED = "recovered"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class RejectedWriteRecoveryResult:
    action: RecoveryAction
    task_id: str
    detail: str = ""


def _maybe_safe_worktree_prune(
    git_manager: GitWorktreeManager,
    *,
    owned_paths: set[str],
) -> None:
    """Call prune only when every prunable entry is Factory-owned."""
    prunable = _list_prunable_worktree_paths(git_manager)
    if not prunable:
        return

    owned_norm = {norm_path_key(p) for p in owned_paths}
    for entry in prunable:
        if norm_path_key(entry) not in owned_norm:
            return

    try:
        git_manager._run_git_command(
            ["worktree", "prune"],
            cwd=git_manager.repo_root,
        )
    except GitOperationError:
        return


def _safe_remove_orphaned_directory(
    path: str,
    *,
    worktree_root: str,
) -> None:
    abs_path = os.path.abspath(path)
    if not _path_contained(abs_path, worktree_root):
        raise RejectedWriteCleanupError(
            f"Refusing to delete path outside worktree_root: {abs_path}"
        )
    if has_symlink_or_junction_escape(abs_path, worktree_root):
        raise RejectedWriteCleanupError(
            f"Refusing to delete symlink/junction worktree path: {abs_path}"
        )
    if os.path.isdir(abs_path) and not is_symlink_entry(abs_path):
        shutil.rmtree(abs_path)
    elif os.path.lexists(abs_path):
        raise RejectedWriteCleanupError(
            f"Refusing to delete non-directory orphan path: {abs_path}"
        )


def verify_rejected_write_ownership(
    *,
    task_id: str,
    state: str | None,
    task_kind: str | None,
    stored_branch: str | None,
    stored_worktree_path: str | None,
    git_manager: GitWorktreeManager,
) -> tuple[WritePathPlan | None, str]:
    """Return (plan, skip_reason). plan is None when cleanup must skip."""
    if (state or "").strip().casefold() != "rejected":
        return None, f"state is {state!r}, expected 'rejected'"

    kind = (task_kind or "").strip().casefold()
    if kind != "write":
        return None, f"task_kind is {task_kind!r}, expected 'write'"

    try:
        plan = verify_write_metadata_ownership(
            task_id=task_id,
            claimed_branch=stored_branch,
            claimed_worktree_path=stored_worktree_path,
            git_manager=git_manager,
        )
    except WriteOwnershipError as exc:
        return None, str(exc)

    return plan, ""


def _artifacts_present(
    git_manager: GitWorktreeManager,
    plan: WritePathPlan,
) -> bool:
    if os.path.lexists(plan.worktree_path):
        return True
    if _worktree_registered(git_manager, plan.worktree_path):
        return True
    if git_manager._branch_exists(plan.branch):
        return True
    return False


@dataclass(frozen=True)
class _CleanupOutcome:
    worktree_error: str | None = None
    branch_error: str | None = None

    @property
    def failed(self) -> bool:
        return bool(self.worktree_error or self.branch_error)

    @property
    def detail(self) -> str:
        parts = [
            part
            for part in (self.worktree_error, self.branch_error)
            if part
        ]
        return "; ".join(parts)


def _cleanup_exact_write_artifacts(
    git_manager: GitWorktreeManager,
    plan: WritePathPlan,
) -> _CleanupOutcome:
    """Remove only the exact Factory WRITE path/branch for this plan."""
    worktree_error: str | None = None
    branch_error: str | None = None
    abs_path = plan.worktree_path

    registered = _worktree_registered(git_manager, abs_path)
    path_exists = os.path.lexists(abs_path)

    if path_exists and has_symlink_or_junction_escape(
        abs_path,
        plan.worktree_root,
    ):
        worktree_error = (
            f"Refusing symlink/junction worktree path: {abs_path}"
        )
    elif registered or path_exists:
        try:
            if registered:
                git_manager.remove_worktree(abs_path, force=True)
            elif path_exists:
                _safe_remove_orphaned_directory(
                    abs_path,
                    worktree_root=plan.worktree_root,
                )
        except Exception as exc:
            worktree_error = (
                f"worktree remove failed ({abs_path}): {exc}"
            )
            if path_exists or os.path.lexists(abs_path):
                try:
                    _safe_remove_orphaned_directory(
                        abs_path,
                        worktree_root=plan.worktree_root,
                    )
                    worktree_error = None
                except Exception as rmtree_exc:
                    worktree_error = (
                        f"worktree rmtree failed ({abs_path}): "
                        f"{rmtree_exc}"
                    )

    if worktree_error is None and _worktree_registered(
        git_manager,
        abs_path,
    ):
        try:
            git_manager.remove_worktree(abs_path, force=True)
        except Exception:
            _maybe_safe_worktree_prune(
                git_manager,
                owned_paths={abs_path},
            )
            if _worktree_registered(git_manager, abs_path):
                worktree_error = (
                    "stale worktree registration remains "
                    f"for {abs_path}"
                )

    if git_manager._branch_exists(plan.branch):
        try:
            git_manager.delete_branch(plan.branch, force=True)
        except Exception as exc:
            branch_error = (
                f"branch delete failed ({plan.branch}): {exc}"
            )

    return _CleanupOutcome(
        worktree_error=worktree_error,
        branch_error=branch_error,
    )


def recover_rejected_write_artifacts(
    *,
    git_manager: GitWorktreeManager,
    task_id: str,
    state: str | None,
    task_kind: str | None,
    stored_branch: str | None,
    stored_worktree_path: str | None,
    append_log: Callable[[str, str], None] | None = None,
) -> RejectedWriteRecoveryResult:
    """Targeted recovery for one DB-backed rejected WRITE task."""
    plan, skip_reason = verify_rejected_write_ownership(
        task_id=task_id,
        state=state,
        task_kind=task_kind,
        stored_branch=stored_branch,
        stored_worktree_path=stored_worktree_path,
        git_manager=git_manager,
    )
    if plan is None:
        return RejectedWriteRecoveryResult(
            action=RecoveryAction.SKIPPED,
            task_id=task_id,
            detail=skip_reason,
        )

    if not _artifacts_present(git_manager, plan):
        return RejectedWriteRecoveryResult(
            action=RecoveryAction.NONE,
            task_id=task_id,
            detail="No stale WRITE artifacts present.",
        )

    try:
        outcome = _cleanup_exact_write_artifacts(git_manager, plan)
    except Exception as exc:
        if append_log is not None:
            append_log(
                task_id,
                (
                    "Rejected task cleanup warning: "
                    f"worktree cleanup failed: {exc}"
                ),
            )
        return RejectedWriteRecoveryResult(
            action=RecoveryAction.FAILED,
            task_id=task_id,
            detail=str(exc),
        )

    if outcome.failed:
        if append_log is not None:
            if outcome.worktree_error:
                append_log(
                    task_id,
                    (
                        "Rejected task cleanup warning: "
                        "worktree cleanup failed: "
                        f"{outcome.worktree_error}"
                    ),
                )
            if outcome.branch_error:
                append_log(
                    task_id,
                    (
                        "Rejected task cleanup warning: "
                        "branch cleanup failed: "
                        f"{outcome.branch_error}"
                    ),
                )
        return RejectedWriteRecoveryResult(
            action=RecoveryAction.FAILED,
            task_id=task_id,
            detail=outcome.detail,
        )

    return RejectedWriteRecoveryResult(
        action=RecoveryAction.RECOVERED,
        task_id=task_id,
        detail=(
            f"Removed stale WRITE artifacts for {plan.branch} "
            f"at {plan.worktree_path}."
        ),
    )


def recover_rejected_write_artifacts_on_startup(
    *,
    worktree_root: str,
    list_task_rows: Callable[[], list[dict[str, Any]]],
    get_task_kind: Callable[[str], str | None],
    get_project_path: Callable[[dict[str, Any]], str | None],
    append_log: Callable[[str, str], None] | None = None,
) -> list[RejectedWriteRecoveryResult]:
    """Startup scan of DB rejected WRITE tasks only (no agent/* sweep)."""
    results: list[RejectedWriteRecoveryResult] = []
    abs_root = os.path.abspath(worktree_root)

    for row in list_task_rows():
        task_id = str(row.get("task_id") or "").strip()
        if not task_id:
            continue

        state = row.get("state") or row.get("status")
        if (state or "").strip().casefold() != "rejected":
            continue

        kind = get_task_kind(task_id)
        if (kind or "").strip().casefold() != "write":
            results.append(
                RejectedWriteRecoveryResult(
                    action=RecoveryAction.SKIPPED,
                    task_id=task_id,
                    detail=f"task_kind is {kind!r}, expected 'write'",
                )
            )
            continue

        project_path = get_project_path(row)
        if not project_path or not os.path.isdir(project_path):
            results.append(
                RejectedWriteRecoveryResult(
                    action=RecoveryAction.SKIPPED,
                    task_id=task_id,
                    detail="project path unavailable",
                )
            )
            continue

        try:
            git_manager = GitWorktreeManager(
                project_path,
                abs_root,
            )
        except Exception as exc:
            results.append(
                RejectedWriteRecoveryResult(
                    action=RecoveryAction.SKIPPED,
                    task_id=task_id,
                    detail=f"git manager unavailable: {exc}",
                )
            )
            continue

        result = recover_rejected_write_artifacts(
            git_manager=git_manager,
            task_id=task_id,
            state=str(state),
            task_kind=kind,
            stored_branch=row.get("branch"),
            stored_worktree_path=row.get("worktree_path"),
            append_log=append_log,
        )
        results.append(result)

        if (
            append_log is not None
            and result.action == RecoveryAction.RECOVERED
        ):
            append_log(
                task_id,
                (
                    "Rejected task startup recovery cleaned "
                    "stale WRITE worktree/branch artifacts."
                ),
            )

    return results
