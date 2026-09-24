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


_TR_TRANSLATION = str.maketrans({
    305: "i",   # dotless i
    304: "I",   # dotted capital I
    351: "s",
    350: "S",
    287: "g",
    286: "G",
    252: "u",
    220: "U",
    246: "o",
    214: "O",
    231: "c",
    199: "C",
})


def _value(
    task: Any,
    key: str,
    default: Any = None,
) -> Any:
    if isinstance(task, dict):
        return task.get(key, default)

    return getattr(task, key, default)


def _normalize(value: str) -> str:
    return value.translate(
        _TR_TRANSLATION
    ).lower()


def _contains(
    logs: list[str],
    *needles: str,
) -> bool:
    normalized_logs = [
        _normalize(item)
        for item in logs
    ]

    return any(
        _normalize(needle) in line
        for needle in needles
        for line in normalized_logs
    )


def _mark_success_through(
    by_id: dict[str, dict[str, str]],
    stage_id: str,
) -> None:
    for stage in PIPELINE_STAGES:
        current_id = stage["id"]

        if current_id == "approval":
            break

        by_id[current_id]["status"] = "success"

        if current_id == stage_id:
            break




EXECUTE_PIPELINE_STAGES = [
    {
        "id": "task",
        "label": "G\u00f6rev Al\u0131nd\u0131",
    },
    {
        "id": "action_prepare",
        "label": "Eylem Haz\u0131rl\u0131\u011f\u0131",
    },
    {
        "id": "action_execute",
        "label": "Yerel \u00c7al\u0131\u015ft\u0131rma",
    },
    {
        "id": "completed",
        "label": "Sonu\u00e7",
    },
]


READ_PIPELINE_STAGES = [
    {
        "id": "task",
        "label": "G\u00f6rev Al\u0131nd\u0131",
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
        "id": "completed",
        "label": "Tamamland\u0131",
    },
]


def _build_read_task_pipeline(
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
        for stage in READ_PIPELINE_STAGES
    ]

    by_id = {
        stage["id"]: stage
        for stage in stages
    }

    # Gorev API tarafindan alinmistir.
    by_id["task"]["status"] = "success"

    router_detected = _contains(
        log_items,
        "Task Router: READ",
    )

    model_routed = _contains(
        log_items,
        "Model Router:",
    )

    read_started = _contains(
        log_items,
        "READ gorevi calistiriliyor",
    )

    read_completed = _contains(
        log_items,
        "READ gorevi tamamlandi",
    )

    read_failed = _contains(
        log_items,
        "READ gorevi basarisiz",
    )

    # Tamamlanmis READ gorevinde tum asamalar
    # basarili kabul edilir. Bu durum DB'den
    # yeniden yuklenen eski gorevlerde log eksik
    # olsa bile dogru pipeline uretir.
    if (
        read_completed
        or task_state == "completed"
    ):
        for stage in stages:
            stage["status"] = "success"

    elif (
        read_failed
        or task_state == "failed"
    ):
        if read_started:
            by_id[
                "repo_analysis"
            ]["status"] = "success"

            by_id[
                "model"
            ]["status"] = "failed"

        elif (
            router_detected
            or model_routed
        ):
            by_id[
                "repo_analysis"
            ]["status"] = "failed"

        else:
            by_id[
                "repo_analysis"
            ]["status"] = "failed"

    elif read_started:
        by_id[
            "repo_analysis"
        ]["status"] = "success"

        by_id[
            "model"
        ]["status"] = "active"

    elif (
        model_routed
        or router_detected
        or task_state == "running"
    ):
        by_id[
            "repo_analysis"
        ]["status"] = "active"

    current_stage = next(
        (
            stage["id"]
            for stage in stages
            if stage["status"]
            in {
                "active",
                "failed",
            }
        ),
        None,
    )

    if current_stage is None:
        pending_stage = next(
            (
                stage["id"]
                for stage in stages
                if stage["status"]
                == "pending"
            ),
            None,
        )

        current_stage = (
            pending_stage
            or "completed"
        )

    completed = sum(
        stage["status"] == "success"
        for stage in stages
    )

    progress_percent = round(
        completed
        / len(stages)
        * 100
    )

    if task_state == "completed":
        progress_percent = 100

    return {
        "task_id": _value(
            task,
            "task_id",
        ),
        "task_state": task_state,
        "task_kind": "read",
        "current_stage": current_stage,
        "progress_percent": progress_percent,
        "stages": stages,
    }



