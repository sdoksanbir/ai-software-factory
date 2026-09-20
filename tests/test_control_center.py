from types import SimpleNamespace

from factory.control_center import (
    _provider_summary,
)


class FakeHealth:
    def __init__(
        self,
        name,
        status,
    ):
        self.provider_name = name
        self.status = SimpleNamespace(
            value=status
        )

    def as_dict(self):
        return {
            "provider_name": (
                self.provider_name
            ),
            "status": (
                self.status.value
            ),
        }


class FakeRegistry:
    def __init__(
        self,
        items,
    ):
        self.items = items

    def runtime_health_all(
        self,
        *,
        timeout_seconds,
    ):
        assert timeout_seconds == 2.0
        return tuple(
            self.items
        )


class FailingRegistry:
    def runtime_health_all(
        self,
        *,
        timeout_seconds,
    ):
        raise RuntimeError(
            "provider probe failed"
        )


def test_provider_summary_without_registry():
    result = _provider_summary(
        None
    )

    assert result == {
        "available": False,
        "total": 0,
        "healthy": 0,
        "unavailable": 0,
        "unknown": 0,
        "items": [],
    }


def test_provider_summary_counts_health_states():
    registry = FakeRegistry(
        [
            FakeHealth(
                "local",
                "available",
            ),
            FakeHealth(
                "gemini",
                "unavailable",
            ),
            FakeHealth(
                "future",
                "unknown",
            ),
        ]
    )

    result = _provider_summary(
        registry
    )

    assert result["available"] is True
    assert result["total"] == 3
    assert result["healthy"] == 1
    assert result["unavailable"] == 1
    assert result["unknown"] == 1

    assert [
        item["provider_name"]
        for item in result["items"]
    ] == [
        "local",
        "gemini",
        "future",
    ]


def test_provider_summary_preserves_health_payload():
    registry = FakeRegistry(
        [
            FakeHealth(
                "local",
                "available",
            ),
        ]
    )

    result = _provider_summary(
        registry
    )

    assert result["items"][0] == {
        "provider_name": "local",
        "status": "available",
    }


def test_provider_probe_failure_does_not_break_control_center():
    result = _provider_summary(
        FailingRegistry()
    )

    assert result["available"] is False
    assert result["total"] == 0
    assert result["healthy"] == 0
    assert result["unavailable"] == 0
    assert result["unknown"] == 0
    assert (
        "provider probe failed"
        in result["error"]
    )


def test_agent_summary_without_registry():
    from factory.control_center import (
        _agent_summary,
    )

    result = _agent_summary(
        None,
        {
            "items": [],
        },
    )

    assert result == {
        "available": False,
        "total": 0,
        "ready": 0,
        "unavailable": 0,
        "unknown": 0,
        "items": [],
    }


def test_agent_summary_uses_provider_health(
    monkeypatch,
):
    from factory.control_center import (
        _agent_summary,
    )

    descriptors = (
        SimpleNamespace(
            name="local-analyst",
            provider_name="local",
            capabilities=(
                SimpleNamespace(
                    value="read_repository"
                ),
                SimpleNamespace(
                    value="plan_task"
                ),
            ),
        ),
        SimpleNamespace(
            name="gemini-reviewer",
            provider_name="gemini",
            capabilities=(
                SimpleNamespace(
                    value="review_code"
                ),
            ),
        ),
    )

    monkeypatch.setattr(
        "factory.control_center."
        "build_default_agent_descriptors",
        lambda registry: descriptors,
    )

    result = _agent_summary(
        object(),
        {
            "items": [
                {
                    "provider_name": "local",
                    "status": "available",
                },
                {
                    "provider_name": "gemini",
                    "status": "unavailable",
                },
            ],
        },
    )

    assert result["available"] is True
    assert result["total"] == 2
    assert result["ready"] == 1
    assert result["unavailable"] == 1
    assert result["unknown"] == 0

    local = result["items"][0]

    assert local["name"] == "local-analyst"
    assert local["provider_name"] == "local"
    assert local["ready"] is True

    assert sorted(
        local["capabilities"]
    ) == [
        "plan_task",
        "read_repository",
    ]

    gemini = result["items"][1]

    assert (
        gemini["provider_status"]
        == "unavailable"
    )

    assert gemini["ready"] is False


