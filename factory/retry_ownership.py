"""Retry ownership map for the production task chain.

These layers are intentionally separate. Do not treat them
as one shared retry counter.

A. provider_transport_retry
   Owner: ModelClient / provider transport adapters
   (e.g. Ollama generation.max_retries).
   Does NOT increment step or task attempt counters.

B. agent_provider_fallback
   Owner: AgentExecutionRouter.execute_with_fallback
   + AgentFallbackPolicy.
   Records provider_attempt / fallback_attempts metadata.
   Does NOT increment step attempt by itself.
   Phase 4 fallback ownership contract is authoritative;
   this module only documents the boundary.

C. step_retry
   Owner: execute_task_plan in task_step_executor.
   Increments plan step ``attempt`` when a non-completed
   step is re-entered after execution/review/verify failure.
   Budget: max_step_attempts (from task.max_attempts).

D. full_task_retry
   Owner: API POST /tasks/{id}/retry
   Resets failed/running steps via reset_retryable_task_steps,
   zeros task.attempt, and re-queues TaskExecutionService.run.
   Must not be confused with an in-process step retry loop.

E. manual_user_retry
   Same entry as full_task_retry (user-initiated API action).
   Distinct from automatic provider/step retries.
"""

from __future__ import annotations

PROVIDER_TRANSPORT_RETRY = (
    "provider_transport_retry"
)
AGENT_PROVIDER_FALLBACK = (
    "agent_provider_fallback"
)
STEP_RETRY = "step_retry"
FULL_TASK_RETRY = "full_task_retry"
MANUAL_USER_RETRY = "manual_user_retry"

RETRY_LAYERS = (
    PROVIDER_TRANSPORT_RETRY,
    AGENT_PROVIDER_FALLBACK,
    STEP_RETRY,
    FULL_TASK_RETRY,
    MANUAL_USER_RETRY,
)

# Production step-attempt owner.
STEP_ATTEMPT_OWNER = "execute_task_plan"

# Full-task reset owner (API).
FULL_TASK_RETRY_OWNER = (
    "api_post_tasks_retry"
)

# Must not share counters with step attempts.
PROVIDER_ATTEMPT_OWNERS = (
    "ModelClient.transport",
    "AgentExecutionRouter.execute_with_fallback",
)
