from factory.task_router import route_task


def test_summary_is_read():
    route = route_task(
        "Projenin mevcut yapisini kisa sekilde ozetle."
    )

    assert route.kind == "read"


def test_explain_is_read():
    route = route_task(
        "factory/orchestrator.py ne yapiyor, acikla."
    )

    assert route.kind == "read"


def test_analysis_is_read():
    route = route_task(
        "Bu projeyi incele ve mimarisini analiz et."
    )

    assert route.kind == "read"


def test_create_function_is_write():
    route = route_task(
        (
            "math_utils.py dosyasinda "
            "multiply(a, b) fonksiyonu olustur."
        )
    )

    assert route.kind == "write"


def test_fix_bug_is_write():
    route = route_task(
        "React component icindeki hatayi duzelt."
    )

    assert route.kind == "write"


def test_add_tests_is_write():
    route = route_task(
        "factorial fonksiyonunu incele ve testlerini ekle."
    )

    # Hem READ hem WRITE sinyali var.
    # Degisiklik talebi daha oncelikli.
    assert route.kind == "write"


def test_unknown_defaults_to_read():
    route = route_task(
        "Bu proje hakkinda bilgi ver."
    )

    assert route.kind == "read"


def test_empty_prompt_rejected():
    try:
        route_task("   ")
    except ValueError:
        return

    raise AssertionError(
        "Bos prompt ValueError vermeliydi."
    )


def test_virtualenv_setup_is_execute():
    route = route_task(
        "Ana klasore venv sanal ortami kur."
    )
    assert route.kind == "execute"


def test_virtualenv_create_is_execute():
    route = route_task(
        "Proje kokunde .venv olustur."
    )
    assert route.kind == "execute"


def test_virtualenv_explanation_stays_read():
    route = route_task(
        "venv sanal ortami nedir, acikla."
    )
    assert route.kind == "read"


def test_pip_setup_is_execute():
    route = route_task(
        "Simdi bu klasore pip kurulumunu gerceklestir."
    )
    assert route.kind == "execute"


def test_pip_install_is_execute():
    route = route_task(
        "Bu projede pip install islemini gerceklestir."
    )
    assert route.kind == "execute"


def test_pip_explanation_stays_read():
    route = route_task(
        "pip nedir, acikla."
    )
    assert route.kind == "read"