def test_agent_summary_marks_missing_provider_unknown(
    monkeypatch,
):
    from factory.control_center import (
        _agent_summary,
    )

    descriptors = (
        SimpleNamespace(
            name="future-agent",
            provider_name="future",
            capabilities=frozenset(),
        ),
    )

    monkeypatch.setattr(
        "factory.control_center."
        "build_default_agent_descriptors",
        lambda registry: descriptors,
    )

    result = _agent_summary(
        object(),
        {
            "items": [],
        },
    )

    assert result["total"] == 1
    assert result["ready"] == 0
    assert result["unknown"] == 1

    assert (
        result["items"][0][
            "provider_status"
        ]
        == "unknown"
    )


def test_agent_descriptor_failure_does_not_break_control_center(
    monkeypatch,
):
    from factory.control_center import (
        _agent_summary,
    )

    def fail(
        registry,
    ):
        raise RuntimeError(
            "agent discovery failed"
        )

    monkeypatch.setattr(
        "factory.control_center."
        "build_default_agent_descriptors",
        fail,
    )

    result = _agent_summary(
        object(),
        {
            "items": [],
        },
    )

    assert result["available"] is False
    assert result["total"] == 0
    assert result["ready"] == 0
    assert result["unavailable"] == 0
    assert result["unknown"] == 0

    assert (
        "agent discovery failed"
        in result["error"]
    )


def test_task_graph_summary_finds_runnable_and_blocked_tasks(
    tmp_path,
):
    from factory.control_center import (
        _task_graph_summary,
    )
    from factory.task_graph_store import (
        add_task_dependency,
        add_task_graph_node,
        create_task_graph,
    )

    db_path = tmp_path / "factory.db"

    create_task_graph(
        "GRAPH-1",
        project_id="PROJECT-1",
        status="running",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-A",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-1",
        "TASK-B",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-1",
        "TASK-B",
        "TASK-A",
        db_path=db_path,
    )

    result = _task_graph_summary(
        [
            {
                "task_id": "TASK-A",
                "state": "queued",
            },
            {
                "task_id": "TASK-B",
                "state": "queued",
            },
        ],
        project_id="PROJECT-1",
        db_path=db_path,
    )

    assert result["available"] is True
    assert result["total"] == 1
    assert result["active"] == 1
    assert result["completed"] == 0
    assert result["failed"] == 0

    graph = result["items"][0]

    assert graph["runnable_tasks"] == [
        "TASK-A",
    ]

    assert graph["blocked_tasks"] == [
        "TASK-B",
    ]

    assert result["runnable_tasks"] == 1
    assert result["blocked"] == 1


def test_task_graph_summary_releases_dependency_after_completion(
    tmp_path,
):
    from factory.control_center import (
        _task_graph_summary,
    )
    from factory.task_graph_store import (
        add_task_dependency,
        add_task_graph_node,
        create_task_graph,
    )

    db_path = tmp_path / "factory.db"

    create_task_graph(
        "GRAPH-2",
        project_id="PROJECT-1",
        status="running",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-2",
        "TASK-A",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-2",
        "TASK-B",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-2",
        "TASK-B",
        "TASK-A",
        db_path=db_path,
    )

    result = _task_graph_summary(
        [
            {
                "task_id": "TASK-A",
                "state": "approved",
            },
            {
                "task_id": "TASK-B",
                "state": "queued",
            },
        ],
        project_id="PROJECT-1",
        db_path=db_path,
    )

    graph = result["items"][0]

    assert graph["blocked_tasks"] == []

    assert graph["runnable_tasks"] == [
        "TASK-B",
    ]


def test_task_graph_summary_reports_failure_blocking(
    tmp_path,
):
    from factory.control_center import (
        _task_graph_summary,
    )
    from factory.task_graph_store import (
        add_task_dependency,
        add_task_graph_node,
        create_task_graph,
    )

    db_path = tmp_path / "factory.db"

    create_task_graph(
        "GRAPH-FAIL",
        project_id="PROJECT-1",
        status="running",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-FAIL",
        "TASK-ROOT",
        db_path=db_path,
    )

    add_task_graph_node(
        "GRAPH-FAIL",
        "TASK-CHILD",
        db_path=db_path,
    )

    add_task_dependency(
        "GRAPH-FAIL",
        "TASK-CHILD",
        "TASK-ROOT",
        db_path=db_path,
    )

    result = _task_graph_summary(
        [
            {
                "task_id": "TASK-ROOT",
                "state": "failed",
            },
            {
                "task_id": "TASK-CHILD",
                "state": "queued",
            },
        ],
        project_id="PROJECT-1",
        db_path=db_path,
    )

    graph = result["items"][0]

    assert graph[
        "failure_blocked_tasks"
    ] == [
        "TASK-CHILD",
    ]

    assert "TASK-CHILD" not in (
        graph["runnable_tasks"]
    )