def _build_execute_task_pipeline(
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
        for stage in EXECUTE_PIPELINE_STAGES
    ]

    by_id = {
        stage["id"]: stage
        for stage in stages
    }

    by_id["task"]["status"] = "success"

    router_detected = _contains(
        log_items,
        "Task Router: EXECUTE",
    )

    execution_routed = _contains(
        log_items,
        "Execution Router:",
    )

    execute_started = _contains(
        log_items,
        "EXECUTE gorevi calistiriliyor",
    )

    execute_completed = _contains(
        log_items,
        "EXECUTE gorevi tamamlandi",
    )

    execute_failed = _contains(
        log_items,
        "EXECUTE gorevi basarisiz",
    )

    if (
        execute_completed
        or task_state == "completed"
    ):
        for stage in stages:
            stage["status"] = "success"

    elif (
        execute_failed
        or task_state == "failed"
    ):
        if execute_started:
            by_id[
                "action_prepare"
            ]["status"] = "success"

            by_id[
                "action_execute"
            ]["status"] = "failed"

        else:
            by_id[
                "action_prepare"
            ]["status"] = "failed"

    elif execute_started:
        by_id[
            "action_prepare"
        ]["status"] = "success"

        by_id[
            "action_execute"
        ]["status"] = "active"

    elif (
        execution_routed
        or router_detected
        or task_state == "running"
    ):
        by_id[
            "action_prepare"
        ]["status"] = "active"

    current_stage = next(
        (
            stage["id"]
            for stage in stages
            if stage["status"]
            in {
                "active",
                "failed",
            }
        ),
        None,
    )

    if current_stage is None:
        pending_stage = next(
            (
                stage["id"]
                for stage in stages
                if stage["status"]
                == "pending"
            ),
            None,
        )

        current_stage = (
            pending_stage
            or "completed"
        )

    completed = sum(
        stage["status"] == "success"
        for stage in stages
    )

    progress_percent = round(
        completed
        / len(stages)
        * 100
    )

    if task_state == "completed":
        progress_percent = 100

    return {
        "task_id": _value(
            task,
            "task_id",
        ),
        "task_state": task_state,
        "task_kind": "execute",
        "current_stage": current_stage,
        "progress_percent": progress_percent,
        "stages": stages,
    }


def build_task_pipeline(
    task: Any,
    logs: Iterable[str] = (),
    task_kind: str | None = None,
) -> dict[str, Any]:
    normalized_kind = (
        task_kind.strip().casefold()
        if task_kind is not None
        else None
    )

    if normalized_kind == "execute":
        return _build_execute_task_pipeline(
            task,
            logs,
        )

    if normalized_kind == "read":
        return _build_read_task_pipeline(
            task,
            logs,
        )

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

    by_id["task"]["status"] = "success"

    worktree_ready = _contains(
        log_items,
        "worktree hazirlandi",
    )

    model_started = _contains(
        log_items,
        "model kod uretiyor",
        "model yaniti alindi",
    )

    model_completed = _contains(
        log_items,
        "model yaniti alindi",
    )

    patch_completed = _contains(
        log_items,
        "patch dogrulandi",
        "patch uygulandi",
    )

    tests_started = _contains(
        log_items,
        "testler calistiriliyor",
    )

    tests_passed = _contains(
        log_items,
        "testler basarili",
    )

    tests_failed = _contains(
        log_items,
        "testler basarisiz",
        "test failed",
        "tests failed",
    )

    terminal_approval_states = {
        "ready_for_approval",
        "approved",
        "rejected",
    }

    # Terminal approval states prove that all
    # previous pipeline stages completed.
    if task_state in terminal_approval_states:
        _mark_success_through(
            by_id,
            "diff",
        )

    elif tests_failed:
        _mark_success_through(
            by_id,
            "patch",
        )
        by_id["tests"]["status"] = "failed"

    elif tests_passed:
        _mark_success_through(
            by_id,
            "tests",
        )
        by_id["diff"]["status"] = "active"

    elif tests_started:
        _mark_success_through(
            by_id,
            "patch",
        )
        by_id["tests"]["status"] = "active"

    elif patch_completed:
        _mark_success_through(
            by_id,
            "patch",
        )
        by_id["tests"]["status"] = "active"

    elif model_completed:
        _mark_success_through(
            by_id,
            "model",
        )
        by_id["patch"]["status"] = "active"

    elif model_started:
        _mark_success_through(
            by_id,
            "repo_analysis",
        )
        by_id["model"]["status"] = "active"

    elif worktree_ready:
        _mark_success_through(
            by_id,
            "worktree",
        )
        by_id["repo_analysis"]["status"] = "active"

    elif task_state == "running":
        by_id["worktree"]["status"] = "active"

    if task_state == "ready_for_approval":
        by_id["approval"]["status"] = "waiting"

    elif task_state == "approved":
        by_id["approval"]["status"] = "success"

    elif task_state == "rejected":
        by_id["approval"]["status"] = "rejected"

    elif task_state == "failed":
        if not any(
            stage["status"] == "failed"
            for stage in stages
        ):
            candidate = next(
                (
                    stage
                    for stage in stages
                    if stage["status"]
                    in {"active", "pending"}
                ),
                None,
            )

            if candidate is not None:
                candidate["status"] = "failed"

    current_stage = next(
        (
            stage["id"]
            for stage in stages
            if stage["status"]
            in {
                "active",
                "waiting",
                "failed",
            }
        ),
        None,
    )

    if current_stage is None:
        unfinished = next(
            (
                stage["id"]
                for stage in stages
                if stage["status"] == "pending"
            ),
            None,
        )

        current_stage = (
            unfinished
            or "approval"
        )

    completed = sum(
        stage["status"]
        in {
            "success",
            "rejected",
        }
        for stage in stages
    )

    progress_percent = round(
        completed
        / len(stages)
        * 100
    )

    if task_state == "ready_for_approval":
        progress_percent = 88

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
