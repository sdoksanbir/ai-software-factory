"""Factory-owned EXECUTE session markers and targeted crash recovery.

Ownership is proven by a controller marker under the configured
worktree_root (never inside the project working tree), plus
pid + process create_time lease checks.

Global `execute/*` branch sweeps are intentionally forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import psutil

from factory.execute_worktree import (
    ActiveExecuteSessionError,
    ExecuteCleanupError,
    ExecuteIsolationError,
    ExecuteMarkerError,
    UnownedExecuteArtifactsError,
)
from factory.tools.git_ops import (
    GitOperationError,
    GitWorktreeManager,
)


MARKER_VERSION = 1
MARKER_DIR_NAME = ".ai-factory-execute"
# psutil create_time is a float; tolerate tiny float/clock jitter only.
CREATE_TIME_TOLERANCE_SECONDS = 0.05

INTERRUPTED_EXECUTE_MESSAGE = (
    "EXECUTE was interrupted because the previous "
    "backend process terminated."
)


class RecoveryAction(str, Enum):
    NONE = "none"
    ACTIVE = "active"
    RECOVERED = "recovered"
    MARKER_ONLY = "marker_only"
    SKIPPED_INVALID = "skipped_invalid"
    UNOWNED_ARTIFACTS = "unowned_artifacts"


@dataclass(frozen=True)
class ExecutePathPlan:
    task_id: str
    branch: str
    worktree_path: str
    canonical_repo_root: str
    worktree_root: str
    repo_namespace: str


@dataclass(frozen=True)
class ExecuteOwnerMarker:
    version: int
    task_id: str
    canonical_repo_root: str
    expected_branch: str
    expected_worktree_path: str
    owner_pid: int
    owner_process_create_time: float
    created_at: str
    session_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "task_id": self.task_id,
            "canonical_repo_root": self.canonical_repo_root,
            "expected_branch": self.expected_branch,
            "expected_worktree_path": self.expected_worktree_path,
            "owner_pid": self.owner_pid,
            "owner_process_create_time": (
                self.owner_process_create_time
            ),
            "created_at": self.created_at,
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class RecoverExecuteResult:
    action: RecoveryAction
    task_id: str
    detail: str = ""
    marker_path: str | None = None


def normalize_repo_root(repo_root: str) -> str:
    return os.path.normcase(
        os.path.abspath(repo_root)
    ).replace("\\", "/")


def repo_namespace_for(repo_root: str) -> str:
    digest = hashlib.sha256(
        normalize_repo_root(repo_root).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def derive_execute_path_plan(
    git_manager: GitWorktreeManager,
    task_id: str,
) -> ExecutePathPlan:
    clean_id = (task_id or "").strip()
    if not clean_id:
        raise ExecuteIsolationError(
            "EXECUTE worktree task_id bos olamaz."
        )

    canonical = os.path.abspath(git_manager.repo_root)
    worktree_root = os.path.abspath(git_manager.worktree_root)
    repo_name = os.path.basename(canonical)
    branch = f"execute/{clean_id}"
    worktree_path = os.path.abspath(
        os.path.join(
            worktree_root,
            repo_name,
            f"execute-{clean_id}",
        )
    )
    return ExecutePathPlan(
        task_id=clean_id,
        branch=branch,
        worktree_path=worktree_path,
        canonical_repo_root=canonical,
        worktree_root=worktree_root,
        repo_namespace=repo_namespace_for(canonical),
    )


def marker_root_dir(worktree_root: str) -> str:
    return os.path.join(
        os.path.abspath(worktree_root),
        MARKER_DIR_NAME,
    )


def marker_path_for(
    worktree_root: str,
    repo_namespace: str,
    task_id: str,
) -> str:
    return os.path.join(
        marker_root_dir(worktree_root),
        repo_namespace,
        f"{task_id}.json",
    )


def current_owner_identity() -> tuple[int, float]:
    pid = os.getpid()
    create_time = psutil.Process(pid).create_time()
    return pid, create_time


def is_owner_process_alive(
    owner_pid: int,
    owner_process_create_time: float,
) -> bool:
    """True only when pid exists AND create_time matches.

    Tolerance is CREATE_TIME_TOLERANCE_SECONDS for float jitter.
    Different create_time with the same pid means PID reuse → dead.
    """
    try:
        proc = psutil.Process(int(owner_pid))
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return False

    try:
        if not proc.is_running():
            return False
        actual = float(proc.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

    return (
        abs(actual - float(owner_process_create_time))
        <= CREATE_TIME_TOLERANCE_SECONDS
    )


def _path_contained(
    candidate: str,
    root: str,
) -> bool:
    try:
        pathlib.Path(candidate).resolve().relative_to(
            pathlib.Path(root).resolve()
        )
        return True
    except (ValueError, OSError):
        return False


def _atomic_write_json(path: str, payload: dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".asf-marker-",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_execute_owner_marker(
    plan: ExecutePathPlan,
    *,
    owner_pid: int | None = None,
    owner_process_create_time: float | None = None,
    session_id: str | None = None,
) -> ExecuteOwnerMarker:
    if not _path_contained(
        plan.worktree_path,
        plan.worktree_root,
    ):
        raise ExecuteMarkerError(
            "Expected execute worktree path escapes "
            "configured worktree_root; marker refused."
        )

    pid, create_time = current_owner_identity()
    if owner_pid is not None:
        pid = int(owner_pid)
    if owner_process_create_time is not None:
        create_time = float(owner_process_create_time)

    marker = ExecuteOwnerMarker(
        version=MARKER_VERSION,
        task_id=plan.task_id,
        canonical_repo_root=plan.canonical_repo_root,
        expected_branch=plan.branch,
        expected_worktree_path=plan.worktree_path,
        owner_pid=pid,
        owner_process_create_time=create_time,
        created_at=datetime.now(timezone.utc).isoformat(),
        session_id=session_id or str(uuid.uuid4()),
    )
    path = marker_path_for(
        plan.worktree_root,
        plan.repo_namespace,
        plan.task_id,
    )
    _atomic_write_json(path, marker.as_dict())
    return marker


def delete_execute_owner_marker(
    git_manager: GitWorktreeManager,
    task_id: str,
) -> None:
    plan = derive_execute_path_plan(git_manager, task_id)
    path = marker_path_for(
        plan.worktree_root,
        plan.repo_namespace,
        plan.task_id,
    )
    try:
        if os.path.isfile(path):
            os.unlink(path)
    except OSError:
        pass


def _load_raw_marker(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecuteMarkerError(
            f"Malformed execute ownership marker: {path}"
        ) from exc

    if not isinstance(data, dict):
        raise ExecuteMarkerError(
            f"Malformed execute ownership marker: {path}"
        )
    return data


def parse_execute_owner_marker(
    path: str,
    *,
    expected_plan: ExecutePathPlan | None = None,
) -> ExecuteOwnerMarker:
    data = _load_raw_marker(path)

    required = (
        "version",
        "task_id",
        "canonical_repo_root",
        "expected_branch",
        "expected_worktree_path",
        "owner_pid",
        "owner_process_create_time",
        "created_at",
        "session_id",
    )
    missing = [key for key in required if key not in data]
    if missing:
        raise ExecuteMarkerError(
            "Execute ownership marker missing fields: "
            + ", ".join(missing)
        )

    try:
        version = int(data["version"])
        task_id = str(data["task_id"]).strip()
        canonical = os.path.abspath(
            str(data["canonical_repo_root"])
        )
        branch = str(data["expected_branch"]).strip()
        worktree_path = os.path.abspath(
            str(data["expected_worktree_path"])
        )
        owner_pid = int(data["owner_pid"])
        owner_ct = float(data["owner_process_create_time"])
        created_at = str(data["created_at"])
        session_id = str(data["session_id"]).strip()
    except (TypeError, ValueError) as exc:
        raise ExecuteMarkerError(
            f"Execute ownership marker has invalid types: {path}"
        ) from exc

    if version != MARKER_VERSION:
        raise ExecuteMarkerError(
            f"Unsupported execute ownership marker version: {version}"
        )

    if not task_id or not session_id:
        raise ExecuteMarkerError(
            "Execute ownership marker has empty identity fields."
        )

    marker = ExecuteOwnerMarker(
        version=version,
        task_id=task_id,
        canonical_repo_root=canonical,
        expected_branch=branch,
        expected_worktree_path=worktree_path,
        owner_pid=owner_pid,
        owner_process_create_time=owner_ct,
        created_at=created_at,
        session_id=session_id,
    )

    if expected_plan is not None:
        if marker.task_id != expected_plan.task_id:
            raise ExecuteMarkerError(
                "Execute ownership marker task_id mismatch."
            )
        if normalize_repo_root(marker.canonical_repo_root) != (
            normalize_repo_root(expected_plan.canonical_repo_root)
        ):
            raise ExecuteMarkerError(
                "Execute ownership marker repo_root mismatch."
            )
        if marker.expected_branch != expected_plan.branch:
            raise ExecuteMarkerError(
                "Execute ownership marker branch mismatch."
            )
        if os.path.normcase(marker.expected_worktree_path) != (
            os.path.normcase(expected_plan.worktree_path)
        ):
            raise ExecuteMarkerError(
                "Execute ownership marker worktree path mismatch."
            )
        if not _path_contained(
            marker.expected_worktree_path,
            expected_plan.worktree_root,
        ):
            raise ExecuteMarkerError(
                "Execute ownership marker path escapes worktree_root."
            )

    return marker


def read_execute_owner_marker(
    git_manager: GitWorktreeManager,
    task_id: str,
) -> ExecuteOwnerMarker | None:
    plan = derive_execute_path_plan(git_manager, task_id)
    path = marker_path_for(
        plan.worktree_root,
        plan.repo_namespace,
        plan.task_id,
    )
    if not os.path.isfile(path):
        return None
    return parse_execute_owner_marker(path, expected_plan=plan)


def execute_artifacts_present(
    git_manager: GitWorktreeManager,
    plan: ExecutePathPlan,
) -> bool:
    if os.path.exists(plan.worktree_path):
        return True
    if _worktree_registered(git_manager, plan.worktree_path):
        return True
    if git_manager._branch_exists(plan.branch):
        return True
    return False


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

    needle = os.path.abspath(abs_path).replace("\\", "/")
    return needle in listing.replace("\\", "/")


def _list_prunable_worktree_paths(
    git_manager: GitWorktreeManager,
) -> list[str]:
    try:
        listing = git_manager._run_git_command(
            ["worktree", "list", "--porcelain"],
            cwd=git_manager.repo_root,
        )
    except GitOperationError:
        return []

    prunable: list[str] = []
    current: str | None = None
    for raw_line in listing.splitlines():
        line = raw_line.strip()
        if line.startswith("worktree "):
            current = line[len("worktree "):].strip()
        elif line.startswith("prunable") and current:
            prunable.append(
                os.path.abspath(current.replace("/", os.sep))
            )
            current = None
        elif not line:
            current = None
    return prunable


def _safe_remove_orphaned_directory(
    path: str,
    *,
    worktree_root: str,
) -> None:
    abs_path = os.path.abspath(path)
    if not _path_contained(abs_path, worktree_root):
        raise ExecuteCleanupError(
            f"Refusing to delete path outside worktree_root: {abs_path}"
        )
    if os.path.islink(abs_path):
        raise ExecuteCleanupError(
            f"Refusing to delete symlink worktree path: {abs_path}"
        )
    if os.path.isdir(abs_path):
        shutil.rmtree(abs_path)
    elif os.path.exists(abs_path):
        os.unlink(abs_path)


def _maybe_safe_worktree_prune(
    git_manager: GitWorktreeManager,
    *,
    owned_paths: set[str],
) -> None:
    """Call prune only when every prunable entry is Factory-owned."""
    prunable = _list_prunable_worktree_paths(git_manager)
    if not prunable:
        return

    owned_norm = {
        os.path.normcase(os.path.abspath(p)).replace("\\", "/")
        for p in owned_paths
    }
    for entry in prunable:
        key = os.path.normcase(
            os.path.abspath(entry)
        ).replace("\\", "/")
        if key not in owned_norm:
            # Another prunable worktree exists — fail closed.
            return

    try:
        git_manager._run_git_command(
            ["worktree", "prune"],
            cwd=git_manager.repo_root,
        )
    except GitOperationError:
        # Best-effort; targeted remove is preferred.
        return


def _cleanup_exact_execute_artifacts(
    git_manager: GitWorktreeManager,
    plan: ExecutePathPlan,
) -> None:
    """Remove only the exact Factory execute path/branch for this plan."""
    errors: list[str] = []
    abs_path = plan.worktree_path

    registered = _worktree_registered(git_manager, abs_path)
    path_exists = os.path.exists(abs_path)

    if registered or path_exists:
        try:
            if registered:
                git_manager.remove_worktree(abs_path, force=True)
            elif path_exists:
                _safe_remove_orphaned_directory(
                    abs_path,
                    worktree_root=plan.worktree_root,
                )
        except Exception as exc:
            errors.append(f"worktree remove failed ({abs_path}): {exc}")
            if path_exists or os.path.exists(abs_path):
                try:
                    _safe_remove_orphaned_directory(
                        abs_path,
                        worktree_root=plan.worktree_root,
                    )
                except Exception as rmtree_exc:
                    errors.append(
                        f"worktree rmtree failed ({abs_path}): "
                        f"{rmtree_exc}"
                    )

    # Registration may remain as prunable after directory loss.
    if _worktree_registered(git_manager, abs_path):
        try:
            git_manager.remove_worktree(abs_path, force=True)
        except Exception:
            _maybe_safe_worktree_prune(
                git_manager,
                owned_paths={abs_path},
            )

    if git_manager._branch_exists(plan.branch):
        try:
            git_manager.delete_branch(plan.branch, force=True)
        except Exception as exc:
            errors.append(
                f"branch delete failed ({plan.branch}): {exc}"
            )

    if errors:
        raise ExecuteCleanupError("; ".join(errors))


def recover_execute_session(
    git_manager: GitWorktreeManager,
    task_id: str,
    *,
    allow_active_reject: bool = True,
) -> RecoverExecuteResult:
    """Targeted recovery for one task_id + canonical repo.

    Requires a valid Factory ownership marker and a dead owner.
    Never sweeps unrelated execute/* branches.
    """
    plan = derive_execute_path_plan(git_manager, task_id)
    marker_file = marker_path_for(
        plan.worktree_root,
        plan.repo_namespace,
        plan.task_id,
    )

    if not os.path.isfile(marker_file):
        if execute_artifacts_present(git_manager, plan):
            return RecoverExecuteResult(
                action=RecoveryAction.UNOWNED_ARTIFACTS,
                task_id=plan.task_id,
                detail=(
                    "Stale execute artifacts exist but no "
                    "Factory ownership marker is available."
                ),
                marker_path=None,
            )
        return RecoverExecuteResult(
            action=RecoveryAction.NONE,
            task_id=plan.task_id,
            detail="No marker and no execute artifacts.",
        )

    try:
        marker = parse_execute_owner_marker(
            marker_file,
            expected_plan=plan,
        )
    except ExecuteMarkerError as exc:
        return RecoverExecuteResult(
            action=RecoveryAction.SKIPPED_INVALID,
            task_id=plan.task_id,
            detail=str(exc),
            marker_path=marker_file,
        )

    if is_owner_process_alive(
        marker.owner_pid,
        marker.owner_process_create_time,
    ):
        if allow_active_reject:
            raise ActiveExecuteSessionError(
                "ACTIVE_EXECUTE_SESSION: execute session for "
                f"{plan.task_id} is still owned by live process "
                f"pid={marker.owner_pid}."
            )
        return RecoverExecuteResult(
            action=RecoveryAction.ACTIVE,
            task_id=plan.task_id,
            detail="Owner process is still alive.",
            marker_path=marker_file,
        )

    had_artifacts = execute_artifacts_present(git_manager, plan)
    _cleanup_exact_execute_artifacts(git_manager, plan)

    try:
        os.unlink(marker_file)
    except OSError as exc:
        raise ExecuteCleanupError(
            f"Failed to remove execute ownership marker "
            f"after recovery ({marker_file}): {exc}"
        ) from exc

    return RecoverExecuteResult(
        action=(
            RecoveryAction.RECOVERED
            if had_artifacts
            else RecoveryAction.MARKER_ONLY
        ),
        task_id=plan.task_id,
        detail="Dead-owner execute session recovered.",
        marker_path=marker_file,
    )


def ensure_execute_session_ready(
    git_manager: GitWorktreeManager,
    task_id: str,
) -> RecoverExecuteResult | None:
    """Prepare-time second line of defense before creating a worktree."""
    plan = derive_execute_path_plan(git_manager, task_id)
    marker_file = marker_path_for(
        plan.worktree_root,
        plan.repo_namespace,
        plan.task_id,
    )

    if os.path.isfile(marker_file):
        result = recover_execute_session(
            git_manager,
            task_id,
            allow_active_reject=True,
        )
        return result

    if execute_artifacts_present(git_manager, plan):
        raise UnownedExecuteArtifactsError(
            "Stale execute artifacts exist but no Factory "
            "ownership marker is available for "
            f"{plan.task_id} (branch={plan.branch}, "
            f"path={plan.worktree_path}). Manual inspection "
            "required; automatic deletion refused."
        )

    return None


def iter_execute_marker_files(worktree_root: str) -> list[str]:
    root = marker_root_dir(worktree_root)
    if not os.path.isdir(root):
        return []

    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(".json"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def recover_stale_execute_markers(
    *,
    worktree_root: str,
    get_task: Callable[[str], Any | None],
    get_task_kind: Callable[[str], str | None],
    get_project_path: Callable[[Any], str | None],
    mark_interrupted: Callable[[str], None] | None = None,
    append_log: Callable[[str, str], None] | None = None,
) -> list[RecoverExecuteResult]:
    """Startup scan of controller-owned markers only (no branch sweep)."""
    results: list[RecoverExecuteResult] = []
    abs_root = os.path.abspath(worktree_root)

    for marker_file in iter_execute_marker_files(abs_root):
        try:
            raw = _load_raw_marker(marker_file)
            task_id = str(raw.get("task_id", "")).strip()
            repo_root = str(
                raw.get("canonical_repo_root", "")
            ).strip()
            if not task_id or not repo_root:
                results.append(
                    RecoverExecuteResult(
                        action=RecoveryAction.SKIPPED_INVALID,
                        task_id=task_id or "unknown",
                        detail="Marker missing task_id/repo_root.",
                        marker_path=marker_file,
                    )
                )
                continue

            if not os.path.isdir(repo_root):
                results.append(
                    RecoverExecuteResult(
                        action=RecoveryAction.SKIPPED_INVALID,
                        task_id=task_id,
                        detail="Marker repo_root does not exist.",
                        marker_path=marker_file,
                    )
                )
                continue

            git_manager = GitWorktreeManager(
                repo_root,
                abs_root,
            )
            plan = derive_execute_path_plan(git_manager, task_id)

            # Marker file must live under expected namespace path.
            expected_marker = marker_path_for(
                plan.worktree_root,
                plan.repo_namespace,
                plan.task_id,
            )
            if os.path.normcase(
                os.path.abspath(marker_file)
            ) != os.path.normcase(
                os.path.abspath(expected_marker)
            ):
                results.append(
                    RecoverExecuteResult(
                        action=RecoveryAction.SKIPPED_INVALID,
                        task_id=task_id,
                        detail="Marker path does not match "
                        "derived Factory location.",
                        marker_path=marker_file,
                    )
                )
                continue

            task = get_task(task_id)
            kind = get_task_kind(task_id)
            if task is None or kind != "execute":
                # Fail closed: do not delete markers/artifacts for
                # unknown or non-execute tasks via startup sweep.
                results.append(
                    RecoverExecuteResult(
                        action=RecoveryAction.SKIPPED_INVALID,
                        task_id=task_id,
                        detail=(
                            "Startup recovery skipped: task missing "
                            "or not kind=execute."
                        ),
                        marker_path=marker_file,
                    )
                )
                continue

            project_path = get_project_path(task)
            if project_path:
                try:
                    project_mgr = GitWorktreeManager(
                        project_path,
                        abs_root,
                    )
                    if normalize_repo_root(
                        project_mgr.repo_root
                    ) != normalize_repo_root(plan.canonical_repo_root):
                        results.append(
                            RecoverExecuteResult(
                                action=RecoveryAction.SKIPPED_INVALID,
                                task_id=task_id,
                                detail="Marker repo does not match "
                                "task project path.",
                                marker_path=marker_file,
                            )
                        )
                        continue
                except GitOperationError:
                    results.append(
                        RecoverExecuteResult(
                            action=RecoveryAction.SKIPPED_INVALID,
                            task_id=task_id,
                            detail="Task project path is not a git repo.",
                            marker_path=marker_file,
                        )
                    )
                    continue

            result = recover_execute_session(
                git_manager,
                task_id,
                allow_active_reject=False,
            )
            results.append(result)

            if result.action in {
                RecoveryAction.RECOVERED,
                RecoveryAction.MARKER_ONLY,
            }:
                state = str(
                    getattr(task, "state", "")
                    or getattr(task, "status", "")
                    or ""
                ).strip().casefold()
                if state == "running" and mark_interrupted is not None:
                    mark_interrupted(task_id)
                    if append_log is not None:
                        append_log(
                            task_id,
                            INTERRUPTED_EXECUTE_MESSAGE,
                        )
                elif append_log is not None:
                    append_log(
                        task_id,
                        (
                            "Recovered stale EXECUTE ownership "
                            f"marker ({result.action.value})."
                        ),
                    )
            elif (
                result.action == RecoveryAction.ACTIVE
                and append_log is not None
            ):
                append_log(
                    task_id,
                    "Skipped EXECUTE recovery: owner process still alive.",
                )

        except ActiveExecuteSessionError as exc:
            results.append(
                RecoverExecuteResult(
                    action=RecoveryAction.ACTIVE,
                    task_id=task_id if "task_id" in locals() else "unknown",
                    detail=str(exc),
                    marker_path=marker_file,
                )
            )
        except Exception as exc:
            results.append(
                RecoverExecuteResult(
                    action=RecoveryAction.SKIPPED_INVALID,
                    task_id=task_id if "task_id" in locals() else "unknown",
                    detail=f"Startup recovery error: {exc}",
                    marker_path=marker_file,
                )
            )

    return results
