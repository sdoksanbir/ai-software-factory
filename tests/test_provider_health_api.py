from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.app as api_app


class FakeHealth:
    def __init__(
        self,
        provider_name: str,
    ):
        self.provider_name = (
            provider_name
        )

    def as_dict(self):
        return {
            "provider_name": (
                self.provider_name
            ),
            "status": "available",
            "available": True,
        }


class FakeRegistry:
    def __init__(self):
        self.calls = []

        self.known = {
            "codex_cli",
            "ollama",
        }

    def has(
        self,
        provider_name,
    ):
        normalized = (
            str(provider_name)
            .strip()
            .lower()
        )

        return normalized in self.known

    def runtime_health_all(
        self,
        *,
        force_refresh=False,
    ):
        self.calls.append(
            (
                "all",
                force_refresh,
            )
        )

        return (
            FakeHealth(
                "codex_cli"
            ),
            FakeHealth(
                "ollama"
            ),
        )

    def runtime_health(
        self,
        provider_name,
        *,
        force_refresh=False,
    ):
        normalized = (
            str(provider_name)
            .strip()
            .lower()
        )

        self.calls.append(
            (
                normalized,
                force_refresh,
            )
        )

        return FakeHealth(
            normalized
        )


def install_fake_registry(
    monkeypatch,
):
    registry = FakeRegistry()

    monkeypatch.setattr(
        api_app,
        "API_PROVIDER_REGISTRY",
        registry,
    )

    return registry


def test_provider_health_list(
    monkeypatch,
):
    registry = install_fake_registry(
        monkeypatch
    )

    result = (
        api_app
        .provider_health_endpoint()
    )

    assert result["count"] == 2

    assert (
        result["refresh"]
        is False
    )

    assert [
        item["provider_name"]
        for item
        in result["providers"]
    ] == [
        "codex_cli",
        "ollama",
    ]

    assert registry.calls == [
        (
            "all",
            False,
        ),
    ]


def test_provider_health_list_refresh(
    monkeypatch,
):
    registry = install_fake_registry(
        monkeypatch
    )

    result = (
        api_app
        .provider_health_endpoint(
            refresh=True
        )
    )

    assert (
        result["refresh"]
        is True
    )

    assert registry.calls == [
        (
            "all",
            True,
        ),
    ]


def test_provider_health_detail(
    monkeypatch,
):
    registry = install_fake_registry(
        monkeypatch
    )

    result = (
        api_app
        .provider_health_detail_endpoint(
            "CODEX_CLI",
            refresh=False,
        )
    )

    assert (
        result["provider_name"]
        == "codex_cli"
    )

    assert registry.calls == [
        (
            "codex_cli",
            False,
        ),
    ]


def test_provider_health_detail_refresh(
    monkeypatch,
):
    registry = install_fake_registry(
        monkeypatch
    )

    result = (
        api_app
        .provider_health_detail_endpoint(
            "codex_cli",
            refresh=True,
        )
    )

    assert (
        result["provider_name"]
        == "codex_cli"
    )

    assert registry.calls == [
        (
            "codex_cli",
            True,
        ),
    ]


def test_unknown_provider_returns_404(
    monkeypatch,
):
    install_fake_registry(
        monkeypatch
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        (
            api_app
            .provider_health_detail_endpoint(
                "missing_provider"
            )
        )

    assert (
        exc_info.value.status_code
        == 404
    )

    assert (
        "missing_provider"
        in str(
            exc_info.value.detail
        )
    )


def test_build_orchestrator_uses_shared_registry(
    monkeypatch,
):
    registry = FakeRegistry()

    monkeypatch.setattr(
        api_app,
        "API_PROVIDER_REGISTRY",
        registry,
    )

    captured = {}

    class FakeOrchestrator:
        def __init__(
            self,
            project_path=".",
            worktree_root=None,
            provider_registry=None,
        ):
            captured[
                "project_path"
            ] = project_path

            captured[
                "provider_registry"
            ] = provider_registry

    monkeypatch.setattr(
        api_app,
        "Orchestrator",
        FakeOrchestrator,
    )

    task = SimpleNamespace(
        project_id=None
    )

    api_app.build_orchestrator_for_task(
        task
    )

    assert (
        captured[
            "provider_registry"
        ]
        is registry
    )


def test_project_orchestrator_uses_shared_registry(
    monkeypatch,
):
    registry = FakeRegistry()

    monkeypatch.setattr(
        api_app,
        "API_PROVIDER_REGISTRY",
        registry,
    )

    monkeypatch.setattr(
        api_app,
        "db_get_project",
        lambda project_id: {
            "project_id": project_id,
            "path": r"C:\Projects\Demo",
        },
    )

    captured = {}

    class FakeOrchestrator:
        def __init__(
            self,
            project_path=".",
            worktree_root=None,
            provider_registry=None,
        ):
            captured[
                "project_path"
            ] = project_path

            captured[
                "provider_registry"
            ] = provider_registry

    monkeypatch.setattr(
        api_app,
        "Orchestrator",
        FakeOrchestrator,
    )

    task = SimpleNamespace(
        project_id="PROJECT-1001"
    )

    api_app.build_orchestrator_for_task(
        task
    )

    assert (
        captured["project_path"]
        == r"C:\Projects\Demo"
    )

    assert (
        captured[
            "provider_registry"
        ]
        is registry
    )