def test_task_graph_summary_filters_by_project(
    tmp_path,
):
    from factory.control_center import (
        _task_graph_summary,
    )
    from factory.task_graph_store import (
        create_task_graph,
    )

    db_path = tmp_path / "factory.db"

    create_task_graph(
        "GRAPH-P1",
        project_id="PROJECT-1",
        status="completed",
        db_path=db_path,
    )

    create_task_graph(
        "GRAPH-P2",
        project_id="PROJECT-2",
        status="failed",
        db_path=db_path,
    )

    result = _task_graph_summary(
        [],
        project_id="PROJECT-1",
        db_path=db_path,
    )

    assert result["total"] == 1
    assert result["completed"] == 1
    assert result["failed"] == 0

    assert [
        item["graph_id"]
        for item in result["items"]
    ] == [
        "GRAPH-P1",
    ]


def _setup_memory_project(
    db_path,
):
    from factory.database import (
        create_project,
        init_database,
    )

    init_database(
        db_path
    )

    create_project(
        "PROJECT-MEMORY",
        name="Control Center Memory Project",
        path=str(
            db_path.parent / "project"
        ),
        db_path=db_path,
    )


def test_project_memory_summary_without_project():
    from factory.control_center import (
        _project_memory_summary,
    )

    result = _project_memory_summary(
        None
    )

    assert result["available"] is False
    assert result["total"] == 0
    assert result["active"] == 0
    assert result["superseded"] == 0
    assert result["archived"] == 0


def test_project_memory_summary_counts_statuses(
    tmp_path,
):
    from factory.control_center import (
        _project_memory_summary,
    )
    from factory.project_memory_store import (
        create_project_memory,
        supersede_project_memory,
        update_project_memory,
    )

    db_path = tmp_path / "factory.db"

    _setup_memory_project(
        db_path
    )

    create_project_memory(
        "PROJECT-MEMORY",
        kind="decision",
        title="Old storage",
        content="Use JSON storage.",
        importance=40,
        memory_id="MEM-OLD",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-MEMORY",
        kind="decision",
        title="New storage",
        content="Use SQLite storage.",
        importance=90,
        memory_id="MEM-NEW",
        db_path=db_path,
    )

    create_project_memory(
        "PROJECT-MEMORY",
        kind="lesson",
        title="Archived lesson",
        content="Historical lesson.",
        importance=20,
        memory_id="MEM-ARCHIVED",
        db_path=db_path,
    )

    supersede_project_memory(
        "MEM-OLD",
        "MEM-NEW",
        db_path=db_path,
    )

    update_project_memory(
        "MEM-ARCHIVED",
        status="archived",
        db_path=db_path,
    )

    result = _project_memory_summary(
        "PROJECT-MEMORY",
        db_path=db_path,
    )

    assert result["available"] is True
    assert result["total"] == 3
    assert result["active"] == 1
    assert result["superseded"] == 1
    assert result["archived"] == 1
    assert result["protected_active"] == 1


def test_project_memory_summary_reports_retention_pressure(
    tmp_path,
    monkeypatch,
):
    import factory.control_center as control_center

    from factory.project_memory_store import (
        create_project_memory,
    )

    db_path = tmp_path / "factory.db"

    _setup_memory_project(
        db_path
    )

    monkeypatch.setattr(
        control_center,
        "DEFAULT_MAX_ACTIVE_MEMORIES",
        2,
    )

    for index in range(2):
        create_project_memory(
            "PROJECT-MEMORY",
            kind="fact",
            title=f"Fact {index}",
            content=f"Fact content {index}.",
            importance=50,
            memory_id=f"MEM-{index}",
            db_path=db_path,
        )

    result = (
        control_center
        ._project_memory_summary(
            "PROJECT-MEMORY",
            db_path=db_path,
        )
    )

    assert result["active"] == 2
    assert result["max_active"] == 2

    assert (
        result["retention_pressure"]
        is True
    )


