from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable

from factory.database import DEFAULT_DB_PATH
from factory.task_graph_store import (
    list_blocked_tasks,
    list_failure_blocked_tasks,
    list_runnable_tasks,
    list_task_graphs,
)
from factory.project_memory_store import (
    DEFAULT_MAX_ACTIVE_MEMORIES,
    DEFAULT_PROTECTED_IMPORTANCE,
    list_project_memories,
)

from factory.agents.runtime import (
    build_default_agent_descriptors,
)


_CACHE: dict[str, dict[str, Any]] = {}

CACHE_SECONDS = 5.0


def _run_command(
    command: list[str],
    *,
    cwd: str | None = None,
    timeout: float = 3.0,
) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        output = (
            result.stdout.strip()
            or result.stderr.strip()
        )

        return result.returncode == 0, output

    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        OSError,
    ) as exc:
        return False, str(exc)


def _memory_status() -> dict[str, Any]:
    try:
        import psutil  # type: ignore

        memory = psutil.virtual_memory()

        return {
            "available": True,
            "total_bytes": int(memory.total),
            "available_bytes": int(memory.available),
            "used_percent": float(memory.percent),
        }

    except ImportError:
        pass

    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(
                MEMORYSTATUSEX
            )

            ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(status)
            )

            return {
                "available": True,
                "total_bytes": int(status.ullTotalPhys),
                "available_bytes": int(status.ullAvailPhys),
                "used_percent": float(status.dwMemoryLoad),
            }

        except Exception:
            pass

    return {
        "available": False,
        "total_bytes": None,
        "available_bytes": None,
        "used_percent": None,
    }


def _cpu_status() -> dict[str, Any]:
    percent: float | None = None

    try:
        import psutil  # type: ignore

        percent = float(
            psutil.cpu_percent(interval=0.15)
        )

    except ImportError:
        pass
    except Exception:
        percent = None

    if percent is None and os.name == "nt":
        try:
            import ctypes

            class FILETIME(ctypes.Structure):
                _fields_ = [
                    ("dwLowDateTime", ctypes.c_uint32),
                    ("dwHighDateTime", ctypes.c_uint32),
                ]

            def to_int(value: FILETIME) -> int:
                return (
                    int(value.dwHighDateTime) << 32
                ) | int(value.dwLowDateTime)

            def sample() -> tuple[int, int, int]:
                idle = FILETIME()
                kernel = FILETIME()
                user = FILETIME()

                ok = ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                )

                if not ok:
                    raise OSError("GetSystemTimes failed")

                return (
                    to_int(idle),
                    to_int(kernel),
                    to_int(user),
                )

            idle_1, kernel_1, user_1 = sample()
            time.sleep(0.15)
            idle_2, kernel_2, user_2 = sample()

            idle_delta = idle_2 - idle_1
            kernel_delta = kernel_2 - kernel_1
            user_delta = user_2 - user_1
            total_delta = kernel_delta + user_delta

            if total_delta > 0:
                busy_delta = total_delta - idle_delta
                percent = (
                    busy_delta
                    / total_delta
                    * 100.0
                )

        except Exception:
            percent = None

    if percent is not None:
        percent = round(
            max(0.0, min(100.0, percent)),
            1,
        )

    return {
        "logical_count": os.cpu_count(),
        "used_percent": percent,
    }


def _disk_status(
    project_path: str,
) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(project_path)

        used = usage.total - usage.free

        used_percent = (
            (used / usage.total) * 100
            if usage.total
            else 0.0
        )

        return {
            "total_bytes": usage.total,
            "used_bytes": used,
            "free_bytes": usage.free,
            "used_percent": round(
                used_percent,
                1,
            ),
        }

    except OSError:
        return {
            "total_bytes": None,
            "used_bytes": None,
            "free_bytes": None,
            "used_percent": None,
        }


def _docker_status() -> dict[str, Any]:
    executable = shutil.which("docker")

    if executable is None:
        return {
            "installed": False,
            "online": False,
            "version": None,
        }

    ok, output = _run_command(
        [
            executable,
            "info",
            "--format",
            "{{json .ServerVersion}}",
        ],
    )

    version = None

    if ok and output:
        try:
            version = json.loads(output)
        except json.JSONDecodeError:
            version = output.strip('"')

    return {
        "installed": True,
        "online": ok,
        "version": version,
    }


