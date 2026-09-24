from types import SimpleNamespace

from factory.semantic_task_router import (
    route_task_semantic,
)


class FakeModelClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=self.content
        )


def test_django_install_is_semantic_execute():
    client = FakeModelClient(
        '{"kind":"execute","intent":"package_install","target":"django",'
        '"confidence":0.98,"reason":"Paket kurulumu istendi."}'
    )

    route = route_task_semantic(
        "Django'nun en son surumunu kur.",
        model_client=client,
    )

    assert route.kind == "execute"
    assert route.intent == "package_install"
    assert route.target == "django"
    assert route.source == "semantic"


def test_django_question_is_read():
    client = FakeModelClient(
        '{"kind":"read","intent":"explain_or_inspect","target":"django",'
        '"confidence":0.99,"reason":"Bilgi isteniyor."}'
    )

    route = route_task_semantic(
        "Django nedir?",
        model_client=client,
    )

    assert route.kind == "read"


def test_file_change_is_write():
    client = FakeModelClient(
        '{"kind":"write","intent":"code_change","target":"requirements.txt",'
        '"confidence":0.96,"reason":"Dosya degisikligi istendi."}'
    )

    route = route_task_semantic(
        "requirements.txt icine django ekle",
        model_client=client,
    )

    assert route.kind == "write"
    assert route.intent == "code_change"


def test_low_confidence_falls_back_to_deterministic():
    client = FakeModelClient(
        '{"kind":"execute","intent":"package_install","target":"django",'
        '"confidence":0.20,"reason":"Emin degilim."}'
    )

    route = route_task_semantic(
        "Bu projeyi incele ve ne yaptigini acikla.",
        model_client=client,
    )

    assert route.source == "deterministic_fallback"
    assert route.kind == "read"


def test_invalid_json_falls_back_without_crash():
    client = FakeModelClient(
        "bu json degil"
    )

    route = route_task_semantic(
        "README.md dosyasini guncelle.",
        model_client=client,
    )

    assert route.source == "deterministic_fallback"
    assert route.kind in {
        "read",
        "write",
        "execute",
    }


def test_django_project_creation_is_framework_scaffold():
    client = FakeModelClient(
        '{"kind":"execute","intent":"framework_scaffold",'
        '"target":"okulprojesi","framework":"django",'
        '"confidence":0.99,"reason":"Django projesi olusturulacak."}'
    )

    route = route_task_semantic(
        "Bu klasorde okulprojesi adinda yeni bir Django projesi olustur.",
        model_client=client,
    )

    assert route.kind == "execute"
    assert route.intent == "framework_scaffold"
    assert route.framework == "django"
    assert route.target == "okulprojesi"
