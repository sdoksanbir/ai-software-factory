from types import SimpleNamespace

from factory.agents.providers.gemini import (
    GeminiCliProvider,
)
from factory.agents.providers.model_client import (
    ModelClientProvider,
)


def make_model_client(
    config,
):
    return SimpleNamespace(
        config=config
    )


def test_explicitly_enabled_gemini_is_registered():
    client = make_model_client(
        {
            "providers": {
                "gemini_cli": {
                    "enabled": True,
                    "executable": (
                        "custom-gemini"
                    ),
                    "default_timeout": 75,
                    "approval_mode": (
                        "auto_edit"
                    ),
                }
            },
            "models": {},
        }
    )

    provider = ModelClientProvider(
        client
    )

    assert provider.registry.has(
        "gemini_cli"
    )

    gemini = provider.registry.get(
        "gemini_cli"
    )

    assert isinstance(
        gemini,
        GeminiCliProvider,
    )

    assert (
        gemini.executable
        == "custom-gemini"
    )

    assert (
        gemini.default_timeout
        == 75
    )

    assert (
        gemini.approval_mode
        == "auto_edit"
    )


def test_gemini_defaults_are_applied():
    client = make_model_client(
        {
            "providers": {
                "gemini_cli": {
                    "enabled": True,
                }
            },
            "models": {},
        }
    )

    provider = ModelClientProvider(
        client
    )

    gemini = provider.registry.get(
        "gemini_cli"
    )

    assert gemini.executable == (
        "gemini"
    )

    assert (
        gemini.default_timeout
        == 120
    )

    assert (
        gemini.approval_mode
        == "plan"
    )


def test_explicitly_disabled_gemini_is_not_registered():
    client = make_model_client(
        {
            "providers": {
                "gemini_cli": {
                    "enabled": False,
                }
            },
            "models": {
                "reviewer": {
                    "provider": (
                        "gemini_cli"
                    )
                }
            },
        }
    )

    provider = ModelClientProvider(
        client
    )

    assert not provider.registry.has(
        "gemini_cli"
    )


def test_model_role_enables_gemini_implicitly():
    client = make_model_client(
        {
            "providers": {},
            "models": {
                "reviewer": {
                    "provider": (
                        "gemini_cli"
                    ),
                    "model": (
                        "gemini-2.5-pro"
                    ),
                }
            },
        }
    )

    provider = ModelClientProvider(
        client
    )

    assert provider.registry.has(
        "gemini_cli"
    )


def test_gemini_descriptor_is_registered():
    client = make_model_client(
        {
            "providers": {
                "gemini_cli": {
                    "enabled": True,
                }
            },
            "models": {},
        }
    )

    provider = ModelClientProvider(
        client
    )

    descriptor = (
        provider.registry.descriptor(
            "gemini_cli"
        )
    )

    assert descriptor.name == (
        "gemini_cli"
    )

    assert (
        descriptor.executable
        == "gemini"
    )

    assert (
        descriptor.metadata[
            "cli_family"
        ]
        == "google_gemini"
    )

    assert (
        descriptor.metadata[
            "approval_mode"
        ]
        == "plan"
    )
