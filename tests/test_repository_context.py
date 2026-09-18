from pathlib import Path

from factory.repository_context import (
    build_repository_map,
    select_context_files,
)


def create_demo_repo(
    root: Path,
) -> None:
    files = {
        "config.yaml":
            "factory:\n  name: demo\n",

        "api/app.py":
            "from fastapi import FastAPI\napp = FastAPI()\n",

        "factory/orchestrator.py":
            "class Orchestrator:\n    pass\n",

        "factory/model_router.py":
            "def route_model(prompt):\n    pass\n",

        "factory/task_router.py":
            "def route_task(prompt):\n    pass\n",

        "factory/database.py":
            "def init_database():\n    pass\n",

        "frontend/src/App.tsx":
            "export default function App() { return null }\n",

        "frontend/src/api.ts":
            "export function listTasks() {}\n",

        "tests/test_model_router.py":
            "def test_router(): pass\n",

        "frontend/README.md":
            "External package documentation\n",

        ".venv-1/Lib/site-packages/litellm/readme.md":
            "LiteLLM documentation\n",
    }

    for relative, content in files.items():
        path = root / relative

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            content,
            encoding="utf-8",
        )


def test_virtualenv_is_excluded(
    tmp_path: Path,
):
    create_demo_repo(tmp_path)

    repository_map = build_repository_map(
        str(tmp_path)
    )

    assert ".venv-1" not in repository_map
    assert "site-packages" not in repository_map
    assert "litellm" not in repository_map


def test_general_overview_is_balanced(
    tmp_path: Path,
):
    create_demo_repo(tmp_path)

    selected = select_context_files(
        str(tmp_path),
        "Projenin mevcut yapisini kisa sekilde ozetle.",
    )

    names = {
        item.relative
        for item in selected
    }

    assert "api/app.py" in names
    assert "factory/orchestrator.py" in names
    assert "factory/model_router.py" in names
    assert "factory/task_router.py" in names
    assert "frontend/src/App.tsx" in names


def test_specific_file_gets_priority(
    tmp_path: Path,
):
    create_demo_repo(tmp_path)

    selected = select_context_files(
        str(tmp_path),
        "factory/model_router.py dosyasini acikla.",
    )

    assert selected[0].relative == (
        "factory/model_router.py"
    )


def test_tests_are_not_prioritized_for_overview(
    tmp_path: Path,
):
    create_demo_repo(tmp_path)

    selected = select_context_files(
        str(tmp_path),
        "Projenin mimarisini ozetle.",
    )

    names = [
        item.relative
        for item in selected
    ]

    assert names.index(
        "factory/orchestrator.py"
    ) < names.index(
        "tests/test_model_router.py"
    )
