import sqlite3

import pytest

from factory.task_graph_store import (
    add_task_dependency,
    add_task_graph_node,
    create_task_graph,
    delete_task_graph,
    get_task_graph,
    init_task_graph_store,
    list_task_graphs,
)


def test_init_creates_graph_tables(
    tmp_path,
):
    db_path = (
        tmp_path
        / "graph.db"
    )

    init_task_graph_store(
        db_path
    )

    connection = sqlite3.connect(
        db_path
    )

    try:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

    finally:
        connection.close()

    names = {
        row[0]
        for row in rows
    }

    assert "task_graphs" in names
    assert "task_graph_nodes" in names
    assert "task_dependencies" in names


def test_create_and_get_graph(
    tmp_path,
):
    db_path = (
        tmp_path
        / "graph.db"
    )

    created = create_task_graph(
        "GRAPH-1",
        project_id="PROJECT-1",
        root_task_id="TASK-1001",
        db_path=db_path,
    )

    assert (
        created["graph_id"]
        == "GRAPH-1"
    )

    assert (
        created["project_id"]
        == "PROJECT-1"
    )

    assert (
        created["root_task_id"]
        == "TASK-1001"
    )

    assert created["status"] == "pending"
    assert created["nodes"] == []


def test_parent_child_nodes_are_persisted(
    tmp_path,
):
    db_path = (
        tmp_path
        / "graph.db"
    )

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1001",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1002",
        parent_task_id="TASK-1001",
        db_path=db_path,
    )

    graph = get_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    nodes = {
        node["task_id"]: node
        for node in graph["nodes"]
    }

    assert (
        nodes["TASK-1001"][
            "parent_task_id"
        ]
        is None
    )

    assert (
        nodes["TASK-1002"][
            "parent_task_id"
        ]
        == "TASK-1001"
    )


def test_dependency_is_persisted(
    tmp_path,
):
    db_path = (
        tmp_path
        / "graph.db"
    )

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1001",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1002",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1002",
        "TASK-1001",
        db_path=db_path,
    )

    graph = get_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    nodes = {
        node["task_id"]: node
        for node in graph["nodes"]
    }

    assert (
        nodes["TASK-1002"][
            "depends_on"
        ]
        == ["TASK-1001"]
    )


def test_duplicate_dependency_is_idempotent(
    tmp_path,
):
    db_path = (
        tmp_path
        / "graph.db"
    )

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

    add_task_dependency(
        "GRAPH-1",
        "TASK-1002",
        "TASK-1001",
        db_path=db_path,
    )

    graph = get_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    node = next(
        item
        for item in graph["nodes"]
        if item["task_id"]
        == "TASK-1002"
    )

    assert node["depends_on"] == [
        "TASK-1001"
    ]


def test_unknown_parent_is_rejected(
    tmp_path,
):
    db_path = (
        tmp_path
        / "graph.db"
    )

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    with pytest.raises(
        KeyError,
        match="Unknown parent",
    ):
        add_task_graph_node(
            "GRAPH-1",
            "TASK-1002",
            parent_task_id="TASK-9999",
            db_path=db_path,
        )


def test_self_dependency_is_rejected(
    tmp_path,
):
    db_path = (
        tmp_path
        / "graph.db"
    )

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1001",
        db_path=db_path,
    )

    with pytest.raises(
        ValueError,
        match="depend on itself",
    ):
        add_task_dependency(
            "GRAPH-1",
            "TASK-1001",
            "TASK-1001",
            db_path=db_path,
        )


def test_delete_graph_cascades_relations(
    tmp_path,
):
    db_path = (
        tmp_path
        / "graph.db"
    )

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1001",
        db_path=db_path,
    )

    assert delete_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    assert (
        get_task_graph(
            "GRAPH-1",
            db_path=db_path,
        )
        is None
    )

    assert list_task_graphs(
        db_path=db_path,
    ) == []


