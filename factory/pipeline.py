from __future__ import annotations

from typing import Any, Iterable


PIPELINE_STAGES = [
    {
        "id": "task",
        "label": "G\u00f6rev Al\u0131nd\u0131",
    },
    {
        "id": "worktree",
        "label": "Worktree",
    },
    {
        "id": "repo_analysis",
        "label": "Repo Analizi",
    },
    {
        "id": "model",
        "label": "Local Model",
    },
    {
        "id": "patch",
        "label": "Patch",
    },
    {
        "id": "tests",
        "label": "Docker Test",
    },
    {
        "id": "diff",
        "label": "Diff",
    },
    {
        "id": "approval",
        "label": "\u0130nsan Onay\u0131",
    },
]


def _value(
    task: Any,
    key: str,
    default: Any = None,
) -> Any:
    if isinstance(task, dict):
        return task.get(key, default)

    return getattr(
        task,
        key,
        default,
    )


def _contains(
    logs: list[str],
    *needles: str,
) -> bool:
    lowered = [
        item.lower()
        for item in logs
    ]

    return any(
        needle.lower() in line
        for needle in needles
        for line in lowered
    )


def build_task_pipeline(
    task: Any,
    logs: Iterable[str] = (),
) -> dict[str, Any]:
    log_items = [
        str(item)
        for item in logs
    ]

    task_state = str(
        _value(
            task,
            "state",
            "queued",
        )
    )

    stages = [
        {
            "id": stage["id"],
            "label": stage["label"],
            "status": "pending",
        }
        for stage in PIPELINE_STAGES
    ]

    by_id = {
        stage["id"]: stage
        for stage in stages
    }

    # A task returned by the API has already
    # passed the "task received" stage.
    by_id["task"]["status"] = "success"

    worktree_ready = _contains(
        log_items,
        "worktree haz?rland?",
        "worktree hazirlandi",
    )

    model_started = _contains(
        log_items,
        "model kod ?retiyor",
        "model kod uretiyor",
        "model yan?t? al?nd?",
        "model yaniti alindi",
    )

    model_completed = _contains(
        log_items,
        "model yan?t? al?nd?",
        "model yaniti alindi",
    )

    patch_completed = _contains(
        log_items,
        "patch do?ruland?",
        "patch dogrulandi",
        "patch uyguland?",
        "patch uygulandi",
    )

    tests_started = _contains(
        log_items,
        "testler ?al??t?r?l?yor",
        "testler calistiriliyor",
    )

    tests_passed = _contains(
        log_items,
        "testler ba?ar?l?",
        "testler basarili",
    )

    tests_failed = _contains(
        log_items,
        "testler ba?ar?s?z",
        "testler basarisiz",
        "test failed",
        "tests failed",
    )

    # Worktree
    if worktree_ready or model_started:
        by_id["worktree"]["status"] = "success"
    elif task_state == "running":
        by_id["worktree"]["status"] = "active"

    # Repo analysis is complete by the time
    # the model begins generation.
    if model_started:
        by_id["repo_analysis"]["status"] = "success"
    elif worktree_ready:
        by_id["repo_analysis"]["status"] = "active"

    # Model
    if model_completed:
        by_id["model"]["status"] = "success"
    elif model_started:
        by_id["model"]["status"] = "active"

    # Patch
    if patch_completed or tests_started:
        by_id["patch"]["status"] = "success"
    elif model_completed:
        by_id["patch"]["status"] = "active"

    # Tests
    if tests_failed:
        by_id["tests"]["status"] = "failed"
    elif tests_passed:
        by_id["tests"]["status"] = "success"
    elif tests_started:
        by_id["tests"]["status"] = "active"

    terminal_diff_states = {
        "ready_for_approval",
        "approved",
        "rejected",
    }

    if task_state in terminal_diff_states:
        by_id["diff"]["status"] = "success"
    elif tests_passed:
        by_id["diff"]["status"] = "active"

    # Human approval
    if task_state == "ready_for_approval":
        by_id["approval"]["status"] = "waiting"

    elif task_state == "approved":
        by_id["approval"]["status"] = "success"

    elif task_state == "rejected":
        by_id["approval"]["status"] = "rejected"

    # Generic failed-task fallback:
    # mark the first unfinished active/pending stage.
    if task_state == "failed":
        if not any(
            stage["status"] == "failed"
            for stage in stages
        ):
            candidate = next(
                (
                    stage
                    for stage in stages
                    if stage["status"]
                    in {
                        "active",
                        "pending",
                    }
                ),
                None,
            )

            if candidate is not None:
                candidate["status"] = "failed"

    current_stage = None

    for stage in stages:
        if stage["status"] in {
            "active",
            "waiting",
            "failed",
        }:
            current_stage = stage["id"]
            break

    if current_stage is None:
        unfinished = next(
            (
                stage
                for stage in stages
                if stage["status"] == "pending"
            ),
            None,
        )

        if unfinished is not None:
            current_stage = unfinished["id"]
        else:
            current_stage = "approval"

    completed = sum(
        stage["status"]
        in {
            "success",
            "rejected",
        }
        for stage in stages
    )

    progress_percent = round(
        (completed / len(stages)) * 100
    )

    if task_state == "ready_for_approval":
        progress_percent = max(
            progress_percent,
            88,
        )

    if task_state in {
        "approved",
        "rejected",
    }:
        progress_percent = 100

    return {
        "task_id": _value(
            task,
            "task_id",
        ),
        "task_state": task_state,
        "current_stage": current_stage,
        "progress_percent": progress_percent,
        "stages": stages,
    }
