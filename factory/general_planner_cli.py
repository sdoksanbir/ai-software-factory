from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from factory.general_project_tools import (
    build_full_project_tool_registry,
)
from factory.general_task_planner import (
    build_general_task_plan,
)
from factory.models import ModelClient


def build_plan_preview(
    *,
    project_path: str,
    prompt: str,
    model_client: Any | None = None,
) -> dict[str, Any]:
    root = Path(
        project_path
    ).expanduser().resolve()

    if not root.exists():
        raise FileNotFoundError(
            f"Proje yolu bulunamadi: {root}"
        )

    if not root.is_dir():
        raise NotADirectoryError(
            f"Proje yolu klasor degil: {root}"
        )

    registry = (
        build_full_project_tool_registry(
            str(root)
        )
    )

    client = (
        model_client
        if model_client is not None
        else ModelClient()
    )

    plan = build_general_task_plan(
        prompt,
        model_client=client,
        tool_registry=registry,
    )

    return plan.model_dump(
        mode="json"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "General Agent Planner dry-run. "
            "Plan uretir; HICBIR tool calistirmaz."
        )
    )

    parser.add_argument(
        "--project",
        required=True,
        help="Aktif proje klasoru",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Kullanici gorevi",
    )

    args = parser.parse_args()

    payload = build_plan_preview(
        project_path=args.project,
        prompt=args.prompt,
    )

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