def test_node_relationship_queries(
    tmp_path,
):
    db_path = (
        tmp_path
        / "graph.db"
    )

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1001",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1002",
        parent_task_id="TASK-1001",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1003",
        parent_task_id="TASK-1001",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1003",
        "TASK-1002",
        db_path=db_path,
    )

    from factory.task_graph_store import (
        get_task_graph_node,
        list_task_children,
        list_task_dependencies,
        list_task_dependents,
    )

    root = get_task_graph_node(
        "GRAPH-1",
        "TASK-1001",
        db_path=db_path,
    )

    assert root["children"] == [
        "TASK-1002",
        "TASK-1003",
    ]

    node_2 = get_task_graph_node(
        "GRAPH-1",
        "TASK-1002",
        db_path=db_path,
    )

    assert (
        node_2["parent_task_id"]
        == "TASK-1001"
    )

    assert (
        node_2["dependents"]
        == ["TASK-1003"]
    )

    assert list_task_children(
        "GRAPH-1",
        "TASK-1001",
        db_path=db_path,
    ) == [
        "TASK-1002",
        "TASK-1003",
    ]

    assert list_task_dependencies(
        "GRAPH-1",
        "TASK-1003",
        db_path=db_path,
    ) == [
        "TASK-1002"
    ]

    assert list_task_dependents(
        "GRAPH-1",
        "TASK-1002",
        db_path=db_path,
    ) == [
        "TASK-1003"
    ]


def test_relationship_query_rejects_unknown_task(
    tmp_path,
):
    from factory.task_graph_store import (
        list_task_dependencies,
    )

    db_path = (
        tmp_path
        / "graph.db"
    )

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    with pytest.raises(
        KeyError,
        match="Unknown task",
    ):
        list_task_dependencies(
            "GRAPH-1",
            "TASK-9999",
            db_path=db_path,
        )


def test_direct_dependency_cycle_is_rejected(
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

    with pytest.raises(
        ValueError,
        match="Dependency cycle",
    ):
        add_task_dependency(
            "GRAPH-1",
            "TASK-1001",
            "TASK-1002",
            db_path=db_path,
        )


def test_transitive_dependency_cycle_is_rejected(
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

    with pytest.raises(
        ValueError,
        match="Dependency cycle",
    ):
        add_task_dependency(
            "GRAPH-1",
            "TASK-1001",
            "TASK-1003",
            db_path=db_path,
        )


def test_parent_cycle_is_rejected(
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

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1002",
        parent_task_id="TASK-1001",
        db_path=db_path,
    )

    with pytest.raises(
        ValueError,
        match="Parent cycle",
    ):
        add_task_graph_node(
            "GRAPH-1",
            "TASK-1001",
            parent_task_id="TASK-1002",
            db_path=db_path,
        )


def test_valid_graph_passes_acyclic_validation(
    tmp_path,
):
    from factory.task_graph_store import (
        validate_task_graph_acyclic,
    )

    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
        "TASK-1003",
        "TASK-1004",
    ):
        add_task_graph_node(
            "GRAPH-1",
            task_id,
            db_path=db_path,
        )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1003",
        "TASK-1001",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1003",
        "TASK-1002",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1004",
        "TASK-1003",
        db_path=db_path,
    )

    assert validate_task_graph_acyclic(
        "GRAPH-1",
        db_path=db_path,
    )


