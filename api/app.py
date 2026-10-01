from urllib import error as urllib_error
from urllib import request as urllib_request
import time
import asyncio
import json
import os
import random
import subprocess
import sys
import uuid
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse

from factory.database import (
    ACTIVE_PROJECT_TASK_STATES,
    DEFAULT_DB_PATH,
    append_task_log as db_append_task_log,
    delete_task_diff as db_delete_task_diff,
    get_task_diff as db_get_task_diff,
    init_database,
    list_task_logs as db_list_task_logs,
    list_tasks as db_list_tasks,
    project_has_active_tasks as db_project_has_active_tasks,
    save_task_diff as db_save_task_diff,
    upsert_task as db_upsert_task,
    create_project as db_create_project,
    delete_project as db_delete_project,
    get_project as db_get_project,
    list_projects as db_list_projects,
    update_project as db_update_project,
)
from factory.control_center import get_control_center_status
from factory.project_memory_capture import (
    capture_approved_task_memory,
)
from factory.project_memory_store import (
    get_project_memory as db_get_project_memory,
    list_project_memories as db_list_project_memories,
    supersede_project_memory as db_supersede_project_memory,
    update_project_memory as db_update_project_memory,
)
from factory.pipeline import build_task_pipeline
from factory.orchestrator import Orchestrator
from factory.project_creator import (
    create_new_git_project,
    find_project_by_canonical_path,
    init_git_in_existing_folder,
    inspect_project_folder,
    normalize_project_path_for_storage,
    path_has_git,
    planned_new_project_path,
    remove_newly_created_project_dir,
)
from factory.models import ModelClient
from factory.agents.providers.model_client import (
    ModelClientProvider,
)
from factory.task_plan_store import (
    get_task_plan,
    reset_retryable_task_steps,
)
from factory.agent_checkpoint_store import (
    list_agent_checkpoints,
)
from factory.agent_execution_store import (
    list_agent_executions,
)
from factory.task_command_store import (
    list_task_commands,
)
from factory.agent_handoff_store import (
    list_agent_handoffs,
)
from factory.agent_telemetry import (
    build_agent_chain_telemetry,
)
from factory.review_quality import (
    build_review_quality_report,
)
from factory.task_route_store import (
    get_task_route,
)
from factory.task_execution_service import (
    TaskExecutionDeps,
    TaskExecutionService,
)
from factory.task_graph_execution import (
    evaluate_task_execution_gate,
    list_newly_runnable_dependents,
)
from factory.task_graph_store import (
    add_task_dependency as db_add_task_dependency,
    add_task_graph_node as db_add_task_graph_node,
    create_task_graph as db_create_task_graph,
    get_task_graph as db_get_task_graph,
    list_runnable_tasks as db_list_runnable_tasks,
    list_task_graphs as db_list_task_graphs,
    topological_task_layers as db_topological_task_layers,
    topological_task_order as db_topological_task_order,
)
from factory.task_read_results import (
    get_task_read_result,
)
from factory.task_model_preferences import (
    set_task_model_preference,
)
from factory.task_secret_store import (
    TaskSecretStoreError,
    clear_task_secrets,
    scrub_prompt_with_secrets,
    set_task_secrets,
    validate_secret_items,
)
from factory.schemas import TaskSpec, TaskStatus
from factory.state import TaskStateMachine



def open_local_project_folder(
    project_path: str,
) -> None:
    if os.name == "nt":
        os.startfile(project_path)  # type: ignore[attr-defined]
        return

    if sys.platform == "darwin":
        subprocess.Popen(
            ["open", project_path],
        )
        return

    subprocess.Popen(
        ["xdg-open", project_path],
    )


def pick_local_project_folder(
    title: str = "Proje klasörünü seç",
) -> str | None:
    """Tek bir modern klasör seçici açar; iptalde None döner."""
    dialog_title = str(title or "").strip() or "Proje klasörünü seç"

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.wm_attributes("-topmost", 1)
        except Exception:
            pass
        selected = filedialog.askdirectory(
            title=dialog_title,
            mustexist=True,
        )
        root.destroy()
        return selected or None
    except Exception:
        pass

    # Tk açılamazsa (nadir): modern Windows diyalogu — eski tree diyaloğu yok
    if os.name == "nt":
        safe_title = dialog_title.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$dialog.Description = '{safe_title}'; "
            "$dialog.UseDescriptionForTitle = $true; "
            "$dialog.ShowNewFolderButton = $true; "
            "try { $dialog.AutoUpgradeEnabled = $true } catch {}; "
            "if ($dialog.ShowDialog() -eq "
            "[System.Windows.Forms.DialogResult]::OK) { "
            "Write-Output $dialog.SelectedPath "
            "}"
        )
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-STA",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            selected = (completed.stdout or "").strip()
            return selected or None
        except Exception:
            return None

    return None


class BrowseFolderRequest(BaseModel):
    title: str | None = None


class BrowseFolderResponse(BaseModel):
    path: str | None = None
    has_git: bool | None = None
    suggested_name: str | None = None
    characteristics: list[str] = Field(
        default_factory=list
    )


class ProjectInspectRequest(BaseModel):
    path: str = Field(min_length=1)


class ProjectInspectResponse(BaseModel):
    path: str
    exists: bool = True
    has_git: bool = False
    suggested_name: str | None = None
    characteristics: list[str] = Field(
        default_factory=list
    )


def open_local_project_terminal(
    project_path: str,
) -> None:
    if os.name == "nt":
        safe_path = project_path.replace(
            "'",
            "''",
        )

        subprocess.Popen(
            [
                "powershell.exe",
                "-NoExit",
                "-Command",
                (
                    "Set-Location "
                    f"-LiteralPath '{safe_path}'"
                ),
            ],
            creationflags=getattr(
                subprocess,
                "CREATE_NEW_CONSOLE",
                0,
            ),
        )
        return

    if sys.platform == "darwin":
        script = (
            'tell application "Terminal" '
            'to do script "cd '
            + project_path.replace(
                '"',
                '\\"',
            )
            + '"'
        )

        subprocess.Popen(
            ["osascript", "-e", script],
        )
        return

    subprocess.Popen(
        [
            "x-terminal-emulator",
            "--working-directory",
            project_path,
        ],
    )


app = FastAPI(
    title="AI Software Factory API",
    version="1.0",
)


API_PROVIDER_REGISTRY = (
    ModelClientProvider(
        ModelClient()
    ).registry
)


class ModelTestRequest(BaseModel):
    model: str
    prompt: str


class TaskSecretInput(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=2048)


class TaskCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    max_attempts: int = Field(default=2, ge=1, le=5)
    project_id: str | None = None
    model: str | None = None
    related_task_id: str | None = None
    # Optional controller-owned secrets. Values are
    # never echoed in TaskCreateResponse / list APIs.
    secrets: list[TaskSecretInput] | None = None


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str
    prompt: str
    max_attempts: int
    project_id: str | None = None
    state: str = "queued"
    model: str | None = None
    attempt: int = 0
    test_result: str | None = None
    started_at: str | None = None
    task_kind: str | None = None
    related_task_id: str | None = None
    # Capability names only — never values.
    secret_names: list[str] = Field(
        default_factory=list
    )



class ProjectMemorySupersedeRequest(BaseModel):
    replacement_memory_id: str = Field(
        min_length=1
    )


class ProjectMemoryResponse(BaseModel):
    memory_id: str
    project_id: str
    kind: str
    title: str
    content: str
    source_task_id: str | None = None
    status: str
    importance: int
    tags: list[str] = Field(
        default_factory=list
    )
    dedup_key: str | None = None
    superseded_by_memory_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


def project_memory_row_to_response(
    row: dict,
) -> ProjectMemoryResponse:
    return ProjectMemoryResponse(
        memory_id=row["memory_id"],
        project_id=row["project_id"],
        kind=row["kind"],
        title=row["title"],
        content=row["content"],
        source_task_id=row.get(
            "source_task_id"
        ),
        status=row["status"],
        importance=int(
            row["importance"]
        ),
        tags=list(
            row.get(
                "tags",
                []
            )
        ),
        dedup_key=row.get(
            "dedup_key"
        ),
        superseded_by_memory_id=row.get(
            "superseded_by_memory_id"
        ),
        created_at=row.get(
            "created_at"
        ),
        updated_at=row.get(
            "updated_at"
        ),
    )


class TaskGraphCreateRequest(BaseModel):
    project_id: str | None = None
    root_task_id: str | None = None


class TaskGraphNodeCreateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    parent_task_id: str | None = None


class TaskGraphDependencyCreateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    depends_on_task_id: str = Field(min_length=1)


