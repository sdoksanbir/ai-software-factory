import asyncio
import json
import os
import random
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse

from factory.database import (
    append_task_log as db_append_task_log,
    clear_task_logs as db_clear_task_logs,
    delete_task_diff as db_delete_task_diff,
    get_task_diff as db_get_task_diff,
    init_database,
    list_task_logs as db_list_task_logs,
    list_tasks as db_list_tasks,
    save_task_diff as db_save_task_diff,
    upsert_task as db_upsert_task,
)
from factory.orchestrator import Orchestrator
from factory.schemas import TaskStatus


app = FastAPI(
    title="AI Software Factory API",
    version="1.0",
)


class TaskCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    max_attempts: int = Field(default=2, ge=1, le=5)


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str
    prompt: str
    max_attempts: int
    state: str = "queued"
    model: str | None = None
    attempt: int = 0
    test_result: str | None = None
    started_at: str | None = None


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
        branch=branch,
        worktree_path=(
            str(worktree_path)
            if worktree_path is not None
            else None
        ),
    )


def hydrate_runtime_from_database() -> None:
    init_database()

    TASKS.clear()
    TASK_LOGS.clear()
    TASK_DIFFS.clear()

    rows = db_list_tasks()

    for row in reversed(rows):
        task = TaskCreateResponse(
            task_id=row["task_id"],
            status=row["status"],
            prompt=row["prompt"],
            max_attempts=int(
                row["max_attempts"] or 2
            ),
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


hydrate_runtime_from_database()

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
        os.path.normpath(orchestrator.project_path)
    )

    worktree_path = os.path.join(
        orchestrator.worktree_root,
        repo_name,
        task_id.lower(),
    )

    branch_name = f"agent/{task_id.lower()}"

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

def run_task_for_api(task_id: str):
    task = TASKS.get(task_id)

    if task is None:
        raise KeyError(f"Unknown task: {task_id}")

    update_task_runtime(
        task_id,
        status="running",
        state="running",
        model="fast_local",
    )

    append_task_log(
        task_id,
        "Görev çalıştırılıyor.",
    )

    orchestrator = Orchestrator()

    try:
        result = orchestrator.run_task(
            task.prompt,
            task_id=task_id,
            max_attempts=task.max_attempts,
            approval_handler=api_approval_handler,
            progress_handler=api_progress_handler,
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


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/factory/status")
def factory_status():
    orchestrator = Orchestrator()

    return {
        "status": "ready",
        "project_path": orchestrator.project_path,
        "worktree_root": orchestrator.worktree_root,
    }

@app.post(
    "/tasks",
    response_model=TaskCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_task(
    request: TaskCreateRequest,
    background_tasks: BackgroundTasks,
):
    while True:
        task_id = f"TASK-{random.randint(1000, 9999)}"
        if task_id not in TASKS:
            break

    task = TaskCreateResponse(
        task_id=task_id,
        status="queued",
        prompt=request.prompt,
        max_attempts=request.max_attempts,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    TASKS[task_id] = task
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
def list_tasks():
    return list(TASKS.values())


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
def approve_task(task_id: str):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    context = TASK_CONTEXTS.get(task_id)

    if context is None or task.state != "ready_for_approval":
        raise HTTPException(
            status_code=409,
            detail="Task is not ready for approval",
        )

    state_machine = context["state_machine"]
    wt_result = context["wt_result"]

    orchestrator = Orchestrator()

    try:
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
        raise HTTPException(
            status_code=500,
            detail=f"Approval failed: {exc}",
        ) from exc

    update_task_runtime(
        task_id,
        status="approved",
        state="approved",
    )

    TASK_CONTEXTS.pop(task_id, None)

    append_task_log(
        task_id,
        "Görev onaylandı ve ana dala birleştirildi.",
    )

    return TASKS[task_id]

@app.post(
    "/tasks/{task_id}/reject",
    response_model=TaskCreateResponse,
)
def reject_task(task_id: str):
    task = TASKS.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    context = TASK_CONTEXTS.get(task_id)

    if context is None or task.state != "ready_for_approval":
        raise HTTPException(
            status_code=409,
            detail="Task is not ready for rejection",
        )

    state_machine = context["state_machine"]
    wt_result = context["wt_result"]

    orchestrator = Orchestrator()

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

