import json
from types import SimpleNamespace

import pytest

from factory.general_agent_contracts import (
    Permission,
)
from factory.general_task_planner import (
    GeneralPlannerError,
    build_general_task_plan,
    first_tool_step,
    plan_uses_tool,
)
from factory.tool_registry import (
    build_contract_registry,
)


class FakeModelClient:
    def __init__(self, payload):
        self.content = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload)
        )
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=self.content
        )


def _step(
    *,
    step_id,
    title,
    description,
    permission,
    tool=None,
    depends_on=None,
    verification_criteria=None,
):
    return {
        "step_id": step_id,
        "title": title,
        "description": description,
        "permission": permission,
        "tool": tool,
        "depends_on": depends_on or [],
        "verification_criteria": (
            verification_criteria or []
        ),
        "status": "pending",
        "max_attempts": 2,
        "attempt": 0,
    }


def test_django_app_request_plans_discovery_before_action():
    client = FakeModelClient(
        {
            "goal": "Mevcut Django projesine users app eklemek",
            "summary": (
                "Once Django proje kokunu bul, "
                "sonra app olustur ve dogrula."
            ),
            "success_criteria": [
                {
                    "criterion_id": "users-app-exists",
                    "description": "users/apps.py mevcut olmali",
                    "required": True,
                }
            ],
            "constraints": [
                "Framework root varsayilmayacak",
            ],
            "steps": [
                _step(
                    step_id="discover-django-root",
                    title="Django proje kokunu bul",
                    description="Repo icinde manage.py ara.",
                    permission="read",
                    tool={
                        "tool_name": "find_files",
                        "arguments": {
                            "pattern": "manage.py",
                        },
                        "permission": "read",
                        "cwd": None,
                    },
                ),
                _step(
                    step_id="create-users-app",
                    title="users app olustur",
                    description=(
                        "Onceki observation'da bulunan manage.py "
                        "klasorunde startapp users calistir."
                    ),
                    permission="execute",
                    tool=None,
                    depends_on=[
                        "discover-django-root",
                    ],
                ),
                _step(
                    step_id="verify-users-app",
                    title="users app dogrula",
                    description=(
                        "Bulunan Django root altinda "
                        "users/apps.py varligini kontrol et."
                    ),
                    permission="read",
                    tool=None,
                    depends_on=[
                        "create-users-app",
                    ],
                    verification_criteria=[
                        "users-app-exists",
                    ],
                ),
            ],
        }
    )

    plan = build_general_task_plan(
        "Şimdi bu projeye users diye bir app oluştur.",
        model_client=client,
        tool_registry=build_contract_registry(),
    )

    first = first_tool_step(plan)

    assert first is not None
    assert first.tool is not None
    assert first.tool.tool_name == "find_files"
    assert first.tool.arguments == {
        "pattern": "manage.py",
    }
    assert first.permission == Permission.READ

    assert plan.steps[1].depends_on == [
        "discover-django-root",
    ]

    system_prompt = client.calls[0][
        "system_prompt"
    ]

    assert (
        "Bilmedigin proje yapisini ASLA varsayma"
        in system_prompt
    )
    assert "run_process" in system_prompt


def test_package_install_can_plan_execute_tool():
    client = FakeModelClient(
        {
            "goal": "Django paketini kurmak",
            "summary": "Pip ile Django kur.",
            "success_criteria": [],
            "constraints": [],
            "steps": [
                _step(
                    step_id="install",
                    title="Django kur",
                    description="Pip ile Django kur.",
                    permission="execute",
                    tool={
                        "tool_name": "run_process",
                        "arguments": {
                            "argv": [
                                "python",
                                "-m",
                                "pip",
                                "install",
                                "--upgrade",
                                "django",
                            ],
                        },
                        "permission": "execute",
                        "cwd": None,
                    },
                ),
            ],
        }
    )

    plan = build_general_task_plan(
        "Django'nun en son sürümünü kur.",
        model_client=client,
        tool_registry=build_contract_registry(),
    )

    assert plan_uses_tool(
        plan,
        "run_process",
    )


