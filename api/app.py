from urllib import error as urllib_error
from urllib import request as urllib_request
import time
import asyncio
import json
import os
import random
import subprocess
import sys
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse

from factory.database import (
    DEFAULT_DB_PATH,
    append_task_log as db_append_task_log,
    clear_task_logs as db_clear_task_logs,
    delete_task_diff as db_delete_task_diff,
    get_task_diff as db_get_task_diff,
    init_database,
    list_task_logs as db_list_task_logs,
    list_tasks as db_list_tasks,
    save_task_diff as db_save_task_diff,
    upsert_task as db_upsert_task,
    create_project as db_create_project,
    delete_project as db_delete_project,
    get_project as db_get_project,
    get_project_by_path as db_get_project_by_path,
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
    planned_new_project_path,
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
from factory.agent_handoff_store import (
    list_agent_handoffs,
)
from factory.agent_telemetry import (
    build_agent_chain_telemetry,
)
from factory.review_quality import (
    build_review_quality_report,
)
from factory.model_router import ModelRoute, route_model
from factory.task_router import route_task
from factory.semantic_task_router import (
    route_task_semantic,
)
from factory.task_route_store import (
    get_task_route,
    save_task_route,
)
from factory.read_task_runner import run_read_task
from factory.execute_task_runner import (
    run_execute_task,
)
from factory.task_execution_dispatcher import execute_write_task
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
    save_task_read_result,
)
from factory.task_model_preferences import (
    get_task_model_preference,
    set_task_model_preference,
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


def pick_local_project_folder() -> str | None:
    """Tek bir modern klasör seçici açar; iptalde None döner."""
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
            title="Proje klasörünü seç",
            mustexist=True,
        )
        root.destroy()
        return selected or None
    except Exception:
        pass

    # Tk açılamazsa (nadir): modern Windows diyalogu — eski tree diyaloğu yok
    if os.name == "nt":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = 'Proje klasörünü seç'; "
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


class BrowseFolderResponse(BaseModel):
    path: str | None = None


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


class TaskCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    max_attempts: int = Field(default=2, ge=1, le=5)
    project_id: str | None = None
    model: str | None = None


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


class ProjectNewRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_path: str = Field(min_length=1)


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1)


class ProjectResponse(BaseModel):
    project_id: str
    name: str
    path: str
    created_at: str | None = None
    updated_at: str | None = None


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


def normalize_and_validate_project_path(
    project_path: str,
) -> str:
    normalized = os.path.normpath(
        os.path.abspath(
            os.path.expanduser(
                project_path.strip()
            )
        )
    )

    if not os.path.isdir(normalized):
        raise HTTPException(
            status_code=400,
            detail="Seçilen klasör bulunamadı.",
        )

    git_marker = os.path.join(
        normalized,
        ".git",
    )

    if not os.path.exists(git_marker):
        raise HTTPException(
            status_code=400,
            detail=(
                "Seçilen klasör bir Git deposu değil. "
                "Klasörün içinde .git bulunmalı."
            ),
        )

    return normalized


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
    )




def build_orchestrator_for_task(
    task: TaskCreateResponse,
) -> Orchestrator:
    if task.project_id is None:
        # Eski, FAZ 13 ?ncesi g?revler i?in uyumluluk.
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

        # Restart sonras?nda onay bekleyen g?revlerin
        # ge?ici runtime context'ini yeniden olu?tur.
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
                # Projesi silinmi? bir g?revin approval
                # context'ini yanl?? repoda kurma.
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