class TaskGraphNodeResponse(BaseModel):
    graph_id: str
    task_id: str
    parent_task_id: str | None = None
    created_at: str | None = None
    depends_on: list[str] = Field(
        default_factory=list
    )


class TaskGraphResponse(BaseModel):
    graph_id: str
    project_id: str | None = None
    root_task_id: str | None = None
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    nodes: list[
        TaskGraphNodeResponse
    ] = Field(
        default_factory=list
    )


def task_graph_row_to_response(
    row: dict,
) -> TaskGraphResponse:
    nodes = [
        TaskGraphNodeResponse(
            graph_id=node["graph_id"],
            task_id=node["task_id"],
            parent_task_id=(
                node.get(
                    "parent_task_id"
                )
            ),
            created_at=node.get(
                "created_at"
            ),
            depends_on=list(
                node.get(
                    "depends_on",
                    [],
                )
            ),
        )
        for node in row.get(
            "nodes",
            [],
        )
    ]

    return TaskGraphResponse(
        graph_id=row["graph_id"],
        project_id=row.get(
            "project_id"
        ),
        root_task_id=row.get(
            "root_task_id"
        ),
        status=row["status"],
        created_at=row.get(
            "created_at"
        ),
        updated_at=row.get(
            "updated_at"
        ),
        nodes=nodes,
    )


class TaskGraphOrderResponse(BaseModel):
    graph_id: str
    order: list[str] = Field(
        default_factory=list
    )
    layers: list[list[str]] = Field(
        default_factory=list
    )


class TaskGraphRunnableResponse(BaseModel):
    graph_id: str
    runnable: list[str] = Field(
        default_factory=list
    )


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1)
    init_git: bool = False


class ProjectNewRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_path: str = Field(min_length=1)
    init_git: bool = True
    create_readme: bool = True
    create_gitignore: bool = True


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1)


class ProjectResponse(BaseModel):
    project_id: str
    name: str
    path: str
    created_at: str | None = None
    updated_at: str | None = None


class ProjectDeleteResponse(BaseModel):
    project_id: str
    deleted: bool = True


