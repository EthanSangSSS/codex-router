# Router V4 Lease Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace V3.3 worker-lifecycle authority coupling with a V4.0 generation lease that can be revoked without native terminal evidence and mechanically fences stale Luna tool calls.

**Architecture:** Add an independent `lease_control.py` journal with one current generation-scoped lease per root session. Root supersession revokes the current lease immediately; stale native worker events become no-ops, and exact Luna `PreToolUse` identity is the mechanical authority gate. Existing V3 state remains diagnostic-only and is never imported as V4 authority.

**Tech Stack:** Python 3.12, stdlib `dataclasses`, `fcntl`, `hashlib`/`hmac`, `json`, `tempfile`, `unittest`; existing Router hook/protocol modules.

**Spec:** `docs/specs/router-v4-lease-core.md`

## Global Constraints

- Production changes use strict RED -> GREEN -> REFACTOR TDD.
- Do not modify real `~/.codex` or install the implementation during repository development.
- Do not implement Stable Dispatcher, permission/A1 redesign, Luna reuse, worker pools, queues, or auto-update.
- V4 authority must not depend on `SubagentStop`, `close_agent`, native task-path cleanup, or native terminal state.
- Revocation fences only future `PreToolUse`; it does not claim rollback for already-admitted native operations.
- Preserve existing AUTO / DIRECT / STRICT classification behavior.
- Preserve V3 journal bytes; V4 uses a separate journal and lock.

---

## File Structure

- Create `src/codex_router/lease_control.py` — V4 journal, lease state machine, fencing and reconciliation API.
- Modify `src/codex_router/hook.py` — route V4 root/spawn/Luna/terminal hook events through the lease API while preserving unrelated V3 behavior during migration.
- Modify `src/codex_router/usability.py` only if required to replace V3 authority/fallback assumptions with V4 authority state; do not change permission policy.
- Modify `src/codex_router/global_install.py` only for model-visible V4 authority wording required by this release; do not implement Stable Dispatcher.
- Create `tests/test_lease_control_v4.py` — focused state-machine tests.
- Modify `tests/test_hook.py` and/or `tests/test_router_usability.py` — end-to-end hook contract tests for supersession, K1 bootstrap and stale event fencing.
- Preserve `tests/test_luna_control_v3.py` — V3 remains regression/diagnostic code and must not silently change semantics as part of V4.0.

---

### Task 1: Secure V4 Lease Journal

**Files:**
- Create: `src/codex_router/lease_control.py`
- Create: `tests/test_lease_control_v4.py`

**Interfaces:**
- Produces: `LeaseRecord`, `LeaseSnapshot`, `read_snapshot()`, `initialize_session()`, `stage_lease()`, `validate_snapshot()`.
- `initialize_session(directory, secret, session_id) -> LeaseSnapshot`
- `stage_lease(directory, secret, session_id, *, root_turn_id, packet_wire) -> LeaseSnapshot`

- [ ] **Step 1: Write RED tests for initial state and persistence safety**

Add tests named:

```python
test_new_v4_session_starts_generation_zero_without_active_lease
test_first_staged_lease_is_generation_one_and_has_unique_lease_id
test_corrupt_v4_schema_fails_closed
test_v4_journal_symlink_is_rejected
test_v4_journal_is_owner_only
test_v4_mutation_fsyncs_file_and_directory
test_v3_journal_is_not_imported_as_v4_authority
```

The first two tests must assert `generation == 0/1`, `active_lease is None/not None`, and that lease identifiers are opaque non-empty values. The migration test must place a synthetic V3 journal beside an absent V4 journal, call `initialize_session`, and assert V4 generation zero with no active lease while V3 bytes remain unchanged.