def test_direct_dependency_cycle_is_rejected(
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

    with pytest.raises(
        ValueError,
        match="Dependency cycle",
    ):
        add_task_dependency(
            "GRAPH-1",
            "TASK-1001",
            "TASK-1002",
            db_path=db_path,
        )


def test_transitive_dependency_cycle_is_rejected(
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

    with pytest.raises(
        ValueError,
        match="Dependency cycle",
    ):
        add_task_dependency(
            "GRAPH-1",
            "TASK-1001",
            "TASK-1003",
            db_path=db_path,
        )


def test_parent_cycle_is_rejected(
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

    add_task_graph_node(
        "GRAPH-1",
        "TASK-1002",
        parent_task_id="TASK-1001",
        db_path=db_path,
    )

    with pytest.raises(
        ValueError,
        match="Parent cycle",
    ):
        add_task_graph_node(
            "GRAPH-1",
            "TASK-1001",
            parent_task_id="TASK-1002",
            db_path=db_path,
        )


def test_valid_graph_passes_acyclic_validation(
    tmp_path,
):
    from factory.task_graph_store import (
        validate_task_graph_acyclic,
    )

    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
        "TASK-1003",
        "TASK-1004",
    ):
        add_task_graph_node(
            "GRAPH-1",
            task_id,
            db_path=db_path,
        )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1003",
        "TASK-1001",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1003",
        "TASK-1002",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1004",
        "TASK-1003",
        db_path=db_path,
    )

    assert validate_task_graph_acyclic(
        "GRAPH-1",
        db_path=db_path,
    )


def test_task_without_dependencies_is_ready(
    tmp_path,
):
    from factory.task_graph_store import (
        evaluate_task_graph_node_state,
    )

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

    result = evaluate_task_graph_node_state(
        "GRAPH-1",
        "TASK-1001",
        {},
        db_path=db_path,
    )

    assert result["state"] == "ready"


def test_task_is_blocked_by_pending_dependency(
    tmp_path,
):
    from factory.task_graph_store import (
        evaluate_task_graph_node_state,
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

    result = evaluate_task_graph_node_state(
        "GRAPH-1",
        "TASK-1002",
        {
            "TASK-1001": "queued",
        },
        db_path=db_path,
    )

    assert result["state"] == "blocked"

    assert result[
        "pending_dependencies"
    ] == [
        "TASK-1001"
    ]


def test_task_becomes_ready_after_dependency_completion(
    tmp_path,
):
    from factory.task_graph_store import (
        evaluate_task_graph_node_state,
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

    result = evaluate_task_graph_node_state(
        "GRAPH-1",
        "TASK-1002",
        {
            "TASK-1001": "approved",
        },
        db_path=db_path,
    )

    assert result["state"] == "ready"


def test_failed_dependency_marks_node_failed(
    tmp_path,
):
    from factory.task_graph_store import (
        evaluate_task_graph_node_state,
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

    result = evaluate_task_graph_node_state(
        "GRAPH-1",
        "TASK-1002",
        {
            "TASK-1001": "failed",
        },
        db_path=db_path,
    )

    assert result["state"] == "failed"

    assert result[
        "failed_dependencies"
    ] == [
        "TASK-1001"
    ]


def test_list_runnable_tasks(
    tmp_path,
):
    from factory.task_graph_store import (
        list_runnable_tasks,
    )

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

    runnable = list_runnable_tasks(
        "GRAPH-1",
        {
            "TASK-1001": "approved",
            "TASK-1002": "queued",
            "TASK-1003": "queued",
        },
        db_path=db_path,
    )

    assert runnable == [
        "TASK-1002"
    ]


def test_topological_task_order_linear_graph(
    tmp_path,
):
    from factory.task_graph_store import (
        topological_task_order,
    )

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

    assert topological_task_order(
        "GRAPH-1",
        db_path=db_path,
    ) == [
        "TASK-1001",
        "TASK-1002",
        "TASK-1003",
    ]


def test_topological_order_handles_parallel_branches(
    tmp_path,
):
    from factory.task_graph_store import (
        topological_task_order,
    )

    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
        "TASK-1003",
        "TASK-1004",
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
        "TASK-1001",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1004",
        "TASK-1002",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1004",
        "TASK-1003",
        db_path=db_path,
    )

    order = topological_task_order(
        "GRAPH-1",
        db_path=db_path,
    )

    assert order[0] == "TASK-1001"
    assert order[-1] == "TASK-1004"

    assert (
        order.index("TASK-1002")
        < order.index("TASK-1004")
    )

    assert (
        order.index("TASK-1003")
        < order.index("TASK-1004")
    )


def test_topological_layers_expose_parallel_tasks(
    tmp_path,
):
    from factory.task_graph_store import (
        topological_task_layers,
    )

    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
        "TASK-1003",
        "TASK-1004",
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
        "TASK-1001",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1004",
        "TASK-1002",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-1004",
        "TASK-1003",
        db_path=db_path,
    )

    assert topological_task_layers(
        "GRAPH-1",
        db_path=db_path,
    ) == [
        ["TASK-1001"],
        [
            "TASK-1002",
            "TASK-1003",
        ],
        ["TASK-1004"],
    ]


def test_empty_graph_has_empty_topological_order(
    tmp_path,
):
    from factory.task_graph_store import (
        topological_task_layers,
        topological_task_order,
    )

    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    assert topological_task_order(
        "GRAPH-1",
        db_path=db_path,
    ) == []

    assert topological_task_layers(
        "GRAPH-1",
        db_path=db_path,
    ) == []


def test_direct_dependency_failure_propagates(
    tmp_path,
):
    from factory.task_graph_store import (
        propagate_dependency_failures,
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
        propagate_dependency_failures(
            "GRAPH-1",
            {
                "TASK-1001": "failed",
                "TASK-1002": "queued",
            },
            db_path=db_path,
        )
    )

    assert (
        result["TASK-1002"][
            "blocked_by_failure"
        ]
        is True
    )

    assert (
        result["TASK-1002"][
            "failed_dependencies"
        ]
        == ["TASK-1001"]
    )


def test_transitive_dependency_failure_propagates(
    tmp_path,
):
    from factory.task_graph_store import (
        propagate_dependency_failures,
    )

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

    result = (
        propagate_dependency_failures(
            "GRAPH-1",
            {
                "TASK-1001": "failed",
                "TASK-1002": "queued",
                "TASK-1003": "queued",
            },
            db_path=db_path,
        )
    )

    assert (
        result["TASK-1003"][
            "blocked_by_failure"
        ]
        is True
    )

    assert (
        result["TASK-1003"][
            "failed_dependencies"
        ]
        == ["TASK-1001"]
    )


def test_successful_dependencies_do_not_propagate_failure(
    tmp_path,
):
    from factory.task_graph_store import (
        propagate_dependency_failures,
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
        propagate_dependency_failures(
            "GRAPH-1",
            {
                "TASK-1001": "approved",
                "TASK-1002": "queued",
            },
            db_path=db_path,
        )
    )

    assert (
        result["TASK-1002"][
            "blocked_by_failure"
        ]
        is False
    )

    assert (
        result["TASK-1002"][
            "failed_dependencies"
        ]
        == []
    )


def test_list_failure_blocked_tasks(
    tmp_path,
):
    from factory.task_graph_store import (
        list_failure_blocked_tasks,
    )

    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
        "TASK-1003",
        "TASK-1004",
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

    blocked = list_failure_blocked_tasks(
        "GRAPH-1",
        {
            "TASK-1001": "failed",
            "TASK-1002": "queued",
            "TASK-1003": "queued",
            "TASK-1004": "queued",
        },
        db_path=db_path,
    )

    assert blocked == [
        "TASK-1002",
        "TASK-1003",
    ]


def test_direct_dependency_failure_propagates(
    tmp_path,
):
    from factory.task_graph_store import (
        propagate_dependency_failures,
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
        propagate_dependency_failures(
            "GRAPH-1",
            {
                "TASK-1001": "failed",
                "TASK-1002": "queued",
            },
            db_path=db_path,
        )
    )

    assert (
        result["TASK-1002"][
            "blocked_by_failure"
        ]
        is True
    )

    assert (
        result["TASK-1002"][
            "failed_dependencies"
        ]
        == ["TASK-1001"]
    )


def test_transitive_dependency_failure_propagates(
    tmp_path,
):
    from factory.task_graph_store import (
        propagate_dependency_failures,
    )

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

    result = (
        propagate_dependency_failures(
            "GRAPH-1",
            {
                "TASK-1001": "failed",
                "TASK-1002": "queued",
                "TASK-1003": "queued",
            },
            db_path=db_path,
        )
    )

    assert (
        result["TASK-1003"][
            "blocked_by_failure"
        ]
        is True
    )

    assert (
        result["TASK-1003"][
            "failed_dependencies"
        ]
        == ["TASK-1001"]
    )


def test_successful_dependencies_do_not_propagate_failure(
    tmp_path,
):
    from factory.task_graph_store import (
        propagate_dependency_failures,
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
        propagate_dependency_failures(
            "GRAPH-1",
            {
                "TASK-1001": "approved",
                "TASK-1002": "queued",
            },
            db_path=db_path,
        )
    )

    assert (
        result["TASK-1002"][
            "blocked_by_failure"
        ]
        is False
    )

    assert (
        result["TASK-1002"][
            "failed_dependencies"
        ]
        == []
    )


def test_list_failure_blocked_tasks(
    tmp_path,
):
    from factory.task_graph_store import (
        list_failure_blocked_tasks,
    )

    db_path = tmp_path / "graph.db"

    create_task_graph(
        "GRAPH-1",
        db_path=db_path,
    )

    for task_id in (
        "TASK-1001",
        "TASK-1002",
        "TASK-1003",
        "TASK-1004",
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

    blocked = list_failure_blocked_tasks(
        "GRAPH-1",
        {
            "TASK-1001": "failed",
            "TASK-1002": "queued",
            "TASK-1003": "queued",
            "TASK-1004": "queued",
        },
        db_path=db_path,
    )

    assert blocked == [
        "TASK-1002",
        "TASK-1003",
    ]


def test_ready_for_approval_dependency_is_not_complete(
    tmp_path,
):
    from factory.task_graph_store import (
        evaluate_task_graph_node_state,
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

    result = evaluate_task_graph_node_state(
        "GRAPH-1",
        "TASK-1002",
        {
            "TASK-1001":
                "ready_for_approval",
        },
        db_path=db_path,
    )

    assert result["state"] == "blocked"