def project_row_to_response(
    row: dict,
) -> ProjectResponse:
    return ProjectResponse(
        project_id=row["project_id"],
        name=row["name"],
        path=row["path"],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def project_has_runtime_active_tasks(
    project_id: str,
) -> bool:
    """True if in-memory or DB tasks block deletion."""
    for task in TASKS.values():
        if (
            getattr(task, "project_id", None)
            == project_id
            and getattr(task, "state", None)
            in ACTIVE_PROJECT_TASK_STATES
        ):
            return True

    return db_project_has_active_tasks(project_id)


def normalize_and_validate_project_path(
    project_path: str,
    *,
    require_git: bool = True,
) -> str:
    try:
        normalized = normalize_project_path_for_storage(
            project_path
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if not os.path.isdir(normalized):
        raise HTTPException(
            status_code=400,
            detail="Seçilen klasör bulunamadı.",
        )

    if require_git and not path_has_git(normalized):
        raise HTTPException(
            status_code=400,
            detail=(
                "Seçilen klasör bir Git deposu değil. "
                "Klasörün içinde .git bulunmalı."
            ),
        )

    return normalized


def find_registered_project_by_path(
    project_path: str,
) -> dict | None:
    return find_project_by_canonical_path(
        project_path,
        db_list_projects(),
    )


TASKS: dict[str, TaskCreateResponse] = {}
TASK_CONTEXTS: dict[str, dict[str, object]] = {}
TASK_DIFFS: dict[str, str] = {}
TASK_LOGS: dict[str, list[str]] = {}


def append_task_log(
    task_id: str,
    message: str,
) -> None:
    TASK_LOGS.setdefault(task_id, []).append(message)
    db_append_task_log(task_id, message)


def persist_task(
    task: TaskCreateResponse,
    *,
    branch: str | None = None,
    worktree_path: str | None = None,
) -> None:
    db_upsert_task(
        task.task_id,
        prompt=task.prompt,
        status=task.status,
        max_attempts=task.max_attempts,
        state=task.state,
        model=task.model,
        attempt=task.attempt,
        test_result=task.test_result,
        started_at=task.started_at,
        project_id=task.project_id,
        branch=branch,
        worktree_path=(
            str(worktree_path)
            if worktree_path is not None
            else None
        ),
        related_task_id=task.related_task_id,
    )


def persist_and_publish_approved_task(
    task_id: str,
) -> TaskCreateResponse:
    """
    Durable approval commit for a verified Git merge.

    Stage approved status/state on a TaskCreateResponse copy, persist
    that snapshot to SQLite first, then publish into the live TASKS
    object only after the DB commit succeeds. This keeps TASKS from
    appearing approved when SQLite still has the prior state.
    """
    current = TASKS.get(task_id)

    if current is None:
        raise KeyError(f"Unknown task: {task_id}")

    candidate = current.model_copy(
        update={
            "status": "approved",
            "state": "approved",
        }
    )

    persist_task(candidate)

    current.status = "approved"
    current.state = "approved"

    return current


def persist_and_publish_rejected_task(
    task_id: str,
) -> TaskCreateResponse:
    """
    Durable reject commit before disposable worktree/branch cleanup.

    Stage rejected status/state on a TaskCreateResponse copy, persist
    that snapshot to SQLite first, then publish into the live TASKS
    object only after the DB commit succeeds. On persistence failure the
    live task stays ready_for_approval so evidence remains usable.
    """
    current = TASKS.get(task_id)

    if current is None:
        raise KeyError(f"Unknown task: {task_id}")

    candidate = current.model_copy(
        update={
            "status": "rejected",
            "state": "rejected",
        }
    )

    persist_task(candidate)

    current.status = "rejected"
    current.state = "rejected"

    return current


def build_orchestrator_for_task(
    task: TaskCreateResponse,
) -> Orchestrator:
    # Structured execution dependency bag for the
    # production API — not the legacy CLI execution
    # engine. Callers use project_path, worktree_root,
    # model_client, git_manager, and sandbox. They do
    # not invoke Orchestrator.run_task().
    if task.project_id is None:
        # Eski, FAZ 13 öncesi görevler için uyumluluk.
        return Orchestrator(
            provider_registry=API_PROVIDER_REGISTRY
        )

    project = db_get_project(
        task.project_id
    )

    if project is None:
        raise KeyError(
            f"Project not found: {task.project_id}"
        )

    return Orchestrator(
        project_path=project["path"],
        provider_registry=API_PROVIDER_REGISTRY,
    )

def hydrate_runtime_from_database() -> None:
    init_database()

    TASKS.clear()
    TASK_CONTEXTS.clear()
    TASK_LOGS.clear()
    TASK_DIFFS.clear()

    rows = db_list_tasks()
    recovery_orchestrator = None

    for row in reversed(rows):
        task = TaskCreateResponse(
            task_id=row["task_id"],
            status=row["status"],
            prompt=row["prompt"],
            max_attempts=int(
                row["max_attempts"] or 2
            ),
            project_id=row["project_id"],
            state=(
                row["state"]
                or row["status"]
            ),
            model=row["model"],
            attempt=int(
                row["attempt"] or 0
            ),
            test_result=row["test_result"],
            started_at=row["started_at"],
            related_task_id=row.get(
                "related_task_id"
            ),
        )

        route_record = get_task_route(
            task.task_id
        )

        if route_record is not None:
            task.task_kind = route_record["kind"]

        TASKS[task.task_id] = task

        logs = db_list_task_logs(
            task.task_id
        )

        if logs:
            TASK_LOGS[task.task_id] = logs

        diff_output = db_get_task_diff(
            task.task_id
        )

        if diff_output is not None:
            TASK_DIFFS[task.task_id] = diff_output

        # Restart sonrasında onay bekleyen görevlerin
        # geçici runtime context'ini yeniden oluştur.
        if (
            task.state == "ready_for_approval"
            and row["branch"]
            and row["worktree_path"]
            and diff_output is not None
        ):
            try:
                recovery_orchestrator = (
                    build_orchestrator_for_task(task)
                )
            except KeyError:
                # Projesi silinmiş bir görevin approval
                # context'ini yanlış repoda kurma.
                continue

            task_spec = TaskSpec(
                task_id=task.task_id,
                project_path=(
                    recovery_orchestrator.project_path
                ),
                request=task.prompt,
                status=TaskStatus.READY_FOR_APPROVAL,
                attempt=task.attempt,
                max_attempts=task.max_attempts,
            )

            state_machine = TaskStateMachine(
                task_spec
            )

            wt_result = SimpleNamespace(
                path=row["worktree_path"],
                branch=row["branch"],
            )

            TASK_CONTEXTS[task.task_id] = {
                "state_machine": state_machine,
                "wt_result": wt_result,
                "diff_output": diff_output,
            }


def recover_stale_execute_sessions_on_startup() -> None:
    """Recover dead-owner EXECUTE markers without sweeping execute/*.

    Runs after approval hydration. Live owners are skipped. Running
    execute tasks whose owner process is dead become failed so UI
    retry works. Legacy running execute tasks without a marker are
    left untouched (fail closed).
    """
    from factory.execute_recovery import (
        recover_stale_execute_markers,
    )
    from factory.orchestrator import Orchestrator

    default_root = Orchestrator().worktree_root

    def _get_task(task_id: str):
        return TASKS.get(task_id)

    def _get_task_kind(task_id: str) -> str | None:
        task = TASKS.get(task_id)
        if task is None:
            return None
        kind = getattr(task, "task_kind", None)
        if kind:
            return str(kind).strip().casefold()
        route = get_task_route(task_id)
        if route is None:
            return None
        return str(route.get("kind") or "").strip().casefold() or None

    def _get_project_path(task) -> str | None:
        project_id = getattr(task, "project_id", None)
        if project_id is None:
            return None
        project = db_get_project(project_id)
        if project is None:
            return None
        return project.get("path")

    def _mark_interrupted(task_id: str) -> None:
        task = TASKS.get(task_id)
        if task is None:
            return
        task.status = "failed"
        task.state = "failed"
        persist_task(task)

    recover_stale_execute_markers(
        worktree_root=default_root,
        get_task=_get_task,
        get_task_kind=_get_task_kind,
        get_project_path=_get_project_path,
        mark_interrupted=_mark_interrupted,
        append_log=append_task_log,
    )


hydrate_runtime_from_database()
recover_stale_execute_sessions_on_startup()

# APPROVAL_RUNTIME_RECOVERY_V2
def ensure_approval_runtime(task_id: str):
    """
    Restore approval runtime after a backend restart.

    TASKS and TASK_CONTEXTS are in-memory caches while the task record,
    branch and worktree metadata are persisted in SQLite.
    """
    task = TASKS.get(task_id)
    context = TASK_CONTEXTS.get(task_id)

    if task is None or (
        task.state == "ready_for_approval"
        and context is None
    ):
        hydrate_runtime_from_database()
        task = TASKS.get(task_id)
        context = TASK_CONTEXTS.get(task_id)

    return task, context


def api_approval_handler(
    task_id,
    state_machine,
    wt_result,
    diff_output,
):
    update_task_runtime(
        task_id,
        status="waiting_approval",
        state="ready_for_approval",
    )

    TASK_CONTEXTS[task_id] = {
        "state_machine": state_machine,
        "wt_result": wt_result,
        "diff_output": diff_output,
    }

    TASK_DIFFS[task_id] = diff_output

    db_save_task_diff(
        task_id,
        diff_output,
    )

    persist_task(
        TASKS[task_id],
        branch=wt_result.branch,
        worktree_path=wt_result.path,
    )

    append_task_log(
        task_id,
        "Testler başarılı. Onay bekleniyor.",
    )

    return "ready_for_approval"


def update_task_runtime(
    task_id: str,
    *,
    status: str | None = None,
    state: str | None = None,
    model: str | None = None,
    attempt: int | None = None,
    test_result: str | None = None,
) -> TaskCreateResponse:
    task = TASKS.get(task_id)

    if task is None:
        raise KeyError(f"Unknown task: {task_id}")

    if status is not None:
        task.status = status

    if state is not None:
        task.state = state

    if model is not None:
        task.model = model

    if attempt is not None:
        task.attempt = attempt

    if test_result is not None:
        task.test_result = test_result

    persist_task(task)

    return task


def cleanup_failed_task_for_api(
    orchestrator: Orchestrator,
    task_id: str,
) -> None:
    repo_name = os.path.basename(
        os.path.normpath(
            orchestrator.project_path
        )
    )

    worktree_path = os.path.join(
        orchestrator.worktree_root,
        repo_name,
        task_id.lower(),
    )

    branch_name = (
        f"agent/{task_id.lower()}"
    )

    # Multi-step gorevde plan ve worktree
    # birlikte mevcutsa FAILED durumu
    # retry edilebilir kabul edilir.
    # Bu nedenle calisma alani korunur.
    plan = get_task_plan(task_id)

    steps = (
        plan.get("steps", [])
        if plan
        else []
    )

    resumable_multi_step = bool(
        len(steps) > 1
        and os.path.isdir(worktree_path)
        and os.path.exists(
            os.path.join(
                worktree_path,
                ".git",
            )
        )
    )

    if resumable_multi_step:
        append_task_log(
            task_id,
            (
                "Multi-step worktree retry "
                "icin korundu."
            ),
        )
        return

    # Legacy/single-step veya yarim kalmis
    # worktree olusumu eski davranisla
    # temizlenir.
    try:
        orchestrator.git_manager.remove_worktree(
            worktree_path,
            force=True,
        )
    except Exception:
        pass

    try:
        orchestrator.git_manager.delete_branch(
            branch_name,
            force=True,
        )
    except Exception:
        pass


def api_progress_handler(
    task_id: str,
    *,
    attempt: int | None = None,
    test_result: str | None = None,
    message: str | None = None,
) -> None:
    update_task_runtime(
        task_id,
        attempt=attempt,
        test_result=test_result,
    )

    if message is not None:
        append_task_log(
            task_id,
            message,
        )

def release_runnable_graph_dependents(
    completed_task_id: str,
) -> list[str]:
    task_states = {}

    for (
        known_task_id,
        known_task,
    ) in TASKS.items():
        known_state = (
            getattr(
                known_task,
                "state",
                None,
            )
            or getattr(
                known_task,
                "status",
                None,
            )
            or ""
        )

        task_states[
            known_task_id
        ] = str(known_state)

    runnable = (
        list_newly_runnable_dependents(
            completed_task_id,
            task_states,
        )
    )

    released: list[str] = []

    for dependent_task_id in runnable:
        dependent_task = TASKS.get(
            dependent_task_id
        )

        if dependent_task is None:
            continue

        if (
            getattr(
                dependent_task,
                "state",
                None,
            )
            != "blocked"
        ):
            continue

        update_task_runtime(
            dependent_task_id,
            status="queued",
            state="queued",
        )

        append_task_log(
            dependent_task_id,
            (
                "Task Graph: dependencies "
                "tamamlandi. Gorev yeniden "
                "siraya alindi."
            ),
        )

        released.append(
            dependent_task_id
        )

    return released


def run_task_for_api(task_id: str):
    # Thin API worker entrypoint. Orchestration
    # lives in TaskExecutionService.
    service = TaskExecutionService(
        TaskExecutionDeps(
            get_task=lambda tid: TASKS.get(
                tid
            ),
            iter_tasks=lambda: TASKS.items(),
            append_log=append_task_log,
            update_runtime=update_task_runtime,
            evaluate_gate=(
                evaluate_task_execution_gate
            ),
            build_orchestrator=(
                build_orchestrator_for_task
            ),
            approval_handler=(
                api_approval_handler
            ),
            progress_handler=(
                api_progress_handler
            ),
            cleanup_failed=(
                cleanup_failed_task_for_api
            ),
            release_dependents=(
                release_runnable_graph_dependents
            ),
        )
    )
    return service.run(task_id)




@app.post(
    "/projects/browse-folder",
    response_model=BrowseFolderResponse,
)
async def browse_project_folder_endpoint(
    request: BrowseFolderRequest = BrowseFolderRequest(),
):
    title = request.title

    selected = await asyncio.to_thread(
        pick_local_project_folder,
        title or "Proje klasörünü seç",
    )
    if not selected:
        return BrowseFolderResponse(path=None)

    try:
        info = inspect_project_folder(selected)
    except ValueError:
        return BrowseFolderResponse(path=selected)

    return BrowseFolderResponse(
        path=info["path"],
        has_git=bool(info.get("has_git")),
        suggested_name=info.get("suggested_name"),
        characteristics=list(
            info.get("characteristics") or []
        ),
    )


@app.post(
    "/projects/inspect-path",
    response_model=ProjectInspectResponse,
)
def inspect_project_path_endpoint(
    request: ProjectInspectRequest,
):
    try:
        info = inspect_project_folder(request.path)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return ProjectInspectResponse(
        path=info["path"],
        exists=bool(info.get("exists", True)),
        has_git=bool(info.get("has_git")),
        suggested_name=info.get("suggested_name"),
        characteristics=list(
            info.get("characteristics") or []
        ),
    )


# NEW_PROJECT_CREATE_V1
@app.post(
    "/projects/create-new",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_new_project_endpoint(
    request: ProjectNewRequest,
):
    try:
        planned_path = planned_new_project_path(
            request.parent_path,
            request.name,
        )
        parent_path = Path(
            normalize_project_path_for_storage(
                request.parent_path
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    factory_root = Path(__file__).resolve().parents[1]

    try:
        planned_path.resolve().relative_to(
            factory_root.resolve()
        )
    except ValueError:
        pass
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "Yeni proje AI Software Factory klasorunun "
                "icinde olusturulamaz. Baska bir konum secin."
            ),
        )

    planned_path_text = normalize_project_path_for_storage(
        str(planned_path)
    )

    existing = find_registered_project_by_path(
        planned_path_text
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Bu proje yolu Factory'de zaten kayitli."
            ),
        )

    try:
        project_path = create_new_git_project(
            request.parent_path,
            request.name,
            init_git=request.init_git,
            create_readme=request.create_readme,
            create_gitignore=request.create_gitignore,
        )
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Git projesi olusturulamadi: "
                f"{exc}"
            ),
        ) from exc

    while True:
        project_id = (
            f"PROJECT-{random.randint(1000, 9999)}"
        )
        if db_get_project(project_id) is None:
            break

    try:
        row = db_create_project(
            project_id,
            name=request.name.strip(),
            path=project_path,
        )
    except Exception as exc:
        cleanup_error: str | None = None
        try:
            remove_newly_created_project_dir(
                Path(project_path),
                expected_parent=parent_path,
            )
        except Exception as cleanup_exc:
            cleanup_error = str(cleanup_exc)

        if cleanup_error is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Factory kaydi basarisiz oldu. "
                    "Bu istekte olusturulan proje klasoru geri alindi."
                ),
            ) from exc

        raise HTTPException(
            status_code=500,
            detail=(
                "Factory kaydi basarisiz oldu ve temizleme "
                "tamamlanamadi. Hedef klasor: "
                f"{project_path}. {cleanup_error}"
            ),
        ) from exc

    return project_row_to_response(row)