- [ ] **Step 2: Run focused RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3.12 -m unittest tests.test_lease_control_v4 -v
```

Expected: FAIL because `codex_router.lease_control` or the required APIs do not exist.

- [ ] **Step 3: Implement minimal secure journal**

Implement protocol constants:

```python
PROTOCOL = "codex-router/lease-control/v4.0"
_STATE = "lease-control-v4-0.json"
_LOCK = "lease-control-v4-0.lock"
```

Define immutable dataclasses for the snapshot and active lease. Reuse the proven V3 persistence mechanics conceptually: owner/mode checks, no symlink following, strict schema, bounded state, `flock`, atomic same-directory replace, file fsync and directory fsync. Do not import V3 lifecycle fields.

- [ ] **Step 4: Run focused GREEN**

Run the focused command again and require all Task 1 tests to pass.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/lease_control.py tests/test_lease_control_v4.py
git commit -m "feat(router): add V4 lease journal"
```

---

### Task 2: Atomic Revocation and Monotonic Generation

**Files:**
- Modify: `src/codex_router/lease_control.py`
- Modify: `tests/test_lease_control_v4.py`

**Interfaces:**
- Produces: `revoke_current_lease()`, `stage_lease()` generation monotonicity and idempotent empty revoke.
- `revoke_current_lease(directory, secret, session_id) -> LeaseSnapshot`

- [ ] **Step 1: Write RED tests**

Add:

```python
test_active_lease_revokes_without_terminal_evidence
test_staged_lease_revokes_without_terminal_evidence
test_revocation_clears_active_authority_immediately
test_revoked_generation_does_not_block_next_generation
test_next_generation_increments_and_changes_lease_id
test_repeated_revoke_with_no_active_lease_is_idempotent
```

Do not call `SubagentStop`, `close_agent`, `interrupt_agent`, or any native status API in these tests.

- [ ] **Step 2: Verify RED**

Focused test module must fail for missing revocation behavior.

- [ ] **Step 3: Implement minimal revocation**

Under the journal lock, replace `active_lease` with `None` without changing the generation counter. `stage_lease` increments from the stored counter and creates a new lease. No V4 state named `QUIESCING`, `PAUSED_SETTLED`, or `RETIRED` may be introduced.

- [ ] **Step 4: Verify GREEN**

Run focused tests and `git diff --check`.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/lease_control.py tests/test_lease_control_v4.py
git commit -m "feat(router): revoke V4 leases without terminal state"
```

---

### Task 3: Generation-Scoped Spawn Reservation and Stale Observation Handling

**Files:**
- Modify: `src/codex_router/lease_control.py`
- Modify: `tests/test_lease_control_v4.py`

**Interfaces:**
- Produces: `expected_task_name()`, `reserve_spawn()`, `observe_spawn_result()`, `observe_subagent_start()`.
- Stale observations return a literal result such as `"STALE"`; current matches return `"CURRENT"` plus updated snapshot, following the repository's existing explicit stale/current style.

- [ ] **Step 1: Write RED tests**

Add:

```python
test_expected_task_name_is_generation_and_lease_scoped
test_spawn_reservation_rejects_wrong_agent_type_or_fork_mode
test_spawn_reservation_belongs_only_to_current_lease
test_revoked_spawn_observation_is_stale_noop
test_stale_subagent_start_cannot_bind_new_lease
test_current_subagent_start_binds_current_lease
test_spawn_result_then_start_race_binds_current_lease
test_start_then_spawn_result_race_binds_current_lease
```

Expected task-name shape:

```text
luna_g<generation>_<8 lowercase hex chars derived from lease_id>
```

`agent_type` remains `luna_worker`, and fork mode remains no-history (`fork_turns=none` on the V2 surface).

- [ ] **Step 2: Verify RED**

Run focused tests and confirm failures are from missing generation-scoped spawn logic.

- [ ] **Step 3: Implement minimal spawn state**

Spawn state lives inside the current lease. Observations must carry enough current identity to decide CURRENT vs STALE; a stale observation must not throw an error that mutates, clears, or blocks the current lease.

- [ ] **Step 4: Verify GREEN**

Run focused tests and `git diff --check`.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/lease_control.py tests/test_lease_control_v4.py
git commit -m "feat(router): scope Luna spawn state to V4 leases"
```

