from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import shutil
import subprocess
import sys

from factory.general_filesystem_tools import (
    UnsafeProjectPathError,
)
from factory.general_process_tools import (
    MAX_CAPTURE_CHARS,
    build_project_tool_registry,
)
from factory.tool_registry import (
    ToolRegistry,
)


DEFAULT_TEST_TIMEOUT = 180
MAX_TEST_TIMEOUT = 300


class ProjectToolError(RuntimeError):
    pass


def _project_root(
    project_path: str,
) -> Path:
    root = Path(
        project_path
    ).expanduser().resolve()

    if not root.exists():
        raise ProjectToolError(
            f"Proje yolu bulunamadi: {root}"
        )

    if not root.is_dir():
        raise ProjectToolError(
            f"Proje yolu klasor degil: {root}"
        )

    return root


def _resolve_cwd(
    root: Path,
    cwd: str | None,
) -> Path:
    value = (
        (cwd or ".").strip()
        or "."
    )

    raw = Path(value)

    if raw.is_absolute():
        candidate = (
            raw
            .expanduser()
            .resolve()
        )
    else:
        candidate = (
            root
            / raw
        ).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeProjectPathError(
            "Tool cwd proje kokunun disina cikamaz: "
            f"{value}"
        ) from exc

    if not candidate.exists():
        raise ProjectToolError(
            f"Tool cwd bulunamadi: {value}"
        )

    if not candidate.is_dir():
        raise ProjectToolError(
            f"Tool cwd klasor degil: {value}"
        )

    return candidate


def _truncate(
    value: str,
) -> tuple[str, bool]:
    if len(value) <= MAX_CAPTURE_CHARS:
        return value, False

    return (
        value[:MAX_CAPTURE_CHARS],
        True,
    )


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout
            if isinstance(
                exc.stdout,
                str,
            )
            else ""
        )
        stderr = (
            exc.stderr
            if isinstance(
                exc.stderr,
                str,
            )
            else ""
        )

        stdout, stdout_truncated = (
            _truncate(stdout)
        )
        stderr, stderr_truncated = (
            _truncate(stderr)
        )

        return {
            "success": False,
            "timed_out": True,
            "exit_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }

    stdout, stdout_truncated = (
        _truncate(
            completed.stdout
            or ""
        )
    )
    stderr, stderr_truncated = (
        _truncate(
            completed.stderr
            or ""
        )
    )

    return {
        "success": (
            completed.returncode
            == 0
        ),
        "timed_out": False,
        "exit_code": (
            completed.returncode
        ),
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


def _git_diff_handler(
    root: Path,
):
    def handler(
        arguments: dict[str, Any],
        cwd: str | None,
    ) -> dict[str, Any]:
        git = shutil.which(
            "git"
        )

        if git is None:
            raise ProjectToolError(
                "git PATH icinde bulunamadi."
            )

        workdir = _resolve_cwd(
            root,
            cwd,
        )

        result = _run(
            [
                git,
                "diff",
                "--no-ext-diff",
                "--",
            ],
            cwd=workdir,
            timeout=60,
        )

        return {
            **result,
            "cwd": (
                workdir
                .relative_to(root)
                .as_posix()
                if workdir != root
                else "."
            ),
            "has_diff": bool(
                result["stdout"].strip()
            ),
        }

    return handler


def _find_python(
    root: Path,
) -> str:
    candidates = []

    if os.name == "nt":
        candidates.extend(
            [
                root
                / ".venv"
                / "Scripts"
                / "python.exe",
                root
                / "venv"
                / "Scripts"
                / "python.exe",
            ]
        )
    else:
        candidates.extend(
            [
                root
                / ".venv"
                / "bin"
                / "python",
                root
                / "venv"
                / "bin"
                / "python",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return str(
                candidate.resolve()
            )

    return str(
        Path(
            sys.executable
        ).resolve()
    )


def _looks_like_python_tests(
    workdir: Path,
) -> bool:
    markers = (
        "pytest.ini",
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
    )

    return (
        any(
            (workdir / marker).exists()
            for marker in markers
        )
        or (
            workdir
            / "tests"
        ).is_dir()
    )


def _load_package_json(
    workdir: Path,
) -> dict[str, Any] | None:
    path = (
        workdir
        / "package.json"
    )

    if not path.exists():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise ProjectToolError(
            f"package.json okunamadi: {exc}"
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise ProjectToolError(
            "package.json nesne olmali."
        )

    return payload


def _node_test_command(
    workdir: Path,
    package: dict[str, Any],
) -> list[str]:
    scripts = package.get(
        "scripts",
        {},
    )

    if not isinstance(
        scripts,
        dict,
    ):
        scripts = {}

    test_script = str(
        scripts.get(
            "test",
            "",
        )
    ).strip()

    if not test_script:
        raise ProjectToolError(
            "package.json icinde test script'i yok."
        )

    npm_name = (
        "npm.cmd"
        if os.name == "nt"
        else "npm"
    )

    npm = shutil.which(
        npm_name
    )

    if npm is None:
        raise ProjectToolError(
            "npm PATH icinde bulunamadi."
        )

    lowered = (
        test_script.casefold()
    )

    command = [
        npm,
        "test",
    ]

    if "vitest" in lowered:
        command.extend(
            [
                "--",
                "--run",
            ]
        )
    elif "jest" in lowered:
        command.extend(
            [
                "--",
                "--runInBand",
            ]
        )

    return command


def _run_tests_handler(
    root: Path,
):
    def handler(
        arguments: dict[str, Any],
        cwd: str | None,
    ) -> dict[str, Any]:
        workdir = _resolve_cwd(
            root,
            cwd,
        )

        target = str(
            arguments.get(
                "target",
                "",
            )
        ).strip()

        if _looks_like_python_tests(
            workdir
        ):
            python = _find_python(
                root
            )

            command = [
                python,
                "-m",
                "pytest",
            ]

            if target:
                command.append(
                    target
                )

            runner = "pytest"

        else:
            package = _load_package_json(
                workdir
            )

            if package is None:
                raise ProjectToolError(
                    "Desteklenen test runner tespit edilemedi. "
                    "run_process ile acik bir komut kullanilabilir."
                )

            command = (
                _node_test_command(
                    workdir,
                    package,
                )
            )

            if target:
                command.extend(
                    [
                        "--",
                        target,
                    ]
                )

            runner = "npm-test"

        result = _run(
            command,
            cwd=workdir,
            timeout=DEFAULT_TEST_TIMEOUT,
        )

        return {
            **result,
            "runner": runner,
            "command": command,
            "cwd": (
                workdir
                .relative_to(root)
                .as_posix()
                if workdir != root
                else "."
            ),
        }

    return handler


def build_full_project_tool_registry(
    project_path: str,
) -> ToolRegistry:
    root = _project_root(
        project_path
    )

    registry = (
        build_project_tool_registry(
            str(root)
        )
    )

    registry.bind_handler(
        "git_diff",
        _git_diff_handler(root),
    )
    registry.bind_handler(
        "run_tests",
        _run_tests_handler(root),
    )

    return registry
