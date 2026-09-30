from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from factory.agent_terminal_loop import (
    run_agent_terminal_loop,
)
from factory.agent_terminal_models import (
    AgentTerminalRouteContext,
    build_execute_terminal_policy,
)
from factory.model_router import (
    ModelRoute,
    route_model,
)
from factory.models import ModelClient
from factory.read_task_runner import (
    run_read_task,
)
from factory.semantic_task_router import (
    route_task_semantic,
)
from factory.task_execution_dispatcher import (
    execute_write_task,
)
from factory.task_model_preferences import (
    get_task_model_preference,
)
from factory.task_read_results import (
    save_task_read_result,
)
from factory.task_route_store import (
    save_task_route,
)


@dataclass(frozen=True)
class TaskExecutionDeps:
    """API-facing callbacks for task execution.

    Keeps TASKS / runtime helpers in api.app while
    moving orchestration into this service.
    """

    get_task: Callable[[str], Any]
    iter_tasks: Callable[
        [],
        Iterable[tuple[str, Any]],
    ]
    append_log: Callable[..., None]
    update_runtime: Callable[..., Any]
    evaluate_gate: Callable[..., dict]
    build_orchestrator: Callable[..., Any]
    approval_handler: Callable[..., Any]
    progress_handler: Callable[..., Any]
    cleanup_failed: Callable[..., None]
    release_dependents: Callable[
        [str],
        list[str],
    ]