def test_project_memory_summary_recent_is_bounded(
    tmp_path,
):
    from factory.control_center import (
        _project_memory_summary,
    )
    from factory.project_memory_store import (
        create_project_memory,
    )

    db_path = tmp_path / "factory.db"

    _setup_memory_project(
        db_path
    )

    for index in range(7):
        create_project_memory(
            "PROJECT-MEMORY",
            kind="fact",
            title=f"Recent fact {index}",
            content=(
                f"Recent fact content {index}."
            ),
            memory_id=f"MEM-RECENT-{index}",
            db_path=db_path,
        )

    result = _project_memory_summary(
        "PROJECT-MEMORY",
        db_path=db_path,
    )

    assert len(
        result["recent"]
    ) == 5

    for item in result["recent"]:
        assert "memory_id" in item
        assert "title" in item
        assert "status" in item

        # Dashboard summary must not expose
        # the full memory body.
        assert "content" not in item


def _healthy_control_center_inputs():
    return {
        "system": {
            "memory": {
                "used_percent": 40.0,
            },
            "disk": {
                "used_percent": 50.0,
            },
        },
        "services": {
            "docker": {
                "installed": True,
                "online": True,
            },
        },
        "tasks": {
            "failed": 0,
        },
        "providers": {
            "available": True,
            "total": 2,
            "healthy": 2,
            "unavailable": 0,
        },
        "agents": {
            "available": True,
            "total": 10,
            "ready": 10,
        },
        "task_graphs": {
            "failed": 0,
            "blocked": 0,
        },
        "project_memory": {
            "retention_pressure": False,
        },
    }


def test_health_summary_is_healthy_without_issues():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["status"] == "healthy"
    assert result["issue_count"] == 0
    assert result["critical_count"] == 0
    assert result["warning_count"] == 0
    assert result["issues"] == []


def test_health_summary_reports_warnings():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    data["system"]["memory"][
        "used_percent"
    ] = 90.0

    data["services"]["docker"] = {
        "installed": True,
        "online": False,
    }

    data["tasks"]["failed"] = 1

    data["task_graphs"]["blocked"] = 1

    data["project_memory"][
        "retention_pressure"
    ] = True

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["status"] == "warning"
    assert result["critical_count"] == 0
    assert result["warning_count"] == 5

    codes = {
        issue["code"]
        for issue in result["issues"]
    }

    assert codes == {
        "memory_pressure",
        "docker_offline",
        "failed_tasks",
        "blocked_task_graphs",
        "project_memory_retention_pressure",
    }


def test_health_summary_reports_critical_provider_failure():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    data["providers"] = {
        "available": True,
        "total": 2,
        "healthy": 0,
        "unavailable": 2,
    }

    data["agents"] = {
        "available": True,
        "total": 10,
        "ready": 0,
    }

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["status"] == "critical"
    assert result["critical_count"] == 2

    codes = {
        issue["code"]
        for issue in result["issues"]
    }

    assert "providers_unavailable" in codes
    assert "agents_unavailable" in codes


def test_health_summary_uses_highest_severity():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    data["system"]["disk"][
        "used_percent"
    ] = 96.0

    data["tasks"]["failed"] = 2

    data["providers"][
        "unavailable"
    ] = 1

    data["providers"][
        "healthy"
    ] = 1

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["status"] == "critical"
    assert result["critical_count"] == 1
    assert result["warning_count"] == 2

    codes = {
        issue["code"]
        for issue in result["issues"]
    }

    assert "disk_pressure_critical" in codes
    assert "failed_tasks" in codes
    assert "provider_degraded" in codes


def test_health_summary_warns_when_ollama_is_offline():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    data["services"]["ollama"] = {
        "installed": True,
        "online": False,
    }

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["status"] == "warning"

    codes = {
        issue["code"]
        for issue in result["issues"]
    }

    assert "ollama_offline" in codes


def test_health_summary_warns_when_git_is_unavailable():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    result = _health_summary(
        git={
            "available": False,
        },
        **data,
    )

    assert result["status"] == "warning"

    codes = {
        issue["code"]
        for issue in result["issues"]
    }

    assert "git_unavailable" in codes