def _ollama_status() -> dict[str, Any]:
    url = "http://127.0.0.1:11434/api/tags"

    try:
        with urllib.request.urlopen(
            url,
            timeout=2.0,
        ) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )

        models = []

        for item in payload.get("models", []):
            name = (
                item.get("name")
                or item.get("model")
            )

            if not name:
                continue

            models.append(
                {
                    "name": name,
                    "size": item.get("size"),
                    "modified_at": item.get(
                        "modified_at"
                    ),
                }
            )

        return {
            "installed": shutil.which(
                "ollama"
            ) is not None,
            "online": True,
            "models": models,
        }

    except Exception:
        return {
            "installed": shutil.which(
                "ollama"
            ) is not None,
            "online": False,
            "models": [],
        }


def _git_status(
    project_path: str,
) -> dict[str, Any]:
    ok_branch, branch = _run_command(
        [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "HEAD",
        ],
        cwd=project_path,
    )

    ok_status, status = _run_command(
        [
            "git",
            "status",
            "--porcelain",
        ],
        cwd=project_path,
    )

    ok_commit, commit = _run_command(
        [
            "git",
            "rev-parse",
            "--short",
            "HEAD",
        ],
        cwd=project_path,
    )

    return {
        "available": (
            ok_branch
            and ok_status
        ),
        "branch": (
            branch
            if ok_branch
            else None
        ),
        "commit": (
            commit
            if ok_commit
            else None
        ),
        "clean": (
            not bool(status)
            if ok_status
            else None
        ),
    }


def _provider_summary(
    provider_registry: Any | None,
) -> dict[str, Any]:
    if provider_registry is None:
        return {
            "available": False,
            "total": 0,
            "healthy": 0,
            "unavailable": 0,
            "unknown": 0,
            "items": [],
        }

    try:
        health_items = (
            provider_registry
            .runtime_health_all(
                timeout_seconds=2.0,
            )
        )

    except Exception as exc:
        return {
            "available": False,
            "total": 0,
            "healthy": 0,
            "unavailable": 0,
            "unknown": 0,
            "items": [],
            "error": str(exc),
        }

    items = []

    for health in health_items:
        if hasattr(
            health,
            "as_dict",
        ):
            item = dict(
                health.as_dict()
            )
        else:
            item = {
                "provider_name": getattr(
                    health,
                    "provider_name",
                    None,
                ),
            }

        raw_status = getattr(
            health,
            "status",
            "unknown",
        )

        status_value = getattr(
            raw_status,
            "value",
            raw_status,
        )

        item["status"] = str(
            status_value
        ).strip().lower()

        items.append(
            item
        )

    return {
        "available": True,
        "total": len(items),
        "healthy": sum(
            item.get("status")
            == "available"
            for item in items
        ),
        "unavailable": sum(
            item.get("status")
            == "unavailable"
            for item in items
        ),
        "unknown": sum(
            item.get("status")
            not in {
                "available",
                "unavailable",
            }
            for item in items
        ),
        "items": items,
    }


def _agent_summary(
    provider_registry: Any | None,
    provider_summary: dict[str, Any],
) -> dict[str, Any]:
    if provider_registry is None:
        return {
            "available": False,
            "total": 0,
            "ready": 0,
            "unavailable": 0,
            "unknown": 0,
            "items": [],
        }

    try:
        descriptors = (
            build_default_agent_descriptors(
                provider_registry
            )
        )

    except Exception as exc:
        return {
            "available": False,
            "total": 0,
            "ready": 0,
            "unavailable": 0,
            "unknown": 0,
            "items": [],
            "error": str(exc),
        }

    provider_states = {
        str(
            item.get(
                "provider_name",
                "",
            )
        ): str(
            item.get(
                "status",
                "unknown",
            )
        ).strip().lower()
        for item in provider_summary.get(
            "items",
            [],
        )
    }

    items = []

    for descriptor in descriptors:
        provider_name = str(
            descriptor.provider_name
        )

        provider_status = (
            provider_states.get(
                provider_name,
                "unknown",
            )
        )

        capabilities = sorted(
            getattr(
                capability,
                "value",
                str(capability),
            )
            for capability in (
                descriptor.capabilities
            )
        )

        items.append(
            {
                "name": descriptor.name,
                "provider_name": (
                    provider_name
                ),
                "capabilities": capabilities,
                "provider_status": (
                    provider_status
                ),
                "ready": (
                    provider_status
                    == "available"
                ),
            }
        )

    return {
        "available": True,
        "total": len(items),
        "ready": sum(
            item["ready"]
            for item in items
        ),
        "unavailable": sum(
            item["provider_status"]
            == "unavailable"
            for item in items
        ),
        "unknown": sum(
            item["provider_status"]
            not in {
                "available",
                "unavailable",
            }
            for item in items
        ),
        "items": items,
    }


