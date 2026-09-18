import os
import random
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

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

    orchestrator = Orchestrator()

    try:
        result = orchestrator.run_task(
            task.prompt,
            task_id=task_id,
            max_attempts=task.max_attempts,
            approval_handler=api_approval_handler,
        )
    except Exception:
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

    task.status = "queued"
    task.state = "queued"
    task.model = None
    task.attempt = 0
    task.test_result = None
    task.started_at = datetime.now(
        timezone.utc
    ).isoformat()

    background_tasks.add_task(
        run_task_for_api,
        task_id,
    )

    return task

