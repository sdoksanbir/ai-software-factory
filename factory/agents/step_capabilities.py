from factory.agents.capabilities import (
    AgentCapability,
)


STEP_CAPABILITIES: dict[
    str,
    frozenset[AgentCapability],
] = {
    "READ": frozenset(
        {
            AgentCapability.READ_REPOSITORY,
        }
    ),
    "WRITE": frozenset(
        {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.WRITE_CODE,
        }
    ),
    "VERIFY": frozenset(
        {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.RUN_TESTS,
        }
    ),
}


def capabilities_for_step(
    step_kind: str,
) -> frozenset[AgentCapability]:
    normalized = step_kind.strip().upper()

    if normalized not in STEP_CAPABILITIES:
        raise KeyError(
            "Unknown task step kind: "
            f"{step_kind}"
        )

    return STEP_CAPABILITIES[
        normalized
    ]
