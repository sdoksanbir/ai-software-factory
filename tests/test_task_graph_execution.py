from factory.task_graph_execution import (
    evaluate_task_execution_gate,
)
from factory.task_graph_store import (
    add_task_dependency,
    add_task_graph_node,
    create_task_graph,
)


def test_unmanaged_task_is_allowed(
    tmp_path,
):
    db_path = tmp_path / "graph.db"

    result = evaluate_task_execution_gate(
        "TASK-1001",
        {},
        db_path=db_path,
    )

    assert result["allowed"] is True
    assert result["state"] == "unmanaged"
    assert result["graph_ids"] == []


def test_root_graph_task_is_ready(
    tmp_path,
):
    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1001",
        db_path=db_path,
    )

    result = evaluate_task_execution_gate(
        "TASK-1001",
        {
            "TASK-1001": "queued",
        },
        db_path=db_path,
    )

    assert result["allowed"] is True
    assert result["state"] == "ready"


def test_pending_dependency_blocks_execution(
    tmp_path,
):
    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
    ):
        add_task_graph_node(
            "GRAPH-1",
            task_id,
            db_path=db_path,
        )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1002",
        "TASK-1001",
        db_path=db_path,
    )

    result = evaluate_task_execution_gate(
        "TASK-1002",
        {
            "TASK-1001": "queued",
            "TASK-1002": "queued",
        },
        db_path=db_path,
    )

    assert result["allowed"] is False
    assert result["state"] == "blocked"

    assert result[
        "pending_dependencies"
    ] == [
        "TASK-1001"
    ]


def test_transitive_failure_blocks_execution(
    tmp_path,
):
    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
        "TASK-1003",
    ):
        add_task_graph_node(
            "GRAPH-1",
            task_id,
            db_path=db_path,
        )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1002",
        "TASK-1001",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1003",
        "TASK-1002",
        db_path=db_path,
    )

    result = evaluate_task_execution_gate(
        "TASK-1003",
        {
            "TASK-1001": "failed",
            "TASK-1002": "queued",
            "TASK-1003": "queued",
        },
        db_path=db_path,
    )

    assert result["allowed"] is False
    assert result["state"] == "failed"

    assert result[
        "failed_dependencies"
    ] == [
        "TASK-1001"
    ]


def test_newly_runnable_dependent_after_approval(
    tmp_path,
):
    from factory.task_graph_execution import (
        list_newly_runnable_dependents,
    )

    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
    ):
        add_task_graph_node(
            "GRAPH-1",
            task_id,
            db_path=db_path,
        )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1002",
        "TASK-1001",
        db_path=db_path,
    )

    result = (
        list_newly_runnable_dependents(
            "TASK-1001",
            {
                "TASK-1001": "approved",
                "TASK-1002": "blocked",
            },
            db_path=db_path,
        )
    )

    assert result == [
        "TASK-1002"
    ]


def test_dependent_not_released_before_approval(
    tmp_path,
):
    from factory.task_graph_execution import (
        list_newly_runnable_dependents,
    )

    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
    ):
        add_task_graph_node(
            "GRAPH-1",
            task_id,
            db_path=db_path,
        )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1002",
        "TASK-1001",
        db_path=db_path,
    )

    result = (
        list_newly_runnable_dependents(
            "TASK-1001",
            {
                "TASK-1001":
                    "ready_for_approval",
                "TASK-1002": "blocked",
            },
            db_path=db_path,
        )
    )

    assert result == []
