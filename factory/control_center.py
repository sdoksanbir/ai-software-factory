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


_CACHE: dict[str, Any] = {
    "timestamp": 0.0,
    "value": None,
}

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
    percent = None

    try:
        import psutil  # type: ignore

        percent = float(
            psutil.cpu_percent(interval=None)
        )

    except ImportError:
        pass

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


def get_control_center_status(
    *,
    project_path: str,
    tasks: Iterable[Any] = (),
    use_cache: bool = True,
) -> dict[str, Any]:
    now = time.monotonic()

    cached_value = _CACHE.get("value")
    cached_at = float(
        _CACHE.get("timestamp", 0.0)
    )

    if (
        use_cache
        and cached_value is not None
        and now - cached_at < CACHE_SECONDS
    ):
        result = dict(cached_value)
        result["tasks"] = _task_summary(tasks)
        return result

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
    }

    _CACHE["timestamp"] = now
    _CACHE["value"] = result

    return result