def test_health_summary_issues_have_actions():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    data["tasks"]["failed"] = 1

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["issues"]

    for issue in result["issues"]:
        assert "action" in issue
        assert issue["action"]


def test_health_summary_healthy_is_ready_for_new_tasks():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["status"] == "healthy"
    assert result["ready_for_new_tasks"] is True
    assert result["top_issue"] is None


def test_health_summary_warning_allows_new_tasks():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    data["tasks"]["failed"] = 1

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["status"] == "warning"
    assert result["ready_for_new_tasks"] is True

    assert (
        result["top_issue"]["severity"]
        == "warning"
    )


def test_health_summary_critical_blocks_new_tasks():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    data["system"]["disk"][
        "used_percent"
    ] = 96.0

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["status"] == "critical"
    assert result["ready_for_new_tasks"] is False

    assert (
        result["top_issue"]["severity"]
        == "critical"
    )


def test_health_summary_prioritizes_critical_before_warning():
    from factory.control_center import (
        _health_summary,
    )

    data = (
        _healthy_control_center_inputs()
    )

    data["tasks"]["failed"] = 1

    data["providers"] = {
        "available": True,
        "total": 2,
        "healthy": 0,
        "unavailable": 2,
    }

    data["agents"] = {
        "available": True,
        "total": 10,
        "ready": 0,
    }

    result = _health_summary(
        git={
            "available": True,
        },
        **data,
    )

    assert result["status"] == "critical"

    assert (
        result["issues"][0]["severity"]
        == "critical"
    )

    assert (
        result["top_issue"]
        == result["issues"][0]
    )

    warning_indexes = [
        index
        for index, issue
        in enumerate(
            result["issues"]
        )
        if issue["severity"]
        == "warning"
    ]

    critical_indexes = [
        index
        for index, issue
        in enumerate(
            result["issues"]
        )
        if issue["severity"]
        == "critical"
    ]

    assert critical_indexes

    if warning_indexes:
        assert max(
            critical_indexes
        ) < min(
            warning_indexes
        )


def test_operational_summary_reports_dashboard_counts():
    from factory.control_center import (
        _operational_summary,
    )

    result = _operational_summary(
        tasks={
            "running": 3,
            "approval": 2,
            "failed": 1,
        },
        providers={
            "healthy": 2,
            "total": 3,
        },
        agents={
            "ready": 8,
            "total": 15,
        },
        task_graphs={
            "active": 4,
            "blocked": 1,
        },
        project_memory={
            "active": 12,
        },
        health={
            "status": "warning",
            "ready_for_new_tasks": True,
            "top_issue": {
                "severity": "warning",
                "code": "failed_tasks",
                "message": "One or more tasks have failed.",
                "action": "Inspect failed task logs.",
            },
        },
    )

    assert result["status"] == "warning"
    assert result["ready_for_new_tasks"] is True

    assert result["running_tasks"] == 3
    assert result["approval_tasks"] == 2
    assert result["failed_tasks"] == 1

    assert result["healthy_providers"] == 2
    assert result["total_providers"] == 3

    assert result["ready_agents"] == 8
    assert result["total_agents"] == 15

    assert result["active_graphs"] == 4
    assert result["blocked_graphs"] == 1
    assert result["active_memories"] == 12

    assert (
        result["top_issue"]["code"]
        == "failed_tasks"
    )


def test_operational_summary_healthy_has_no_top_issue():
    from factory.control_center import (
        _operational_summary,
    )

    result = _operational_summary(
        tasks={},
        providers={},
        agents={},
        task_graphs={},
        project_memory={},
        health={
            "status": "healthy",
            "ready_for_new_tasks": True,
            "top_issue": None,
        },
    )

    assert result["status"] == "healthy"
    assert result["ready_for_new_tasks"] is True
    assert result["top_issue"] is None

    assert result["running_tasks"] == 0
    assert result["healthy_providers"] == 0
    assert result["ready_agents"] == 0
    assert result["active_graphs"] == 0
    assert result["active_memories"] == 0


