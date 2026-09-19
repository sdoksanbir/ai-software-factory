from factory.agents.provider_errors import (
    AgentModelUnavailableError,
    AgentProviderRateLimitError,
    AgentProviderUnavailableError,
    is_fallback_eligible_error,
)


def test_connection_failure_is_fallback_eligible():
    assert is_fallback_eligible_error(
        AgentProviderUnavailableError(
            "offline"
        )
    )


def test_missing_model_is_fallback_eligible():
    assert is_fallback_eligible_error(
        AgentModelUnavailableError(
            "missing model"
        )
    )


def test_rate_limit_is_fallback_eligible():
    assert is_fallback_eligible_error(
        AgentProviderRateLimitError(
            "rate limited"
        )
    )


def test_unexpected_runtime_error_is_not_eligible():
    assert not is_fallback_eligible_error(
        RuntimeError(
            "bad response parser"
        )
    )


def test_value_error_is_not_generically_eligible():
    assert not is_fallback_eligible_error(
        ValueError(
            "invalid request"
        )
    )
