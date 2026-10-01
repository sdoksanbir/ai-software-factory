from types import SimpleNamespace

from factory.semantic_task_router import (
    route_task_semantic,
)


class FakeModelClient:
    def __init__(
        self,
        content=None,
        *,
        error=None,
    ):
        self.content = content
        self.error = error
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        if self.error is not None:
            raise self.error

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


def test_provider_failure_html_prototype_fallback_write():
    client = FakeModelClient(
        error=RuntimeError("model down"),
    )

    route = route_task_semantic(
        "bana statik bir HTML tasarım prototipi yap",
        model_client=client,
    )

    assert route.kind == "write"
    assert route.source == "deterministic_fallback"


def test_provider_failure_repo_analizi_fallback_read():
    client = FakeModelClient(
        error=RuntimeError("model down"),
    )

    route = route_task_semantic(
        "repo analizi yap",
        model_client=client,
    )

    assert route.kind == "read"
    assert route.source == "deterministic_fallback"


def test_provider_failure_testleri_calistir_fallback_execute():
    client = FakeModelClient(
        error=RuntimeError("model down"),
    )

    route = route_task_semantic(
        "testleri çalıştır",
        model_client=client,
    )

    assert route.kind == "execute"
    assert route.source == "deterministic_fallback"


def test_provider_failure_python_script_fallback_execute():
    client = FakeModelClient(
        error=RuntimeError("model down"),
    )

    route = route_task_semantic(
        "python script.py çalıştır",
        model_client=client,
    )

    assert route.kind == "execute"
    assert route.source == "deterministic_fallback"


def test_low_confidence_html_prototype_fallback_write():
    client = FakeModelClient(
        '{"kind":"read","intent":"explain_or_inspect",'
        '"confidence":0.20,"reason":"Emin degilim."}'
    )

    route = route_task_semantic(
        "bana statik bir HTML tasarım prototipi yap",
        model_client=client,
    )

    assert route.kind == "write"
    assert route.source == "deterministic_fallback"


def test_git_tag_command_is_execute_command():
    client = FakeModelClient(
        '{"kind":"execute","intent":"execute_command",'
        '"target":"git tag e2e-execute-mutation-test",'
        '"confidence":0.97,'
        '"reason":"Generic komut calistirma istendi."}'
    )

    route = route_task_semantic(
        "git tag e2e-execute-mutation-test komutunu çalıştır.",
        model_client=client,
    )

    assert route.kind == "execute"
    assert route.intent == "execute_command"
    assert route.source == "semantic"


def test_python_script_invocation_is_execute_command():
    client = FakeModelClient(
        '{"kind":"execute","intent":"execute_command",'
        '"target":"script.py","confidence":0.96,'
        '"reason":"Script calistirma istendi."}'
    )

    route = route_task_semantic(
        "python script.py çalıştır",
        model_client=client,
    )

    assert route.kind == "execute"
    assert route.intent == "execute_command"
    assert route.source == "semantic"


def test_real_test_request_remains_run_tests():
    client = FakeModelClient(
        '{"kind":"execute","intent":"run_tests",'
        '"target":null,"confidence":0.98,'
        '"reason":"Test suite calistirilacak."}'
    )

    route = route_task_semantic(
        "testleri çalıştır",
        model_client=client,
    )

    assert route.kind == "execute"
    assert route.intent == "run_tests"
    assert route.source == "semantic"


def test_system_prompt_covers_execute_command_semantics():
    client = FakeModelClient(
        '{"kind":"execute","intent":"execute_command",'
        '"confidence":0.95,"reason":"komut"}'
    )

    route_task_semantic(
        "git tag e2e-execute-mutation-test komutunu çalıştır.",
        model_client=client,
    )

    assert len(client.calls) == 1
    system_prompt = client.calls[0]["system_prompt"]
    assert "execute_command" in system_prompt
    assert (
        "git tag e2e-execute-mutation-test komutunu calistir"
        in system_prompt
    )
    assert "python script.py calistir" in system_prompt
    assert "run_tests yalnizca" in system_prompt
    assert "generic komut calistirma" in system_prompt.casefold()


def test_unsupported_intent_falls_back_to_unknown():
    client = FakeModelClient(
        '{"kind":"execute","intent":"not_a_real_intent",'
        '"confidence":0.99,"reason":"desteklenmeyen intent"}'
    )

    route = route_task_semantic(
        "python script.py çalıştır",
        model_client=client,
    )

    assert route.kind == "execute"
    assert route.intent == "unknown"
    assert route.source == "semantic"