def test_operational_summary_reflects_critical_health():
    from factory.control_center import (
        _operational_summary,
    )

    result = _operational_summary(
        tasks={
            "running": 0,
            "approval": 0,
            "failed": 0,
        },
        providers={
            "healthy": 0,
            "total": 2,
        },
        agents={
            "ready": 0,
            "total": 10,
        },
        task_graphs={
            "active": 0,
            "blocked": 0,
        },
        project_memory={
            "active": 4,
        },
        health={
            "status": "critical",
            "ready_for_new_tasks": False,
            "top_issue": {
                "severity": "critical",
                "code": "providers_unavailable",
                "message": (
                    "No registered provider is "
                    "currently available."
                ),
                "action": (
                    "Check provider configuration."
                ),
            },
        },
    )

    assert result["status"] == "critical"
    assert result["ready_for_new_tasks"] is False

    assert (
        result["top_issue"]["severity"]
        == "critical"
    )

    assert (
        result["top_issue"]["code"]
        == "providers_unavailable"
    )


def test_control_center_snapshot_has_stable_top_level_contract(
    tmp_path,
):
    from factory.control_center import (
        get_control_center_status,
    )

    result = get_control_center_status(
        project_path=str(
            tmp_path
        ),
        tasks=(),
        project_id=None,
        use_cache=False,
    )

    expected_keys = {
        "generated_at",
        "system",
        "services",
        "git",
        "tasks",
        "providers",
        "agents",
        "task_graphs",
        "project_memory",
        "health",
        "operational",
    }

    assert expected_keys.issubset(
        result.keys()
    )

    assert {
        "status",
        "ready_for_new_tasks",
        "issue_count",
        "critical_count",
        "warning_count",
        "top_issue",
        "issues",
    }.issubset(
        result["health"].keys()
    )

    assert {
        "status",
        "ready_for_new_tasks",
        "running_tasks",
        "approval_tasks",
        "failed_tasks",
        "healthy_providers",
        "total_providers",
        "ready_agents",
        "total_agents",
        "active_graphs",
        "blocked_graphs",
        "active_memories",
        "top_issue",
    }.issubset(
        result["operational"].keys()
    )


def test_control_center_cache_does_not_leak_project_scoped_data(
    monkeypatch,
    tmp_path,
):
    import factory.control_center as cc

    cc._CACHE.clear()

    graph_calls = []
    memory_calls = []

    def fake_graph_summary(
        tasks,
        *,
        project_id=None,
        db_path=None,
    ):
        graph_calls.append(
            project_id
        )

        return {
            "available": True,
            "total": 1,
            "active": 1,
            "blocked": 0,
            "completed": 0,
            "failed": 0,
            "runnable_tasks": 0,
            "items": [
                {
                    "project_id": project_id,
                }
            ],
        }

    def fake_memory_summary(
        project_id,
        *,
        db_path=None,
    ):
        memory_calls.append(
            project_id
        )

        return {
            "available": True,
            "total": 1,
            "active": 1,
            "superseded": 0,
            "archived": 0,
            "protected_active": 0,
            "max_active": 100,
            "retention_pressure": False,
            "recent": [
                {
                    "project_id": project_id,
                }
            ],
        }

    monkeypatch.setattr(
        cc,
        "_task_graph_summary",
        fake_graph_summary,
    )

    monkeypatch.setattr(
        cc,
        "_project_memory_summary",
        fake_memory_summary,
    )

    project_path = str(
        tmp_path
    )

    first = cc.get_control_center_status(
        project_path=project_path,
        tasks=(),
        project_id="PROJECT-A",
        use_cache=True,
    )

    second = cc.get_control_center_status(
        project_path=project_path,
        tasks=(),
        project_id="PROJECT-B",
        use_cache=True,
    )

    assert (
        first["task_graphs"]["items"][0][
            "project_id"
        ]
        == "PROJECT-A"
    )

    assert (
        second["task_graphs"]["items"][0][
            "project_id"
        ]
        == "PROJECT-B"
    )

    assert (
        first["project_memory"]["recent"][0][
            "project_id"
        ]
        == "PROJECT-A"
    )

    assert (
        second["project_memory"]["recent"][0][
            "project_id"
        ]
        == "PROJECT-B"
    )

    assert graph_calls == [
        "PROJECT-A",
        "PROJECT-B",
    ]

    assert memory_calls == [
        "PROJECT-A",
        "PROJECT-B",
    ]

    cc._CACHE.clear()