@app.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_endpoint(
    request: ProjectCreateRequest,
):
    project_path = normalize_and_validate_project_path(
        request.path,
        require_git=False,
    )

    existing = find_registered_project_by_path(
        project_path
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Bu proje yolu zaten kayıtlı.",
        )

    has_git = path_has_git(project_path)
    git_initialized_now = False

    if not has_git:
        if not request.init_git:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Seçilen klasör bir Git deposu değil. "
                    "Klasörün içinde .git bulunmalı."
                ),
            )
        try:
            project_path = init_git_in_existing_folder(
                project_path
            )
            git_initialized_now = True
        except FileExistsError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Git deposu olusturulamadi: "
                    f"{exc}"
                ),
            ) from exc

    while True:
        project_id = (
            f"PROJECT-{random.randint(1000, 9999)}"
        )

        if db_get_project(project_id) is None:
            break

    try:
        row = db_create_project(
            project_id,
            name=request.name.strip(),
            path=project_path,
        )
    except Exception as exc:
        if git_initialized_now:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Git baslatildi ancak Factory kaydi "
                    "basarisiz oldu. Kaynak dosyalar ve .git "
                    "korundu. 'Projeyi Ekle' ile tekrar deneyin."
                ),
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=(
                "Factory kaydi basarisiz oldu: "
                f"{exc}"
            ),
        ) from exc

    return project_row_to_response(row)


@app.get(
    "/projects",
    response_model=list[ProjectResponse],
)
def list_projects_endpoint():
    return [
        project_row_to_response(row)
        for row in db_list_projects()
    ]


@app.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
)
def get_project_endpoint(
    project_id: str,
):
    row = db_get_project(project_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    return project_row_to_response(row)


@app.get(
    "/projects/{project_id}/memories",
    response_model=list[ProjectMemoryResponse],
)
def list_project_memories_endpoint(
    project_id: str,
    status: str | None = "active",
    kind: str | None = None,
    limit: int | None = 100,
):
    project = db_get_project(
        project_id
    )

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    if (
        limit is not None
        and not 1 <= limit <= 500
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Memory limit must be "
                "between 1 and 500"
            ),
        )

    try:
        memories = db_list_project_memories(
            project_id,
            status=status,
            kind=kind,
            limit=limit,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return [
        project_memory_row_to_response(
            memory
        )
        for memory in memories
    ]


@app.get(
    "/projects/{project_id}/memories/{memory_id}",
    response_model=ProjectMemoryResponse,
)
def get_project_memory_endpoint(
    project_id: str,
    memory_id: str,
):
    project = db_get_project(
        project_id
    )

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    memory = db_get_project_memory(
        memory_id
    )

    # Deliberately return the same 404 for a missing
    # memory and for a memory belonging to another
    # project. Do not expose cross-project existence.
    if (
        memory is None
        or memory.get("project_id")
        != project_id
    ):
        raise HTTPException(
            status_code=404,
            detail="Project memory not found",
        )

    return project_memory_row_to_response(
        memory
    )


@app.post(
    "/projects/{project_id}/memories/{memory_id}/archive",
    response_model=ProjectMemoryResponse,
)
def archive_project_memory_endpoint(
    project_id: str,
    memory_id: str,
):
    project = db_get_project(
        project_id
    )

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    memory = db_get_project_memory(
        memory_id
    )

    if (
        memory is None
        or memory.get("project_id")
        != project_id
    ):
        raise HTTPException(
            status_code=404,
            detail="Project memory not found",
        )

    if memory.get("status") == "superseded":
        raise HTTPException(
            status_code=409,
            detail=(
                "Superseded project memory "
                "cannot be archived"
            ),
        )

    try:
        updated = db_update_project_memory(
            memory_id,
            status="archived",
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Project memory not found",
        ) from exc

    return project_memory_row_to_response(
        updated
    )


@app.post(
    "/projects/{project_id}/memories/{memory_id}/supersede",
)
def supersede_project_memory_endpoint(
    project_id: str,
    memory_id: str,
    request: ProjectMemorySupersedeRequest,
):
    project = db_get_project(
        project_id
    )

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    old_memory = db_get_project_memory(
        memory_id
    )

    replacement = db_get_project_memory(
        request.replacement_memory_id
    )

    # Same 404 response prevents cross-project
    # memory existence disclosure.
    if (
        old_memory is None
        or old_memory.get("project_id")
        != project_id
        or replacement is None
        or replacement.get("project_id")
        != project_id
    ):
        raise HTTPException(
            status_code=404,
            detail="Project memory not found",
        )

    try:
        result = db_supersede_project_memory(
            memory_id,
            request.replacement_memory_id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Project memory not found",
        ) from exc

    return {
        "superseded": (
            project_memory_row_to_response(
                result["superseded"]
            )
        ),
        "replacement": (
            project_memory_row_to_response(
                result["replacement"]
            )
        ),
    }


@app.put(
    "/projects/{project_id}",
    response_model=ProjectResponse,
)
def update_project_endpoint(
    project_id: str,
    request: ProjectUpdateRequest,
):
    current = db_get_project(project_id)

    if current is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    project_path = normalize_and_validate_project_path(
        request.path
    )

    existing = find_registered_project_by_path(
        project_path
    )

    if (
        existing is not None
        and existing["project_id"] != project_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Project path is already registered",
        )

    row = db_update_project(
        project_id,
        name=request.name.strip(),
        path=project_path,
    )

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    return project_row_to_response(row)


@app.delete(
    "/projects/{project_id}",
    response_model=ProjectDeleteResponse,
)
def delete_project_endpoint(
    project_id: str,
):
    """Remove Factory project registration only.

    Does not delete directories, repositories, worktrees,
    or any filesystem content belonging to the project.
    """
    current = db_get_project(project_id)

    if current is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    if project_has_runtime_active_tasks(
        project_id
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Bu projeye ait aktif görevler "
                "bulunduğu için proje "
                "kaldırılamıyor."
            ),
        )

    deleted = db_delete_project(project_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    return ProjectDeleteResponse(
        project_id=project_id,
        deleted=True,
    )


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/factory/status")
def factory_status():
    orchestrator = Orchestrator(
        provider_registry=API_PROVIDER_REGISTRY
    )

    return {
        "status": "ready",
        "project_path": orchestrator.project_path,
        "worktree_root": orchestrator.worktree_root,
    }

@app.get("/providers/health")
def provider_health_endpoint(
    refresh: bool = False,
):
    registry = API_PROVIDER_REGISTRY

    health_results = (
        registry.runtime_health_all(
            force_refresh=refresh
        )
    )

    return {
        "count": len(health_results),
        "refresh": refresh,
        "providers": [
            health.as_dict()
            for health in health_results
        ],
    }


@app.get(
    "/providers/{provider_name}/health"
)
def provider_health_detail_endpoint(
    provider_name: str,
    refresh: bool = False,
):
    registry = API_PROVIDER_REGISTRY

    if not registry.has(
        provider_name
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Provider not found: "
                f"{provider_name}"
            ),
        )

    health = registry.runtime_health(
        provider_name,
        force_refresh=refresh,
    )

    return health.as_dict()


