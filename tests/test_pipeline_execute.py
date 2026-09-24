from factory.pipeline import (
    build_task_pipeline,
)


def test_execute_completed_pipeline_is_four_steps():
    result = build_task_pipeline(
        {
            "task_id": "TASK-EXEC-1",
            "state": "completed",
        },
        [
            "Task Router: EXECUTE - local action",
            "Execution Router: local-executor",
            "EXECUTE gorevi calistiriliyor.",
            "EXECUTE gorevi tamamlandi.",
        ],
        task_kind="execute",
    )

    assert result["task_kind"] == "execute"
    assert result["progress_percent"] == 100
    assert [
        stage["id"]
        for stage in result["stages"]
    ] == [
        "task",
        "action_prepare",
        "action_execute",
        "completed",
    ]
    assert all(
        stage["status"] == "success"
        for stage in result["stages"]
    )


def test_execute_running_pipeline_marks_local_action_active():
    result = build_task_pipeline(
        {
            "task_id": "TASK-EXEC-2",
            "state": "running",
        },
        [
            "Task Router: EXECUTE",
            "Execution Router: local-executor",
            "EXECUTE gorevi calistiriliyor.",
        ],
        task_kind="execute",
    )

    by_id = {
        stage["id"]: stage["status"]
        for stage in result["stages"]
    }

    assert by_id["task"] == "success"
    assert by_id["action_prepare"] == "success"
    assert by_id["action_execute"] == "active"
    assert by_id["completed"] == "pending"


def test_execute_failure_marks_execution_failed():
    result = build_task_pipeline(
        {
            "task_id": "TASK-EXEC-3",
            "state": "failed",
        },
        [
            "Task Router: EXECUTE",
            "Execution Router: local-executor",
            "EXECUTE gorevi calistiriliyor.",
            "EXECUTE gorevi basarisiz: test",
        ],
        task_kind="execute",
    )

    by_id = {
        stage["id"]: stage["status"]
        for stage in result["stages"]
    }

    assert by_id["action_prepare"] == "success"
    assert by_id["action_execute"] == "failed"
