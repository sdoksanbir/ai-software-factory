from factory.capability_discovery import (
    CapabilityCandidateStore,
    detect_node_entry_signals,
    detect_python_entry_signals,
)


def test_python_main_and_argv_are_entry_signals():
    source = (
        "import sys\n"
        "if __name__ == '__main__':\n"
        "    print(sys.argv)\n"
    )
    signals = detect_python_entry_signals(source)
    assert "python_main_guard" in signals
    assert "sys_argv" in signals


def test_python_library_modules_are_not_entry_points():
    settings = (
        "DEBUG = True\n"
        "INSTALLED_APPS = []\n"
    )
    init_mod = (
        "from .models import User\n"
    )
    asgi = (
        "import os\n"
        "from django.core.asgi import get_asgi_application\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'x.settings')\n"
        "application = get_asgi_application()\n"
    )
    assert detect_python_entry_signals(settings) == ()
    assert detect_python_entry_signals(init_mod) == ()
    assert detect_python_entry_signals(asgi) == ()


def test_node_process_argv_is_entry_signal():
    source = (
        "const args = process.argv.slice(2);\n"
        "console.log(args);\n"
    )
    assert "process_argv" in detect_node_entry_signals(
        source
    )


def test_candidate_store_rejects_non_entry_scripts():
    store = CapabilityCandidateStore()
    assert (
        store.assess_file(
            script_path="pkg/settings.py",
            content="DEBUG = True\n",
            source_evidence_ref="ev-1",
        )
        is None
    )
    assert store.assessed("pkg/settings.py")
    assert not store.is_candidate("pkg/settings.py")


def test_candidate_store_accepts_cli_script():
    store = CapabilityCandidateStore()
    candidate = store.assess_file(
        script_path="pkg/tool.py",
        content=(
            "import sys\n"
            "if __name__ == '__main__':\n"
            "    print(sys.argv)\n"
        ),
        source_evidence_ref="ev-2",
    )
    assert candidate is not None
    assert candidate.logical_prefix == [
        "python",
        "tool.py",
    ]
    assert "python_main_guard" in candidate.signals