def _task_id(
    task: Any,
) -> str | None:
    if isinstance(task, dict):
        value = task.get("task_id")
    else:
        value = getattr(
            task,
            "task_id",
            None,
        )

    if value is None:
        return None

    normalized = str(
        value
    ).strip()

    return normalized or None


def _task_state_map(
    tasks: Iterable[Any],
) -> dict[str, str]:
    result: dict[str, str] = {}

    for task in tasks:
        task_id = _task_id(
            task
        )

        if task_id is None:
            continue

        state = _task_state(
            task
        )

        result[task_id] = (
            str(state or "")
            .strip()
            .lower()
        )

    return result


def _project_memory_summary(
    project_id: str | None,
    *,
    db_path=DEFAULT_DB_PATH,
) -> dict[str, Any]:
    normalized_project_id = str(
        project_id or ""
    ).strip()

    if not normalized_project_id:
        return {
            "available": False,
            "total": 0,
            "active": 0,
            "superseded": 0,
            "archived": 0,
            "protected_active": 0,
            "max_active": (
                DEFAULT_MAX_ACTIVE_MEMORIES
            ),
            "retention_pressure": False,
            "recent": [],
        }

    try:
        memories = list_project_memories(
            normalized_project_id,
            status=None,
            db_path=db_path,
        )

    except Exception as exc:
        return {
            "available": False,
            "total": 0,
            "active": 0,
            "superseded": 0,
            "archived": 0,
            "protected_active": 0,
            "max_active": (
                DEFAULT_MAX_ACTIVE_MEMORIES
            ),
            "retention_pressure": False,
            "recent": [],
            "error": str(exc),
        }

    active = [
        memory
        for memory in memories
        if str(
            memory.get(
                "status",
                ""
            )
        ).strip().lower()
        == "active"
    ]

    protected_active = [
        memory
        for memory in active
        if int(
            memory.get(
                "importance",
                0,
            )
        )
        >= DEFAULT_PROTECTED_IMPORTANCE
    ]

    recent = sorted(
        memories,
        key=lambda memory: (
            str(
                memory.get(
                    "created_at",
                    ""
                )
                or ""
            ),
            str(
                memory.get(
                    "memory_id",
                    ""
                )
            ),
        ),
        reverse=True,
    )[:5]

    return {
        "available": True,
        "total": len(memories),
        "active": len(active),
        "superseded": sum(
            str(
                memory.get(
                    "status",
                    ""
                )
            ).strip().lower()
            == "superseded"
            for memory in memories
        ),
        "archived": sum(
            str(
                memory.get(
                    "status",
                    ""
                )
            ).strip().lower()
            == "archived"
            for memory in memories
        ),
        "protected_active": len(
            protected_active
        ),
        "max_active": (
            DEFAULT_MAX_ACTIVE_MEMORIES
        ),
        "retention_pressure": (
            len(active)
            >= DEFAULT_MAX_ACTIVE_MEMORIES
        ),
        "recent": [
            {
                "memory_id": memory.get(
                    "memory_id"
                ),
                "kind": memory.get(
                    "kind"
                ),
                "title": memory.get(
                    "title"
                ),
                "status": memory.get(
                    "status"
                ),
                "importance": memory.get(
                    "importance"
                ),
                "created_at": memory.get(
                    "created_at"
                ),
            }
            for memory in recent
        ],
    }


