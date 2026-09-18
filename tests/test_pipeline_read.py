from factory.pipeline import build_task_pipeline


def test_read_pipeline_has_four_stages():
    result = build_task_pipeline(
        {
            "task_id": "TASK-READ-1",
            "state": "running",
        },
        [
            "Task Router: READ - Salt-okuma.",
        ],
        task_kind="read",
    )

    assert [
        stage["id"]
        for stage in result["stages"]
    ] == [
        "task",
        "repo_analysis",
        "model",
        "completed",
    ]

    assert result["task_kind"] == "read"


def test_read_pipeline_model_active():
    result = build_task_pipeline(
        {
            "task_id": "TASK-READ-2",
            "state": "running",
        },
        [
            "Task Router: READ",
            "Model Router: qwen2.5-coder:14b",
            "READ gorevi calistiriliyor.",
        ],
        task_kind="read",
    )

    by_id = {
        stage["id"]: stage["status"]
        for stage in result["stages"]
    }

    assert by_id["task"] == "success"
    assert (
        by_id["repo_analysis"]
        == "success"
    )
    assert by_id["model"] == "active"
    assert by_id["completed"] == "pending"


def test_read_pipeline_completed():
    result = build_task_pipeline(
        {
            "task_id": "TASK-READ-3",
            "state": "completed",
        },
        [
            "Task Router: READ",
            "READ gorevi calistiriliyor.",
            "READ gorevi tamamlandi.",
        ],
        task_kind="read",
    )

    assert all(
        stage["status"] == "success"
        for stage in result["stages"]
    )

    assert result["progress_percent"] == 100
    assert result["current_stage"] == "completed"


def test_read_pipeline_failure():
    result = build_task_pipeline(
        {
            "task_id": "TASK-READ-4",
            "state": "failed",
        },
        [
            "Task Router: READ",
            "READ gorevi calistiriliyor.",
            "READ gorevi basarisiz: model error",
        ],
        task_kind="read",
    )

    by_id = {
        stage["id"]: stage["status"]
        for stage in result["stages"]
    }

    assert (
        by_id["repo_analysis"]
        == "success"
    )
    assert by_id["model"] == "failed"


def test_write_pipeline_stays_unchanged():
    result = build_task_pipeline(
        {
            "task_id": "TASK-WRITE-1",
            "state": "running",
        },
        [],
        task_kind="write",
    )

    ids = [
        stage["id"]
        for stage in result["stages"]
    ]

    assert "worktree" in ids
    assert "patch" in ids
    assert "tests" in ids
    assert "approval" in ids
    assert len(ids) == 8
