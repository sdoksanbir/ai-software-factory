from factory.agents.capabilities import (
    AgentCapability,
    AgentDescriptor,
)


def test_agent_descriptor_supports_capabilities():
    agent = AgentDescriptor(
        name="local-coder",
        provider_name="ollama",
        capabilities=frozenset(
            {
                AgentCapability.READ_REPOSITORY,
                AgentCapability.WRITE_CODE,
            }
        ),
    )

    assert agent.supports(
        {
            AgentCapability.READ_REPOSITORY,
        }
    )

    assert agent.supports(
        {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.WRITE_CODE,
        }
    )


def test_agent_descriptor_rejects_missing_capability():
    agent = AgentDescriptor(
        name="local-reader",
        provider_name="ollama",
        capabilities=frozenset(
            {
                AgentCapability.READ_REPOSITORY,
            }
        ),
    )

    assert not agent.supports(
        {
            AgentCapability.WRITE_CODE,
        }
    )


def test_agent_capability_values_are_stable():
    assert (
        AgentCapability.READ_REPOSITORY.value
        == "read_repository"
    )
    assert (
        AgentCapability.WRITE_CODE.value
        == "write_code"
    )
    assert (
        AgentCapability.RUN_TESTS.value
        == "run_tests"
    )
