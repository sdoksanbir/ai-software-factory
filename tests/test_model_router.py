from factory.model_router import (
    CODER_MODEL,
    FAST_MODEL,
    route_model,
)


AVAILABLE = [
    "qwen2.5-coder:32b",
    "qwen2.5-coder:14b",
    "llama3.1:8b",
]


def test_general_task_uses_fast_model():
    route = route_model(
        "Bugunku proje durumunu kisaca ozetle.",
        AVAILABLE,
    )

    assert route.model == FAST_MODEL
    assert route.profile == "fast_local"


def test_python_task_uses_coder_model():
    route = route_model(
        (
            "math_utils.py dosyasinda "
            "factorial(n) fonksiyonu olustur."
        ),
        AVAILABLE,
    )

    assert route.model == CODER_MODEL
    assert route.profile == "coder_local"
    assert route.code_score > 0


def test_react_task_uses_coder_model():
    route = route_model(
        (
            "React component icindeki bug'i "
            "duzelt ve test ekle."
        ),
        AVAILABLE,
    )

    assert route.model == CODER_MODEL


def test_32b_is_never_auto_selected():
    route = route_model(
        "Python kodunu refactor et.",
        [
            "qwen2.5-coder:32b",
            "llama3.1:8b",
        ],
    )

    assert route.model == FAST_MODEL
    assert route.model != "qwen2.5-coder:32b"


def test_coder_fallback():
    route = route_model(
        "TypeScript API endpoint ekle.",
        [
            "llama3.1:8b",
        ],
    )

    assert route.model == FAST_MODEL


def test_fast_fallback_to_coder():
    route = route_model(
        "Bu metni kisaca ozetle.",
        [
            "qwen2.5-coder:14b",
        ],
    )

    assert route.model == CODER_MODEL


def test_empty_prompt_rejected():
    try:
        route_model("   ", AVAILABLE)
    except ValueError:
        return

    raise AssertionError(
        "Bos prompt ValueError vermeliydi."
    )