@app.post(
    "/tasks",
    response_model=TaskCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_task(
    request: TaskCreateRequest,
    background_tasks: BackgroundTasks,
):
    if request.project_id is not None:
        selected_project = db_get_project(
            request.project_id
        )

        if selected_project is None:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )
    else:
        projects = db_list_projects()

        if len(projects) == 0:
            raise HTTPException(
                status_code=400,
                detail="No project is registered",
            )

        if len(projects) > 1:
            raise HTTPException(
                status_code=400,
                detail="project_id is required when multiple projects exist",
            )

        selected_project = projects[0]

    related_task_id = None

    if request.related_task_id is not None:
        related_raw = str(
            request.related_task_id
        ).strip()

        if related_raw:
            from factory.task_execution_evidence import (
                validate_related_task_id,
            )

            try:
                validate_related_task_id(
                    related_task_id=related_raw,
                    project_id=selected_project[
                        "project_id"
                    ],
                )
            except ValueError as exc:
                message = str(exc)

                if "not found" in message:
                    raise HTTPException(
                        status_code=404,
                        detail=message,
                    ) from exc

                raise HTTPException(
                    status_code=400,
                    detail=message,
                ) from exc

            related_task_id = related_raw

    try:
        secret_map = validate_secret_items(
            [
                item.model_dump()
                for item in (
                    request.secrets or []
                )
            ]
            if request.secrets
            else None
        )
    except TaskSecretStoreError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    while True:
        task_id = f"TASK-{random.randint(1000, 9999)}"
        if task_id not in TASKS:
            break

    scrubbed_prompt = scrub_prompt_with_secrets(
        request.prompt,
        secret_map,
    )
    secret_names = sorted(secret_map.keys())

    # Register secrets before making the task
    # runnable. On any later failure, clear them.
    if secret_map:
        try:
            set_task_secrets(task_id, secret_map)
        except TaskSecretStoreError as exc:
            clear_task_secrets(task_id)
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

    task = TaskCreateResponse(
        task_id=task_id,
        status="queued",
        prompt=scrubbed_prompt,
        max_attempts=request.max_attempts,
        project_id=selected_project["project_id"],
        started_at=datetime.now(timezone.utc).isoformat(),
        related_task_id=related_task_id,
        secret_names=secret_names,
    )

    try:
        TASKS[task_id] = task

        set_task_model_preference(
            task_id,
            request.model,
        )
        persist_task(task)

        TASK_LOGS[task_id] = []
        append_task_log(
            task_id,
            "Görev sıraya alındı.",
        )
    except Exception:
        clear_task_secrets(task_id)
        TASKS.pop(task_id, None)
        TASK_LOGS.pop(task_id, None)
        raise

    background_tasks.add_task(
        run_task_for_api,
        task_id,
    )

    return task


@app.get(
    "/tasks",
    response_model=list[TaskCreateResponse],
)
def list_tasks(
    project_id: str | None = None,
):
    tasks = list(TASKS.values())

    if project_id is None:
        return tasks

    return [
        task
        for task in tasks
        if task.project_id == project_id
    ]


@app.get(
    "/tasks/{task_id}",
    response_model=TaskCreateResponse,
)
def get_task(task_id: str):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return task

