"""P3 support tools around the orchestrator (nothing here runs a graph).

- `orchestration_limits`: the limits of a request as one object and the start-up audit of the
  `agents` config. USED IN PRODUCTION: `real_orchestrator()` calls `audit_configured_limits()`.
- `state_validator` (+ `orchestration_errors`): invariants of the orchestrator's `GraphState`,
  as a list of issues. A verification tool: test_orchestrator_integration.py applies it to every
  state of real graph runs. The graph does not call it (a failed invariant must not become a new
  way for a request to fail).
- `plan_validator`: why a planner reply was or was not usable, for tuning (schedule day 10).
  Kept equal to `plan_node` by test_plan_validator.py, which runs the real node on the same replies.

The dependency goes one way only: `orchestrator` may import `orchestration_support.
orchestration_limits` (which imports only `src.core.config`); nothing here imports `graph` or
`real`, so there is no import cycle.
"""
