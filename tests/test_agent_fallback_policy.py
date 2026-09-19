import pytest

from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)
from factory.agents.fallback import (
    AgentFallbackPolicy,
    build_fallback_candidates,
    remaining_fallback_candidates,
)
from factory.agents.router import (
    AgentRouter,
)


def _router():
    return AgentRouter(
        [
            AgentDescriptor(
                name="ollama-coder",
                provider_name="ollama",
                capabilities=frozenset(
                    {
                        AgentCapability.WRITE_CODE,
                    }
                ),
            ),
            AgentDescriptor(
                name="gemini-coder",
                provider_name="gemini_cli",
                capabilities=frozenset(
                    {
                        AgentCapability.WRITE_CODE,
                    }
                ),
            ),
            AgentDescriptor(
                name="codex-coder",
                provider_name="codex",
                capabilities=frozenset(
                    {
                        AgentCapability.WRITE_CODE,
                    }
                ),
            ),
        ]
    )


def test_preferred_provider_is_first():
    candidates = build_fallback_candidates(
        _router(),
        {
            AgentCapability.WRITE_CODE,
        },
        preferred_provider="gemini_cli",
    )

    assert [
        item.name
        for item in candidates
    ] == [
        "gemini-coder",
        "ollama-coder",
        "codex-coder",
    ]


def test_policy_limits_candidate_count():
    candidates = build_fallback_candidates(
        _router(),
        {
            AgentCapability.WRITE_CODE,
        },
        policy=AgentFallbackPolicy(
            max_attempts=2
        ),
    )

    assert len(candidates) == 2


def test_failed_provider_can_be_skipped():
    candidates = build_fallback_candidates(
        _router(),
        {
            AgentCapability.WRITE_CODE,
        },
    )

    remaining = (
        remaining_fallback_candidates(
            candidates,
            failed_agent=candidates[0],
            policy=AgentFallbackPolicy(
                skip_failed_provider=True
            ),
        )
    )

    assert [
        item.provider_name
        for item in remaining
    ] == [
        "gemini_cli",
        "codex",
    ]


def test_policy_rejects_zero_attempts():
    with pytest.raises(
        ValueError,
        match="max_attempts",
    ):
        AgentFallbackPolicy(
            max_attempts=0
        )