@app.post(
    "/tasks/{task_id}/approve",
    response_model=TaskCreateResponse,
)
def approve_task(
    task_id: str,
    background_tasks: BackgroundTasks,
):
    # User-facing HTTP details only. Technical exception text goes to
    # task logs — never interpolate {exc} into these strings.
    TASK_NOT_FOUND_DETAIL = "Görev bulunamadı."
    INVALID_APPROVAL_STATE_DETAIL = (
        "Görev şu anda onaylanabilir durumda değil."
    )
    APPROVAL_CONTEXT_UNAVAILABLE_DETAIL = (
        "Onay için gerekli görev bağlamı geri yüklenemedi."
    )
    PROJECT_UNAVAILABLE_DETAIL = (
        "Görevin bağlı olduğu proje kullanılamıyor."
    )
    NO_CHANGE_DETAIL = (
        "Birleştirilecek yeni Git değişikliği bulunamadı."
    )
    LOCAL_CONFLICT_DETAIL = (
        "yerel kullanıcı değişiklikleri ile task değişiklikleri çakışıyor."
    )
    CONCURRENT_CHANGE_DETAIL = (
        "Approval sırasında repository'de yeni kullanıcı değişiklikleri "
        "algılandı; otomatik rollback veri kaybı riski nedeniyle durduruldu."
    )
    LOCAL_CHANGES_PRESERVE_FAILED_DETAIL = (
        "Yerel değişiklikler güvenli şekilde korunamadığı için onay "
        "işlemi durduruldu."
    )
    LOCAL_CHANGES_STILL_DIRTY_DETAIL = (
        "Yerel değişiklikler güvenli şekilde ayrılamadığı için onay "
        "işlemi durduruldu."
    )
    MERGE_FAILED_DETAIL = (
        "Görev değişiklikleri ana dala birleştirilemedi. "
        "Görev kayıtlarını kontrol edin."
    )
    POST_MERGE_VERIFICATION_FAILED_DETAIL = (
        "Birleştirme tamamlandı ancak sonuç güvenli şekilde "
        "doğrulanamadı. Görev kayıtlarını kontrol edin."
    )
    RECOVERY_FAILED_DETAIL = (
        "Onay sırasında çakışma oluştu ve otomatik kurtarma "
        "tamamlanamadı. Görev kayıtlarını kontrol edin."
    )
    APPROVAL_PERSISTENCE_FAILED_DETAIL = (
        "Birleştirme tamamlandı ancak onay durumu kaydedilemedi. "
        "Görev kayıtlarını kontrol edin."
    )

    task, context = ensure_approval_runtime(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail=TASK_NOT_FOUND_DETAIL,
        )

    if task.state != "ready_for_approval":
        append_task_log(
            task_id,
            (
                "Approval refused: task state is "
                f"{task.state!r}, expected 'ready_for_approval'"
            ),
        )
        raise HTTPException(
            status_code=409,
            detail=INVALID_APPROVAL_STATE_DETAIL,
        )

    if context is None:
        append_task_log(
            task_id,
            (
                "Approval runtime context could not be recovered from "
                f"SQLite for {task_id}"
            ),
        )
        raise HTTPException(
            status_code=409,
            detail=APPROVAL_CONTEXT_UNAVAILABLE_DETAIL,
        )

    state_machine = context["state_machine"]
    wt_result = context["wt_result"]

    try:
        orchestrator = build_orchestrator_for_task(
            task
        )
    except KeyError as exc:
        append_task_log(
            task_id,
            f"Approval orchestrator unavailable: {exc}",
        )
        raise HTTPException(
            status_code=409,
            detail=PROJECT_UNAVAILABLE_DETAIL,
        ) from exc

    git_manager = orchestrator.git_manager

    local_snapshot = None
    target_head_before = None
    task_head = None
    target_head_after = None

    def _restore_local_snapshot_or_recover(
        *,
        context: str,
    ) -> None:
        """Restore Factory snapshot; never drop on failure."""
        nonlocal local_snapshot
        if local_snapshot is None:
            return
        try:
            git_manager.restore_local_changes(
                local_snapshot,
                restore_index=True,
            )
        except Exception as restore_exc:
            append_task_log(
                task_id,
                (
                    f"{context}: failed to restore local user changes "
                    f"from snapshot {local_snapshot.commit_sha} "
                    f"({local_snapshot.label}): {restore_exc}. "
                    "Snapshot was NOT dropped; manual recovery required."
                ),
            )
            raise

        try:
            git_manager.drop_local_changes_snapshot(
                local_snapshot
            )
            local_snapshot = None
        except Exception as drop_exc:
            append_task_log(
                task_id,
                (
                    f"{context}: local user changes were restored, but "
                    f"snapshot cleanup failed for "
                    f"{local_snapshot.commit_sha}: {drop_exc}. "
                    "No data loss; approval flow continues."
                ),
            )
            local_snapshot = None

    def _rollback_merge_and_restore_locals(
        *,
        reason: str,
    ) -> None:
        """
        Undo a completed Factory merge commit and restore the pre-approval
        local working tree. Fail closed on concurrent / unowned dirty paths
        or working-tree fingerprint drift (same-owned-path races).
        """
        nonlocal local_snapshot
        if (
            target_head_before is None
            or target_head_after is None
        ):
            raise RuntimeError(
                "Cannot roll back merge without recorded HEAD bounds"
            )

        # Capture guard immediately after restore conflict, before any
        # destructive rollback work. reset_repository_to re-verifies it.
        expected_guard = git_manager.capture_working_tree_guard()

        owned_paths: set[str] = set()
        if local_snapshot is not None:
            owned_paths |= git_manager.list_snapshot_owned_paths(
                local_snapshot
            )
        owned_paths |= git_manager.list_commit_range_paths(
            target_head_before,
            target_head_after,
        )

        try:
            git_manager.reset_repository_to(
                target_head_before,
                expected_current_head=target_head_after,
                owned_paths=owned_paths,
                expected_guard=expected_guard,
                snapshot=local_snapshot,
            )
        except Exception as reset_exc:
            from factory.tools.git_ops import UnsafeRollbackError

            append_task_log(
                task_id,
                (
                    f"{reason}: safe rollback refused "
                    f"({reset_exc}). Snapshot "
                    f"{getattr(local_snapshot, 'commit_sha', None)} "
                    "was NOT dropped; merge HEAD may still include the "
                    "task tip; branch/worktree evidence preserved."
                ),
            )
            if isinstance(reset_exc, UnsafeRollbackError):
                raise HTTPException(
                    status_code=409,
                    detail=CONCURRENT_CHANGE_DETAIL,
                ) from reset_exc
            raise

        if local_snapshot is None:
            return

        try:
            git_manager.restore_local_changes(
                local_snapshot,
                restore_index=True,
            )
        except Exception as restore_exc:
            append_task_log(
                task_id,
                (
                    f"{reason}: merge rolled back to "
                    f"{target_head_before}, but restoring local user "
                    f"changes from snapshot {local_snapshot.commit_sha} "
                    f"({local_snapshot.label}) failed: {restore_exc}. "
                    "Snapshot was NOT dropped; manual recovery required."
                ),
            )
            raise

        try:
            git_manager.drop_local_changes_snapshot(
                local_snapshot
            )
            local_snapshot = None
        except Exception as drop_exc:
            append_task_log(
                task_id,
                (
                    f"{reason}: local user changes restored after "
                    f"merge rollback, but snapshot cleanup failed for "
                    f"{local_snapshot.commit_sha}: {drop_exc}."
                ),
            )
            local_snapshot = None

    # PHASE 1A — Before / during merge. abort_merge only here.
    try:
        worktree_status = git_manager.get_status(
            wt_result.path
        )

        if worktree_status.strip():
            git_manager.commit_all(
                wt_result.path,
                f"{task_id}: AI generated changes",
            )

        target_head_before = (
            git_manager.get_repository_head()
        )
        task_head = git_manager.get_branch_head(
            wt_result.branch
        )

        # Reject when the task tip is already in target history.
        # Covers identical tips, behind branches, and already-merged commits.
        # Run BEFORE touching the dirty main working tree.
        if git_manager.is_ancestor(
            task_head,
            target_head_before,
        ):
            raise HTTPException(
                status_code=409,
                detail=NO_CHANGE_DETAIL,
            )

        main_status = git_manager.get_repository_status()
        if main_status.strip():
            snapshot_label = (
                f"factory-approval-{task_id}-{uuid.uuid4().hex[:12]}"
            )
            try:
                local_snapshot = (
                    git_manager.preserve_local_changes(
                        snapshot_label
                    )
                )
            except Exception as preserve_exc:
                append_task_log(
                    task_id,
                    (
                        "Approval preserve local changes failed: "
                        f"{preserve_exc}"
                    ),
                )
                raise HTTPException(
                    status_code=409,
                    detail=LOCAL_CHANGES_PRESERVE_FAILED_DETAIL,
                ) from preserve_exc

            remaining = git_manager.get_repository_status()
            if remaining.strip():
                try:
                    _restore_local_snapshot_or_recover(
                        context=(
                            "Dirty-main preserve left repository dirty"
                        ),
                    )
                except Exception:
                    pass
                raise HTTPException(
                    status_code=409,
                    detail=LOCAL_CHANGES_STILL_DIRTY_DETAIL,
                )

        git_manager.merge_branch(
            wt_result.branch
        )

    except HTTPException:
        # Controlled Git-phase rejections (including no-change).
        # No-change is raised before any stash, so local_snapshot is None.
        if local_snapshot is not None:
            try:
                _restore_local_snapshot_or_recover(
                    context="Approval HTTP rejection after preserve",
                )
            except Exception:
                pass
        raise

    except Exception as exc:
        # APPROVAL_MERGE_ABORT_V1
        # Only abort while merge is incomplete / conflicted.
        try:
            git_manager.abort_merge()
        except Exception:
            pass

        if local_snapshot is not None:
            try:
                _restore_local_snapshot_or_recover(
                    context="Approval merge failure",
                )
            except Exception:
                pass

        append_task_log(
            task_id,
            f"Approval merge failed: {exc}",
        )
        raise HTTPException(
            status_code=409,
            detail=MERGE_FAILED_DETAIL,
        ) from exc

    # PHASE 1B — Merge command returned successfully. Verify Git truth.
    # A completed merge commit cannot be assumed undoable via merge --abort.
    try:
        target_head_after = (
            git_manager.get_repository_head()
        )

        if not git_manager.is_ancestor(
            task_head,
            target_head_after,
        ):
            raise RuntimeError(
                "task commit "
                f"{task_head} is not an ancestor of "
                f"target HEAD {target_head_after}"
            )

    except Exception as exc:
        if local_snapshot is not None:
            try:
                _restore_local_snapshot_or_recover(
                    context="Post-merge verification failure",
                )
            except Exception:
                pass

        append_task_log(
            task_id,
            (
                "Post-merge verification failed after merge command "
                f"completed: {exc}. Git target may already include the "
                "merge; manual reconciliation inspection is required. "
                "Branch/worktree evidence was preserved."
            ),
        )
        raise HTTPException(
            status_code=409,
            detail=POST_MERGE_VERIFICATION_FAILED_DETAIL,
        ) from exc

    # PHASE 1C — Restore preserved local user changes onto merged HEAD.
    # Conflicts here mean approval must NOT persist; roll merge back.
    if local_snapshot is not None:
        try:
            git_manager.restore_local_changes(
                local_snapshot,
                restore_index=True,
            )
        except Exception as restore_exc:
            try:
                _rollback_merge_and_restore_locals(
                    reason=(
                        "Local restore conflict after verified merge"
                    ),
                )
            except HTTPException:
                # Concurrent-change / controlled rollback refusal.
                raise
            except Exception as rollback_exc:
                append_task_log(
                    task_id,
                    (
                        "Transactional approval rollback failed after "
                        f"local restore conflict: {rollback_exc}. "
                        f"Original restore error: {restore_exc}. "
                        "Snapshot retained if still present; task stays "
                        "ready_for_approval."
                    ),
                )
                raise HTTPException(
                    status_code=409,
                    detail=RECOVERY_FAILED_DETAIL,
                ) from rollback_exc

            raise HTTPException(
                status_code=409,
                detail=LOCAL_CONFLICT_DETAIL,
            ) from restore_exc

        try:
            git_manager.drop_local_changes_snapshot(
                local_snapshot
            )
            local_snapshot = None
        except Exception as drop_exc:
            # User changes are already restored — do not roll back merge.
            append_task_log(
                task_id,
                (
                    "Approval warning: local user changes were restored "
                    "after merge, but snapshot cleanup failed for "
                    f"{local_snapshot.commit_sha}: {drop_exc}"
                ),
            )
            local_snapshot = None

    # PHASE 2 — Persistent application commit (SQLite is authoritative).
    # Git truth is already established. Never abort_merge from this point.
    #
    # Recovery note: if this persistence fails, Git already contains the
    # task tip while DB still says ready_for_approval. Retrying approve
    # may then hit the no-change gate. Preserve branch/worktree evidence
    # and return a controlled 409; automatic reconciliation is out of scope.
    try:
        persist_and_publish_approved_task(task_id)
    except Exception as exc:
        append_task_log(
            task_id,
            (
                "Approval persistence failed after verified merge: "
                f"{exc}. Git merge remains applied; task stays "
                "ready_for_approval pending recovery."
            ),
        )
        raise HTTPException(
            status_code=409,
            detail=APPROVAL_PERSISTENCE_FAILED_DETAIL,
        ) from exc

    # PHASE 3 — Ephemeral synchronization / finalization.
    # Failures here must not invalidate the durable approved DB commit.
    try:
        state_machine.transition(TaskStatus.APPROVED)
    except Exception as exc:
        append_task_log(
            task_id,
            (
                "Approval state-machine synchronization warning: "
                f"{exc}"
            ),
        )

    try:
        capture_approved_task_memory(
            task_id
        )
    except Exception as exc:
        append_task_log(
            task_id,
            (
                "Project memory capture failed "
                f"after approval: {exc}"
            ),
        )

    TASK_CONTEXTS.pop(task_id, None)

    append_task_log(
        task_id,
        "Görev onaylandı ve ana dala birleştirildi.",
    )

    try:
        git_manager.remove_worktree(
            wt_result.path
        )
        git_manager.delete_branch(
            wt_result.branch
        )
    except Exception as cleanup_exc:
        append_task_log(
            task_id,
            (
                "Approval cleanup warning: merge is verified "
                "and task remains approved, but worktree/branch "
                f"cleanup failed: {cleanup_exc}"
            ),
        )

    released_dependents = (
        release_runnable_graph_dependents(
            task_id
        )
    )

    for dependent_task_id in (
        released_dependents
    ):
        background_tasks.add_task(
            run_task_for_api,
            dependent_task_id,
        )

    return TASKS[task_id]

