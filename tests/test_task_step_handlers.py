import json
from types import SimpleNamespace

import pytest

from factory.orchestrator import Orchestrator
from factory.task_step_handlers import (
    TaskStepHandlers,
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


class FakeSandbox:
    def __init__(self, exit_codes=None):
        self.exit_codes = list(
            exit_codes or [0, 0]
        )
        self.calls = []

    def run_command(
        self,
        worktree_path,
        command,
        timeout_seconds=60,
    ):
        self.calls.append(
            (
                worktree_path,
                command,
                timeout_seconds,
            )
        )

        exit_code = (
            self.exit_codes.pop(0)
        )

        return SimpleNamespace(
            success=(
                exit_code in {0, 5}
            ),
            stdout=(
                "ok"
                if exit_code in {0, 5}
                else ""
            ),
            stderr=(
                ""
                if exit_code in {0, 5}
                else "failed"
            ),
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
        sandbox=None,
    ):
        self.model_client = (
            model_client
        )
        self.sandbox = sandbox


def _patch(path, content):
    return json.dumps(
        {
            "files": [
                {
                    "path": path,
                    "content": content,
                }
            ],
            "explanation": "test",
        }
    )


def test_write_applies_patch(
    tmp_path,
):
    model = FakeModelClient(
        [
            _patch(
                "hello.txt",
                "HELLO",
            )
        ]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=model
        ),
        model_name="fake-model",
    )

    handlers.write(
        {
            "instruction": (
                "hello.txt dosyasi olustur"
            )
        },
        str(tmp_path),
    )

    assert (
        tmp_path
        / "hello.txt"
    ).read_text(
        encoding="utf-8"
    ) == "HELLO\n"


def test_second_write_sees_first_write(
    tmp_path,
):
    model = FakeModelClient(
        [
            _patch(
                "first.txt",
                "FIRST_STEP_VALUE",
            ),
            _patch(
                "second.txt",
                "SECOND",
            ),
        ]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=model
        ),
        model_name="fake-model",
    )

    handlers.write(
        {
            "instruction": (
                "first.txt dosyasi olustur"
            )
        },
        str(tmp_path),
    )

    handlers.write(
        {
            "instruction": (
                "second.txt dosyasi olustur"
            )
        },
        str(tmp_path),
    )

    assert len(model.calls) == 2

    second_prompt = (
        model.calls[1]["user_prompt"]
    )

    assert "FIRST_STEP_VALUE" in (
        second_prompt
    )


def test_write_respects_explicit_scope(
    tmp_path,
):
    model = FakeModelClient(
        [
            _patch(
                "wrong.txt",
                "BAD",
            )
        ]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=model
        ),
        scope_prompt=(
            "allowed.txt dosyasi olustur"
        ),
        model_name="fake-model",
    )

    with pytest.raises(Exception):
        handlers.write(
            {
                "instruction": (
                    "Dosyayi olustur"
                )
            },
            str(tmp_path),
        )

    assert not (
        tmp_path
        / "wrong.txt"
    ).exists()


def test_verify_runs_compile_and_pytest(
    tmp_path,
):
    sandbox = FakeSandbox(
        [0, 0]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            sandbox=sandbox
        )
    )

    result = handlers.verify(
        {
            "instruction": (
                "Testleri calistir"
            )
        },
        str(tmp_path),
    )

    assert len(sandbox.calls) == 2

    assert (
        sandbox.calls[0][1]
        == "python -m compileall -q ."
    )

    assert (
        sandbox.calls[1][1]
        .startswith(
            "python -m pytest -q"
        )
    )

    assert "basarili" in result


def test_verify_accepts_no_tests(
    tmp_path,
):
    sandbox = FakeSandbox(
        [0, 5]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            sandbox=sandbox
        )
    )

    result = handlers.verify(
        {
            "instruction": "Dogrula"
        },
        str(tmp_path),
    )

    assert "basarili" in result


def test_verify_failure_raises(
    tmp_path,
):
    sandbox = FakeSandbox(
        [0, 1]
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            sandbox=sandbox
        )
    )

    with pytest.raises(
        RuntimeError,
        match="Test validation failed",
    ):
        handlers.verify(
            {
                "instruction": "Dogrula"
            },
            str(tmp_path),
        )


def test_read_delegates_to_read_runner(
    tmp_path,
    monkeypatch,
):
    captured = {}

    def fake_run_read_task(
        project_path,
        prompt,
        model_route,
        model_client,
    ):
        captured["project_path"] = (
            project_path
        )
        captured["prompt"] = prompt
        captured["model"] = (
            model_route.model
        )

        return "READ_OK"

    monkeypatch.setattr(
        "factory.task_step_handlers."
        "run_read_task",
        fake_run_read_task,
    )

    handlers = TaskStepHandlers(
        FakeOrchestrator(
            model_client=object()
        ),
        model_name="fake-model",
    )

    result = handlers.read(
        {
            "instruction": (
                "Repository yapisini incele"
            )
        },
        str(tmp_path),
    )

    assert result == "READ_OK"

    assert captured["project_path"] == (
        str(tmp_path)
    )

    assert captured["model"] == (
        "fake-model"
    )



def test_verify_uses_scoped_test_files(
    tmp_path,
):
    from types import SimpleNamespace

    class Result:
        success = True
        stdout = ""
        stderr = ""

    class RecordingSandbox:
        def __init__(self):
            self.commands = []

        def run_command(
            self,
            worktree_path,
            command,
            timeout_seconds=60,
        ):
            self.commands.append(command)
            return Result()

    source = tmp_path / "multi_step_probe.py"
    source.write_text(
        "def normalize_name(value):\n"
        "    return ' '.join(value.split())\n",
        encoding="utf-8",
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    test_file = (
        tests_dir
        / "test_multi_step_probe.py"
    )

    test_file.write_text(
        "def test_placeholder():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    sandbox = RecordingSandbox()

    orchestrator = SimpleNamespace(
        sandbox=sandbox,
    )

    handlers = TaskStepHandlers(
        orchestrator,
        scope_prompt=(
            "multi_step_probe.py dosyasini "
            "olustur ve "
            "tests/test_multi_step_probe.py "
            "dosyasinda testlerini yaz."
        ),
    )

    result = handlers.verify(
        {
            "instruction": (
                "Testleri calistir."
            )
        },
        str(tmp_path),
    )

    assert len(sandbox.commands) == 2

    compile_command = sandbox.commands[0]
    pytest_command = sandbox.commands[1]

    assert (
        "python -m py_compile"
        in compile_command
    )
    assert (
        "multi_step_probe.py"
        in compile_command
    )
    assert (
        "tests/test_multi_step_probe.py"
        in compile_command
    )

    assert pytest_command == (
        "python -m pytest -q "
        "tests/test_multi_step_probe.py"
    )

    assert pytest_command != (
        "python -m pytest -q"
    )

    assert "Scoped dogrulama" in result
