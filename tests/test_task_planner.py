from types import SimpleNamespace

import pytest

from factory.task_planner import (
    build_task_plan,
    create_and_save_task_plan,
    should_create_multi_step_plan,
)
from factory.task_plan_store import get_task_plan


class FakeModelClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=self.content
        )


def test_simple_task_does_not_call_model():
    client = FakeModelClient(
        '{"steps":[]}'
    )

    result = build_task_plan(
        "hello.txt dosyasi olustur",
        model_client=client,
    )

    assert result["planner_mode"] == (
        "single_step"
    )
    assert len(result["steps"]) == 1
    assert result["steps"][0]["kind"] == (
        "write"
    )
    assert client.calls == []


def test_complex_task_detected():
    assert should_create_multi_step_plan(
        "Backend API ekle, frontend'i bağla "
        "ve testlerini yaz."
    )


def test_complex_task_uses_model():
    client = FakeModelClient(
        """
        {
          "summary": "Kullanıcı kaydı",
          "steps": [
            {
              "title": "Mevcut yapıyı incele",
              "instruction": "Auth yapısını incele.",
              "kind": "read"
            },
            {
              "title": "Backend'i geliştir",
              "instruction": "Kayıt endpointini ekle.",
              "kind": "write"
            },
            {
              "title": "Doğrula",
              "instruction": "Testleri çalıştır.",
              "kind": "verify"
            }
          ]
        }
        """
    )

    result = build_task_plan(
        "Backend API ekle, frontend'i bağla "
        "ve testlerini yaz.",
        model_client=client,
        model_name="fake-model",
    )

    assert result["planner_mode"] == (
        "multi_step"
    )

    assert [
        step["kind"]
        for step in result["steps"]
    ] == [
        "read",
        "write",
        "verify",
    ]

    assert len(client.calls) == 1

    assert (
        client.calls[0][
            "model_name_override"
        ]
        == "fake-model"
    )


def test_markdown_json_is_accepted():
    client = FakeModelClient(
        """```json
        {
          "summary": "Plan",
          "steps": [
            {
              "title": "İncele",
              "instruction": "Yapıyı incele.",
              "kind": "read"
            },
            {
              "title": "Değiştir",
              "instruction": "Kodu değiştir.",
              "kind": "write"
            }
          ]
        }
        ```"""
    )

    result = build_task_plan(
        "API yapısını incele ve endpoint ekle",
        model_client=client,
        model_name="fake-model",
    )

    assert len(result["steps"]) == 2


def test_invalid_kind_is_rejected():
    client = FakeModelClient(
        """
        {
          "steps": [
            {
              "title": "Bir",
              "instruction": "Birinci",
              "kind": "read"
            },
            {
              "title": "İki",
              "instruction": "İkinci",
              "kind": "delete_everything"
            }
          ]
        }
        """
    )

    with pytest.raises(ValueError):
        build_task_plan(
            "Backend API yapisini incele ve kodu guncelle",
            model_client=client,
            model_name="fake-model",
        )


def test_too_many_steps_rejected():
    steps = [
        {
            "title": f"Step {i}",
            "instruction": f"Do {i}",
            "kind": "write",
        }
        for i in range(7)
    ]

    import json

    client = FakeModelClient(
        json.dumps(
            {
                "summary": "Too many",
                "steps": steps,
            }
        )
    )

    with pytest.raises(ValueError):
        build_task_plan(
            "Backend, frontend, API ve test "
            "sistemlerini güncelle.",
            model_client=client,
            model_name="fake-model",
        )


def test_create_and_save_plan(tmp_path):
    db_path = tmp_path / "factory.db"

    client = FakeModelClient(
        """
        {
          "summary": "Entegrasyon",
          "steps": [
            {
              "title": "İncele",
              "instruction": "Mevcut sistemi incele.",
              "kind": "read"
            },
            {
              "title": "Uygula",
              "instruction": "Değişikliği uygula.",
              "kind": "write"
            },
            {
              "title": "Test",
              "instruction": "Sonucu doğrula.",
              "kind": "verify"
            }
          ]
        }
        """
    )

    created = create_and_save_task_plan(
        "TASK-2001",
        "Backend API ekle, frontend'i bağla "
        "ve testlerini yaz.",
        model_client=client,
        model_name="fake-model",
        db_path=db_path,
    )

    loaded = get_task_plan(
        "TASK-2001",
        db_path=db_path,
    )

    assert created["planner_mode"] == (
        "multi_step"
    )
    assert loaded is not None
    assert len(loaded["steps"]) == 3
    assert loaded["summary"] == "Entegrasyon"



def test_full_six_step_plan_makes_room_for_read():
    from factory.task_planner import (
        MAX_PLAN_STEPS,
        _ensure_read_first,
    )

    steps = [
        {
            "title": "Backend",
            "instruction": "Backend kodunu yaz.",
            "kind": "write",
        },
        {
            "title": "API",
            "instruction": "API endpointini yaz.",
            "kind": "write",
        },
        {
            "title": "Frontend",
            "instruction": "Frontend formunu yaz.",
            "kind": "write",
        },
        {
            "title": "Baglanti",
            "instruction": "Frontend API baglantisini yaz.",
            "kind": "write",
        },
        {
            "title": "Testler",
            "instruction": "Test kodlarini yaz.",
            "kind": "write",
        },
        {
            "title": "Dogrula",
            "instruction": "Tum testleri calistir.",
            "kind": "verify",
        },
    ]

    result = _ensure_read_first(
        "Komple sistemi olustur.",
        steps,
    )

    assert len(result) == MAX_PLAN_STEPS
    assert result[0]["kind"] == "read"
    assert result[-1]["kind"] == "verify"

    combined_instructions = "\n".join(
        step["instruction"]
        for step in result
    )

    assert "Backend kodunu yaz." in combined_instructions
    assert "API endpointini yaz." in combined_instructions
    assert "Frontend formunu yaz." in combined_instructions
    assert "Test kodlarini yaz." in combined_instructions
    assert "Tum testleri calistir." in combined_instructions


