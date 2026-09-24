import json
from types import SimpleNamespace

from factory.general_planner_cli import (
    build_plan_preview,
)


class FakeModelClient:
    def complete(
        self,
        **kwargs,
    ):
        payload = {
            "goal": (
                "Mevcut Django projesine "
                "users app eklemek"
            ),
            "summary": (
                "Once manage.py bul."
            ),
            "success_criteria": [],
            "constraints": [],
            "steps": [
                {
                    "step_id": "discover",
                    "title": "Django root bul",
                    "description": (
                        "manage.py ara"
                    ),
                    "permission": "read",
                    "tool": {
                        "tool_name": "find_files",
                        "arguments": {
                            "pattern": "manage.py",
                        },
                        "permission": "read",
                        "cwd": None,
                    },
                    "depends_on": [],
                    "verification_criteria": [],
                    "status": "pending",
                    "max_attempts": 2,
                    "attempt": 0,
                }
            ],
        }

        return SimpleNamespace(
            content=json.dumps(
                payload
            )
        )


def test_build_plan_preview_is_dry_run(
    tmp_path,
):
    manage = (
        tmp_path
        / "okulprojesi"
    )
    manage.mkdir()

    (
        manage
        / "manage.py"
    ).write_text(
        "# manage",
        encoding="utf-8",
    )

    result = build_plan_preview(
        project_path=str(tmp_path),
        prompt=(
            "Bu projeye users diye "
            "bir app olustur."
        ),
        model_client=FakeModelClient(),
    )

    assert result["goal"].startswith(
        "Mevcut Django"
    )

    assert (
        result["steps"][0]["tool"][
            "tool_name"
        ]
        == "find_files"
    )

    # Dry-run HICBIR sey olusturmamali.
    assert not (
        manage
        / "users"
    ).exists()
