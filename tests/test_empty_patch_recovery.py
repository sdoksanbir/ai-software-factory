import json
from types import SimpleNamespace

import pytest

from factory.multi_step_task_runner import (
    run_multi_step_task,
)
from factory.orchestrator import Orchestrator
from factory.task_plan_store import (
    save_task_plan,
)
from factory.task_step_handlers import (
    EMPTY_PATCH_REPAIR_FEEDBACK,
    EMPTY_PATCH_USER_FAILURE,
    TaskStepHandlers,
)
from factory.tools.patch import (
    PatchTool,
    PatchToolError,
)


class FakeModelClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        if not self.responses:
            raise AssertionError(
                "Unexpected model call"
            )

        return SimpleNamespace(
            content=self.responses.pop(0)
        )


class FakeOrchestrator:
    _validate_explicit_file_scope = (
        staticmethod(
            Orchestrator
            ._validate_explicit_file_scope
        )
    )

    def __init__(
        self,
        model_client=None,
        worktree_path=None,
    ):
        self.model_client = model_client
        self.project_path = str(
            worktree_path or "."
        )
        self.git_manager = SimpleNamespace(
            create_worktree=lambda task_id: (
                SimpleNamespace(
                    path=self.project_path,
                    branch=f"agent/{task_id}",
                )
            ),
            get_diff=lambda path: "FINAL_DIFF",
        )
        self.sandbox = SimpleNamespace(
            run_command=lambda *a, **k: (
                SimpleNamespace(
                    success=True,
                    stdout="ok",
                    stderr="",
                )
            )
        )


def _empty_patch():
    return json.dumps(
        {
            "files": [],
            "explanation": "none",
        }
    )


def _html_patch(path="prototype.html"):
    return json.dumps(
        {
            "files": [
                {
                    "operation": "write",
                    "path": path,
                    "content": (
                        "<!doctype html>"
                        "<html><body>"
                        "Hello"
                        "</body></html>\n"
                    ),
                }
            ],
            "explanation": "html prototype",
        }
    )


def test_extract_explicit_html_css_scss_targets():
    assert (
        Orchestrator
        ._extract_explicit_file_targets(
            "admin.html olustur"
        )
        == ["admin.html"]
    )

    assert (
        Orchestrator
        ._extract_explicit_file_targets(
            "styles.css guncelle"
        )
        == ["styles.css"]
    )

    assert (
        Orchestrator
        ._extract_explicit_file_targets(
            "theme.scss duzenle"
        )
        == ["theme.scss"]
    )

    assert (
        Orchestrator
        ._extract_explicit_file_targets(
            "page.htm olustur"
        )
        == ["page.htm"]
    )


def test_admin_html_scope_lock_rejects_other_file(
    tmp_path,
):
    model = FakeModelClient(
        [
            _html_patch("other.html"),
        ]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=model,
            worktree_path=tmp_path,
        ),
        scope_prompt="admin.html olustur",
        model_name="fake-model",
    )

    with pytest.raises(
        PatchToolError,
        match="explicit task scope",
    ):
        handlers.write(
            {
                "instruction": (
                    "admin.html olustur"
                )
            },
            str(tmp_path),
        )

    assert not (
        tmp_path / "other.html"
    ).exists()
    assert len(model.calls) == 1


def test_empty_patch_repairs_once_and_succeeds(
    tmp_path,
):
    model = FakeModelClient(
        [
            _empty_patch(),
            _html_patch("prototype.html"),
        ]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=model,
            worktree_path=tmp_path,
        ),
        scope_prompt=(
            "bana statik bir HTML "
            "tasarim prototipi yap"
        ),
        model_name="fake-model",
    )

    result = handlers.write(
        {
            "instruction": (
                "bana statik bir HTML "
                "tasarim prototipi yap"
            )
        },
        str(tmp_path),
    )

    assert len(model.calls) == 2

    second_prompt = model.calls[1][
        "user_prompt"
    ]

    assert (
        EMPTY_PATCH_REPAIR_FEEDBACK
        in second_prompt
    )
    assert "zero file changes" in (
        second_prompt
    )

    written = (
        tmp_path / "prototype.html"
    )

    assert written.is_file()
    assert "Hello" in written.read_text(
        encoding="utf-8"
    )
    assert "prototype.html" in result.output
    assert result.handoff_request is not None


def test_double_empty_patch_controlled_failure(
    tmp_path,
):
    model = FakeModelClient(
        [
            _empty_patch(),
            _empty_patch(),
            _html_patch("should-not-run.html"),
        ]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=model,
            worktree_path=tmp_path,
        ),
        scope_prompt=(
            "bana statik bir HTML "
            "tasarim prototipi yap"
        ),
        model_name="fake-model",
    )

    with pytest.raises(
        PatchToolError,
        match=EMPTY_PATCH_USER_FAILURE,
    ) as caught:
        handlers.write(
            {
                "instruction": (
                    "bana statik bir HTML "
                    "tasarim prototipi yap"
                )
            },
            str(tmp_path),
        )

    assert len(model.calls) == 2
    assert "pydantic.dev" not in str(
        caught.value
    ).casefold()
    assert "validation error" not in str(
        caught.value
    ).casefold()
    assert list(tmp_path.iterdir()) == []


