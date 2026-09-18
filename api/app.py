import random

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from factory.orchestrator import Orchestrator


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


TASKS: dict[str, TaskCreateResponse] = {}


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
def create_task(request: TaskCreateRequest):
    while True:
        task_id = f"TASK-{random.randint(1000, 9999)}"
        if task_id not in TASKS:
            break

    task = TaskCreateResponse(
        task_id=task_id,
        status="queued",
        prompt=request.prompt,
        max_attempts=request.max_attempts,
    )

    TASKS[task_id] = task

    return task


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

