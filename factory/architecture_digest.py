from __future__ import annotations

import ast
import re
from pathlib import Path

from factory.repository_context import (
    select_context_files,
)


MAX_FILES = 12


FILE_ROLES = {
    "config.yaml": (
        "Uygulama, model ve routing konfigurasyonu"
    ),
    "api/app.py": (
        "FastAPI HTTP API ve gorev/proje yonetimi"
    ),
    "factory/orchestrator.py": (
        "WRITE gorevlerinin Git, model, patch, test "
        "ve onay akislarini yuruten ana orkestrator"
    ),
    "factory/task_router.py": (
        "Gorevleri READ ve WRITE olarak siniflandirir"
    ),
    "factory/model_router.py": (
        "Goreve uygun yerel modeli secer"
    ),
    "factory/read_task_runner.py": (
        "READ gorevlerinde repository analizini yurutur"
    ),
    "factory/repository_context.py": (
        "READ gorevleri icin ilgili repository "
        "dosyalarini secer"
    ),
    "factory/database.py": (
        "SQLite kalicilik katmani"
    ),
    "factory/pipeline.py": (
        "Gorev pipeline asamalarini ve ilerlemeyi uretir"
    ),
    "factory/control_center.py": (
        "Sistem, Git, Docker ve Ollama durumlarini toplar"
    ),
    "frontend/src/api.ts": (
        "React frontend ile FastAPI arasindaki "
        "HTTP istemci katmani"
    ),
    "frontend/src/App.tsx": (
        "Ana React kontrol paneli ve uygulama durumu"
    ),
    "frontend/package.json": (
        "Frontend bagimliliklari ve scriptleri"
    ),
}


def _safe_read(
    path: Path,
    limit: int | None = None,
) -> str:
    try:
        content = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        if limit is None:
            return content

        return content[:limit]

    except OSError:
        return ""


def _python_imports(
    tree: ast.AST,
) -> list[str]:
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            module = node.module or ""

            if module:
                imports.append(module)

    return sorted(set(imports))


def _python_classes(
    tree: ast.AST,
) -> list[str]:
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    ]


def _python_functions(
    tree: ast.AST,
) -> list[str]:
    return [
        node.name
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    ]


def _fastapi_routes(
    source: str,
) -> list[str]:
    pattern = re.compile(
        r'@app\.(get|post|put|delete|patch)\('
        r'\s*["\']([^"\']+)["\']'
    )

    routes = []

    for method, route in pattern.findall(source):
        routes.append(
            f"{method.upper()} {route}"
        )

    return routes


def _ts_exports(
    source: str,
) -> list[str]:
    patterns = (
        r"export\s+function\s+([A-Za-z0-9_]+)",
        r"export\s+async\s+function\s+([A-Za-z0-9_]+)",
        r"export\s+type\s+([A-Za-z0-9_]+)",
        r"export\s+interface\s+([A-Za-z0-9_]+)",
        r"export\s+const\s+([A-Za-z0-9_]+)",
    )

    found: list[str] = []

    for pattern in patterns:
        found.extend(
            re.findall(
                pattern,
                source,
            )
        )

    return list(dict.fromkeys(found))


def _react_signals(
    source: str,
) -> list[str]:
    signals: list[str] = []

    checks = {
        "useState": "React state yonetimi",
        "useEffect": "React effect/polling",
        "EventSource": "SSE canli log baglantisi",
        "createTask": "Gorev olusturma UI akisi",
        "getTaskPipeline": "Pipeline goruntuleme",
        "getControlCenterStatus": (
            "Kontrol merkezi durumunu yukleme"
        ),
    }

    for needle, label in checks.items():
        if needle in source:
            signals.append(label)

    return signals


def _config_signals(
    source: str,
) -> list[str]:
    signals = []

    for key in (
        "models:",
        "routing:",
        "cloud:",
        "generation:",
    ):
        if key in source:
            signals.append(
                key.rstrip(":")
            )

    model_names = re.findall(
        r'model:\s*["\']?([^"\'\n]+)',
        source,
    )

    for model in model_names:
        signals.append(
            f"model={model.strip()}"
        )

    return signals


def _describe_python(
    relative: str,
    source: str,
) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [
            "Python kaynagi parse edilemedi."
        ]

    lines: list[str] = []

    imports = _python_imports(tree)

    if imports:
        lines.append(
            "IMPORTS: "
            + ", ".join(imports[:14])
        )

    classes = _python_classes(tree)

    if classes:
        lines.append(
            "CLASSES: "
            + ", ".join(classes[:12])
        )

    functions = _python_functions(tree)

    if functions:
        lines.append(
            "FUNCTIONS: "
            + ", ".join(functions[:18])
        )

    if relative == "api/app.py":
        routes = _fastapi_routes(source)

        if routes:
            lines.append(
                "HTTP_ROUTES: "
                + ", ".join(routes[:30])
            )

    return lines


def _describe_typescript(
    relative: str,
    source: str,
) -> list[str]:
    lines: list[str] = []

    exports = _ts_exports(source)

    if exports:
        lines.append(
            "EXPORTS: "
            + ", ".join(exports[:25])
        )

    if relative == "frontend/src/App.tsx":
        signals = _react_signals(source)

        if signals:
            lines.append(
                "UI_SIGNALS: "
                + ", ".join(signals)
            )

    dependencies = []

    for name in (
        "react",
        "vite",
        "lucide-react",
    ):
        if (
            relative == "frontend/package.json"
            and f'"{name}"' in source
        ):
            dependencies.append(name)

    if dependencies:
        lines.append(
            "DEPENDENCIES: "
            + ", ".join(dependencies)
        )

    return lines


def build_architecture_digest(
    project_path: str,
    prompt: str,
) -> str:
    root = Path(project_path).resolve()

    ranked = select_context_files(
        project_path,
        prompt,
    )[:MAX_FILES]

    sections = [
        "ARCHITECTURE_DIGEST",
        f"PROJECT_ROOT: {root}",
        "",
    ]

    for item in ranked:
        relative = item.relative
        source = _safe_read(item.path)

        role = FILE_ROLES.get(
            relative,
            "Destekleyici proje modulu",
        )

        sections.append(
            f"FILE: {relative}"
        )

        sections.append(
            f"ROLE: {role}"
        )

        suffix = item.path.suffix.lower()

        if suffix == ".py":
            sections.extend(
                _describe_python(
                    relative,
                    source,
                )
            )

        elif suffix in {
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".json",
        }:
            sections.extend(
                _describe_typescript(
                    relative,
                    source,
                )
            )

        elif relative in {
            "config.yaml",
            "config.yml",
        }:
            signals = _config_signals(
                source
            )

            if signals:
                sections.append(
                    "CONFIG_SIGNALS: "
                    + ", ".join(signals)
                )

        sections.append("")

    return "\n".join(sections)
