"""Disposable EXECUTE worktree isolation.

Materializes the main repository working-tree state into a disposable
Git worktree WITHOUT mutating main (no stash/add/reset/checkout/clean/
commit on main). Production EXECUTE runs only inside that worktree.

Ignored files are intentionally NOT copied (git ls-files
--others --exclude-standard). EXECUTE mirrors the non-ignored
untracked set that `git status` reports.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import pathlib
import shutil
import subprocess

from factory.tools.git_ops import (
    GitOperationError,
    GitWorkingTreeGuard,
    GitWorktreeManager,
    GitWorktreeResult,
)


class ExecuteIsolationError(RuntimeError):
    """Base error for EXECUTE worktree prepare/cleanup."""


class ExecuteConflictError(ExecuteIsolationError):
    """Main repository has unresolved merge/index conflicts."""


class ExecuteConcurrencyError(ExecuteIsolationError):
    """Main working tree changed during materialization."""


class ExecuteCleanupError(ExecuteIsolationError):
    """Disposable execute worktree/branch cleanup failed."""


class ActiveExecuteSessionError(ExecuteIsolationError):
    """Another live backend still owns this EXECUTE session."""


class UnownedExecuteArtifactsError(ExecuteIsolationError):
    """Exact execute artifacts exist without a Factory ownership marker."""


class ExecuteMarkerError(ExecuteIsolationError):
    """Marker missing, malformed, tampered, or mismatched."""


@dataclass(frozen=True)
class ExecuteWorktreeSession:
    task_id: str
    branch: str
    path: str
    repository_root: str
    before_guard: GitWorkingTreeGuard
    # EXECUTE worktree fingerprint AFTER materialization
    # and BEFORE the agent runs. Distinct from
    # before_guard (main concurrency guard).
    execute_baseline_guard: GitWorkingTreeGuard


EXECUTE_ISOLATED_GIT_CHANGES_LOG = (
    "EXECUTE left isolated Git-visible changes; "
    "they were not applied to the main project."
)


def capture_execute_worktree_guard(
    *,
    worktree_path: str,
    worktree_root: str,
) -> GitWorkingTreeGuard:
    """Fingerprint a linked EXECUTE worktree.

    Uses a dedicated manager so ``repo_root`` resolves
    to the worktree toplevel (not the main checkout).
    """
    manager = GitWorktreeManager(
        project_path=worktree_path,
        worktree_root=worktree_root,
    )
    return manager.capture_working_tree_guard()


def _post_materialize_before_guard_recheck() -> None:
    """Test injection between materialize and guard recheck.

    Production no-op. Tests may monkeypatch to mutate main and
    verify concurrency refusal without destructive recovery.
    """
    return None


def has_unmerged_paths(
    git_manager: GitWorktreeManager,
) -> bool:
    """True when the main index has unresolved conflict stages."""
    result = git_manager._run_git_command_result(
        ["ls-files", "-u"],
        cwd=git_manager.repo_root,
    )
    if result.returncode != 0:
        err = (
            (result.stderr or "").strip()
            or (result.stdout or "").strip()
            or f"exit {result.returncode}"
        )
        raise GitOperationError(
            f"Git ls-files -u failed: {err}"
        )
    return bool((result.stdout or "").strip())


def _git_stdout_bytes(
    args: list[str],
    *,
    cwd: str,
) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitOperationError(
            "Git is not installed or not found in system PATH."
        ) from exc

    if completed.returncode != 0:
        err = (completed.stderr or b"").decode(
            "utf-8",
            errors="replace",
        ).strip()
        raise GitOperationError(
            f"Git command failed ('git {' '.join(args)}'): {err}"
        )
    return completed.stdout or b""


def _git_apply_bytes(
    patch: bytes,
    *,
    cwd: str,
    index: bool,
) -> None:
    if not patch:
        return

    args = ["apply", "--binary"]
    if index:
        args.append("--index")
    args.append("-")

    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            input=patch,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitOperationError(
            "Git is not installed or not found in system PATH."
        ) from exc

    if completed.returncode != 0:
        err = (completed.stderr or b"").decode(
            "utf-8",
            errors="replace",
        ).strip()
        raise ExecuteIsolationError(
            "Failed to materialize main working-tree "
            f"state into execute worktree: {err}"
        )


def _list_untracked_z(
    repo_root: str,
) -> list[str]:
    """Non-ignored untracked paths (NUL-separated).

    Ignored paths are excluded on purpose via --exclude-standard.
    """
    raw = _git_stdout_bytes(
        [
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=repo_root,
    )
    if not raw:
        return []

    parts = raw.split(b"\0")
    paths: list[str] = []
    for part in parts:
        if not part:
            continue
        paths.append(
            part.decode("utf-8", errors="surrogateescape")
        )
    return paths


def _validated_worktree_dest(
    worktree_root: pathlib.Path,
    rel_path: str,
) -> pathlib.Path:
    normalized = (rel_path or "").strip().replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or normalized.startswith("~")
    ):
        raise ExecuteIsolationError(
            f"Unsafe untracked path rejected: {rel_path!r}"
        )

    parts = pathlib.PurePosixPath(normalized).parts
    if not parts or any(part == ".." for part in parts):
        raise ExecuteIsolationError(
            f"Path traversal rejected: {rel_path!r}"
        )

    candidate = worktree_root.joinpath(*parts)
    try:
        parent = candidate.parent.resolve()
    except OSError as exc:
        raise ExecuteIsolationError(
            f"Cannot resolve untracked destination: {rel_path!r}"
        ) from exc

    try:
        parent.relative_to(worktree_root.resolve())
    except ValueError as exc:
        raise ExecuteIsolationError(
            f"Untracked destination escapes worktree: {rel_path!r}"
        ) from exc

    return parent / candidate.name


def _copy_untracked_into_worktree(
    git_manager: GitWorktreeManager,
    worktree_path: str,
) -> None:
    repo = pathlib.Path(git_manager.repo_root).resolve()
    wt = pathlib.Path(worktree_path).resolve()

    for rel in _list_untracked_z(str(repo)):
        source = git_manager._validated_repo_path(rel)
        if source.is_symlink():
            raise ExecuteIsolationError(
                "Untracked symlink is not supported for "
                f"execute materialization: {rel}"
            )
        if not source.is_file():
            # Skip unexpected non-file entries fail-closed only for
            # symlinks; directories are represented by their files.
            if source.exists():
                raise ExecuteIsolationError(
                    "Unsupported untracked entry for "
                    f"execute materialization: {rel}"
                )
            continue

        dest = _validated_worktree_dest(wt, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)


def materialize_main_state_into_worktree(
    git_manager: GitWorktreeManager,
    worktree_path: str,
) -> None:
    """Copy staged/unstaged/untracked main state into execute worktree.

    Never mutates main index or working tree.
    """
    repo = git_manager.repo_root
    wt = os.path.abspath(worktree_path)

    staged = _git_stdout_bytes(
        [
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--no-renames",
            "HEAD",
            "--",
        ],
        cwd=repo,
    )
    _git_apply_bytes(staged, cwd=wt, index=True)

    unstaged = _git_stdout_bytes(
        [
            "diff",
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--no-renames",
            "--",
        ],
        cwd=repo,
    )
    # Working-tree only — preserves staged vs unstaged split.
    _git_apply_bytes(unstaged, cwd=wt, index=False)

    _copy_untracked_into_worktree(git_manager, wt)


def cleanup_execute_worktree(
    git_manager: GitWorktreeManager,
    *,
    path: str | None,
    branch: str | None,
    task_id: str | None = None,
    remove_marker_on_success: bool = True,
) -> None:
    """Force-remove disposable execute worktree and branch.

    Never runs reset/clean/checkout/stash on main.

    When Git cleanup succeeds and ``remove_marker_on_success`` is true,
    the Factory ownership marker for ``task_id`` (or derived from
    ``branch``) is removed. If Git cleanup fails, the marker is kept
    so later recovery can retry.
    """
    errors: list[str] = []

    if path:
        abs_path = os.path.abspath(path)
        try:
            if os.path.exists(abs_path) or _worktree_registered(
                git_manager,
                abs_path,
            ):
                git_manager.remove_worktree(
                    abs_path,
                    force=True,
                )
        except Exception as exc:
            errors.append(
                f"worktree remove failed ({abs_path}): {exc}"
            )
            # Best-effort directory cleanup if git leave leftovers.
            if os.path.isdir(abs_path):
                try:
                    shutil.rmtree(abs_path, ignore_errors=True)
                except Exception as rmtree_exc:
                    errors.append(
                        f"worktree rmtree failed ({abs_path}): "
                        f"{rmtree_exc}"
                    )

    if branch:
        try:
            git_manager.delete_branch(branch, force=True)
        except Exception as exc:
            errors.append(
                f"branch delete failed ({branch}): {exc}"
            )

    if errors:
        raise ExecuteCleanupError("; ".join(errors))

    if remove_marker_on_success:
        resolved_task_id = (task_id or "").strip()
        if not resolved_task_id and branch:
            prefix = "execute/"
            if branch.startswith(prefix):
                resolved_task_id = branch[len(prefix):].strip()
        if resolved_task_id:
            from factory.execute_recovery import (
                delete_execute_owner_marker,
            )

            delete_execute_owner_marker(
                git_manager,
                resolved_task_id,
            )


def _worktree_registered(
    git_manager: GitWorktreeManager,
    abs_path: str,
) -> bool:
    try:
        listing = git_manager._run_git_command(
            ["worktree", "list", "--porcelain"],
            cwd=git_manager.repo_root,
        )
    except GitOperationError:
        return False

    needle = abs_path.replace("\\", "/")
    return needle in listing.replace("\\", "/")


def prepare_execute_worktree(
    git_manager: GitWorktreeManager,
    task_id: str,
) -> ExecuteWorktreeSession:
    """Create an execute worktree and materialize main dirty state."""
    from factory.execute_recovery import (
        derive_execute_path_plan,
        ensure_execute_session_ready,
        write_execute_owner_marker,
        delete_execute_owner_marker,
    )

    if has_unmerged_paths(git_manager):
        raise ExecuteConflictError(
            "Project contains unresolved Git conflicts; "
            "isolated execution was not started."
        )

    # Second line of defense: recover dead-owner sessions or refuse
    # when a live owner / unmarked artifacts block creation.
    ensure_execute_session_ready(git_manager, task_id)

    plan = derive_execute_path_plan(git_manager, task_id)
    before_guard = git_manager.capture_working_tree_guard()
    created: GitWorktreeResult | None = None
    marker_written = False

    try:
        # Marker before worktree creation so mid-create crashes
        # still leave recoverable ownership proof.
        write_execute_owner_marker(plan)
        marker_written = True

        created = git_manager.create_execute_worktree(task_id)
        materialize_main_state_into_worktree(
            git_manager,
            created.path,
        )
        _post_materialize_before_guard_recheck()
        after_guard = git_manager.capture_working_tree_guard()
        if after_guard != before_guard:
            raise ExecuteConcurrencyError(
                "Project working tree changed while preparing "
                "isolated execution; retry."
            )
        # Baseline includes materialized dirty main
        # state. Agent-produced changes are detected
        # against this fingerprint, not against clean.
        execute_baseline_guard = (
            capture_execute_worktree_guard(
                worktree_path=created.path,
                worktree_root=git_manager.worktree_root,
            )
        )
    except Exception:
        if created is not None:
            try:
                cleanup_execute_worktree(
                    git_manager,
                    path=created.path,
                    branch=created.branch,
                    task_id=plan.task_id,
                    remove_marker_on_success=False,
                )
            except ExecuteCleanupError:
                # Preserve the original prepare failure; best-effort
                # cleanup may be incomplete.
                pass

        if marker_written:
            # Always drop this process's lease on prepare abort so a
            # retry is not blocked by ACTIVE_EXECUTE_SESSION against
            # ourselves. If Git cleanup failed, unmarked leftovers
            # fail closed on the next prepare.
            try:
                delete_execute_owner_marker(
                    git_manager,
                    plan.task_id,
                )
            except Exception:
                pass
        raise

    if created is None:
        raise ExecuteIsolationError(
            "Execute worktree prepare completed without "
            "a worktree session."
        )

    return ExecuteWorktreeSession(
        task_id=created.task_id,
        branch=created.branch,
        path=created.path,
        repository_root=created.repository_root,
        before_guard=before_guard,
        execute_baseline_guard=execute_baseline_guard,
    )
