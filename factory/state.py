from datetime import datetime, timezone

from factory.schemas import TaskSpec, TaskStatus


class InvalidStateTransition(Exception):
    """Raised when a task tries to enter an invalid state."""
    pass


class MaxAttemptsExceeded(Exception):
    """Raised when the task retry limit has been reached."""
    pass


class TaskStateMachine:
    def __init__(self, task: TaskSpec):
        self.task = task

        self.terminal_states = {
            TaskStatus.APPROVED,
            TaskStatus.REJECTED,
            TaskStatus.FAILED,
        }

        self.valid_transitions = {
            TaskStatus.CREATED: {
                TaskStatus.WORKTREE_CREATING,
                TaskStatus.FAILED,
            },

            TaskStatus.WORKTREE_CREATING: {
                TaskStatus.WORKTREE_READY,
                TaskStatus.FAILED,
            },

            TaskStatus.WORKTREE_READY: {
                TaskStatus.CONTEXT_BUILDING,
                TaskStatus.FAILED,
            },

            TaskStatus.CONTEXT_BUILDING: {
                TaskStatus.CONTEXT_READY,
                TaskStatus.FAILED,
            },

            TaskStatus.CONTEXT_READY: {
                TaskStatus.MODEL_RUNNING,
                TaskStatus.FAILED,
            },

            TaskStatus.MODEL_RUNNING: {
                TaskStatus.MODEL_COMPLETED,
                TaskStatus.FAILED,
            },

            TaskStatus.MODEL_COMPLETED: {
                TaskStatus.PATCH_VALIDATING,
                TaskStatus.FAILED,
            },

            TaskStatus.PATCH_VALIDATING: {
                TaskStatus.PATCH_READY,
                TaskStatus.MODEL_RUNNING,
                TaskStatus.FAILED,
            },

            TaskStatus.PATCH_READY: {
                TaskStatus.PATCH_APPLIED,
                TaskStatus.MODEL_RUNNING,
                TaskStatus.FAILED,
            },

            TaskStatus.PATCH_APPLIED: {
                TaskStatus.TESTING,
                TaskStatus.FAILED,
            },

            TaskStatus.TESTING: {
                TaskStatus.TEST_PASSED,
                TaskStatus.TEST_FAILED,
                TaskStatus.FAILED,
            },

            TaskStatus.TEST_PASSED: {
                TaskStatus.READY_FOR_APPROVAL,
                TaskStatus.FAILED,
            },

            TaskStatus.TEST_FAILED: {
                TaskStatus.MODEL_RUNNING,
                TaskStatus.FAILED,
            },

            TaskStatus.READY_FOR_APPROVAL: {
                TaskStatus.APPROVED,
                TaskStatus.REJECTED,
                TaskStatus.FAILED,
            },

            TaskStatus.APPROVED: set(),
            TaskStatus.REJECTED: set(),
            TaskStatus.FAILED: set(),
        }

    @property
    def is_terminal(self) -> bool:
        return self.task.status in self.terminal_states

    def transition(self, to_status: TaskStatus) -> None:
        if self.is_terminal:
            raise InvalidStateTransition(
                f"Invalid task transition: "
                f"Task is already in terminal state "
                f"'{self.task.status.value}' and cannot transition "
                f"to '{to_status.value}'"
            )

        allowed_next_states = self.valid_transitions.get(
            self.task.status,
            set(),
        )

        if to_status not in allowed_next_states:
            raise InvalidStateTransition(
                f"Invalid task transition: "
                f"{self.task.status.value} -> {to_status.value}"
            )

        self.task.status = to_status
        self.task.updated_at = datetime.now(timezone.utc)

    def register_attempt(self) -> None:
        if self.is_terminal:
            raise InvalidStateTransition(
                f"Cannot register attempt: "
                f"Task is already in terminal state "
                f"'{self.task.status.value}'"
            )

        if self.task.attempt >= self.task.max_attempts:
            raise MaxAttemptsExceeded(
                f"Maximum attempt limit reached: "
                f"{self.task.attempt}/{self.task.max_attempts}"
            )

        self.task.attempt += 1
        self.task.updated_at = datetime.now(timezone.utc)
