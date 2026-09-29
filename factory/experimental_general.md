# Experimental General Agent Subsystem

Status: **EXPERIMENTAL** — not used by the production API.

## Boundary

| Layer | Role |
|---|---|
| Production | Structured WRITE / READ / EXECUTE via `TaskExecutionService` → dispatcher / runners / step handlers |
| Experimental | `factory/general_*`, capability_*, command/runtime grounding, tool_registry |

Production modules must not import the experimental general agent stack.

## Entry points

- `factory/general_planner_cli.py` — planner dry-run CLI
- `factory/general_agent_loop_cli.py` — agent loop preview CLI

## Notes

Ideas from this subsystem (evidence-bound mutation, capability probes, tool contracts) may be reused later. Do not merge them into the structured production path in isolation phases.