def test_information_question_may_use_model_only_step():
    client = FakeModelClient(
        {
            "goal": "Django'nun ne oldugunu aciklamak",
            "summary": "Kullaniciya bilgi ver.",
            "success_criteria": [],
            "constraints": [],
            "steps": [
                _step(
                    step_id="answer",
                    title="Yaniti uret",
                    description="Django hakkinda bilgi ver.",
                    permission="read",
                    tool=None,
                ),
            ],
        }
    )

    plan = build_general_task_plan(
        "Django nedir?",
        model_client=client,
        tool_registry=build_contract_registry(),
    )

    assert plan.steps[0].tool is None


def test_unknown_tool_is_rejected():
    client = FakeModelClient(
        {
            "goal": "Test",
            "summary": "Test",
            "success_criteria": [],
            "constraints": [],
            "steps": [
                _step(
                    step_id="x",
                    title="X",
                    description="X",
                    permission="read",
                    tool={
                        "tool_name": "magic_django_tool",
                        "arguments": {},
                        "permission": "read",
                        "cwd": None,
                    },
                ),
            ],
        }
    )

    with pytest.raises(
        GeneralPlannerError,
        match="bilinmeyen tool",
    ):
        build_general_task_plan(
            "Bir sey yap",
            model_client=client,
            tool_registry=build_contract_registry(),
        )


def test_registry_overrides_model_permission_mismatch():
    client = FakeModelClient(
        {
            "goal": "Dosya oku",
            "summary": "README oku",
            "success_criteria": [],
            "constraints": [],
            "steps": [
                _step(
                    step_id="read",
                    title="Oku",
                    description="README oku",
                    permission="write",
                    tool={
                        "tool_name": "read_file",
                        "arguments": {
                            "path": "README.md",
                        },
                        "permission": "execute",
                        "cwd": None,
                    },
                ),
            ],
        }
    )

    plan = build_general_task_plan(
        "README oku",
        model_client=client,
        tool_registry=build_contract_registry(),
    )

    step = plan.steps[0]

    assert (
        step.permission
        == Permission.READ
    )

    assert step.tool is not None

    assert (
        step.tool.permission
        == Permission.READ
    )


def test_invalid_json_is_rejected_cleanly():
    client = FakeModelClient(
        "bu json degil"
    )

    with pytest.raises(
        GeneralPlannerError,
        match="JSON",
    ):
        build_general_task_plan(
            "Test",
            model_client=client,
            tool_registry=build_contract_registry(),
        )


def test_dependency_cycle_is_rejected_by_contract():
    client = FakeModelClient(
        {
            "goal": "Cycle",
            "summary": "Cycle",
            "success_criteria": [],
            "constraints": [],
            "steps": [
                _step(
                    step_id="a",
                    title="A",
                    description="A",
                    permission="read",
                    tool=None,
                    depends_on=["b"],
                ),
                _step(
                    step_id="b",
                    title="B",
                    description="B",
                    permission="read",
                    tool=None,
                    depends_on=["a"],
                ),
            ],
        }
    )

    with pytest.raises(
        GeneralPlannerError,
        match="semasina uymadi",
    ):
        build_general_task_plan(
            "Cycle",
            model_client=client,
            tool_registry=build_contract_registry(),
        )

def test_registry_canonicalizes_execute_permission():
    client = FakeModelClient(
        {
            "goal": "Test calistir",
            "summary": "Komut calistir",
            "success_criteria": [],
            "constraints": [],
            "steps": [
                _step(
                    step_id="execute",
                    title="Komut",
                    description="Python script calistir",
                    permission="read",
                    tool={
                        "tool_name": "run_process",
                        "arguments": {
                            "argv": [
                                "python",
                                "manage.py",
                                "check",
                            ],
                        },
                        "permission": "write",
                        "cwd": None,
                    },
                ),
            ],
        }
    )

    plan = build_general_task_plan(
        "Django check calistir",
        model_client=client,
        tool_registry=build_contract_registry(),
    )

    assert (
        plan.steps[0].permission
        == Permission.EXECUTE
    )

    assert (
        plan.steps[0].tool.permission
        == Permission.EXECUTE
    )