@app.post(
    "/tasks/{task_id}/reject",
    response_model=TaskCreateResponse,
)
def reject_task(task_id: str):
    # User-facing HTTP details only. Technical exception text goes to
    # task logs — never interpolate {exc} into these strings.
    TASK_NOT_FOUND_DETAIL = "Görev bulunamadı."
    INVALID_REJECTION_STATE_DETAIL = (
        "Görev şu anda reddedilebilir durumda değil."
    )
    REJECTION_CONTEXT_UNAVAILABLE_DETAIL = (
        "Reddetme için gerekli görev bağlamı geri yüklenemedi."
    )
    PROJECT_UNAVAILABLE_DETAIL = (
        "Görevin bağlı olduğu proje kullanılamıyor."
    )
    REJECTION_PERSISTENCE_FAILED_DETAIL = (
        "Reddetme durumu kaydedilemedi. "
        "Görev kayıtlarını kontrol edin."
    )

    task, context = ensure_approval_runtime(task_id)

    if task is None:
        append_task_log(
            task_id,
            (
                "Reject refused: task not found after SQLite "
                f"recovery: {task_id}"
            ),
        )
        raise HTTPException(
            status_code=404,
            detail=TASK_NOT_FOUND_DETAIL,
        )

    if task.state != "ready_for_approval":
        append_task_log(
            task_id,
            (
                "Reject refused: task state is "
                f"{task.state!r}, expected 'ready_for_approval'"
            ),
        )
        raise HTTPException(
            status_code=409,
            detail=INVALID_REJECTION_STATE_DETAIL,
        )

    if context is None:
        append_task_log(
            task_id,
            (
                "Approval runtime context could not be recovered from "
                f"SQLite for {task_id}"
            ),
        )
        raise HTTPException(
            status_code=409,
            detail=REJECTION_CONTEXT_UNAVAILABLE_DETAIL,
        )

    state_machine = context["state_machine"]
    wt_result = context["wt_result"]
    worktree_path = wt_result.path
    branch_name = wt_result.branch

    try:
        orchestrator = build_orchestrator_for_task(
            task
        )
    except KeyError as exc:
        append_task_log(
            task_id,
            f"Reject orchestrator unavailable: {exc}",
        )
        raise HTTPException(
            status_code=409,
            detail=PROJECT_UNAVAILABLE_DETAIL,
        ) from exc

    git_manager = orchestrator.git_manager

    # PHASE 1 — Durable reject decision (SQLite is authoritative).
    # Do not mutate live TASKS, cleanup evidence, or sync the state
    # machine until this commit succeeds.
    try:
        persist_and_publish_rejected_task(task_id)
    except Exception as exc:
        append_task_log(
            task_id,
            f"Task rejection persistence failed: {exc}",
        )
        raise HTTPException(
            status_code=500,
            detail=REJECTION_PERSISTENCE_FAILED_DETAIL,
        ) from exc

    # PHASE 2 — Ephemeral synchronization / disposable cleanup.
    # Failures here must not invalidate the durable rejected DB commit.
    try:
        state_machine.transition(TaskStatus.REJECTED)
    except Exception as exc:
        append_task_log(
            task_id,
            (
                "Reject state-machine synchronization failed: "
                f"{exc}"
            ),
        )

    TASK_CONTEXTS.pop(task_id, None)

    try:
        git_manager.remove_worktree(
            worktree_path,
            force=True,
        )
    except Exception as cleanup_exc:
        append_task_log(
            task_id,
            (
                "Reject cleanup warning: worktree cleanup failed: "
                f"{cleanup_exc}"
            ),
        )

    try:
        git_manager.delete_branch(
            branch_name,
            force=True,
        )
    except Exception as cleanup_exc:
        append_task_log(
            task_id,
            (
                "Reject cleanup warning: branch cleanup failed: "
                f"{cleanup_exc}"
            ),
        )

    append_task_log(
        task_id,
        "Görev reddedildi.",
    )

    return TASKS[task_id]

class TaskDiffResponse(BaseModel):
    task_id: str
    diff: str


@app.get(
    "/tasks/{task_id}/diff",
    response_model=TaskDiffResponse,
)
def get_task_diff(task_id: str):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    diff_output = TASK_DIFFS.get(task_id)

    if diff_output is None:
        raise HTTPException(
            status_code=409,
            detail="Task diff is not available",
        )

    return TaskDiffResponse(
        task_id=task_id,
        diff=diff_output,
    )


@app.post(
    "/tasks/{task_id}/retry",
    response_model=TaskCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    if task.state != "failed":
        raise HTTPException(
            status_code=409,
            detail="Only failed tasks can be retried",
        )

    # Capture failure evidence before active
    # step state is reset. task_logs keep the
    # historical record; task_steps become the
    # fresh retry state.
    existing_plan = get_task_plan(task_id)
    failure_evidence = []

    if existing_plan is not None:
        for step in existing_plan.get(
            "steps",
            [],
        ):
            status_value = str(
                step.get("status", "")
            ).strip().casefold()

            if status_value not in {
                "failed",
                "running",
            }:
                continue

            error_text = str(
                step.get("error") or ""
            ).strip()

            if not error_text:
                continue

            failure_evidence.append(
                {
                    "step_index": step.get(
                        "step_index"
                    ),
                    "kind": step.get("kind"),
                    "attempt": step.get(
                        "attempt"
                    ),
                    "error": error_text,
                }
            )

    TASK_CONTEXTS.pop(task_id, None)
    TASK_DIFFS.pop(task_id, None)

    db_delete_task_diff(task_id)

    append_task_log(
        task_id,
        (
            "Retry baslatildi. Onceki basarisiz "
            "calisma korunuyor."
        ),
    )

    for evidence in failure_evidence:
        append_task_log(
            task_id,
            (
                "Onceki run failure evidence: "
                f"step={evidence['step_index']} "
                f"kind={evidence['kind']} "
                f"attempt={evidence['attempt']} "
                f"error={evidence['error']}"
            ),
        )

    reset_retryable_task_steps(task_id)

    task.status = "queued"
    task.state = "queued"
    task.model = None
    task.attempt = 0
    task.test_result = None
    task.started_at = datetime.now(
        timezone.utc
    ).isoformat()

    persist_task(task)

    append_task_log(
        task_id,
        "Görev yeniden sıraya alındı.",
    )

    background_tasks.add_task(
        run_task_for_api,
        task_id,
    )

    return task

@app.get("/tasks/{task_id}/events")
async def task_events(task_id: str):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    async def event_stream():
        index = 0

        while True:
            logs = TASK_LOGS.get(task_id, [])

            while index < len(logs):
                payload = json.dumps(
                    {
                        "message": logs[index],
                    },
                    ensure_ascii=False,
                )

                yield f"data: {payload}\n\n"
                index += 1

            current_task = TASKS.get(task_id)

            if current_task is None:
                break

            if current_task.state in {
                "ready_for_approval",
                "approved",
                "rejected",
                "failed",
            }:
                payload = json.dumps(
                    {
                        "state": current_task.state,
                    },
                    ensure_ascii=False,
                )

                yield (
                    "event: done\n"
                    f"data: {payload}\n\n"
                )
                break

            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )




@app.get("/control-center/status")
def control_center_status(
    project_id: str | None = None,
    refresh: bool = False,
):
    project_path = Orchestrator().project_path
    selected_tasks = list(
        TASKS.values()
    )

    if project_id is not None:
        project = db_get_project(
            project_id
        )

        if project is None:
            raise HTTPException(
                status_code=404,
                detail="Proje bulunamadı.",
            )

        project_path = project["path"]

        selected_tasks = [
            task
            for task in TASKS.values()
            if task.project_id
            == project_id
        ]

    return get_control_center_status(
        project_path=project_path,
        tasks=selected_tasks,
        provider_registry=(
            API_PROVIDER_REGISTRY
        ),
        project_id=project_id,
        db_path=DEFAULT_DB_PATH,
        use_cache=not refresh,
    )

