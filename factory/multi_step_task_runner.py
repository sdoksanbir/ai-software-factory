from types import SimpleNamespace
from typing import Any, Callable

from factory.database import get_task
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


def _derive_test_result(
    plan_result: dict[str, Any] | None,
) -> str:
    """Map verify step outcomes to test_result.

    Returns:
      - "passed" when every verify step completed
      - "failed" when a verify step did not complete
      - "not_required" when the plan has no verify step
    """
    steps = (
        (plan_result or {}).get("steps")
        or []
    )

    verify_steps = [
        step
        for step in steps
        if str(step.get("kind", ""))
        .strip()
        .lower()
        == "verify"
    ]

    if not verify_steps:
        return "not_required"

    if all(
        str(step.get("status", ""))
        .strip()
        .lower()
        == "completed"
        for step in verify_steps
    ):
        return "passed"

    return "failed"


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

        # Step progress lives in task_plan_store.
        # TaskStateMachine only tracks coarse
        # worktree → plan execution → approval.
        persisted_task = get_task(
            task_id
        )

        project_id = None

        if persisted_task is not None:
            project_id = str(
                persisted_task.get(
                    "project_id"
                )
                or ""
            ).strip() or None

        handlers = TaskStepHandlers(
            orchestrator,
            scope_prompt=prompt,
            model_name=model_name,
            project_id=project_id,
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

        plan_result = execute_task_plan(
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

        diff_output = (
            orchestrator
            .git_manager
            .get_diff(
                wt_result.path
            )
        )

        # WRITE finalization invariant: a mutation
        # task with no net repository delta must
        # not become ready_for_approval. Gate on
        # the final worktree state after ALL steps
        # complete — not per intermediate WRITE.
        final_diff = str(
            diff_output or ""
        ).strip()

        if not final_diff:
            raise RuntimeError(
                "Görev tamamlandı ancak projede "
                "onaylanacak bir değişiklik oluşmadı."
            )

        diff_output = final_diff

        state_machine.transition(
            TaskStatus.READY_FOR_APPROVAL
        )

        test_result = _derive_test_result(
            plan_result
        )

        if progress_handler is not None:
            progress_handler(
                task_id,
                test_result=test_result,
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
