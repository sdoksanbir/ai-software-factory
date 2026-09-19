import pytest

from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.router import (
    AgentRouter,
)


def _reader():
    return AgentDescriptor(
        name="local-reader",
        provider_name="ollama",
        capabilities=frozenset(
            {
                AgentCapability.READ_REPOSITORY,
            }
        ),
    )


def _coder():
    return AgentDescriptor(
        name="local-coder",
        provider_name="ollama",
        capabilities=frozenset(
            {
                AgentCapability.READ_REPOSITORY,
                AgentCapability.WRITE_CODE,
                AgentCapability.RUN_TESTS,
            }
        ),
    )


def _cloud_reviewer():
    return AgentDescriptor(
        name="cloud-reviewer",
        provider_name="gemini_cli",
        capabilities=frozenset(
            {
                AgentCapability.READ_REPOSITORY,
                AgentCapability.REVIEW_CODE,
            }
        ),
    )


def test_router_selects_matching_agent():
    router = AgentRouter(
        [
            _reader(),
            _coder(),
        ]
    )

    selected = router.route(
        {
            AgentCapability.WRITE_CODE,
            AgentCapability.RUN_TESTS,
        }
    )

    assert selected.name == "local-coder"


def test_router_filters_by_provider():
    router = AgentRouter(
        [
            _coder(),
            _cloud_reviewer(),
        ]
    )

    selected = router.route(
        {
            AgentCapability.READ_REPOSITORY,
        },
        preferred_provider="gemini_cli",
    )

    assert selected.name == "cloud-reviewer"


def test_router_returns_all_matches():
    router = AgentRouter(
        [
            _reader(),
            _coder(),
        ]
    )

    matches = router.matching_agents(
        {
            AgentCapability.READ_REPOSITORY,
        }
    )

    assert [
        agent.name
        for agent in matches
    ] == [
        "local-reader",
        "local-coder",
    ]


def test_router_rejects_duplicate_agent_name():
    router = AgentRouter()

    router.register(
        _reader()
    )

    with pytest.raises(
        ValueError,
        match="already registered",
    ):
        router.register(
            _reader()
        )


def test_router_raises_when_no_agent_matches():
    router = AgentRouter(
        [
            _reader(),
        ]
    )

    with pytest.raises(
        LookupError,
        match="write_code",
    ):
        router.route(
            {
                AgentCapability.WRITE_CODE,
            }
        )