def test_path_traversal_does_not_get_empty_repair(
    tmp_path,
):
    model = FakeModelClient(
        [
            json.dumps(
                {
                    "files": [
                        {
                            "path": (
                                "../escape.html"
                            ),
                            "operation": "write",
                            "content": "nope\n",
                        }
                    ],
                    "explanation": "bad",
                }
            ),
            _html_patch("should-not-run.html"),
        ]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=model,
            worktree_path=tmp_path,
        ),
        model_name="fake-model",
    )

    with pytest.raises(
        PatchToolError,
        match="Path traversal rejected",
    ):
        handlers.write(
            {
                "instruction": (
                    "statik HTML prototipi yap"
                )
            },
            str(tmp_path),
        )

    assert len(model.calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_absolute_path_does_not_get_empty_repair(
    tmp_path,
):
    model = FakeModelClient(
        [
            json.dumps(
                {
                    "files": [
                        {
                            "path": (
                                "C:/Windows/"
                                "evil.html"
                            ),
                            "operation": "write",
                            "content": "nope\n",
                        }
                    ],
                    "explanation": "bad",
                }
            )
        ]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=model,
            worktree_path=tmp_path,
        ),
        model_name="fake-model",
    )

    with pytest.raises(
        PatchToolError,
        match="Absolute path rejected",
    ):
        handlers.write(
            {
                "instruction": (
                    "HTML dosyasi olustur"
                )
            },
            str(tmp_path),
        )

    assert len(model.calls) == 1


def test_git_path_does_not_get_empty_repair(
    tmp_path,
):
    model = FakeModelClient(
        [
            json.dumps(
                {
                    "files": [
                        {
                            "path": (
                                ".git/config"
                            ),
                            "operation": "write",
                            "content": "nope\n",
                        }
                    ],
                    "explanation": "bad",
                }
            )
        ]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=model,
            worktree_path=tmp_path,
        ),
        model_name="fake-model",
    )

    with pytest.raises(
        PatchToolError,
        match=".git path rejected",
    ):
        handlers.write(
            {
                "instruction": (
                    "config yaz"
                )
            },
            str(tmp_path),
        )

    assert len(model.calls) == 1


def test_empty_files_still_rejected_by_schema():
    with pytest.raises(PatchToolError):
        PatchTool.parse_multi_file_response(
            _empty_patch()
        )


def test_unnamed_html_create_repair_ready_for_approval(
    tmp_path,
    monkeypatch,
):
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    db_path = tmp_path / "factory.db"
    task_id = "TASK-9001"
    prompt = (
        "bana statik bir HTML "
        "tasarim prototipi yap"
    )

    model = FakeModelClient(
        [
            _empty_patch(),
            _html_patch("prototype.html"),
        ]
    )

    class AcceptHandlers(TaskStepHandlers):
        def handoff(
            self,
            source_checkpoint,
            request,
            db_path,
        ):
            raise LookupError(
                "no alternate reviewer"
            )

        def verify(
            self,
            step,
            worktree_path,
        ):
            return "verify ok"

    monkeypatch.setattr(
        "factory.multi_step_task_runner."
        "TaskStepHandlers",
        AcceptHandlers,
    )

    real_execute = None

    from factory import (
        multi_step_task_runner as runner_module,
    )
    from factory.task_step_executor import (
        execute_task_plan as real_execute_task_plan,
    )

    real_execute = real_execute_task_plan

    def execute_with_test_db(
        current_task_id,
        worktree_path,
        **kwargs,
    ):
        return real_execute(
            current_task_id,
            worktree_path,
            db_path=db_path,
            **kwargs,
        )

    monkeypatch.setattr(
        runner_module,
        "execute_task_plan",
        execute_with_test_db,
    )

    monkeypatch.setattr(
        "factory.multi_step_task_runner.get_task",
        lambda task_id: None,
    )

    save_task_plan(
        task_id,
        [
            {
                "title": "Gorevi tamamla",
                "instruction": prompt,
                "kind": "write",
            },
            {
                "title": "Dogrula",
                "instruction": (
                    "Uygulanan degisikligi "
                    "dogrula."
                ),
                "kind": "verify",
            },
        ],
        db_path=db_path,
    )

    orchestrator = FakeOrchestrator(
        model_client=model,
        worktree_path=worktree,
    )

    result = run_multi_step_task(
        orchestrator=orchestrator,
        prompt=prompt,
        task_id=task_id,
        max_attempts=2,
        approval_handler=(
            lambda *args, **kwargs: (
                "ready_for_approval"
            )
        ),
        model_name="fake-model",
    )

    assert result == "ready_for_approval"
    assert len(model.calls) == 2
    assert (
        EMPTY_PATCH_REPAIR_FEEDBACK
        in model.calls[1]["user_prompt"]
    )

    written = worktree / "prototype.html"
    assert written.is_file()
    assert written.resolve().is_relative_to(
        worktree.resolve()
    )