COMPLEX_PROMPT = (
    "Backend API ekle, frontend'i bagla "
    "ve testlerini yaz."
)

VALID_PLAN_JSON = """
{
  "summary": "Entegrasyon",
  "steps": [
    {
      "title": "Incele",
      "instruction": "Yapiyi incele.",
      "kind": "read"
    },
    {
      "title": "Yaz",
      "instruction": "Kodu yaz.",
      "kind": "write"
    },
    {
      "title": "Dogrula",
      "instruction": "Testleri calistir.",
      "kind": "verify"
    }
  ]
}
"""


def test_build_task_plan_keeps_domain_contract():
    client = FakeModelClient(VALID_PLAN_JSON)

    result = build_task_plan(
        COMPLEX_PROMPT,
        model_client=client,
        model_name="fake-model",
    )

    assert result["planner_mode"] == "multi_step"
    assert "summary" in result
    assert "steps" in result
    assert "provider" not in result
    assert "model" not in result
    assert "configured_provider" not in result
    assert "actual_provider" not in result
    assert "transport_fallback_used" not in result
    assert "fallback_used" not in result
    assert "router_fallback_used" not in result


def test_complete_planner_returns_agent_result():
    from factory.agents.contracts import (
        AgentResult,
    )
    from factory.task_planner import (
        PLANNER_MODEL_ROLE,
        _complete_planner,
    )

    client = FakeModelClient(VALID_PLAN_JSON)

    result = _complete_planner(
        client,
        system_prompt="system",
        user_prompt="user",
        model_name="fake-model",
    )

    assert isinstance(result, AgentResult)
    assert result.content == VALID_PLAN_JSON
    assert result.provider == "model_client"
    assert result.model == "fake-model"
    assert result.metadata[
        "actual_provider"
    ] == "model_client"
    assert result.metadata[
        "actual_model"
    ] == "fake-model"
    assert "router_fallback_used" not in (
        result.metadata
    )

    assert client.calls[0]["model_role"] == (
        PLANNER_MODEL_ROLE
    )


def test_complete_planner_preserves_explicit_timeout():
    from factory.task_planner import (
        _complete_planner,
    )

    client = FakeModelClient(VALID_PLAN_JSON)

    _complete_planner(
        client,
        system_prompt="system",
        user_prompt="user",
        model_name="fake-model",
        timeout=30,
    )

    assert client.calls[0]["timeout"] == 30


def test_complete_planner_uses_role_config_timeout():
    from factory.task_planner import (
        _complete_planner,
    )

    client = FakeModelClient(VALID_PLAN_JSON)
    client.config = {
        "models": {
            "fast_local": {
                "provider": "openai",
                "model": "cloud-model",
                "timeout_seconds": 75,
            }
        }
    }

    _complete_planner(
        client,
        system_prompt="system",
        user_prompt="user",
        model_name="fake-model",
    )

    assert client.calls[0]["timeout"] == 75


def test_complete_planner_uses_default_timeout():
    from factory.agents.timeout_policy import (
        DEFAULT_AGENT_TIMEOUT,
    )
    from factory.task_planner import (
        _complete_planner,
    )

    client = FakeModelClient(VALID_PLAN_JSON)

    _complete_planner(
        client,
        system_prompt="system",
        user_prompt="user",
        model_name="fake-model",
    )

    assert client.calls[0]["timeout"] == (
        DEFAULT_AGENT_TIMEOUT
    )


def test_complete_planner_keeps_transport_fallback_metadata():
    from factory.models import ModelResponse
    from factory.task_planner import (
        _complete_planner,
    )

    class FallbackClient:
        config = {
            "models": {
                "fast_local": {
                    "provider": "openrouter",
                    "model": "primary-model",
                    "timeout_seconds": 40,
                }
            }
        }
        calls = []

        def complete(self, **kwargs):
            self.calls.append(kwargs)

            return ModelResponse(
                content=VALID_PLAN_JSON,
                model="fallback-model",
                provider="ollama",
                fallback_used=True,
            )

    client = FallbackClient()

    result = _complete_planner(
        client,
        system_prompt="system",
        user_prompt="user",
        model_name="ignored",
    )

    assert result.provider == "ollama"
    assert result.model == "fallback-model"
    assert result.metadata[
        "configured_provider"
    ] == "openrouter"
    assert result.metadata[
        "transport_fallback_used"
    ] is True
    assert result.metadata[
        "fallback_used"
    ] is True
    assert "router_fallback_used" not in (
        result.metadata
    )


def test_complete_planner_normalizes_content_only_response():
    from factory.agents.contracts import (
        AgentResult,
    )
    from factory.task_planner import (
        _complete_planner,
    )

    client = FakeModelClient(VALID_PLAN_JSON)

    result = _complete_planner(
        client,
        system_prompt="system",
        user_prompt="user",
        model_name="fake-model",
    )

    assert isinstance(result, AgentResult)
    assert result.provider == "model_client"
    assert result.model == "fake-model"
    assert result.metadata[
        "transport_fallback_used"
    ] is False

    plan = build_task_plan(
        COMPLEX_PROMPT,
        model_client=FakeModelClient(
            VALID_PLAN_JSON
        ),
        model_name="fake-model",
    )

    assert [
        step["kind"]
        for step in plan["steps"]
    ] == ["read", "write", "verify"]
    assert "transport_fallback_used" not in plan
