class AgentProviderUnavailableError(
    ConnectionError
):
    """Provider cannot currently be reached."""


class AgentModelUnavailableError(
    ValueError
):
    """Requested model is unavailable."""


class AgentProviderRateLimitError(
    RuntimeError
):
    """Provider temporarily rejected the request."""


class AgentProviderTimeoutError(
    TimeoutError
):
    """Provider request timed out."""


FALLBACK_ELIGIBLE_ERRORS = (
    AgentProviderUnavailableError,
    AgentModelUnavailableError,
    AgentProviderRateLimitError,
    AgentProviderTimeoutError,
    ConnectionError,
    TimeoutError,
)


def is_fallback_eligible_error(
    error: BaseException,
) -> bool:
    return isinstance(
        error,
        FALLBACK_ELIGIBLE_ERRORS,
    )