---

### Task 4: Exact Luna PreToolUse Fencing and K1 Bootstrap

**Files:**
- Modify: `src/codex_router/lease_control.py`
- Modify: `src/codex_router/hook.py`
- Modify: `tests/test_lease_control_v4.py`
- Modify: `tests/test_hook.py`

**Interfaces:**
- Produces: `authorize_executor_tool()` backed by native `session_id`, `turn_id`, `agent_id`, `agent_type`, `tool_use_id`.
- First exact `Bash {"command":"pwd"}` may bind `child_turn_id` and return canonical K1 context; later calls for the same bound child return no new K1 context.

- [ ] **Step 1: Write RED tests**

Add tests proving:

```python
test_current_worker_first_pwd_binds_child_turn_and_returns_k1
test_current_worker_later_tool_is_allowed_without_reinjecting_k1
test_wrong_worker_is_denied
test_wrong_child_turn_is_denied
test_revoked_worker_is_denied
test_generation_n_worker_is_denied_after_generation_n_plus_one_exists
test_no_active_lease_denies_luna_tool
test_stale_worker_cannot_consume_new_lease_k1
```

Hook tests must construct the same native field names Codex emits; do not invent model-controlled identity fields.

- [ ] **Step 2: Verify RED**

Run only the new lease and hook tests first.

- [ ] **Step 3: Implement minimal fencing**

Replace the V4 routed Luna admission path with exact current-lease identity matching. Preserve the already-correct context-only `PreToolUse.additionalContext` bootstrap contract; do not reintroduce `permissionDecision="allow"` without `updatedInput`.

- [ ] **Step 4: Verify GREEN**

Run the focused tests and existing bootstrap regression tests.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/lease_control.py src/codex_router/hook.py tests/test_lease_control_v4.py tests/test_hook.py
git commit -m "feat(router): fence Luna tools with V4 leases"
```

---

### Task 5: Root Supersession Without QUIESCING

**Files:**
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/usability.py` only if a V3 fallback-state read would otherwise block the V4 route.
- Modify: `tests/test_hook.py`
- Modify: `tests/test_router_usability.py`

**Interfaces:**
- UserPromptSubmit routed path revokes any current V4 lease before staging the new generation.
- DIRECT/BYPASS remains PRIMARY-local and must not require `SAFE_LOCAL_FALLBACK`; that state is only a routed capability-failure concept.

- [ ] **Step 1: Write RED tests**

Add:

```python
test_new_routed_root_turn_revokes_current_v4_lease
test_new_routed_root_turn_can_stage_next_generation_without_terminal
test_direct_turn_does_not_require_safe_local_fallback
test_direct_turn_does_not_stage_k1_or_spawn_luna
test_strict_routed_turn_stages_next_generation_after_logical_revoke
test_v4_route_has_no_quiescing_authority_state
```

The DIRECT test must begin with exact first non-empty line `[CODEX_ROUTER_DIRECT]` and must assert no K1 stage command is produced for that turn.

- [ ] **Step 2: Verify RED**

Focused hook/usability tests must show the current V3 dependency before implementation.

- [ ] **Step 3: Implement minimal supersession**

On routed root work, call V4 logical revoke before staging a new lease. Do not wait for terminal evidence and do not use V3 worker binding as the V4 admission gate. Keep permission/A1 behavior otherwise unchanged.

- [ ] **Step 4: Verify GREEN**

