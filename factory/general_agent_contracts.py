from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DESTRUCTIVE = "destructive"


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


class SuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(
        min_length=1,
        max_length=80,
    )
    description: str = Field(
        min_length=1,
        max_length=1000,
    )
    required: bool = True


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(
        min_length=1,
        max_length=120,
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
    )
    permission: Permission
    cwd: str | None = Field(
        default=None,
        max_length=1000,
    )


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(
        min_length=1,
        max_length=80,
    )
    tool_name: str = Field(
        min_length=1,
        max_length=120,
    )
    success: bool
    summary: str = Field(
        min_length=1,
        max_length=4000,
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
    )
    error: str | None = Field(
        default=None,
        max_length=4000,
    )


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(
        min_length=1,
        max_length=80,
    )
    status: VerificationStatus = (
        VerificationStatus.PENDING
    )
    evidence: str | None = Field(
        default=None,
        max_length=4000,
    )


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(
        min_length=1,
        max_length=80,
    )
    title: str = Field(
        min_length=1,
        max_length=240,
    )
    description: str = Field(
        min_length=1,
        max_length=2000,
    )
    permission: Permission
    tool: ToolRequest | None = None
    depends_on: list[str] = Field(
        default_factory=list,
    )
    verification_criteria: list[str] = Field(
        default_factory=list,
    )
    status: StepStatus = StepStatus.PENDING
    max_attempts: int = Field(
        default=2,
        ge=1,
        le=10,
    )
    attempt: int = Field(
        default=0,
        ge=0,
    )

    @field_validator("depends_on")
    @classmethod
    def _unique_dependencies(
        cls,
        value: list[str],
    ) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError(
                "depends_on ayni step'i birden fazla kez iceremez."
            )
        return value

    @model_validator(mode="after")
    def _tool_permission_matches(
        self,
    ) -> "PlanStep":
        if (
            self.tool is not None
            and self.tool.permission
            != self.permission
        ):
            raise ValueError(
                "PlanStep.permission ile ToolRequest.permission "
                "ayni olmali."
            )

        if self.step_id in self.depends_on:
            raise ValueError(
                "Bir step kendisine bagimli olamaz."
            )

        return self


class GeneralTaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"

    goal: str = Field(
        min_length=1,
        max_length=4000,
    )
    summary: str = Field(
        min_length=1,
        max_length=2000,
    )
    success_criteria: list[
        SuccessCriterion
    ] = Field(
        default_factory=list,
    )
    steps: list[PlanStep] = Field(
        min_length=1,
    )
    constraints: list[str] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def _validate_graph(
        self,
    ) -> "GeneralTaskPlan":
        ids = [
            step.step_id
            for step in self.steps
        ]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "step_id degerleri benzersiz olmali."
            )

        known = set(ids)

        for step in self.steps:
            missing = [
                dependency
                for dependency in step.depends_on
                if dependency not in known
            ]

            if missing:
                raise ValueError(
                    f"{step.step_id} bilinmeyen dependency "
                    f"iceriyor: {missing}"
                )

        criterion_ids = [
            item.criterion_id
            for item in self.success_criteria
        ]

        if len(criterion_ids) != len(
            set(criterion_ids)
        ):
            raise ValueError(
                "criterion_id degerleri benzersiz olmali."
            )

        known_criteria = set(
            criterion_ids
        )

        for step in self.steps:
            missing_criteria = [
                criterion_id
                for criterion_id in step.verification_criteria
                if criterion_id
                not in known_criteria
            ]

            if missing_criteria:
                raise ValueError(
                    f"{step.step_id} bilinmeyen verification "
                    f"criterion iceriyor: {missing_criteria}"
                )

        self._assert_acyclic()
        return self

    def _assert_acyclic(self) -> None:
        graph = {
            step.step_id: list(
                step.depends_on
            )
            for step in self.steps
        }

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visited:
                return

            if node in visiting:
                raise ValueError(
                    "TaskPlan dependency dongusu iceremez."
                )

            visiting.add(node)

            for dependency in graph[node]:
                visit(dependency)

            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)

    def ready_step_ids(
        self,
    ) -> list[str]:
        status_by_id = {
            step.step_id: step.status
            for step in self.steps
        }

        ready: list[str] = []

        for step in self.steps:
            if step.status not in {
                StepStatus.PENDING,
                StepStatus.READY,
            }:
                continue

            if all(
                status_by_id[dependency]
                == StepStatus.SUCCEEDED
                for dependency in step.depends_on
            ):
                ready.append(
                    step.step_id
                )

        return ready
