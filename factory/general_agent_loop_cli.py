from __future__ import annotations

import argparse
import json
from pathlib import Path

from factory.general_agent_loop import (
    run_agent_loop_preview,
)
from factory.general_project_tools import (
    build_full_project_tool_registry,
)
from factory.models import ModelClient


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evidence-bound General Agent preview. "
            "READ tool'lari calisir; mutation sadece "
            "kanit dogrulamasi sonrasi pending_action olur."
        )
    )

    parser.add_argument("--project", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument(
        "--max-read-actions",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--max-probe-actions",
        type=int,
        default=4,
    )

    parser.add_argument(
        "--max-decisions",
        type=int,
        default=16,
    )

    args = parser.parse_args()

    root = Path(
        args.project
    ).expanduser().resolve()

    registry = (
        build_full_project_tool_registry(
            str(root)
        )
    )

    result = run_agent_loop_preview(
        prompt=args.prompt,
        model_client=ModelClient(),
        project_root=str(root),
        tool_registry=registry,
        max_read_actions=args.max_read_actions,
        max_probe_actions=args.max_probe_actions,
        max_decisions=args.max_decisions,
    )

    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
