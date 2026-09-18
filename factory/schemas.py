from enum import Enum
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
from typing import List


class TaskStatus(str, Enum):
    CREATED = "created"
    
    WORKTREE_CREATING = "worktree_creating"
    WORKTREE_READY = "worktree_ready"
    
    CONTEXT_BUILDING = "context_building"
    CONTEXT_READY = "context_ready"
    
    MODEL_RUNNING = "model_running"
    MODEL_COMPLETED = "model_completed"
    
    PATCH_VALIDATING = "patch_validating"
    PATCH_READY = "patch_ready"
    PATCH_APPLIED = "patch_applied"
    
    TESTING = "testing"
    TEST_PASSED = "test_passed"
    TEST_FAILED = "test_failed"
    
    READY_FOR_APPROVAL = "ready_for_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    
    FAILED = "failed"


def _generate_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskSpec(BaseModel):
    task_id: str = Field(..., pattern=r"^TASK-\d{4}$")
    project_path: str = Field(...)
    request: str = Field(...)
    
    status: TaskStatus = Field(default=TaskStatus.CREATED)
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=2, gt=0)
    
    created_at: datetime = Field(default_factory=_generate_utc_now)
    updated_at: datetime = Field(default_factory=_generate_utc_now)

    @field_validator("project_path", "request")
    @classmethod
    def validate_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Bu alan yalnızca boşluk karakterlerinden oluşamaz.")
        return v


class PatchResult(BaseModel):
    patch: str
    explanation: str
    files_changed: List[str] = Field(default_factory=list)


class TestResult(BaseModel):
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = Field(ge=0)


class TaskResult(BaseModel):
    task_id: str
    status: TaskStatus
    files_changed: int = 0
    tests_passed: bool = False
    attempts: int
    message: str