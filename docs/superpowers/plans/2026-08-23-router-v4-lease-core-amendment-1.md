# Router V4 Lease Core Plan Amendment 1 — Worker Correlation

This amendment supersedes the original plan's Task 3 and the bootstrap-binding portion of Task 4 in `2026-08-23-router-v4-lease-core.md`.

## Why the original plan is unsafe

Current MultiAgent V2 exposes no stable shared correlation identifier between:

- parent `spawn_agent` success (`task_name`, optional nickname), and
- `SubagentStart` (`agent_id`, `agent_type`, `session_id`, `turn_id`).

`list_agents` adds path/name plus status, but still does not expose the exact `agent_id`. The spawn message arrives in the child as `InterAgentCommunication`, so it does not run `UserPromptSubmit` hooks. Therefore a late unknown `SubagentStart` cannot be safely assigned to the current lease by event ordering or task-name inference.

No implementation may bind `worker_agent_id` from `SubagentStart` alone.

---

## Replacement Task 3: Spawn Reservation Without Worker Binding

**Files:**
- Modify: `src/codex_router/lease_control.py`
- Modify: `tests/test_lease_control_v4.py`

**Interfaces:**
- `reserve_spawn(directory, secret, session_id, *, tool_use_id, task_name, agent_type, fork_turns) -> LeaseSnapshot`
- `observe_spawn_result(directory, secret, session_id, *, tool_use_id, task_path) -> tuple[LeaseSnapshot, str]`
- `observe_subagent_start(directory, secret, session_id, *, agent_id, agent_type, turn_id) -> tuple[LeaseSnapshot, str]`
- dispositions: `CURRENT`, `STALE`, `NOOP`
- `build_bootstrap_capability(secret, lease) -> str`
- `verify_bootstrap_capability(secret, lease, capability) -> None`

### RED tests

Add:

```python
test_expected_task_name_is_generation_and_lease_scoped
test_spawn_reservation_rejects_wrong_task_name_agent_type_or_fork_mode
test_spawn_reservation_belongs_only_to_current_lease
test_revoked_spawn_observation_is_stale_noop
test_exact_spawn_result_records_only_current_task_path
test_wrong_path_for_current_spawn_result_fails_closed
test_subagent_start_never_binds_uncorrelated_worker
test_late_subagent_start_after_revoke_is_noop
test_bootstrap_capability_is_lease_scoped
test_old_bootstrap_capability_fails_against_new_lease
```

### Minimal implementation

- `reserve_spawn` stores `spawn_tool_use_id` only inside the current lease.
- Expected native task name is `luna_g<generation>_<8 hex lease prefix>`.
- Exact current spawn result may store `worker_task_path=expected_task_name`; it still does **not** set `worker_agent_id`.
- A result with a non-current `tool_use_id` is `STALE` and does not mutate current state.
- Same current tool id plus wrong task path is a current-authority conflict and fails closed.
- `SubagentStart` is telemetry-only in V4.0 and never sets `worker_agent_id` or `child_turn_id`.
- Bootstrap capability is domain-separated HMAC over at least `root_session_tag`, `task_epoch`, `generation`, `lease_id`, and `expected_task_name`.

### GREEN verification

Run the focused V4 module, then complete CI. No Hook changes in this task.

---

## Replacement Task 4: Capability-Correlated First PreToolUse

**Files:**
- Modify: `src/codex_router/lease_control.py`
- Modify: `src/codex_router/hook.py`
- Modify: `tests/test_lease_control_v4.py`
- Modify: `tests/test_hook.py`

**Bootstrap contract:**

For an unbound current lease, the first Luna tool must be the exact benign command:

```text
pwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4=<current capability>
```

The parser must be anchored. The shell suffix is a comment, so the only executed command is `pwd`.

### RED tests

Add:

```python
test_current_capability_bootstrap_binds_native_agent_and_child_turn
test_bootstrap_injects_exact_k1_context_without_unsupported_allow_decision
test_old_capability_cannot_bind_new_generation
test_wrong_capability_does_not_bind_worker
test_missing_capability_does_not_bind_worker
test_wrong_agent_type_does_not_bind_worker
test_already_bound_worker_later_tool_is_allowed_without_capability
test_wrong_worker_after_binding_is_denied
test_wrong_child_turn_after_binding_is_denied
test_revoked_worker_is_denied
test_no_active_lease_denies_luna_tool
test_stale_subagent_start_cannot_replace_capability_bound_worker
```

### Minimal implementation

- Validate native `session_id`, `agent_id`, `agent_type`, `turn_id` from `PreToolUse`.
- For an unbound STAGED lease, parse the exact bootstrap command and verify its current HMAC capability under the journal lock.
- Only then atomically set `worker_agent_id`, `child_turn_id`, and `status=ACTIVE` and return exact canonical K1 context.
- The first bootstrap must not emit `permissionDecision=allow` unless an `updatedInput` is intentionally required; context-only output remains the default.
- After binding, exact native `agent_id + child_turn_id` is mandatory on every Luna tool.
- `SubagentStart` never upgrades authority.

### Explicitly prohibited

Do not correlate workers by:

- event timing;
- 'first SubagentStart wins';
- transcript-path parsing;
- `list_agents` ordering;
- task-name guessing from `agent_id`;
- waiting/polling for a matching event.

These are not stable native contracts.
