from dataclasses import dataclass
from enum import Enum


class AgentCapability(str, Enum):
    READ_REPOSITORY = "read_repository"
    WRITE_CODE = "write_code"
    RUN_TESTS = "run_tests"
    REVIEW_CODE = "review_code"
    PLAN_TASK = "plan_task"


@dataclass(frozen=True)
class AgentDescriptor:
    name: str
    provider_name: str
    capabilities: frozenset[
        AgentCapability
    ]

    def supports(
        self,
        required: set[
            AgentCapability
        ]
        | frozenset[
            AgentCapability
        ],
    ) -> bool:
        return required.issubset(
            self.capabilities
        )