def _task_graph_summary(
    tasks: Iterable[Any],
    *,
    project_id: str | None = None,
    db_path=DEFAULT_DB_PATH,
) -> dict[str, Any]:
    task_states = _task_state_map(
        tasks
    )

    try:
        graphs = list_task_graphs(
            db_path=db_path
        )

    except Exception as exc:
        return {
            "available": False,
            "total": 0,
            "active": 0,
            "blocked": 0,
            "completed": 0,
            "failed": 0,
            "runnable_tasks": 0,
            "items": [],
            "error": str(exc),
        }

    normalized_project_id = (
        str(project_id).strip()
        if project_id is not None
        else None
    )

    if normalized_project_id:
        graphs = [
            graph
            for graph in graphs
            if str(
                graph.get(
                    "project_id"
                )
                or ""
            ).strip()
            == normalized_project_id
        ]

    items = []

    for graph in graphs:
        graph_id = str(
            graph["graph_id"]
        )

        try:
            runnable = list_runnable_tasks(
                graph_id,
                task_states,
                db_path=db_path,
            )

            blocked = list_blocked_tasks(
                graph_id,
                task_states,
                db_path=db_path,
            )

            failure_blocked = (
                list_failure_blocked_tasks(
                    graph_id,
                    task_states,
                    db_path=db_path,
                )
            )

            error = None

        except Exception as exc:
            runnable = []
            blocked = []
            failure_blocked = []
            error = str(exc)

        item = dict(
            graph
        )

        item.update(
            {
                "runnable_tasks": runnable,
                "blocked_tasks": blocked,
                "failure_blocked_tasks": (
                    failure_blocked
                ),
            }
        )

        if error is not None:
            item["error"] = error

        items.append(
            item
        )

    def graph_status(
        item: dict[str, Any],
    ) -> str:
        return str(
            item.get(
                "status",
                "",
            )
        ).strip().lower()

    return {
        "available": True,
        "total": len(items),
        "active": sum(
            graph_status(item)
            in {
                "pending",
                "running",
            }
            for item in items
        ),
        "blocked": sum(
            bool(
                item.get(
                    "blocked_tasks"
                )
            )
            for item in items
        ),
        "completed": sum(
            graph_status(item)
            == "completed"
            for item in items
        ),
        "failed": sum(
            graph_status(item)
            == "failed"
            for item in items
        ),
        "runnable_tasks": sum(
            len(
                item.get(
                    "runnable_tasks",
                    []
                )
            )
            for item in items
        ),
        "items": items,
    }


def _task_state(
    task: Any,
) -> str | None:
    if isinstance(task, dict):
        value = task.get("state")
    else:
        value = getattr(
            task,
            "state",
            None,
        )

    if value is None:
        return None

    return str(value)


def _task_summary(
    tasks: Iterable[Any],
) -> dict[str, int]:
    states = [
        _task_state(task)
        for task in tasks
    ]

    return {
        "total": len(states),
        "running": sum(
            state in {
                "queued",
                "running",
            }
            for state in states
        ),
        "approval": sum(
            state == "ready_for_approval"
            for state in states
        ),
        "failed": sum(
            state == "failed"
            for state in states
        ),
        "approved": sum(
            state == "approved"
            for state in states
        ),
    }