def test_inline_verification_text_is_promoted_to_success_criterion():
    client = FakeModelClient(
        {
            "goal": "Projeyi incele",
            "summary": "Dosyalari listele ve dogrula",
            "success_criteria": [],
            "constraints": [],
            "steps": [
                _step(
                    step_id="step-1",
                    title="Listele",
                    description="Proje yapisini gor",
                    permission="read",
                    tool={
                        "tool_name": "list_files",
                        "arguments": {},
                        "permission": "read",
                        "cwd": None,
                    },
                    verification_criteria=[
                        "Listelenen dosyalar ve klasorler "
                        "projenin yapisini gostermelidir."
                    ],
                ),
            ],
        }
    )

    plan = build_general_task_plan(
        "Projeyi incele",
        model_client=client,
        tool_registry=build_contract_registry(),
    )

    assert len(plan.success_criteria) == 1

    criterion = plan.success_criteria[0]

    assert criterion.description == (
        "Listelenen dosyalar ve klasorler "
        "projenin yapisini gostermelidir."
    )

    assert (
        plan.steps[0].verification_criteria
        == [criterion.criterion_id]
    )


def test_existing_verification_id_is_preserved():
    client = FakeModelClient(
        {
            "goal": "README kontrol et",
            "summary": "README varligini dogrula",
            "success_criteria": [
                {
                    "criterion_id": "readme-exists",
                    "description": "README mevcut olmali",
                    "required": True,
                }
            ],
            "constraints": [],
            "steps": [
                _step(
                    step_id="step-1",
                    title="Kontrol",
                    description="README kontrol et",
                    permission="read",
                    tool={
                        "tool_name": "file_exists",
                        "arguments": {
                            "path": "README.md",
                        },
                        "permission": "read",
                        "cwd": None,
                    },
                    verification_criteria=[
                        "readme-exists"
                    ],
                ),
            ],
        }
    )

    plan = build_general_task_plan(
        "README kontrol et",
        model_client=client,
        tool_registry=build_contract_registry(),
    )

    assert (
        plan.steps[0].verification_criteria
        == ["readme-exists"]
    )

    assert len(plan.success_criteria) == 1

def test_dependent_tool_call_is_deferred_until_observation():
    client = FakeModelClient(
        {
            "goal": "Mevcut projeye users app ekle",
            "summary": "Once root bul, sonra app olustur",
            "success_criteria": [],
            "constraints": [],
            "steps": [
                _step(
                    step_id="discover",
                    title="Root bul",
                    description="manage.py ara",
                    permission="read",
                    tool={
                        "tool_name": "find_files",
                        "arguments": {
                            "pattern": "manage.py",
                        },
                        "permission": "read",
                        "cwd": None,
                    },
                ),
                _step(
                    step_id="create",
                    title="App olustur",
                    description=(
                        "Bulunan Django root icinde "
                        "users app olustur"
                    ),
                    permission="execute",
                    tool={
                        "tool_name": "run_process",
                        "arguments": {
                            "argv": [
                                "create",
                                "app",
                                "users",
                            ],
                        },
                        "permission": "execute",
                        "cwd": None,
                    },
                    depends_on=[
                        "discover"
                    ],
                ),
            ],
        }
    )

    plan = build_general_task_plan(
        "Bu projeye users diye bir app olustur",
        model_client=client,
        tool_registry=build_contract_registry(),
    )

    assert plan.steps[0].tool is not None
    assert (
        plan.steps[0].tool.tool_name
        == "find_files"
    )

    assert plan.steps[1].tool is None


def test_independent_tool_call_is_not_deferred():
    client = FakeModelClient(
        {
            "goal": "README oku",
            "summary": "README oku",
            "success_criteria": [],
            "constraints": [],
            "steps": [
                _step(
                    step_id="read",
                    title="Oku",
                    description="README oku",
                    permission="read",
                    tool={
                        "tool_name": "read_file",
                        "arguments": {
                            "path": "README.md",
                        },
                        "permission": "read",
                        "cwd": None,
                    },
                ),
            ],
        }
    )

    plan = build_general_task_plan(
        "README oku",
        model_client=client,
        tool_registry=build_contract_registry(),
    )

    assert plan.steps[0].tool is not None
