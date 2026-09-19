import pytest

from factory.agents.capabilities import (
    AgentCapability,
)
from factory.agents.step_capabilities import (
    capabilities_for_step,
)


def test_read_step_capabilities():
    capabilities = capabilities_for_step(
        "READ"
    )

    assert capabilities == frozenset(
        {
            AgentCapability.READ_REPOSITORY,
        }
    )


def test_write_step_capabilities():
    capabilities = capabilities_for_step(
        "write"
    )

    assert capabilities == frozenset(
        {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.WRITE_CODE,
        }
    )


def test_verify_step_capabilities():
    capabilities = capabilities_for_step(
        " VERIFY "
    )

    assert capabilities == frozenset(
        {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.RUN_TESTS,
        }
    )


def test_unknown_step_kind_is_rejected():
    with pytest.raises(
        KeyError,
        match="UNKNOWN",
    ):
        capabilities_for_step(
            "UNKNOWN"
        )