hydrate_runtime_from_database()

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
        test_result="passed",
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
    task = TASKS.get(task_id)

    if task is None:
        raise KeyError(f"Unknown task: {task_id}")

    append_task_log(
        task_id,
        "Task worker baslatildi.",
    )

    # Task Graph: dependency kontrolu
    # planner/model/worktree baslamadan once
    # yapilir.
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

    try:
        graph_gate = (
            evaluate_task_execution_gate(
                task_id,
                task_states,
            )
        )
    except Exception as exc:
        append_task_log(
            task_id,
            (
                "Task Graph baslangic hatasi: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

        update_task_runtime(
            task_id,
            status="failed",
            state="failed",
        )

        return None

    if graph_gate["state"] == "blocked":
        pending = (
            graph_gate[
                "pending_dependencies"
            ]
        )

        dependency_text = (
            ", ".join(pending)
            if pending
            else "unknown"
        )

        update_task_runtime(
            task_id,
            status="queued",
            state="blocked",
        )

        append_task_log(
            task_id,
            (
                "Task Graph: gorev bekletildi. "
                "Beklenen dependency: "
                f"{dependency_text}"
            ),
        )

        return None

    if graph_gate["state"] == "failed":
        failed_dependencies = (
            graph_gate[
                "failed_dependencies"
            ]
        )

        dependency_text = (
            ", ".join(
                failed_dependencies
            )
            if failed_dependencies
            else "unknown"
        )

        update_task_runtime(
            task_id,
            status="failed",
            state="failed",
        )

        append_task_log(
            task_id,
            (
                "Task Graph: dependency "
                "basarisizligi nedeniyle "
                "gorev calistirilmadi. "
                "Basarisiz dependency: "
                f"{dependency_text}"
            ),
        )

        return None

    # SEMANTIC_TASK_ROUTER_V1
    task_route = route_task_semantic(
        task.prompt,
        model_client=ModelClient(),
    )

    save_task_route(
        task_id,
        task_route.kind,
        task_route.reason,
    )

    task.task_kind = task_route.kind

    append_task_log(
        task_id,
        (
            "Task Router: "
            f"{task_route.kind.upper()} - "
            f"{task_route.reason} "
            f"[intent={task_route.intent}; "
            f"target={task_route.target}; "
            f"framework={task_route.framework}; "
            f"confidence={task_route.confidence:.2f}; "
            f"source={task_route.source}]"
        ),
    )

    requested_model = (
        get_task_model_preference(
            task_id,
        )
    )

    if task_route.kind == "execute":
        model_route = ModelRoute(
            model="local-executor",
            profile="execute",
            reason=(
                "Deterministik yerel eylem "
                "calistiricisi secildi."
            ),
            code_score=0,
        )

        selection_log = (
            "Execution Router: local-executor - "
            "Model cagrisi gerekmiyor."
        )

    elif requested_model:
        model_route = ModelRoute(
            model=requested_model,
            profile="manual",
            reason=(
                "Kullan\u0131c\u0131 taraf\u0131ndan "
                "manuel olarak se\u00e7ildi."
            ),
            code_score=0,
        )

        selection_log = (
            "Manuel Model: "
            f"{model_route.model}"
        )
    else:
        model_route = route_model(
            task.prompt,
        )

        selection_log = (
            "Model Router: "
            f"{model_route.model} - "
            f"{model_route.reason}"
        )

    update_task_runtime(
        task_id,
        status="running",
        state="running",
        model=model_route.model,
    )

    append_task_log(
        task_id,
        selection_log,
    )

    append_task_log(
        task_id,
        "Görev çalıştırılıyor.",
    )

    try:
        orchestrator = build_orchestrator_for_task(
            task
        )
    except KeyError:
        append_task_log(
            task_id,
            "G?revin ba?l? oldu?u proje bulunamad?.",
        )
        update_task_runtime(
            task_id,
            status="failed",
            state="failed",
        )
        return None

    if task_route.kind == "execute":
        try:
            append_task_log(
                task_id,
                "EXECUTE gorevi calistiriliyor.",
            )

            execute_result = run_execute_task(
                project_path=orchestrator.project_path,
                prompt=task.prompt,
                intent=task_route.intent,
                target=task_route.target,
                framework=task_route.framework,
            )

            save_task_read_result(
                task_id,
                execute_result,
            )

            update_task_runtime(
                task_id,
                status="completed",
                state="completed",
                test_result="not_required",
            )

            append_task_log(
                task_id,
                execute_result,
            )

            append_task_log(
                task_id,
                "EXECUTE gorevi tamamlandi.",
            )

            released_dependents = (
                release_runnable_graph_dependents(
                    task_id
                )
            )

            for dependent_task_id in (
                released_dependents
            ):
                run_task_for_api(
                    dependent_task_id
                )

            return

        except Exception as exc:
            append_task_log(
                task_id,
                (
                    "EXECUTE gorevi basarisiz: "
                    f"{exc}"
                ),
            )

            update_task_runtime(
                task_id,
                status="failed",
                state="failed",
            )

            return

    if task_route.kind == "read":
        try:
            append_task_log(
                task_id,
                "READ gorevi calistiriliyor.",
            )

            read_result = run_read_task(
                project_path=orchestrator.project_path,
                prompt=task.prompt,
                model_route=model_route,
                model_client=orchestrator.model_client,
            )

            save_task_read_result(
                task_id,
                read_result,
            )

            update_task_runtime(
                task_id,
                status="completed",
                state="completed",
                test_result="not_required",
            )

            append_task_log(
                task_id,
                "READ gorevi tamamlandi.",
            )

            released_dependents = (
                release_runnable_graph_dependents(
                    task_id
                )
            )

            for dependent_task_id in (
                released_dependents
            ):
                run_task_for_api(
                    dependent_task_id
                )

            return

        except Exception as exc:
            append_task_log(
                task_id,
                (
                    "READ gorevi basarisiz: "
                    f"{exc}"
                ),
            )

            update_task_runtime(
                task_id,
                status="failed",
                state="failed",
            )

            return

    try:
        result, execution_plan = execute_write_task(
            orchestrator=orchestrator,
            prompt=task.prompt,
            task_id=task_id,
            max_attempts=task.max_attempts,
            model_route=model_route,
            approval_handler=api_approval_handler,
            progress_handler=api_progress_handler,
        )

        append_task_log(
            task_id,
            (
                "Planner modu: "
                f"{execution_plan.get('planner_mode', 'single_step')}"
            ),
        )
    except Exception:
        append_task_log(
            task_id,
            "Görev beklenmeyen bir hata nedeniyle başarısız oldu.",
        )

        cleanup_failed_task_for_api(
            orchestrator,
            task_id,
        )

        update_task_runtime(
            task_id,
            status="failed",
            state="failed",
        )
        return None

    if result != "ready_for_approval":
        append_task_log(
            task_id,
            "Görev başarısız oldu.",
        )

        cleanup_failed_task_for_api(
            orchestrator,
            task_id,
        )

        update_task_runtime(
            task_id,
            status="failed",
            state="failed",
        )

    return result




@app.post(
    "/projects/browse-folder",
    response_model=BrowseFolderResponse,
)
async def browse_project_folder_endpoint():
    selected = await asyncio.to_thread(
        pick_local_project_folder,
    )
    return BrowseFolderResponse(path=selected)


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

    planned_path_text = str(planned_path.resolve())

    existing = db_get_project_by_path(
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

    row = db_create_project(
        project_id,
        name=request.name.strip(),
        path=project_path,
    )

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
        request.path
    )

    existing = db_get_project_by_path(
        project_path
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Bu proje yolu zaten kayıtlı.",
        )

    while True:
        project_id = (
            f"PROJECT-{random.randint(1000, 9999)}"
        )

        if db_get_project(project_id) is None:
            break

    row = db_create_project(
        project_id,
        name=request.name.strip(),
        path=project_path,
    )

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

    existing = db_get_project_by_path(
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
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_endpoint(
    project_id: str,
):
    current = db_get_project(project_id)

    if current is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    deleted = db_delete_project(project_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    return None


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

    while True:
        task_id = f"TASK-{random.randint(1000, 9999)}"
        if task_id not in TASKS:
            break

    task = TaskCreateResponse(
        task_id=task_id,
        status="queued",
        prompt=request.prompt,
        max_attempts=request.max_attempts,
        project_id=selected_project["project_id"],
        started_at=datetime.now(timezone.utc).isoformat(),
    )

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
    task, context = ensure_approval_runtime(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found after SQLite recovery: {task_id}",
        )

    if task.state != "ready_for_approval":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Task state is {task.state!r}, expected "
                "'ready_for_approval'"
            ),
        )

    if context is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Approval runtime context could not be recovered from "
                f"SQLite for {task_id}"
            ),
        )

    state_machine = context["state_machine"]
    wt_result = context["wt_result"]

    try:
        orchestrator = build_orchestrator_for_task(
            task
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    try:
        worktree_status = orchestrator.git_manager.get_status(
            wt_result.path
        )

        if worktree_status.strip():
            orchestrator.git_manager.commit_all(
                wt_result.path,
                f"{task_id}: AI generated changes",
            )

        orchestrator.git_manager.merge_branch(
            wt_result.branch
        )

        orchestrator.git_manager.remove_worktree(
            wt_result.path
        )

        orchestrator.git_manager.delete_branch(
            wt_result.branch
        )

        state_machine.transition(TaskStatus.APPROVED)

    except Exception as exc:
        # APPROVAL_MERGE_ABORT_V1
        # Merge conflict veya merge sirasindaki baska bir Git hatasi,
        # ana repository'yi yarim merge durumunda birakmamalidir.
        try:
            orchestrator.git_manager.abort_merge()
        except Exception:
            # Hata merge baslamadan once olustuysa aktif merge olmayabilir.
            pass

        raise HTTPException(
            status_code=409,
            detail=(
                "Approval merge failed and the merge was rolled back: "
                f"{exc}"
            ),
        ) from exc

    update_task_runtime(
        task_id,
        status="approved",
        state="approved",
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
    task, context = ensure_approval_runtime(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found after SQLite recovery: {task_id}",
        )

    if task.state != "ready_for_approval":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Task state is {task.state!r}, expected "
                "'ready_for_approval'"
            ),
        )

    if context is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Approval runtime context could not be recovered from "
                f"SQLite for {task_id}"
            ),
        )

    state_machine = context["state_machine"]
    wt_result = context["wt_result"]

    try:
        orchestrator = build_orchestrator_for_task(
            task
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    try:
        orchestrator.git_manager.remove_worktree(
            wt_result.path,
            force=True,
        )

        orchestrator.git_manager.delete_branch(
            wt_result.branch,
            force=True,
        )

        state_machine.transition(TaskStatus.REJECTED)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Rejection failed: {exc}",
        ) from exc

    update_task_runtime(
        task_id,
        status="rejected",
        state="rejected",
    )

    TASK_CONTEXTS.pop(task_id, None)

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

    TASK_CONTEXTS.pop(task_id, None)
    TASK_DIFFS.pop(task_id, None)

    db_delete_task_diff(task_id)
    db_clear_task_logs(task_id)

    reset_retryable_task_steps(task_id)

    task.status = "queued"
    task.state = "queued"
    task.model = None
    task.attempt = 0
    task.test_result = None
    task.started_at = datetime.now(
        timezone.utc
    ).isoformat()

    TASK_LOGS[task_id] = []

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
                detail="Proje bulunamad\u0131.",
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
            detail="G?rev bulunamad?.",
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
            detail="Proje bulunamad?.",
        )

    try:
        open_local_project_folder(
            project["path"]
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Proje a??lamad?: {exc}",
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
            detail="Proje bulunamad?.",
        )

    try:
        open_local_project_terminal(
            project["path"]
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Terminal a??lamad?: {exc}",
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
            detail="Model ad? zorunludur.",
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
            detail=f"Ollama hatas?: {detail}",
        ) from exc

    except urllib_error.URLError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama servisine ula??lam?yor.",
        ) from exc

    elapsed_ms = round(
        (time.perf_counter() - started) * 1000
    )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="Ollama ge?ersiz JSON d?nd?rd?.",
        ) from exc

    answer = result.get("response")

    if not isinstance(answer, str):
        raise HTTPException(
            status_code=502,
            detail="Ollama yan?t? bulunamad?.",
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
