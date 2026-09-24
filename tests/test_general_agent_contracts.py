import pytest
from pydantic import ValidationError

from factory.general_agent_contracts import (
    GeneralTaskPlan,
    Observation,
    Permission,
    PlanStep,
    StepStatus,
    SuccessCriterion,
    ToolRequest,
    Verification,
    VerificationStatus,
)
from factory.general_plan_adapter import (
    from_legacy_plan,
    to_legacy_plan,
)


def test_generic_plan_supports_mixed_permissions():
    plan = GeneralTaskPlan(
        goal="Django projesine users app ekle ve dogrula.",
        summary="Projeyi kesfet, app olustur, dogrula.",
        success_criteria=[
            SuccessCriterion(
                criterion_id="users-exists",
                description="users/apps.py mevcut olmali.",
            ),
        ],
        steps=[
            PlanStep(
                step_id="discover",
                title="Django kokunu bul",
                description="manage.py dosyasini ara.",
                permission=Permission.READ,
                tool=ToolRequest(
                    tool_name="find_files",
                    arguments={
                        "pattern": "manage.py",
                    },
                    permission=Permission.READ,
                ),
            ),
            PlanStep(
                step_id="create-app",
                title="users app olustur",
                description=(
                    "Bulunan Django proje kokunde "
                    "users uygulamasini olustur."
                ),
                permission=Permission.EXECUTE,
                tool=ToolRequest(
                    tool_name="run_process",
                    arguments={
                        "argv": [
                            "python",
                            "manage.py",
                            "startapp",
                            "users",
                        ],
                    },
                    permission=Permission.EXECUTE,
                ),
                depends_on=[
                    "discover",
                ],
            ),
            PlanStep(
                step_id="verify",
                title="Sonucu dogrula",
                description="users/apps.py dosyasini kontrol et.",
                permission=Permission.READ,
                tool=ToolRequest(
                    tool_name="file_exists",
                    arguments={
                        "path": "users/apps.py",
                    },
                    permission=Permission.READ,
                ),
                depends_on=[
                    "create-app",
                ],
                verification_criteria=[
                    "users-exists",
                ],
            ),
        ],
    )

    assert [
        step.permission
        for step in plan.steps
    ] == [
        Permission.READ,
        Permission.EXECUTE,
        Permission.READ,
    ]

    assert plan.ready_step_ids() == [
        "discover",
    ]


def test_ready_steps_follow_dependency_status():
    plan = GeneralTaskPlan(
        goal="Test",
        summary="Test",
        steps=[
            PlanStep(
                step_id="one",
                title="One",
                description="One",
                permission=Permission.READ,
                status=StepStatus.SUCCEEDED,
            ),
            PlanStep(
                step_id="two",
                title="Two",
                description="Two",
                permission=Permission.WRITE,
                depends_on=["one"],
            ),
        ],
    )

    assert plan.ready_step_ids() == [
        "two",
    ]


def test_dependency_cycle_is_rejected():
    with pytest.raises(
        ValidationError,
        match="dongusu",
    ):
        GeneralTaskPlan(
            goal="Cycle",
            summary="Cycle",
            steps=[
                PlanStep(
                    step_id="a",
                    title="A",
                    description="A",
                    permission=Permission.READ,
                    depends_on=["b"],
                ),
                PlanStep(
                    step_id="b",
                    title="B",
                    description="B",
                    permission=Permission.READ,
                    depends_on=["a"],
                ),
            ],
        )


def test_unknown_dependency_is_rejected():
    with pytest.raises(
        ValidationError,
        match="bilinmeyen dependency",
    ):
        GeneralTaskPlan(
            goal="Unknown",
            summary="Unknown",
            steps=[
                PlanStep(
                    step_id="a",
                    title="A",
                    description="A",
                    permission=Permission.READ,
                    depends_on=["missing"],
                ),
            ],
        )


def test_tool_permission_must_match_step():
    with pytest.raises(
        ValidationError,
        match="ayni olmali",
    ):
        PlanStep(
            step_id="a",
            title="A",
            description="A",
            permission=Permission.READ,
            tool=ToolRequest(
                tool_name="run_process",
                permission=Permission.EXECUTE,
            ),
        )


def test_observation_and_verification_contracts():
    observation = Observation(
        step_id="discover",
        tool_name="find_files",
        success=True,
        summary="manage.py bulundu.",
        data={
            "paths": [
                "okulprojesi/manage.py",
            ],
        },
    )

    verification = Verification(
        criterion_id="users-exists",
        status=VerificationStatus.PASSED,
        evidence="okulprojesi/users/apps.py bulundu.",
    )

    assert observation.success is True
    assert (
        verification.status
        == VerificationStatus.PASSED
    )


def test_legacy_plan_can_be_adapted():
    legacy = {
        "summary": "Eski plan",
        "planner_mode": "multi_step",
        "steps": [
            {
                "title": "Inspect",
                "instruction": "Projeyi incele",
                "kind": "read",
                "status": "completed",
                "attempt": 1,
            },
            {
                "title": "Implement",
                "instruction": "Dosyayi degistir",
                "kind": "write",
                "status": "pending",
                "attempt": 0,
            },
            {
                "title": "Verify",
                "instruction": "Testleri calistir",
                "kind": "verify",
                "status": "pending",
                "attempt": 0,
            },
        ],
    }

    plan = from_legacy_plan(
        legacy,
        goal="Legacy gorev",
    )

    assert [
        step.permission
        for step in plan.steps
    ] == [
        Permission.READ,
        Permission.WRITE,
        Permission.EXECUTE,
    ]

    assert plan.steps[1].depends_on == [
        "legacy-step-1",
    ]

    projected = to_legacy_plan(
        plan
    )

    assert projected["planner_mode"] == (
        "multi_step"
    )
    assert [
        step["kind"]
        for step in projected["steps"]
    ] == [
        "read",
        "write",
        "execute",
    ]
