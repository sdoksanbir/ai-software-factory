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
        "Backend API ekle, frontend'i ba?la "
        "ve testlerini yaz."
    )


def test_complex_task_uses_model():
    client = FakeModelClient(
        """
        {
          "summary": "Kullan?c? kayd?",
          "steps": [
            {
              "title": "Mevcut yap?y? incele",
              "instruction": "Auth yap?s?n? incele.",
              "kind": "read"
            },
            {
              "title": "Backend'i geli?tir",
              "instruction": "Kay?t endpointini ekle.",
              "kind": "write"
            },
            {
              "title": "Do?rula",
              "instruction": "Testleri ?al??t?r.",
              "kind": "verify"
            }
          ]
        }
        """
    )

    result = build_task_plan(
        "Backend API ekle, frontend'i ba?la "
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
              "title": "?ncele",
              "instruction": "Yap?y? incele.",
              "kind": "read"
            },
            {
              "title": "De?i?tir",
              "instruction": "Kodu de?i?tir.",
              "kind": "write"
            }
          ]
        }
        ```"""
    )

    result = build_task_plan(
        "API yap?s?n? incele ve endpoint ekle",
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
              "title": "?ki",
              "instruction": "?kinci",
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
            "sistemlerini g?ncelle.",
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
              "title": "?ncele",
              "instruction": "Mevcut sistemi incele.",
              "kind": "read"
            },
            {
              "title": "Uygula",
              "instruction": "De?i?ikli?i uygula.",
              "kind": "write"
            },
            {
              "title": "Test",
              "instruction": "Sonucu do?rula.",
              "kind": "verify"
            }
          ]
        }
        """
    )

    created = create_and_save_task_plan(
        "TASK-2001",
        "Backend API ekle, frontend'i ba?la "
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
