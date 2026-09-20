from pathlib import Path
from typing import Any

from factory.database import DEFAULT_DB_PATH
from factory.task_graph_store import (
    evaluate_task_graph_node_state,
    list_task_graph_ids_for_task,
    propagate_dependency_failures,
)


def evaluate_task_execution_gate(
    task_id: str,
    task_states: dict[str, str],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    graph_ids = (
        list_task_graph_ids_for_task(
            task_id,
            db_path=db_path,
        )
    )

    if not graph_ids:
        return {
            "task_id": task_id,
            "allowed": True,
            "state": "unmanaged",
            "graph_ids": [],
            "blocked_graphs": [],
            "failed_graphs": [],
            "pending_dependencies": [],
            "failed_dependencies": [],
        }

    blocked_graphs: list[str] = []
    failed_graphs: list[str] = []

    pending_dependencies: set[str] = set()
    failed_dependencies: set[str] = set()

    for graph_id in graph_ids:
        failure_state = (
            propagate_dependency_failures(
                graph_id,
                task_states,
                db_path=db_path,
            )
        )

        task_failure = (
            failure_state.get(
                task_id,
                {},
            )
        )

        if task_failure.get(
            "blocked_by_failure",
            False,
        ):
            failed_graphs.append(
                graph_id
            )

            failed_dependencies.update(
                task_failure.get(
                    "failed_dependencies",
                    [],
                )
            )

            continue

        evaluation = (
            evaluate_task_graph_node_state(
                graph_id,
                task_id,
                task_states,
                db_path=db_path,
            )
        )

        if evaluation["state"] == "failed":
            failed_graphs.append(
                graph_id
            )

            failed_dependencies.update(
                evaluation[
                    "failed_dependencies"
                ]
            )

        elif evaluation["state"] == "blocked":
            blocked_graphs.append(
                graph_id
            )

            pending_dependencies.update(
                evaluation[
                    "pending_dependencies"
                ]
            )

    if failed_graphs:
        state = "failed"
        allowed = False

    elif blocked_graphs:
        state = "blocked"
        allowed = False

    else:
        state = "ready"
        allowed = True

    return {
        "task_id": task_id,
        "allowed": allowed,
        "state": state,
        "graph_ids": graph_ids,
        "blocked_graphs": sorted(
            blocked_graphs
        ),
        "failed_graphs": sorted(
            failed_graphs
        ),
        "pending_dependencies": sorted(
            pending_dependencies
        ),
        "failed_dependencies": sorted(
            failed_dependencies
        ),
    }


def list_newly_runnable_dependents(
    completed_task_id: str,
    task_states: dict[str, str],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    from factory.task_graph_store import (
        list_task_dependents,
    )

    graph_ids = (
        list_task_graph_ids_for_task(
            completed_task_id,
            db_path=db_path,
        )
    )

    candidates: set[str] = set()

    for graph_id in graph_ids:
        dependents = list_task_dependents(
            graph_id,
            completed_task_id,
            db_path=db_path,
        )

        for dependent_id in dependents:
            gate = evaluate_task_execution_gate(
                dependent_id,
                task_states,
                db_path=db_path,
            )

            if gate["allowed"]:
                candidates.add(
                    dependent_id
                )

    return sorted(
        candidates
    )