def _health_summary(
    *,
    system: dict[str, Any],
    services: dict[str, Any],
    git: dict[str, Any],
    tasks: dict[str, Any],
    providers: dict[str, Any],
    agents: dict[str, Any],
    task_graphs: dict[str, Any],
    project_memory: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    actions = {
        "memory_pressure_critical": (
            "Close unnecessary processes or "
            "reduce concurrent agent workloads."
        ),
        "memory_pressure": (
            "Review memory usage before starting "
            "additional concurrent agents."
        ),
        "disk_pressure_critical": (
            "Free project disk space before "
            "starting additional tasks."
        ),
        "disk_pressure": (
            "Review worktrees, logs and cached "
            "artifacts to free disk space."
        ),
        "docker_offline": (
            "Start Docker if sandboxed execution "
            "is required."
        ),
        "ollama_offline": (
            "Start the Ollama service before "
            "using local Ollama models."
        ),
        "git_unavailable": (
            "Verify that the project path is a "
            "valid Git repository and Git is installed."
        ),
        "providers_unavailable": (
            "Check provider installation, "
            "configuration and authentication."
        ),
        "provider_degraded": (
            "Review unavailable providers before "
            "routing tasks to them."
        ),
        "agents_unavailable": (
            "Restore at least one healthy provider "
            "so an agent can become ready."
        ),
        "failed_tasks": (
            "Inspect failed task logs and retry "
            "only after the failure cause is resolved."
        ),
        "failed_task_graphs": (
            "Inspect failed graph nodes and their "
            "dependency chain."
        ),
        "blocked_task_graphs": (
            "Resolve pending or failed dependencies "
            "blocking graph execution."
        ),
        "project_memory_retention_pressure": (
            "Review active project memories and "
            "archive or supersede stale entries."
        ),
    }

    def add_issue(
        severity: str,
        code: str,
        message: str,
    ) -> None:
        issues.append(
            {
                "severity": severity,
                "code": code,
                "message": message,
                "action": actions.get(
                    code
                ),
            }
        )

    memory = system.get(
        "memory",
        {},
    )

    memory_percent = memory.get(
        "used_percent"
    )

    if isinstance(
        memory_percent,
        (int, float),
    ):
        if memory_percent >= 95:
            add_issue(
                "critical",
                "memory_pressure_critical",
                "System memory usage is at least 95%.",
            )

        elif memory_percent >= 85:
            add_issue(
                "warning",
                "memory_pressure",
                "System memory usage is at least 85%.",
            )

    disk = system.get(
        "disk",
        {},
    )

    disk_percent = disk.get(
        "used_percent"
    )

    if isinstance(
        disk_percent,
        (int, float),
    ):
        if disk_percent >= 95:
            add_issue(
                "critical",
                "disk_pressure_critical",
                "Project disk usage is at least 95%.",
            )

        elif disk_percent >= 85:
            add_issue(
                "warning",
                "disk_pressure",
                "Project disk usage is at least 85%.",
            )

    docker = services.get(
        "docker",
        {},
    )

    if (
        docker.get("installed")
        and not docker.get("online")
    ):
        add_issue(
            "warning",
            "docker_offline",
            "Docker is installed but unavailable.",
        )

    ollama = services.get(
        "ollama",
        {},
    )

    if (
        ollama.get("installed")
        and not ollama.get("online")
    ):
        add_issue(
            "warning",
            "ollama_offline",
            "Ollama is installed but unavailable.",
        )

    if git.get("available") is False:
        add_issue(
            "warning",
            "git_unavailable",
            "Git status could not be read for the project.",
        )

    if providers.get("available"):
        provider_total = int(
            providers.get(
                "total",
                0,
            )
        )

        provider_healthy = int(
            providers.get(
                "healthy",
                0,
            )
        )

        if (
            provider_total > 0
            and provider_healthy == 0
        ):
            add_issue(
                "critical",
                "providers_unavailable",
                "No registered provider is currently available.",
            )

        elif int(
            providers.get(
                "unavailable",
                0,
            )
        ) > 0:
            add_issue(
                "warning",
                "provider_degraded",
                "One or more providers are unavailable.",
            )

    if (
        agents.get("available")
        and int(
            agents.get(
                "total",
                0,
            )
        ) > 0
        and int(
            agents.get(
                "ready",
                0,
            )
        ) == 0
    ):
        add_issue(
            "critical",
            "agents_unavailable",
            "No agent is currently ready.",
        )

    if int(
        tasks.get(
            "failed",
            0,
        )
    ) > 0:
        add_issue(
            "warning",
            "failed_tasks",
            "One or more tasks have failed.",
        )

    if int(
        task_graphs.get(
            "failed",
            0,
        )
    ) > 0:
        add_issue(
            "warning",
            "failed_task_graphs",
            "One or more task graphs have failed.",
        )

    if int(
        task_graphs.get(
            "blocked",
            0,
        )
    ) > 0:
        add_issue(
            "warning",
            "blocked_task_graphs",
            "One or more task graphs contain blocked tasks.",
        )

    if project_memory.get(
        "retention_pressure"
    ):
        add_issue(
            "warning",
            "project_memory_retention_pressure",
            "Project memory active-item limit has been reached.",
        )

    severity_rank = {
        "healthy": 0,
        "warning": 1,
        "critical": 2,
    }

    status = "healthy"

    for issue in issues:
        severity = str(
            issue["severity"]
        )

        if (
            severity_rank.get(
                severity,
                0,
            )
            > severity_rank[status]
        ):
            status = severity

    issue_priority = {
        "critical": 0,
        "warning": 1,
    }

    issues.sort(
        key=lambda issue: (
            issue_priority.get(
                str(
                    issue.get(
                        "severity",
                        ""
                    )
                ),
                99,
            ),
            str(
                issue.get(
                    "code",
                    ""
                )
            ),
        )
    )

    critical_count = sum(
        issue["severity"]
        == "critical"
        for issue in issues
    )

    warning_count = sum(
        issue["severity"]
        == "warning"
        for issue in issues
    )

    return {
        "status": status,
        "ready_for_new_tasks": (
            status != "critical"
        ),
        "issue_count": len(
            issues
        ),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "top_issue": (
            dict(issues[0])
            if issues
            else None
        ),
        "issues": issues,
    }


def _operational_summary(
    *,
    tasks: dict[str, Any],
    providers: dict[str, Any],
    agents: dict[str, Any],
    task_graphs: dict[str, Any],
    project_memory: dict[str, Any],
    health: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": health.get(
            "status",
            "healthy",
        ),
        "ready_for_new_tasks": bool(
            health.get(
                "ready_for_new_tasks",
                True,
            )
        ),
        "running_tasks": int(
            tasks.get(
                "running",
                0,
            )
        ),
        "approval_tasks": int(
            tasks.get(
                "approval",
                0,
            )
        ),
        "failed_tasks": int(
            tasks.get(
                "failed",
                0,
            )
        ),
        "healthy_providers": int(
            providers.get(
                "healthy",
                0,
            )
        ),
        "total_providers": int(
            providers.get(
                "total",
                0,
            )
        ),
        "ready_agents": int(
            agents.get(
                "ready",
                0,
            )
        ),
        "total_agents": int(
            agents.get(
                "total",
                0,
            )
        ),
        "active_graphs": int(
            task_graphs.get(
                "active",
                0,
            )
        ),
        "blocked_graphs": int(
            task_graphs.get(
                "blocked",
                0,
            )
        ),
        "active_memories": int(
            project_memory.get(
                "active",
                0,
            )
        ),
        "top_issue": (
            dict(
                health["top_issue"]
            )
            if health.get(
                "top_issue"
            )
            else None
        ),
    }


