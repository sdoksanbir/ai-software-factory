from pathlib import Path
from typing import Any

from factory.database import (
    DEFAULT_DB_PATH,
    get_connection,
)


GRAPH_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
}


def _require_text(
    value: Any,
    field_name: str,
) -> str:
    normalized = str(
        value or ""
    ).strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must not be blank"
        )

    return normalized


def _require_graph_status(
    value: str,
) -> str:
    normalized = _require_text(
        value,
        "graph status",
    ).lower()

    if normalized not in GRAPH_STATUSES:
        raise ValueError(
            "Invalid graph status: "
            f"{normalized}"
        )

    return normalized


def init_task_graph_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    connection = get_connection(
        db_path
    )

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_graphs (
                graph_id TEXT PRIMARY KEY,
                project_id TEXT,
                root_task_id TEXT,
                status TEXT NOT NULL
                    DEFAULT 'pending',
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS task_graph_nodes (
                graph_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                parent_task_id TEXT,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (
                    graph_id,
                    task_id
                ),
                FOREIGN KEY (
                    graph_id
                )
                REFERENCES task_graphs (
                    graph_id
                )
                ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_dependencies (
                graph_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                depends_on_task_id TEXT NOT NULL,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (
                    graph_id,
                    task_id,
                    depends_on_task_id
                ),

                CHECK (
                    task_id
                    <> depends_on_task_id
                ),

                FOREIGN KEY (
                    graph_id,
                    task_id
                )
                REFERENCES task_graph_nodes (
                    graph_id,
                    task_id
                )
                ON DELETE CASCADE,

                FOREIGN KEY (
                    graph_id,
                    depends_on_task_id
                )
                REFERENCES task_graph_nodes (
                    graph_id,
                    task_id
                )
                ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS
                idx_task_graph_nodes_graph
            ON task_graph_nodes (
                graph_id,
                task_id
            );

            CREATE INDEX IF NOT EXISTS
                idx_task_dependencies_task
            ON task_dependencies (
                graph_id,
                task_id
            );

            CREATE INDEX IF NOT EXISTS
                idx_task_dependencies_dependency
            ON task_dependencies (
                graph_id,
                depends_on_task_id
            );
            """
        )

        connection.commit()

    finally:
        connection.close()


def create_task_graph(
    graph_id: str,
    *,
    project_id: str | None = None,
    root_task_id: str | None = None,
    status: str = "pending",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    graph_id = _require_text(
        graph_id,
        "graph_id",
    )

    status = _require_graph_status(
        status
    )

    normalized_project_id = (
        str(project_id).strip()
        if project_id is not None
        else None
    )

    normalized_root_task_id = (
        str(root_task_id).strip()
        if root_task_id is not None
        else None
    )

    init_task_graph_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        connection.execute(
            """
            INSERT INTO task_graphs (
                graph_id,
                project_id,
                root_task_id,
                status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                graph_id,
                normalized_project_id,
                normalized_root_task_id,
                status,
            ),
        )

        connection.commit()

    finally:
        connection.close()

    result = get_task_graph(
        graph_id,
        db_path=db_path,
    )

    if result is None:
        raise RuntimeError(
            "Task graph could not be loaded "
            "after creation"
        )

    return result


def _graph_exists(
    connection,
    graph_id: str,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM task_graphs
        WHERE graph_id = ?
        """,
        (graph_id,),
    ).fetchone()

    return row is not None


def _node_exists(
    connection,
    graph_id: str,
    task_id: str,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM task_graph_nodes
        WHERE graph_id = ?
          AND task_id = ?
        """,
        (
            graph_id,
            task_id,
        ),
    ).fetchone()

    return row is not None


def add_task_graph_node(
    graph_id: str,
    task_id: str,
    *,
    parent_task_id: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    graph_id = _require_text(
        graph_id,
        "graph_id",
    )

    task_id = _require_text(
        task_id,
        "task_id",
    )

    if parent_task_id is not None:
        parent_task_id = _require_text(
            parent_task_id,
            "parent_task_id",
        )

        if parent_task_id == task_id:
            raise ValueError(
                "Task cannot be its own parent"
            )

    init_task_graph_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        if not _graph_exists(
            connection,
            graph_id,
        ):
            raise KeyError(
                f"Unknown task graph: {graph_id}"
            )

        if (
            parent_task_id is not None
            and not _node_exists(
                connection,
                graph_id,
                parent_task_id,
            )
        ):
            raise KeyError(
                "Unknown parent task in graph: "
                f"{parent_task_id}"
            )

        if (
            parent_task_id is not None
            and _would_create_parent_cycle(
                connection,
                graph_id,
                task_id,
                parent_task_id,
            )
        ):
            raise ValueError(
                "Parent cycle detected: "
                f"{task_id} -> "
                f"{parent_task_id}"
            )

        connection.execute(
            """
            INSERT INTO task_graph_nodes (
                graph_id,
                task_id,
                parent_task_id
            )
            VALUES (?, ?, ?)
            ON CONFLICT(
                graph_id,
                task_id
            )
            DO UPDATE SET
                parent_task_id =
                    excluded.parent_task_id
            """,
            (
                graph_id,
                task_id,
                parent_task_id,
            ),
        )

        connection.execute(
            """
            UPDATE task_graphs
            SET updated_at =
                CURRENT_TIMESTAMP
            WHERE graph_id = ?
            """,
            (graph_id,),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def add_task_dependency(
    graph_id: str,
    task_id: str,
    depends_on_task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    graph_id = _require_text(
        graph_id,
        "graph_id",
    )

    task_id = _require_text(
        task_id,
        "task_id",
    )

    depends_on_task_id = _require_text(
        depends_on_task_id,
        "depends_on_task_id",
    )

    if task_id == depends_on_task_id:
        raise ValueError(
            "Task cannot depend on itself"
        )

    init_task_graph_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        if not _graph_exists(
            connection,
            graph_id,
        ):
            raise KeyError(
                f"Unknown task graph: {graph_id}"
            )

        if not _node_exists(
            connection,
            graph_id,
            task_id,
        ):
            raise KeyError(
                "Unknown task in graph: "
                f"{task_id}"
            )

        if not _node_exists(
            connection,
            graph_id,
            depends_on_task_id,
        ):
            raise KeyError(
                "Unknown dependency task "
                "in graph: "
                f"{depends_on_task_id}"
            )

        if _would_create_dependency_cycle(
            connection,
            graph_id,
            task_id,
            depends_on_task_id,
        ):
            raise ValueError(
                "Dependency cycle detected: "
                f"{task_id} -> "
                f"{depends_on_task_id}"
            )

        connection.execute(
            """
            INSERT OR IGNORE
            INTO task_dependencies (
                graph_id,
                task_id,
                depends_on_task_id
            )
            VALUES (?, ?, ?)
            """,
            (
                graph_id,
                task_id,
                depends_on_task_id,
            ),
        )

        connection.execute(
            """
            UPDATE task_graphs
            SET updated_at =
                CURRENT_TIMESTAMP
            WHERE graph_id = ?
            """,
            (graph_id,),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_task_graph(
    graph_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    graph_id = _require_text(
        graph_id,
        "graph_id",
    )

    init_task_graph_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        graph_row = connection.execute(
            """
            SELECT *
            FROM task_graphs
            WHERE graph_id = ?
            """,
            (graph_id,),
        ).fetchone()

        if graph_row is None:
            return None

        node_rows = connection.execute(
            """
            SELECT *
            FROM task_graph_nodes
            WHERE graph_id = ?
            ORDER BY task_id ASC
            """,
            (graph_id,),
        ).fetchall()

        dependency_rows = (
            connection.execute(
                """
                SELECT
                    task_id,
                    depends_on_task_id
                FROM task_dependencies
                WHERE graph_id = ?
                ORDER BY
                    task_id ASC,
                    depends_on_task_id ASC
                """,
                (graph_id,),
            ).fetchall()
        )

        dependencies: dict[
            str,
            list[str],
        ] = {}

        for row in dependency_rows:
            dependencies.setdefault(
                row["task_id"],
                [],
            ).append(
                row[
                    "depends_on_task_id"
                ]
            )

        result = dict(
            graph_row
        )

        result["nodes"] = []

        for row in node_rows:
            node = dict(
                row
            )

            node["depends_on"] = list(
                dependencies.get(
                    row["task_id"],
                    [],
                )
            )

            result["nodes"].append(
                node
            )

        return result

    finally:
        connection.close()


def list_task_graphs(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    init_task_graph_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM task_graphs
            ORDER BY
                created_at ASC,
                graph_id ASC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def delete_task_graph(
    graph_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    graph_id = _require_text(
        graph_id,
        "graph_id",
    )

    init_task_graph_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        cursor = connection.execute(
            """
            DELETE FROM task_graphs
            WHERE graph_id = ?
            """,
            (graph_id,),
        )

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()


def get_task_graph_node(
    graph_id: str,
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    graph_id = _require_text(
        graph_id,
        "graph_id",
    )

    task_id = _require_text(
        task_id,
        "task_id",
    )

    init_task_graph_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        row = connection.execute(
            """
            SELECT *
            FROM task_graph_nodes
            WHERE graph_id = ?
              AND task_id = ?
            """,
            (
                graph_id,
                task_id,
            ),
        ).fetchone()

        if row is None:
            return None

        node = dict(row)

        dependency_rows = (
            connection.execute(
                """
                SELECT depends_on_task_id
                FROM task_dependencies
                WHERE graph_id = ?
                  AND task_id = ?
                ORDER BY depends_on_task_id
                """,
                (
                    graph_id,
                    task_id,
                ),
            ).fetchall()
        )

        dependent_rows = (
            connection.execute(
                """
                SELECT task_id
                FROM task_dependencies
                WHERE graph_id = ?
                  AND depends_on_task_id = ?
                ORDER BY task_id
                """,
                (
                    graph_id,
                    task_id,
                ),
            ).fetchall()
        )

        child_rows = connection.execute(
            """
            SELECT task_id
            FROM task_graph_nodes
            WHERE graph_id = ?
              AND parent_task_id = ?
            ORDER BY task_id
            """,
            (
                graph_id,
                task_id,
            ),
        ).fetchall()

        node["depends_on"] = [
            row["depends_on_task_id"]
            for row in dependency_rows
        ]

        node["dependents"] = [
            row["task_id"]
            for row in dependent_rows
        ]

        node["children"] = [
            row["task_id"]
            for row in child_rows
        ]

        return node

    finally:
        connection.close()


def list_task_children(
    graph_id: str,
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    node = get_task_graph_node(
        graph_id,
        task_id,
        db_path=db_path,
    )

    if node is None:
        raise KeyError(
            f"Unknown task in graph: {task_id}"
        )

    return list(
        node["children"]
    )


def list_task_dependencies(
    graph_id: str,
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    node = get_task_graph_node(
        graph_id,
        task_id,
        db_path=db_path,
    )

    if node is None:
        raise KeyError(
            f"Unknown task in graph: {task_id}"
        )

    return list(
        node["depends_on"]
    )


def list_task_dependents(
    graph_id: str,
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    node = get_task_graph_node(
        graph_id,
        task_id,
        db_path=db_path,
    )

    if node is None:
        raise KeyError(
            f"Unknown task in graph: {task_id}"
        )

    return list(
        node["dependents"]
    )



def _would_create_parent_cycle(
    connection,
    graph_id: str,
    task_id: str,
    parent_task_id: str,
) -> bool:
    current: str | None = (
        parent_task_id
    )

    visited: set[str] = set()

    while current is not None:
        if current == task_id:
            return True

        if current in visited:
            # Existing corrupted hierarchy.
            return True

        visited.add(
            current
        )

        row = connection.execute(
            """
            SELECT parent_task_id
            FROM task_graph_nodes
            WHERE graph_id = ?
              AND task_id = ?
            """,
            (
                graph_id,
                current,
            ),
        ).fetchone()

        if row is None:
            return False

        current = row[
            "parent_task_id"
        ]

    return False


def _would_create_dependency_cycle(
    connection,
    graph_id: str,
    task_id: str,
    depends_on_task_id: str,
) -> bool:
    stack = [
        depends_on_task_id
    ]

    visited: set[str] = set()

    while stack:
        current = stack.pop()

        if current == task_id:
            return True

        if current in visited:
            continue

        visited.add(
            current
        )

        rows = connection.execute(
            """
            SELECT depends_on_task_id
            FROM task_dependencies
            WHERE graph_id = ?
              AND task_id = ?
            """,
            (
                graph_id,
                current,
            ),
        ).fetchall()

        stack.extend(
            row["depends_on_task_id"]
            for row in rows
        )

    return False


def validate_task_graph_acyclic(
    graph_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    graph_id = _require_text(
        graph_id,
        "graph_id",
    )

    init_task_graph_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        if not _graph_exists(
            connection,
            graph_id,
        ):
            raise KeyError(
                f"Unknown task graph: {graph_id}"
            )

        nodes = connection.execute(
            """
            SELECT
                task_id,
                parent_task_id
            FROM task_graph_nodes
            WHERE graph_id = ?
            """,
            (graph_id,),
        ).fetchall()

        for node in nodes:
            parent_task_id = (
                node["parent_task_id"]
            )

            if (
                parent_task_id is not None
                and _would_create_parent_cycle(
                    connection,
                    graph_id,
                    node["task_id"],
                    parent_task_id,
                )
            ):
                raise ValueError(
                    "Parent cycle detected "
                    "in task graph"
                )

        dependencies = (
            connection.execute(
                """
                SELECT
                    task_id,
                    depends_on_task_id
                FROM task_dependencies
                WHERE graph_id = ?
                """,
                (graph_id,),
            ).fetchall()
        )

        for dependency in dependencies:
            if _would_create_dependency_cycle(
                connection,
                graph_id,
                dependency["task_id"],
                dependency[
                    "depends_on_task_id"
                ],
            ):
                raise ValueError(
                    "Dependency cycle detected "
                    "in task graph"
                )

        return True

    finally:
        connection.close()


def _normalize_execution_state(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip().lower()


def evaluate_task_graph_node_state(
    graph_id: str,
    task_id: str,
    task_states: dict[str, str],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    node = get_task_graph_node(
        graph_id,
        task_id,
        db_path=db_path,
    )

    if node is None:
        raise KeyError(
            f"Unknown task in graph: {task_id}"
        )

    dependencies = list(
        node["depends_on"]
    )

    completed_states = {
        "approved",
        "completed",
        "test_passed",
    }

    failed_states = {
        "failed",
        "rejected",
        "test_failed",
    }

    failed_dependencies: list[str] = []
    pending_dependencies: list[str] = []

    for dependency_id in dependencies:
        state = _normalize_execution_state(
            task_states.get(
                dependency_id
            )
        )

        if state in failed_states:
            failed_dependencies.append(
                dependency_id
            )

        elif state not in completed_states:
            pending_dependencies.append(
                dependency_id
            )

    if failed_dependencies:
        scheduling_state = "failed"

    elif pending_dependencies:
        scheduling_state = "blocked"

    else:
        scheduling_state = "ready"

    return {
        "graph_id": graph_id,
        "task_id": task_id,
        "state": scheduling_state,
        "depends_on": dependencies,
        "pending_dependencies": (
            pending_dependencies
        ),
        "failed_dependencies": (
            failed_dependencies
        ),
    }


def list_runnable_tasks(
    graph_id: str,
    task_states: dict[str, str],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    graph = get_task_graph(
        graph_id,
        db_path=db_path,
    )

    if graph is None:
        raise KeyError(
            f"Unknown task graph: {graph_id}"
        )

    runnable: list[str] = []

    for node in graph["nodes"]:
        task_id = node["task_id"]

        current_state = (
            _normalize_execution_state(
                task_states.get(
                    task_id
                )
            )
        )

        if current_state in {
            "approved",
            "completed",
            "failed",
            "rejected",
            "running",
            "model_running",
            "testing",
            "ready_for_approval",
        }:
            continue

        evaluation = (
            evaluate_task_graph_node_state(
                graph_id,
                task_id,
                task_states,
                db_path=db_path,
            )
        )

        if (
            evaluation["state"]
            == "ready"
        ):
            runnable.append(
                task_id
            )

    return sorted(
        runnable
    )


def list_blocked_tasks(
    graph_id: str,
    task_states: dict[str, str],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    graph = get_task_graph(
        graph_id,
        db_path=db_path,
    )

    if graph is None:
        raise KeyError(
            f"Unknown task graph: {graph_id}"
        )

    blocked: list[str] = []

    for node in graph["nodes"]:
        task_id = node["task_id"]

        evaluation = (
            evaluate_task_graph_node_state(
                graph_id,
                task_id,
                task_states,
                db_path=db_path,
            )
        )

        if (
            evaluation["state"]
            == "blocked"
        ):
            blocked.append(
                task_id
            )

    return sorted(
        blocked
    )


def topological_task_order(
    graph_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    graph = get_task_graph(
        graph_id,
        db_path=db_path,
    )

    if graph is None:
        raise KeyError(
            f"Unknown task graph: {graph_id}"
        )

    task_ids = {
        node["task_id"]
        for node in graph["nodes"]
    }

    indegree: dict[str, int] = {
        task_id: 0
        for task_id in task_ids
    }

    dependents: dict[
        str,
        list[str],
    ] = {
        task_id: []
        for task_id in task_ids
    }

    for node in graph["nodes"]:
        task_id = node["task_id"]

        for dependency_id in (
            node["depends_on"]
        ):
            if dependency_id not in task_ids:
                raise ValueError(
                    "Task graph contains "
                    "an unknown dependency: "
                    f"{dependency_id}"
                )

            indegree[task_id] += 1

            dependents[
                dependency_id
            ].append(
                task_id
            )

    ready = sorted(
        task_id
        for task_id, degree
        in indegree.items()
        if degree == 0
    )

    result: list[str] = []

    while ready:
        current = ready.pop(0)

        result.append(
            current
        )

        for dependent in sorted(
            dependents[current]
        ):
            indegree[
                dependent
            ] -= 1

            if (
                indegree[dependent]
                == 0
            ):
                ready.append(
                    dependent
                )

        ready.sort()

    if len(result) != len(task_ids):
        raise ValueError(
            "Dependency cycle detected "
            "while calculating "
            "topological task order"
        )

    return result


def topological_task_layers(
    graph_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[list[str]]:
    graph = get_task_graph(
        graph_id,
        db_path=db_path,
    )

    if graph is None:
        raise KeyError(
            f"Unknown task graph: {graph_id}"
        )

    task_ids = {
        node["task_id"]
        for node in graph["nodes"]
    }

    indegree: dict[str, int] = {
        task_id: 0
        for task_id in task_ids
    }

    dependents: dict[
        str,
        list[str],
    ] = {
        task_id: []
        for task_id in task_ids
    }

    for node in graph["nodes"]:
        task_id = node["task_id"]

        for dependency_id in (
            node["depends_on"]
        ):
            indegree[
                task_id
            ] += 1

            dependents[
                dependency_id
            ].append(
                task_id
            )

    current_layer = sorted(
        task_id
        for task_id, degree
        in indegree.items()
        if degree == 0
    )

    layers: list[
        list[str]
    ] = []

    visited_count = 0

    while current_layer:
        layers.append(
            list(current_layer)
        )

        next_layer: list[str] = []

        for current in current_layer:
            visited_count += 1

            for dependent in sorted(
                dependents[current]
            ):
                indegree[
                    dependent
                ] -= 1

                if (
                    indegree[
                        dependent
                    ]
                    == 0
                ):
                    next_layer.append(
                        dependent
                    )

        current_layer = sorted(
            next_layer
        )

    if visited_count != len(task_ids):
        raise ValueError(
            "Dependency cycle detected "
            "while calculating "
            "topological task layers"
        )

    return layers


def propagate_dependency_failures(
    graph_id: str,
    task_states: dict[str, str],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, dict[str, Any]]:
    graph = get_task_graph(
        graph_id,
        db_path=db_path,
    )

    if graph is None:
        raise KeyError(
            f"Unknown task graph: {graph_id}"
        )

    normalized_states = {
        task_id: _normalize_execution_state(
            state
        )
        for task_id, state
        in task_states.items()
    }

    failed_states = {
        "failed",
        "rejected",
        "test_failed",
    }

    failure_map: dict[
        str,
        set[str],
    ] = {
        node["task_id"]: set()
        for node in graph["nodes"]
    }

    dependencies = {
        node["task_id"]: list(
            node["depends_on"]
        )
        for node in graph["nodes"]
    }

    changed = True

    while changed:
        changed = False

        for task_id, depends_on in dependencies.items():
            current_failures = (
                failure_map[
                    task_id
                ]
            )

            before = len(
                current_failures
            )

            for dependency_id in (
                depends_on
            ):
                dependency_state = (
                    normalized_states.get(
                        dependency_id,
                        "",
                    )
                )

                if (
                    dependency_state
                    in failed_states
                ):
                    current_failures.add(
                        dependency_id
                    )

                current_failures.update(
                    failure_map.get(
                        dependency_id,
                        set(),
                    )
                )

            if (
                len(current_failures)
                != before
            ):
                changed = True

    result: dict[
        str,
        dict[str, Any],
    ] = {}

    for node in graph["nodes"]:
        task_id = node["task_id"]

        failures = sorted(
            failure_map[
                task_id
            ]
        )

        result[
            task_id
        ] = {
            "task_id": task_id,
            "blocked_by_failure": (
                bool(failures)
            ),
            "failed_dependencies": (
                failures
            ),
        }

    return result


def list_failure_blocked_tasks(
    graph_id: str,
    task_states: dict[str, str],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    propagation = (
        propagate_dependency_failures(
            graph_id,
            task_states,
            db_path=db_path,
        )
    )

    return sorted(
        task_id
        for task_id, result
        in propagation.items()
        if result[
            "blocked_by_failure"
        ]
    )


def list_task_graph_ids_for_task(
    task_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    task_id = _require_text(
        task_id,
        "task_id",
    )

    init_task_graph_store(
        db_path
    )

    connection = get_connection(
        db_path
    )

    try:
        rows = connection.execute(
            """
            SELECT graph_id
            FROM task_graph_nodes
            WHERE task_id = ?
            ORDER BY graph_id ASC
            """,
            (task_id,),
        ).fetchall()

        return [
            row["graph_id"]
            for row in rows
        ]

    finally:
        connection.close()