@app.get(
    "/projects/{project_id}/control-center/status"
)
def project_control_center_status(
    project_id: str,
    refresh: bool = False,
):
    return control_center_status(
        project_id=project_id,
        refresh=refresh,
    )


@app.get("/tasks/{task_id}/pipeline")
def task_pipeline(task_id: str):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Görev bulunamadı.",
        )

    logs = TASK_LOGS.get(
        task_id,
        [],
    )

    route_record = get_task_route(
        task_id
    )

    task_kind = (
        route_record["kind"]
        if route_record is not None
        else None
    )

    # Eski gorevlerde DB route kaydi yoksa
    # mevcut loglardan READ kararini geri kazan.
    if task_kind is None:
        if any(
            "task router: read"
            in str(item).casefold()
            for item in logs
        ):
            task_kind = "read"

    return build_task_pipeline(
        task,
        logs,
        task_kind=task_kind,
    )



@app.post("/projects/{project_id}/open")
def open_project_folder(project_id: str):
    project = db_get_project(project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Proje bulunamadı.",
        )

    try:
        open_local_project_folder(
            project["path"]
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Proje açılamadı: {exc}",
        ) from exc

    return {
        "ok": True,
        "project_id": project_id,
    }


@app.post("/projects/{project_id}/terminal")
def open_project_terminal(project_id: str):
    project = db_get_project(project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Proje bulunamadı.",
        )

    try:
        open_local_project_terminal(
            project["path"]
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Terminal açılamadı: {exc}",
        ) from exc

    return {
        "ok": True,
        "project_id": project_id,
    }



@app.post("/models/test")
def test_local_model(payload: ModelTestRequest):
    model = payload.model.strip()
    prompt = payload.prompt.strip()

    if not model:
        raise HTTPException(
            status_code=400,
            detail="Model adı zorunludur.",
        )

    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="Prompt zorunludur.",
        )

    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
    ).encode("utf-8")

    request = urllib_request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=body,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    started = time.perf_counter()

    try:
        with urllib_request.urlopen(
            request,
            timeout=180,
        ) as response:
            raw = response.read().decode("utf-8")

    except urllib_error.HTTPError as exc:
        detail = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise HTTPException(
            status_code=502,
            detail=f"Ollama hatası: {detail}",
        ) from exc

    except urllib_error.URLError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama servisine ulaşılamıyor.",
        ) from exc

    elapsed_ms = round(
        (time.perf_counter() - started) * 1000
    )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="Ollama geçersiz JSON döndürdü.",
        ) from exc

    answer = result.get("response")

    if not isinstance(answer, str):
        raise HTTPException(
            status_code=502,
            detail="Ollama yanıtı bulunamadı.",
        )

    return {
        "model": model,
        "response": answer,
        "duration_ms": elapsed_ms,
        "done": bool(result.get("done", True)),
    }




@app.get("/tasks/{task_id}/plan")
def get_task_plan_endpoint(
    task_id: str,
):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    plan = get_task_plan(task_id)

    return {
        "task_id": task_id,
        "state": task.state,
        "task_kind": task.task_kind,
        "plan": plan,
    }



@app.get("/tasks/{task_id}/agent-executions")
def get_task_agent_executions_endpoint(
    task_id: str,
):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return {
        "task_id": task_id,
        "state": task.state,
        "executions": list_agent_executions(
            task_id
        ),
    }


@app.get("/tasks/{task_id}/commands")
def get_task_commands_endpoint(
    task_id: str,
):
    """Read-only command history for Terminal UI.

    No public command execution endpoint in Step 1.
    """
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return {
        "task_id": task_id,
        "state": task.state,
        "commands": list_task_commands(
            task_id
        ),
    }


@app.get("/tasks/{task_id}/checkpoints")
def get_task_checkpoints_endpoint(
    task_id: str,
):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return {
        "task_id": task_id,
        "state": task.state,
        "checkpoints": list_agent_checkpoints(
            task_id
        ),
    }


@app.get("/tasks/{task_id}/quality-reviews")
def get_task_quality_reviews_endpoint(
    task_id: str,
):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    checkpoints = list_agent_checkpoints(
        task_id
    )

    return {
        "task_id": task_id,
        "state": task.state,
        **build_review_quality_report(
            checkpoints
        ),
    }


@app.get("/tasks/{task_id}/handoffs")
def get_task_handoffs_endpoint(
    task_id: str,
):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return {
        "task_id": task_id,
        "state": task.state,
        "handoffs": list_agent_handoffs(
            task_id
        ),
    }



@app.get("/tasks/{task_id}/agent-chain")
def get_task_agent_chain_endpoint(
    task_id: str,
):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return {
        "task_id": task_id,
        "state": task.state,
        "telemetry": (
            build_agent_chain_telemetry(
                task_id
            )
        ),
    }


@app.get("/tasks/{task_id}/result")
def get_task_result_endpoint(
    task_id: str,
):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Gorev bulunamadi.",
        )

    result = get_task_read_result(
        task_id,
    )

    return {
        "task_id": task_id,
        "state": task.state,
        "result": result,
    }



@app.post(
    "/task-graphs",
    response_model=TaskGraphResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task_graph_api(
    request: TaskGraphCreateRequest,
):
    existing_ids = {
        row["graph_id"]
        for row in db_list_task_graphs()
    }

    while True:
        graph_id = (
            f"GRAPH-{random.randint(1000, 9999)}"
        )

        if graph_id not in existing_ids:
            break

    created = db_create_task_graph(
        graph_id,
        project_id=request.project_id,
        root_task_id=request.root_task_id,
    )

    return task_graph_row_to_response(
        created
    )


@app.get(
    "/task-graphs",
    response_model=list[TaskGraphResponse],
)
def list_task_graphs_api():
    rows = db_list_task_graphs()

    return [
        task_graph_row_to_response(
            row
        )
        for row in rows
    ]


@app.get(
    "/task-graphs/{graph_id}",
    response_model=TaskGraphResponse,
)
def get_task_graph_api(
    graph_id: str,
):
    graph = db_get_task_graph(
        graph_id
    )

    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Task graph not found",
        )

    return task_graph_row_to_response(
        graph
    )



@app.post(
    "/task-graphs/{graph_id}/nodes",
    response_model=TaskGraphResponse,
)
def add_task_graph_node_api(
    graph_id: str,
    request: TaskGraphNodeCreateRequest,
):
    graph = db_get_task_graph(
        graph_id
    )

    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Task graph not found",
        )

    try:
        db_add_task_graph_node(
            graph_id,
            request.task_id,
            parent_task_id=(
                request.parent_task_id
            ),
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    updated = db_get_task_graph(
        graph_id
    )

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="Task graph not found",
        )

    return task_graph_row_to_response(
        updated
    )


@app.post(
    "/task-graphs/{graph_id}/dependencies",
    response_model=TaskGraphResponse,
)
def add_task_graph_dependency_api(
    graph_id: str,
    request: TaskGraphDependencyCreateRequest,
):
    graph = db_get_task_graph(
        graph_id
    )

    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Task graph not found",
        )

    try:
        db_add_task_dependency(
            graph_id,
            request.task_id,
            request.depends_on_task_id,
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    updated = db_get_task_graph(
        graph_id
    )

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="Task graph not found",
        )

    return task_graph_row_to_response(
        updated
    )



@app.get(
    "/task-graphs/{graph_id}/order",
    response_model=TaskGraphOrderResponse,
)
def get_task_graph_order_api(
    graph_id: str,
):
    graph = db_get_task_graph(
        graph_id
    )

    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Task graph not found",
        )

    try:
        order = db_topological_task_order(
            graph_id
        )

        layers = db_topological_task_layers(
            graph_id
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return TaskGraphOrderResponse(
        graph_id=graph_id,
        order=order,
        layers=layers,
    )


@app.get(
    "/task-graphs/{graph_id}/runnable",
    response_model=TaskGraphRunnableResponse,
)
def get_task_graph_runnable_api(
    graph_id: str,
):
    graph = db_get_task_graph(
        graph_id
    )

    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Task graph not found",
        )

    task_states: dict[str, str] = {}

    for task_id, task in TASKS.items():
        current_state = (
            getattr(
                task,
                "state",
                None,
            )
            or getattr(
                task,
                "status",
                None,
            )
            or ""
        )

        task_states[
            task_id
        ] = str(current_state)

    runnable = db_list_runnable_tasks(
        graph_id,
        task_states,
    )

    return TaskGraphRunnableResponse(
        graph_id=graph_id,
        runnable=runnable,
    )