Run focused tests plus all policy/usability tests.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/hook.py src/codex_router/usability.py tests/test_hook.py tests/test_router_usability.py
git commit -m "feat(router): supersede Luna authority with V4 leases"
```

---

### Task 6: Terminal Reconciliation Is Optional and Idempotent

**Files:**
- Modify: `src/codex_router/lease_control.py`
- Modify: `src/codex_router/hook.py`
- Modify: `tests/test_lease_control_v4.py`
- Modify: `tests/test_hook.py`

**Interfaces:**
- Produces: `observe_subagent_stop()` returning `CURRENT`, `STALE`, or `NOOP` without allowing stale events to clear the current lease.

- [ ] **Step 1: Write RED tests**

Add:

```python
test_current_exact_subagent_stop_closes_current_lease
test_stale_previous_generation_stop_does_not_clear_new_lease
test_duplicate_old_stop_is_noop
test_wrong_agent_stop_does_not_clear_current_lease
test_wrong_child_turn_stop_does_not_clear_current_lease
test_missing_subagent_stop_does_not_block_next_root_generation
test_current_exact_reconciliation_error_is_not_silently_reported_as_cleanup_success
```

- [ ] **Step 2: Verify RED**

Run focused tests.

- [ ] **Step 3: Implement minimal reconciliation**

Current exact terminal evidence may clear the current lease. Late/duplicate/wrong-generation events must be stale/no-op. Remove the V4 dependency on V3 `observe_turn_boundary()` semantics.

- [ ] **Step 4: Verify GREEN**

Run focused tests and existing lifecycle regressions.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/lease_control.py src/codex_router/hook.py tests/test_lease_control_v4.py tests/test_hook.py
git commit -m "feat(router): make Luna terminal reconciliation optional"
```

---

### Task 7: Documentation, V3 Dirty-Diff Comparison and Full Verification

**Files:**
- Modify: `src/codex_router/global_install.py` only if V3.3 model-visible lifecycle wording contradicts the V4 spec.
- Modify: `README.md` if architecture summary needs V4.0 wording.
- Modify: tests only for explicit documentation-contract assertions already used by the project.

**Interfaces:**
- Produces a repository state whose source, docs and tests describe the same V4.0 authority model.

- [ ] **Step 1: Compare the preserved dirty V3.3 checkout read-only**

Classify each uncommitted change as `KEEP_FOR_V4`, `SUPERSEDED_BY_V4`, `STILL_USEFUL_AS_REGRESSION_TEST`, or `UNRELATED`. Do not copy any change whose prerequisite is successful old-worker close/terminal settlement before the next generation.

- [ ] **Step 2: Update only contradictory V3.3 lifecycle wording**

Required wording must state that current authority is generation-lease-scoped, stale native workers do not block N+1, `SubagentStop` is optional reconciliation evidence, and revocation does not roll back already-admitted operations. Do not describe Stable Dispatcher or permission redesign as implemented.

- [ ] **Step 3: Run full verification**

```bash
PYTHONDONTWRITEBYTECODE=1 python3.12 -m unittest discover -s tests -v
TMP_PYCACHE="$(mktemp -d)"
PYTHONPYCACHEPREFIX="$TMP_PYCACHE" python3.12 -m compileall -q src tests
rm -rf "$TMP_PYCACHE"
git diff --check
```

Expected: all tests PASS, compileall exits 0, `git diff --check` exits 0.

- [ ] **Step 4: Verify repository status**

```bash
git status --short
git log --oneline --decorate -8
git diff origin/main...HEAD --stat
git diff --check origin/main...HEAD
```

Only intended V4.0 files may differ from `origin/main`.

- [ ] **Step 5: Final local commit if documentation changed**

```bash
git add README.md src/codex_router/global_install.py
git commit -m "docs(router): document V4 lease authority"
```

Skip this commit if neither file changed.

---

## Self-Review Checklist

- Every spec invariant I1-I12 maps to Tasks 1-6.
- No task requires native worker terminal state for revocation or N+1 admission.
- No task implements permission passthrough, Stable Dispatcher, reuse, pool, queue, or auto-update.
- PreToolUse identity is sourced only from native hook fields.
- DIRECT is explicitly tested as one-turn PRIMARY-local behavior and must not be confused with routed safe-local fallback.
- V3 journal migration is distrust-by-default, not state translation.
- Full live Codex acceptance is deliberately excluded from repository implementation and is a separate post-CI gate.