def get_control_center_status(
    *,
    project_path: str,
    tasks: Iterable[Any] = (),
    provider_registry: Any | None = None,
    project_id: str | None = None,
    db_path=DEFAULT_DB_PATH,
    use_cache: bool = True,
) -> dict[str, Any]:
    task_items = tuple(
        tasks
    )

    now = time.monotonic()

    cache_key = os.path.normcase(
        os.path.abspath(project_path)
    )

    cache_entry = _CACHE.get(
        cache_key,
        {},
    )

    cached_value = cache_entry.get(
        "value"
    )

    cached_at = float(
        cache_entry.get(
            "timestamp",
            0.0,
        )
    )

    if (
        use_cache
        and cached_value is not None
        and now - cached_at < CACHE_SECONDS
    ):
        result = dict(cached_value)
        result["tasks"] = _task_summary(task_items)

        providers = _provider_summary(
            provider_registry
        )

        result["providers"] = providers
        result["agents"] = _agent_summary(
            provider_registry,
            providers,
        )

        result["task_graphs"] = (
            _task_graph_summary(
                task_items,
                project_id=project_id,
                db_path=db_path,
            )
        )

        result["project_memory"] = (
            _project_memory_summary(
                project_id,
                db_path=db_path,
            )
        )

        result["health"] = _health_summary(
            system=result.get(
                "system",
                {},
            ),
            services=result.get(
                "services",
                {},
            ),
            git=result.get(
                "git",
                {},
            ),
            tasks=result["tasks"],
            providers=result["providers"],
            agents=result["agents"],
            task_graphs=result["task_graphs"],
            project_memory=(
                result["project_memory"]
            ),
        )

        result["operational"] = (
            _operational_summary(
                tasks=result["tasks"],
                providers=result[
                    "providers"
                ],
                agents=result["agents"],
                task_graphs=result[
                    "task_graphs"
                ],
                project_memory=result[
                    "project_memory"
                ],
                health=result["health"],
            )
        )

        return result

    providers = _provider_summary(
        provider_registry
    )

    result = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "system": {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "python_version": platform.python_version(),
            "cpu": _cpu_status(),
            "memory": _memory_status(),
            "disk": _disk_status(
                project_path
            ),
        },
        "services": {
            "docker": _docker_status(),
            "ollama": _ollama_status(),
        },
        "git": _git_status(
            project_path
        ),
        "tasks": _task_summary(
            tasks
        ),
        "providers": providers,
        "agents": _agent_summary(
            provider_registry,
            providers,
        ),
        "task_graphs": _task_graph_summary(
            task_items,
            project_id=project_id,
            db_path=db_path,
        ),
        "project_memory": (
            _project_memory_summary(
                project_id,
                db_path=db_path,
            )
        ),
    }

    result["health"] = _health_summary(
        system=result["system"],
        services=result["services"],
        git=result["git"],
        tasks=result["tasks"],
        providers=result["providers"],
        agents=result["agents"],
        task_graphs=result["task_graphs"],
        project_memory=result[
            "project_memory"
        ],
    )

    result["operational"] = (
        _operational_summary(
            tasks=result["tasks"],
            providers=result["providers"],
            agents=result["agents"],
            task_graphs=result[
                "task_graphs"
            ],
            project_memory=result[
                "project_memory"
            ],
            health=result["health"],
        )
    )

    _CACHE[cache_key] = {
        "timestamp": now,
        "value": result,
    }

    return result
