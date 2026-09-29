"""Production modules must not import the experimental general agent stack."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PRODUCTION_MODULES = (
    ROOT / "api" / "app.py",
    ROOT / "factory" / "task_execution_service.py",
    ROOT / "factory" / "task_execution_dispatcher.py",
    ROOT / "factory" / "multi_step_task_runner.py",
    ROOT / "factory" / "task_step_executor.py",
    ROOT / "factory" / "task_step_handlers.py",
    ROOT / "main.py",
)

FORBIDDEN_PREFIXES = (
    "factory.general_",
    "factory.capability_",
    "factory.command_grounding",
    "factory.runtime_grounding",
    "factory.tool_registry",
)


def _is_forbidden(module_name: str) -> bool:
    for prefix in FORBIDDEN_PREFIXES:
        if module_name == prefix:
            return True
        if module_name.startswith(prefix):
            return True
        # factory.general_foo matches factory.general_
        if prefix.endswith("_") and module_name.startswith(
            prefix
        ):
            return True
    return False


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module)

    return found


def test_production_modules_do_not_import_general_system():
    violations: list[str] = []

    for path in PRODUCTION_MODULES:
        assert path.is_file(), f"missing {path}"

        for module_name in _imported_modules(path):
            if _is_forbidden(module_name):
                violations.append(
                    f"{path.relative_to(ROOT)} imports {module_name}"
                )

    assert violations == []
