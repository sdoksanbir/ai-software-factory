from types import SimpleNamespace
from typing import Any, Callable

from factory.schemas import (
    TaskSpec,
    TaskStatus,
)
from factory.state import TaskStateMachine
from factory.task_step_executor import (
    execute_task_plan,
)
from factory.task_step_handlers import (
    TaskStepHandlers,
)


def run_multi_step_task(
    *,
    orchestrator: Any,
    prompt: str,
    task_id: str,
    max_attempts: int = 2,
    approval_handler: Callable | None = None,
    progress_handler: Callable | None = None,
    model_name: str | None = None,
    resume_worktree_path: str | None = None,
    resume_branch: str | None = None,
) -> str | None:
    task_spec = TaskSpec(
        task_id=task_id,
        project_path=orchestrator.project_path,
        request=prompt,
        max_attempts=max_attempts,
    )

    state_machine = TaskStateMachine(
        task_spec
    )

    try:
        state_machine.transition(
            TaskStatus.WORKTREE_CREATING
        )

        if resume_worktree_path:
            wt_result = SimpleNamespace(
                path=resume_worktree_path,
                branch=(
                    resume_branch
                    or f"agent/{task_id.lower()}"
                ),
            )

            worktree_message = (
                "Multi-step mevcut worktree "
                "resume edildi."
            )

        else:
            wt_result = (
                orchestrator
                .git_manager
                .create_worktree(
                    task_id.lower()
                )
            )

            worktree_message = (
                "Multi-step worktree "
                "hazirlandi."
            )

        state_machine.transition(
            TaskStatus.WORKTREE_READY
        )

        if progress_handler is not None:
            progress_handler(
                task_id,
                message=worktree_message,
            )

        # Legacy state machine gorevin genel
        # pipeline durumunu izler.
        # Alt adim durumlari task_plan_store
        # tarafindan kalici olarak tutulur.
        state_machine.transition(
            TaskStatus.CONTEXT_BUILDING
        )

        state_machine.transition(
            TaskStatus.CONTEXT_READY
        )

        handlers = TaskStepHandlers(
            orchestrator,
            scope_prompt=prompt,
            model_name=model_name,
        )

        state_machine.transition(
            TaskStatus.MODEL_RUNNING
        )

        state_machine.register_attempt()

        if progress_handler is not None:
            progress_handler(
                task_id,
                attempt=task_spec.attempt,
                message=(
                    "Multi-step plan "
                    "calistiriliyor."
                ),
            )

        execute_task_plan(
            task_id,
            wt_result.path,
            read_handler=handlers.read,
            write_handler=handlers.write,
            verify_handler=handlers.verify,
            handoff_executor=handlers.handoff,
            max_step_attempts=max_attempts,
        )

        state_machine.transition(
            TaskStatus.MODEL_COMPLETED
        )

        state_machine.transition(
            TaskStatus.PATCH_VALIDATING
        )

        state_machine.transition(
            TaskStatus.PATCH_READY
        )

        state_machine.transition(
            TaskStatus.PATCH_APPLIED
        )

        state_machine.transition(
            TaskStatus.TESTING
        )

        state_machine.transition(
            TaskStatus.TEST_PASSED
        )

        state_machine.transition(
            TaskStatus.READY_FOR_APPROVAL
        )

        diff_output = (
            orchestrator
            .git_manager
            .get_diff(
                wt_result.path
            )
        )

        if progress_handler is not None:
            progress_handler(
                task_id,
                test_result="passed",
                message=(
                    "Multi-step gorev "
                    "tamamlandi. Onay bekleniyor."
                ),
            )

        if approval_handler is not None:
            return approval_handler(
                task_id,
                state_machine,
                wt_result,
                diff_output,
            )

        return (
            orchestrator
            ._handle_cli_approval(
                task_id,
                state_machine,
                wt_result,
                diff_output,
            )
        )

    except Exception as exc:
        if not state_machine.is_terminal:
            try:
                state_machine.transition(
                    TaskStatus.FAILED
                )
            except Exception:
                pass

        if progress_handler is not None:
            progress_handler(
                task_id,
                test_result="failed",
                message=(
                    "Multi-step gorev "
                    f"basarisiz: {exc}"
                ),
            )

        print(
            "[-] Multi-step gorev "
            f"basarisiz: {exc}"
        )

        # Burada worktree SILINMEZ.
        # API retry ayni worktree ve kalici
        # plan uzerinden devam edebilir.
        return None