class TaskExecutionService:
    """Coordinates production API task execution.

    Dispatches to structured runners
    (execute_write_task / run_read_task /
    Agent Terminal Loop for execute). Does not
    call Orchestrator.run_task().
    """

    def __init__(
        self,
        deps: TaskExecutionDeps,
    ):
        self._deps = deps

    def run(
        self,
        task_id: str,
    ):
        task = self._deps.get_task(
            task_id
        )

        if task is None:
            raise KeyError(
                f"Unknown task: {task_id}"
            )

        self._deps.append_log(
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
        ) in self._deps.iter_tasks():
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
                self._deps.evaluate_gate(
                    task_id,
                    task_states,
                )
            )
        except Exception as exc:
            self._deps.append_log(
                task_id,
                (
                    "Task Graph baslangic hatasi: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

            self._deps.update_runtime(
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

            self._deps.update_runtime(
                task_id,
                status="queued",
                state="blocked",
            )

            self._deps.append_log(
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

            self._deps.update_runtime(
                task_id,
                status="failed",
                state="failed",
            )

            self._deps.append_log(
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
            source=task_route.source,
        )

        task.task_kind = task_route.kind

        self._deps.append_log(
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

        if requested_model:
            model_route = ModelRoute(
                model=requested_model,
                profile="manual",
                reason=(
                    "Kullan\u0131c\u0131 taraf\u0131ndan "
                    "manuel olarak se\u00e7ildi."
                ),
                code_score=0,
            )

            if task_route.kind == "execute":
                selection_log = (
                    "Agent Terminal Model: "
                    f"{model_route.model} - "
                    f"{model_route.reason}"
                )
            else:
                selection_log = (
                    "Manuel Model: "
                    f"{model_route.model}"
                )
        else:
            model_route = route_model(
                task.prompt,
            )

            if task_route.kind == "execute":
                selection_log = (
                    "Agent Terminal Model: "
                    f"{model_route.model} - "
                    f"{model_route.reason}"
                )
            else:
                selection_log = (
                    "Model Router: "
                    f"{model_route.model} - "
                    f"{model_route.reason}"
                )

        self._deps.update_runtime(
            task_id,
            status="running",
            state="running",
            model=model_route.model,
        )

        self._deps.append_log(
            task_id,
            selection_log,
        )

        self._deps.append_log(
            task_id,
            "Görev çalıştırılıyor.",
        )

        try:
            orchestrator = (
                self._deps.build_orchestrator(
                    task
                )
            )
        except KeyError:
            self._deps.append_log(
                task_id,
                "Görevin bağlı olduğu proje bulunamadı.",
            )
            self._deps.update_runtime(
                task_id,
                status="failed",
                state="failed",
            )
            return None

        if task_route.kind == "execute":
            return self._run_execute(
                task_id,
                task,
                task_route,
                model_route,
                orchestrator,
            )

        if task_route.kind == "read":
            return self._run_read(
                task_id,
                task,
                model_route,
                orchestrator,
            )

        return self._run_write(
            task_id,
            task,
            model_route,
            orchestrator,
            task_route=task_route,
        )

    def _run_execute(
        self,
        task_id: str,
        task: Any,
        task_route: Any,
        model_route: Any,
        orchestrator: Any,
    ):
        try:
            self._deps.append_log(
                task_id,
                "Agent Terminal baslatildi.",
            )

            policy = (
                build_execute_terminal_policy()
            )
            route_context = (
                AgentTerminalRouteContext(
                    intent=getattr(
                        task_route,
                        "intent",
                        None,
                    ),
                    target=getattr(
                        task_route,
                        "target",
                        None,
                    ),
                    framework=getattr(
                        task_route,
                        "framework",
                        None,
                    ),
                )
            )

            loop_result = (
                run_agent_terminal_loop(
                    project_path=(
                        orchestrator.project_path
                    ),
                    task_id=task_id,
                    prompt=task.prompt,
                    model_route=model_route,
                    model_client=(
                        orchestrator.model_client
                    ),
                    policy=policy,
                    route_context=route_context,
                )
            )

            if loop_result.status == "completed":
                summary = (
                    loop_result.summary
                    or loop_result.reason
                )

                save_task_read_result(
                    task_id,
                    summary,
                )

                self._deps.update_runtime(
                    task_id,
                    status="completed",
                    state="completed",
                    test_result="not_required",
                )

                self._deps.append_log(
                    task_id,
                    (
                        "Agent Terminal tamamlandi: "
                        f"{summary}"
                    ),
                )

                self._release_and_run_dependents(
                    task_id
                )

                return

            reason = (
                loop_result.reason
                or loop_result.summary
                or loop_result.status
            )

            if loop_result.status == "stalled":
                self._deps.append_log(
                    task_id,
                    (
                        "Agent Terminal stalled: "
                        f"{reason}"
                    ),
                )
            elif (
                loop_result.status
                == "budget_exceeded"
            ):
                self._deps.append_log(
                    task_id,
                    (
                        "Agent Terminal basarisiz: "
                        f"budget_exceeded: {reason}"
                    ),
                )
            else:
                self._deps.append_log(
                    task_id,
                    (
                        "Agent Terminal basarisiz: "
                        f"{reason}"
                    ),
                )

            self._deps.update_runtime(
                task_id,
                status="failed",
                state="failed",
            )

            return

        except Exception as exc:
            self._deps.append_log(
                task_id,
                (
                    "Agent Terminal basarisiz: "
                    f"{exc}"
                ),
            )

            self._deps.update_runtime(
                task_id,
                status="failed",
                state="failed",
            )

            return

    def _run_read(
        self,
        task_id: str,
        task: Any,
        model_route: Any,
        orchestrator: Any,
    ):
        try:
            self._deps.append_log(
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

            self._deps.update_runtime(
                task_id,
                status="completed",
                state="completed",
                test_result="not_required",
            )

            self._deps.append_log(
                task_id,
                "READ gorevi tamamlandi.",
            )

            self._release_and_run_dependents(
                task_id
            )

            return

        except Exception as exc:
            self._deps.append_log(
                task_id,
                (
                    "READ gorevi basarisiz: "
                    f"{exc}"
                ),
            )

            self._deps.update_runtime(
                task_id,
                status="failed",
                state="failed",
            )

            return

    def _run_write(
        self,
        task_id: str,
        task: Any,
        model_route: Any,
        orchestrator: Any,
        *,
        task_route: Any = None,
    ):
        try:
            result, execution_plan = (
                execute_write_task(
                    orchestrator=orchestrator,
                    prompt=task.prompt,
                    task_id=task_id,
                    max_attempts=task.max_attempts,
                    model_route=model_route,
                    approval_handler=(
                        self._deps.approval_handler
                    ),
                    progress_handler=(
                        self._deps.progress_handler
                    ),
                    task_kind=(
                        getattr(
                            task_route,
                            "kind",
                            None,
                        )
                        or getattr(
                            task,
                            "task_kind",
                            None,
                        )
                    ),
                )
            )

            self._deps.append_log(
                task_id,
                (
                    "Planner modu: "
                    f"{execution_plan.get('planner_mode', 'single_step')}"
                ),
            )
        except Exception as exc:
            self._deps.append_log(
                task_id,
                (
                    "Görev beklenmeyen bir hata nedeniyle başarısız oldu: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

            self._deps.cleanup_failed(
                orchestrator,
                task_id,
            )

            self._deps.update_runtime(
                task_id,
                status="failed",
                state="failed",
            )
            return None

        if result != "ready_for_approval":
            self._deps.append_log(
                task_id,
                "Görev başarısız oldu.",
            )

            self._deps.cleanup_failed(
                orchestrator,
                task_id,
            )

            self._deps.update_runtime(
                task_id,
                status="failed",
                state="failed",
            )

        return result

    def _release_and_run_dependents(
        self,
        task_id: str,
    ) -> None:
        released_dependents = (
            self._deps.release_dependents(
                task_id
            )
        )

        for dependent_task_id in (
            released_dependents
        ):
            self.run(dependent_task_id)
