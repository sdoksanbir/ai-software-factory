from fastapi import FastAPI

from factory.orchestrator import Orchestrator


app = FastAPI(
    title="AI Software Factory API",
    version="1.0",
)


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