# K1 Control-Plane Sideband Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move K1 authority off opaque native V2 collaboration messages into a one-shot authenticated Router sideband while preserving generation, scope/A1, persistent-executor, QueueOnly, recovery-overlay, and fail-closed guarantees.

**Architecture:** PRIMARY stages canonical K1 through `router stage-k1` using a one-time HMAC capability bound to the current root turn/task epoch/next generation. Native `spawn_agent`/`followup_task` messages are trigger-only. Parent native admission consumes staged authority through one locked journal transition, and the first EXECUTOR `PreToolUse` is blocked while Router injects the canonical K1 as developer `additionalContext`; the second same-turn tool attempt proceeds under existing policy.

**Tech Stack:** Python 3, stdlib `argparse`/`json`/`hmac`/`hashlib`, existing Router journal/HMAC/Hook infrastructure, `unittest`, Codex managed Hooks.

**Spec:** `docs/superpowers/specs/2026-08-19-k1-control-plane-sideband-design.md`

**Implementation authorization:** Approved by the user on 2026-08-19. Repository task execution may begin only after the exact planning head containing this note has passing CI + Secret Scan and the local worktree passes the pre-implementation sync gate.

## Global Constraints

- K1 plaintext is Router authoritative control plane; native collaboration message plaintext is never an authority source.
- PRIMARY model selection remains inherited/capability-based; EXECUTOR model/reasoning remain explicit configuration.
- Keep exactly the existing five live Hooks: `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`.
- `src/codex_router/luna_control_recovery.py` is a load-bearing runtime overlay installed at package import; changes to snapshot schema or packet transitions must preserve both base and overlay semantics.
- Do not add a daemon, socket, MCP server, packet-history database, checkpoint service, automatic model selection, workspace transaction layer, process supervisor, or encrypted-message decoder.
- Keep `send_message` QueueOnly: it cannot consume staged K1, advance generation, or trigger an authorized new turn.
- Keep one persistent EXECUTOR per task epoch and existing native spawn binding via `tool_use_id` + `SubagentStart`/`PostToolUse` evidence.
- Every parent lifecycle admission must match the persisted current root turn. If explicit actor identity fields are present they must additionally resolve to a root actor; missing actor fields may use the already-approved session/current-turn HMAC fallback.
- Keep PR #8 open, Draft, unmerged, and not ready for review.
- No live `~/.codex` mutation, reinstall, Hook trust change, live agent spawn, or production smoke during repository implementation.

## File Structure

- `src/codex_router/protocol.py`: K1 packet format plus sideband capability encoding/verification only.
- `src/codex_router/luna_control.py`: base durable state model and compatibility schema.
- `src/codex_router/luna_control_recovery.py`: installed recovery overlay, strict snapshot migration, current-root-turn authority, recovery baseline, and atomic staged packet admission.
- `src/codex_router/cli.py`: `stage-k1` command only.
- `src/codex_router/hook.py`: root staging context, parent native dispatch gate, first-tool executor handshake.
- `src/codex_router/global_install_adapter.py`: sideband readiness classification and the only current V3 executor/policy renderer.
- `tests/test_k1_sideband_v31.py`: new focused sideband tests.
- Existing V3.1 root/recovery/control/global-install tests: regression authority.

## Pre-implementation gate

Before Task 1:

```bash
git fetch origin
git checkout hardening/native-luna-safety-v2
git status --short
git rev-parse HEAD
```

Require clean worktree and local HEAD equal to the exact PR head containing this corrected plan. Fast-forward only. Stop on divergence, dirty worktree, non-Draft PR, or unexpected head.

---

### Task 1: Add domain-separated authenticated stage-capability primitives

**Files:**
- Modify: `src/codex_router/protocol.py`
- Create/Test: `tests/test_k1_sideband_v31.py`

**Interfaces:**

```python
build_k1_stage_capability(
    secret: bytes,
    *,
    session_tag: str,
    root_turn_tag: str,
    task_epoch: str,
    generation: int,
) -> str

verify_k1_stage_capability(
    token: str,
    secret: bytes,
    *,
    session_tag: str,
    root_turn_tag: str,
    task_epoch: str,
    generation: int,
) -> None
```

HMAC domain separator is exactly:

```python
_K1_STAGE_CAPABILITY_DOMAIN = b"codex-router/k1-stage-capability/v1\0"
```

MAC input is:

```python
_K1_STAGE_CAPABILITY_DOMAIN + canonical_json_bytes(claims)
```

Claims contain only:

```python
{
    "v": 1,
    "session_tag": session_tag,
    "root_turn_tag": root_turn_tag,
    "task_epoch": task_epoch,
    "generation": generation,
}
```

- [ ] **Step 1: Write RED capability tests**

Tests:

```python
test_stage_capability_accepts_exact_current_authority
test_stage_capability_rejects_changed_session_tag
test_stage_capability_rejects_changed_root_turn_tag
test_stage_capability_rejects_changed_task_epoch
test_stage_capability_rejects_generation_replay
test_stage_capability_rejects_malformed_token
test_stage_capability_rejects_tampered_mac
test_stage_capability_mac_is_domain_separated
```

The domain-separation test independently recomputes an HMAC over bare canonical claims and proves that token MAC is not that value.

- [ ] **Step 2: Run RED**

```bash
python -m unittest tests.test_k1_sideband_v31.K1StageCapabilityTests -v
```

Expected: FAIL because the capability functions do not exist.

- [ ] **Step 3: Implement minimal capability codec**

Use URL-safe base64 without introducing timestamps or persistence. Verification must decode one claims object, require exact field set/type constraints, recompute the domain-separated HMAC, use `hmac.compare_digest`, then compare every expected claim exactly.

- [ ] **Step 4: Run GREEN**

Run the same command; expected zero failures/errors.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/protocol.py tests/test_k1_sideband_v31.py
git commit -m "feat: add authenticated K1 stage capabilities"
```

- [ ] **Step 6: Review gate**

Spec-compliance review, then code-quality/security review. Do not begin Task 2 until both pass.

---

### Task 2: Extend base + recovery-overlay journal state safely

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `src/codex_router/luna_control_recovery.py`
- Modify/Test: `tests/test_k1_sideband_v31.py`
- Regression: `tests/test_luna_control_v3.py`
- Regression: `tests/test_v31_quarantined_recovery.py`
- Regression: `tests/test_v31_quarantined_recovery_edges.py`
- Regression: `tests/test_v31_turn_boundary_mode.py`

**Interfaces:**

Add to the durable snapshot:

```python
authority_packet_wire: str | None = None
```

Produce:

```python
stage_authority_packet(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    root_turn_id: str,
    capability: str,
    packet_wire: str,
) -> ControlSnapshot

clear_staged_authority(
    directory: Path,
    secret: bytes,
    session_id: str,
) -> ControlSnapshot
```

Do **not** add `commit_staged_packet()` as the parent-dispatch primitive. Parent commit becomes atomic with native admission in Task 4.

- [ ] **Step 1: Write RED state + overlay migration tests**

Required tests:

```python
test_stage_packet_accepts_exact_next_generation
test_identical_stage_retry_is_idempotent
test_different_duplicate_stage_is_denied
test_legacy_base_snapshot_loads_authority_wire_as_none
test_legacy_overlay_snapshot_loads_authority_wire_as_none
test_new_root_turn_clears_unused_staged_authority
test_same_root_turn_rebind_does_not_destroy_current_stage
test_retire_clears_staged_authority
test_logical_cancel_clears_staged_authority
test_replacement_snapshot_starts_without_staged_authority
test_staging_does_not_change_packet_generation
test_recovery_baseline_unchanged_by_staging_only
```

The legacy-overlay test must serialize a pre-sideband journal record containing overlay fields `recovery_baseline` and `current_root_turn_tag` but no `authority_packet_wire`, load it through the installed package overlay, and assert `authority_packet_wire is None`.

- [ ] **Step 2: Run RED**

```bash
python -m unittest tests.test_k1_sideband_v31.K1SidebandStateTests -v
```

Expected: FAIL on missing field/functions or overlay exact-schema rejection.

- [ ] **Step 3: Update both strict snapshot loaders**

In `luna_control.py`, old records missing the new field gain `authority_packet_wire=None` before exact-field validation.

In `luna_control_recovery.py::snapshot_from_mapping()`, add the same migration **before** computing/checking `expected_fields = set(ControlSnapshot.__dataclass_fields__)`.

Do not weaken exact-field validation for unknown fields.

- [ ] **Step 4: Implement staging in the installed overlay-aware state model**

`stage_authority_packet()` must execute under one existing `_locked_state(..., mutate=True)` transaction and:

```python
snapshot = _record_for_session(...)
require snapshot.logical_task_status == "ACTIVE"
require snapshot.current_root_turn_tag matches root_turn_id
expected_generation = snapshot.packet_generation + 1
verify_k1_stage_capability(... expected_generation ...)
packet = parse_luna_packet(packet_wire)
require packet["generation"] == expected_generation
require packet_wire is canonical parser-accepted K1
if snapshot.authority_packet_wire is None:
    store exact packet_wire
elif snapshot.authority_packet_wire == packet_wire:
    return snapshot  # idempotent
else:
    fail closed
```

Staging alone must not change generation, active packet, execution status, pending spawn, recovery baseline, scope, or A1 metadata.

- [ ] **Step 5: Clear staged authority on authority invalidation**

Update transitions so stale authority cannot survive:

- `set_current_root_turn`: clear `authority_packet_wire` when the root-turn tag changes or is cleared; retain it only when setting the identical current tag.
- `freeze_authority(... logical_cancel=True)`: clear it.
- `retire_luna`: clear it.
- replacement/new-task snapshot constructors: explicitly initialize `None` where clarity is needed.
- terminal/result paths must never leave an impossible active-packet/no-wire/no-child state; Task 5 adds the hard validation invariant.

Preserve `recovery_baseline` semantics exactly.

- [ ] **Step 6: Run focused + recovery regressions**

```bash
python -m unittest tests.test_k1_sideband_v31.K1SidebandStateTests -v
python -m unittest tests.test_luna_control_v3 -v
python -m unittest tests.test_v31_quarantined_recovery -v
python -m unittest tests.test_v31_quarantined_recovery_edges -v
python -m unittest tests.test_v31_turn_boundary_mode -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/codex_router/luna_control.py src/codex_router/luna_control_recovery.py tests/test_k1_sideband_v31.py
git commit -m "feat: stage K1 authority in overlay journal"
```

- [ ] **Step 8: Review gate**

Spec-compliance review must explicitly verify legacy journal migration and overlay monkey-patch behavior before Task 3.

---

### Task 3: Add `stage-k1`, root staging context, and sideband readiness

**Files:**
- Modify: `src/codex_router/cli.py`
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/global_install_adapter.py`
- Modify/Test: `tests/test_k1_sideband_v31.py`
- Modify/Test: `tests/test_primary_capability_v3.py`
- Regression: `tests/test_cli.py`
- Regression: `tests/test_global_install.py`

**Interfaces:**

New CLI:

```text
router stage-k1 \
  --installation-dir PATH \
  --session-id ID \
  --root-turn-id ID \
  --capability TOKEN
```

K1 wire is read from stdin once.

Add readiness values:

```python
SIDEBAND_STAGE_AVAILABLE = "AVAILABLE"
SIDEBAND_STAGE_UNAVAILABLE = "UNAVAILABLE"
SIDEBAND_STAGE_UNKNOWN = "UNKNOWN_REQUIRES_CAPABILITY_CHECK"
```

Add a narrow classifier:

```python
sideband_stage_capability(runtime_capabilities: Any) -> str
```

Runtime evidence key is normalized to:

```text
router_stage_k1_exec
```

Semantics:

- explicit `router_stage_k1_exec=true` -> `AVAILABLE`;
- explicit false -> `UNAVAILABLE`;
- absent/ambiguous -> `UNKNOWN_REQUIRES_CAPABILITY_CHECK`.

Do not infer availability merely from V2 collaboration tools or a model name.

`global-status` compatibility may be `COMPATIBLE` for sideband routing only when the existing V2 gate passes **and** sideband stage capability is `AVAILABLE`; explicit unavailable is incompatible; unknown remains unknown.

- [ ] **Step 1: Write RED CLI/context/readiness tests**

```python
test_routed_root_context_contains_stage_capability_and_command
test_stage_k1_cli_reads_one_packet_from_stdin_and_stages_it
test_stage_k1_cli_rejects_stale_capability
test_direct_or_bypass_context_does_not_issue_stage_authority
test_sideband_stage_capability_available_from_explicit_runtime_evidence
test_sideband_stage_capability_unavailable_from_explicit_negative
test_sideband_stage_capability_unknown_when_unproven
test_primary_readiness_not_compatible_when_sideband_exec_unproven
test_primary_readiness_incompatible_when_sideband_exec_explicitly_unavailable
```

- [ ] **Step 2: Run RED**

```bash
python -m unittest tests.test_k1_sideband_v31.K1StageCliTests -v
python -m unittest tests.test_primary_capability_v3.PrimaryCapabilityV3Tests -v
```

- [ ] **Step 3: Implement `stage-k1`**

Use existing private installation loading to obtain the installation secret and state root; do not accept a secret/path to journal from model input. Bound stdin size to the existing Hook/K1 limits, parse UTF-8 strictly, call `stage_authority_packet()`, and print only bounded metadata:

```json
{"status":"staged","generation":2,"packet_id":"..."}
```

Never echo packet body or capability.

- [ ] **Step 4: Inject current-turn staging instructions**

For routed root `UserPromptSubmit`, after current root authority is stored, build the one-time capability from the actual session tag/current root-turn tag/task epoch/next generation and include:

```text
K1_STAGE_CAPABILITY=<token>
K1_STAGE_COMMAND=<exact installed Python/module/installation-dir command template>
```

No staging authority for direct/bypass turns.

- [ ] **Step 5: Implement sideband readiness without broad shell naming**

Extend `global_install_adapter.py` runtime capability evidence extraction with the exact normalized signal `router_stage_k1_exec`. Keep `PRIMARY_REQUIRED_CAPABILITIES` focused on V2 collaboration if desired, but overall compatibility must combine:

```text
primary V2 gate
AND
sideband_stage_capability == AVAILABLE
```

Expose the sideband result in status/diagnostic payload through the narrowest existing `GlobalStatus`/compatibility reason seam; if adding a dataclass field would expand core compatibility unnecessarily, include it in the existing compatibility reason and public helper tests, but routing readiness must still fail closed on UNKNOWN/UNAVAILABLE.

- [ ] **Step 6: Run GREEN + regressions**

```bash
python -m unittest tests.test_k1_sideband_v31.K1StageCliTests -v
python -m unittest tests.test_primary_capability_v3 -v
python -m unittest tests.test_cli -v
python -m unittest tests.test_global_install -v
```

- [ ] **Step 7: Commit**

```bash
git add src/codex_router/cli.py src/codex_router/hook.py src/codex_router/global_install_adapter.py tests/test_k1_sideband_v31.py tests/test_primary_capability_v3.py
git commit -m "feat: expose K1 sideband staging readiness"
```

- [ ] **Step 8: Review gate**

Reviewer must confirm repository cannot claim normal sideband routing compatible from V2 tools alone.

---

### Task 4: Atomically admit opaque native spawn/follow-up dispatch

**Files:**
- Modify: `src/codex_router/luna_control.py` only for shared base helpers/validation if required
- Modify: `src/codex_router/luna_control_recovery.py`
- Modify: `src/codex_router/hook.py`
- Modify/Test: `tests/test_k1_sideband_v31.py`
- Modify/Test: `tests/test_v31_exact_root_hook_identity.py`
- Regression: `tests/test_v31_control_plane_corrections.py`
- Regression: `tests/test_v31_turn_boundary_mode.py`

**Interfaces:**

Produce two atomic journal transitions on the installed overlay:

```python
admit_staged_spawn(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    root_turn_id: str,
    tool_use_id: str,
    task_name: str,
    agent_type: str,
    fork_turns: str,
) -> ControlSnapshot

admit_staged_followup(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    root_turn_id: str,
    target: str,
) -> ControlSnapshot
```

Each function must use exactly one `_locked_state(..., mutate=True)` transaction and one final `_store_snapshot()` for the successful state mutation. The current root-turn check is part of that same transaction: before reading or consuming `authority_packet_wire`, derive the tag for `root_turn_id`, require a non-`None` persisted `current_root_turn_tag`, and compare them with `hmac.compare_digest`. Hook-layer root identity remains an early rejection only; the atomic transition is the final authority check.

- [ ] **Step 1: Write RED opaque-message + atomicity tests**

Use:

```python
OPAQUE = "enc_01J9opaque_native_payload"
```

Required tests:

```python
test_spawn_accepts_opaque_message_with_valid_staged_gen1
test_spawn_without_stage_fails_closed
test_spawn_identity_fields_still_fail_closed
test_spawn_validation_failure_changes_neither_reservation_nor_generation
test_spawn_packet_commit_failure_leaves_no_pending_spawn
test_spawn_retry_after_denied_admission_is_not_poisoned
test_followup_accepts_opaque_message_for_exact_bound_executor
test_followup_wrong_target_changes_neither_stage_nor_generation
test_followup_commit_and_target_check_use_one_snapshot
test_send_message_cannot_consume_stage_or_advance_generation
test_stale_explicit_root_cannot_consume_current_staged_k1
test_atomic_spawn_revalidates_root_turn_inside_transaction
test_atomic_followup_revalidates_root_turn_inside_transaction
```

For the Hook-level stale-root integration test:

```text
persisted current root = turn-2
staged packet = generation N
event turn_id = turn-1
explicit actor_type = root
spawn_agent or followup_task -> DENY
authority_packet_wire unchanged
packet_generation unchanged
pending_spawn unchanged
```

For each state-transition-level atomic root-turn test:

```text
persisted current root = turn-2
staged packet = generation N authorized by turn-2
call admit_staged_*(root_turn_id=turn-1)
    -> fail closed
    -> authority_packet_wire unchanged
    -> packet_generation unchanged
    -> pending_spawn unchanged
```

- [ ] **Step 2: Run RED**

```bash
python -m unittest tests.test_k1_sideband_v31.K1ParentDispatchTests -v
python -m unittest tests.test_v31_exact_root_hook_identity -v
```

Expected: opaque positive cases fail on plaintext K1 parser; stale explicit root is incorrectly admitted by current identity helper; direct atomic stale-root tests fail because the current planned interfaces/implementation do not yet revalidate root authority inside the journal transaction.

- [ ] **Step 3: Implement one-snapshot packet commit semantics with atomic root-turn revalidation**

Inside the overlay, factor the current `begin_packet()` packet/recovery-baseline calculation into a private pure helper that accepts the already-read snapshot and staged packet wire and returns replacement fields without taking another lock. Both `begin_packet()` and the two new atomic admission functions must use that same helper so `recovery_baseline` behavior remains identical.

`admit_staged_spawn()` under one lock:

```text
read current snapshot
expected_root_tag = _root_turn_tag(secret, root_turn_id)
require snapshot.current_root_turn_tag is not None
require hmac.compare_digest(snapshot.current_root_turn_tag, expected_root_tag)
validate ACTIVE / eligible execution / current staged K1 / exact next generation
validate task_name / agent_type / fork_turns
validate no pending/bound executor
construct SpawnReservation(tool_use_id)
compute packet + recovery-baseline replacement fields
replace snapshot with reservation + committed packet metadata
retain authority_packet_wire for Task 5 handshake
store once
```

Any exception before `_store_snapshot()` must leave journal bytes logically unchanged.

`admit_staged_followup()` under one lock:

```text
read current snapshot
expected_root_tag = _root_turn_tag(secret, root_turn_id)
require snapshot.current_root_turn_tag is not None
require hmac.compare_digest(snapshot.current_root_turn_tag, expected_root_tag)
validate exact current executor target
validate IDLE/PAUSED_SETTLED
validate staged K1 + exact next generation
compute packet + recovery-baseline replacement fields
commit packet metadata while retaining authority_packet_wire
store once
```

No separate `authorize_parent_target()` then commit transaction for follow-up, and no root-turn authorization result computed outside this lock is sufficient to consume staged authority.

- [ ] **Step 4: Make current-root-turn mandatory for every root lifecycle event**

Change `_root_lifecycle_identity()` semantics to:

```text
if actor fields are ambiguous/child -> not root
if actor fields are present -> they must resolve to a recognized root
regardless of actor-field presence -> persisted current root turn must match event turn_id
only then -> root
```

Preserve the already-approved identity-free root fallback by allowing missing actor fields **only when** current root turn matches. Do not require actor fields on runtimes that omit them.

- [ ] **Step 5: Replace plaintext K1 parsing in parent V2 admission**

`spawn_agent` calls `admit_staged_spawn(...)`; `followup_task` calls `admit_staged_followup(...)`. Neither parses `tool_input.message`.

`send_message` authorizes current target then denies QueueOnly without consuming stage.

Do not add encrypted-token pattern matching.

- [ ] **Step 6: Run GREEN + root/control regressions**

```bash
python -m unittest tests.test_k1_sideband_v31.K1ParentDispatchTests -v
python -m unittest tests.test_v31_exact_root_hook_identity -v
python -m unittest tests.test_v31_control_plane_corrections -v
python -m unittest tests.test_v31_turn_boundary_mode -v
```

- [ ] **Step 7: Commit**

```bash
git add src/codex_router/luna_control.py src/codex_router/luna_control_recovery.py src/codex_router/hook.py tests/test_k1_sideband_v31.py tests/test_v31_exact_root_hook_identity.py
git commit -m "fix: atomically admit staged K1 native dispatch"
```

- [ ] **Step 8: Review gate**

Security review must explicitly inspect failure-before-store paths and prove no `pending_spawn` poison state can survive a denied Gen1 admission.

---

### Task 5: Enforce executor first-tool K1 handshake and impossible-state invariant

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `src/codex_router/luna_control_recovery.py`
- Modify: `src/codex_router/hook.py`
- Modify/Test: `tests/test_k1_sideband_v31.py`
- Regression: `tests/test_v31_turn_boundary_mode.py`
- Regression: `tests/test_v31_quarantined_recovery.py`

**Interfaces:**

First current-generation EXECUTOR tool is denied with canonical K1 as `additionalContext`; second same-turn attempt clears transient wire then enters ordinary policy.

Add the cross-field invariant:

```text
active_packet_id != None
AND active_child_turn_id == None
AND authority_packet_wire == None
=> INVALID / FAIL-CLOSED
```

Normal valid states are:

```text
committed, handshake not begun:
    active_packet_id != None
    active_child_turn_id == None
    authority_packet_wire != None

handshake begun/established:
    active_packet_id != None
    active_child_turn_id != None
    authority_packet_wire may be present on first blocked attempt, then None after same-turn retry
```

- [ ] **Step 1: Write RED handshake + invariant tests**

```python
test_first_executor_tool_is_blocked_and_receives_exact_k1_context
test_first_executor_tool_has_no_fake_side_effect
test_first_tool_does_not_clear_staged_wire
test_second_same_turn_tool_clears_staged_wire_then_runs_normal_policy
test_second_different_turn_fails_closed
test_forbidden_lifecycle_tool_remains_forbidden_after_handshake
test_unbound_executor_cannot_trigger_handshake
test_active_packet_without_child_turn_or_authority_wire_is_invalid
test_overlay_loader_rejects_impossible_active_packet_state
test_child_user_prompt_plaintext_k1_is_not_required
```

- [ ] **Step 2: Run RED**

```bash
python -m unittest tests.test_k1_sideband_v31.K1ExecutorHandshakeTests -v
```

- [ ] **Step 3: Enforce invariant in both base and overlay validation**

Base validation must reject the impossible cross-field state. Overlay validation calls base validation and must preserve that result; add an explicit overlay regression test because it replaces `ControlSnapshot/_snapshot_from_mapping`.

Do not reject historical idle snapshots with no active packet and no wire.

- [ ] **Step 4: Implement handshake-before-ordinary-policy**

Bound EXECUTOR `PreToolUse` flow:

```python
snapshot = read_snapshot(...)
if snapshot.active_packet_id is not None:
    if snapshot.active_child_turn_id is None:
        if snapshot.authority_packet_wire is None:
            deny/fail closed
        start_execution(... child_turn_id=base["turn_id"])
        return PreToolUse deny + additionalContext=authority_packet_wire
    if snapshot.active_child_turn_id != base["turn_id"]:
        deny/fail closed
    if snapshot.authority_packet_wire is not None:
        clear_staged_authority(...)
# then ordinary descendant/lifecycle/A1/tool policy
```

The first attempted tool never executes, including if it is already forbidden.

- [ ] **Step 5: Remove child prompt plaintext K1 from hard authority**

If bound child `UserPromptSubmit` occurs, it may validate identity but must not parse/require K1 prompt text and must not independently advance packet generation. The hard authority injection point is first bound EXECUTOR `PreToolUse`.

- [ ] **Step 6: Run GREEN + lifecycle/recovery regressions**

```bash
python -m unittest tests.test_k1_sideband_v31.K1ExecutorHandshakeTests -v
python -m unittest tests.test_v31_turn_boundary_mode -v
python -m unittest tests.test_v31_quarantined_recovery -v
```

- [ ] **Step 7: Commit**

```bash
git add src/codex_router/luna_control.py src/codex_router/luna_control_recovery.py src/codex_router/hook.py tests/test_k1_sideband_v31.py
git commit -m "feat: inject K1 before executor tool side effects"
```

- [ ] **Step 8: Review gate**

Review must prove no normal tool-policy path exists for a bound executor in the impossible active-packet/no-wire/no-child state.

---

### Task 6: Align the exact V3 renderer and current-facing docs

**Files:**
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `README.md`
- Modify/Test: `tests/test_primary_capability_v3.py`
- Modify/Test: `tests/test_k1_sideband_v31.py`
- Update current 2026-08-19 docs only if implementation details require wording alignment

**Interfaces:**

`global_install_adapter.py` is the exact current renderer. Do not create or search for an alternate renderer.

Generated PRIMARY policy must say:

```text
stage canonical K1 through router stage-k1 first
native spawn_agent/followup_task message is a transport trigger, not authority
send_message is QueueOnly and cannot advance K1
```

Generated EXECUTOR instructions must say:

```text
Native collaboration messages are transport triggers, not work authority.
The authoritative work packet is [CODEX_ROUTER_PACKET_V3_1] injected by Router as developer context.
Do not perform tool work for a new generation until Router performs the first-tool authority handshake.
```

- [ ] **Step 1: Write RED renderer tests**

Update the existing V3 policy assertions that currently require `generation-1 K1 packet as message`. New tests must assert trigger-only/native-message semantics, stage-k1, first-tool handshake, and model-name decoupling.

- [ ] **Step 2: Run RED**

```bash
python -m unittest tests.test_primary_capability_v3.PrimaryCapabilityV3Tests -v
```

- [ ] **Step 3: Update `AGENTS_BLOCK_V3` and `LUNA_DEVELOPER_INSTRUCTIONS_V3` only**

Keep legacy exported aliases pointing to the updated V3 constants. No broad terminology rewrite.

- [ ] **Step 4: Update README/current authority references**

Document the control-plane/data-plane split, sideband readiness status, and first-tool handshake. Historical 8/16 docs remain history, not current authority.

- [ ] **Step 5: Run GREEN**

```bash
python -m unittest tests.test_primary_capability_v3 -v
python -m unittest tests.test_global_install -v
python -m unittest tests.test_k1_sideband_v31 -v
```

- [ ] **Step 6: Commit**

```bash
git add src/codex_router/global_install_adapter.py README.md tests/test_primary_capability_v3.py tests/test_k1_sideband_v31.py
git commit -m "docs: align Router policy with K1 sideband authority"
```

- [ ] **Step 7: Review gate**

Reviewer must search current rendered text for stale requirements that native `message` itself contains plaintext K1.

---

### Task 7: Full verification and exact-head GitHub Reality Audit

**Files:**
- No production-code changes expected unless verification exposes a concrete defect.
- Any correction follows RED -> GREEN and its own commit/review gate.

- [ ] **Step 1: Run focused sideband suite**

```bash
python -m unittest tests.test_k1_sideband_v31 -v
```

- [ ] **Step 2: Run load-bearing V3.1 regressions explicitly**

```bash
python -m unittest tests.test_luna_control_v3 -v
python -m unittest tests.test_v31_exact_root_hook_identity -v
python -m unittest tests.test_v31_control_plane_corrections -v
python -m unittest tests.test_v31_quarantined_recovery -v
python -m unittest tests.test_v31_quarantined_recovery_edges -v
python -m unittest tests.test_v31_turn_boundary_mode -v
python -m unittest tests.test_primary_capability_v3 -v
python -m unittest tests.test_global_install -v
python -m unittest tests.test_cli -v
```

- [ ] **Step 3: Run full unit suite**

```bash
python -m unittest discover -s tests -v
```

Require zero failures/errors.

- [ ] **Step 4: Run static/package checks**

```bash
python -m compileall -q src tests
git diff --check
```

- [ ] **Step 5: Run CI-equivalent package lifecycle**

Use repository CI commands for:

```text
fake adapter smoke
wheel build
fresh virtualenv install
fresh-wheel fake adapter smoke
disposable global-install -> global-self-test -> global-uninstall
```

Do not substitute editable install for fresh-wheel checks.

- [ ] **Step 6: Verify bounded diff**

Expected implementation scope:

```text
src/codex_router/protocol.py
src/codex_router/luna_control.py
src/codex_router/luna_control_recovery.py
src/codex_router/hook.py
src/codex_router/cli.py
src/codex_router/global_install_adapter.py
tests/test_k1_sideband_v31.py
tests/test_primary_capability_v3.py
tests/test_v31_exact_root_hook_identity.py
README.md
current 2026-08-19 docs if needed
```

Investigate any unrelated production file.

- [ ] **Step 7: Push normally**

```bash
git push origin hardening/native-luna-safety-v2
```

No force push.

- [ ] **Step 8: Exact-head GitHub Reality Audit**

Require:

```text
PR #8 = OPEN
PR #8 = DRAFT
PR #8 = UNMERGED
PR head = local HEAD
CI exact head = SUCCESS
Secret Scan exact head = SUCCESS
```

No ready-for-review, no merge.

- [ ] **Step 9: Return evidence report**

```text
SYNC_GATE=
SPEC_HEAD=
IMPLEMENTATION_HEAD=

SIDE_BAND_CAPABILITY=
SIDE_BAND_READINESS=
STAGE_K1_CLI=
STAGED_PACKET_JOURNAL=
RECOVERY_OVERLAY_MIGRATION=
ATOMIC_GEN1_ADMISSION=
ATOMIC_GEN2_ADMISSION=
ATOMIC_ROOT_TURN_REVALIDATION=
STALE_ROOT_TURN_GUARD=
OPAQUE_SPAWN_ADMISSION=
OPAQUE_FOLLOWUP_ADMISSION=
SEND_MESSAGE_QUEUE_ONLY=
EXECUTOR_FIRST_TOOL_HANDSHAKE=
IMPOSSIBLE_STATE_FAIL_CLOSED=
CHILD_PROMPT_K1_DEPENDENCY_REMOVED=
MODEL_ROLE_DECOUPLING_PRESERVED=

FOCUSED_TESTS=
V31_RECOVERY_REGRESSIONS=
FULL_UNIT_TESTS=
COMPILEALL=
DIFF_CHECK=
FAKE_ADAPTER=
FRESH_WHEEL_TEST=

PATCH_FILES=
COMMIT_SHA=
PR_HEAD_AFTER=
CI_RESULT=
SECRET_SCAN_RESULT=

LIVE_CODEX_HOME_TOUCHED=NO
LIVE_REINSTALL_PERFORMED=NO
AGENT_SPAWNED=NO
NESTED_CODEX=NO
PR_DRAFT=YES
PR_MERGED=NO

BLOCKERS=
FINAL_DISPOSITION=
```

Only success disposition:

```text
K1_SIDEBAND_READY_FOR_GITHUB_REALITY_AUDIT
```

## Sequential Subagent-Driven Discipline

Tasks are independently reviewable, not parallel-executable:

```text
Task N
  -> fresh implementer
  -> RED observed
  -> minimal implementation
  -> GREEN observed
  -> commit
  -> spec-compliance review
  -> code-quality/security review
  -> only then Task N+1
```

Task dependencies are strict:

```text
1 capability
-> 2 base + recovery-overlay state
-> 3 stage producer + readiness
-> 4 atomic native consumer
-> 5 executor handshake
-> 6 rendered contract/docs
-> 7 whole-branch verification
```

## Plan self-review

- Recovery overlay coverage: `luna_control_recovery.py` is explicitly modified/tested for schema migration, current-root invalidation, recovery baseline, and atomic admission.
- Atomicity: Gen1 reservation + packet commit and Gen2 target-check + packet commit occur in one journal transaction each; no plan step calls `reserve_spawn()` followed by a separate packet transaction.
- Atomic root-turn revalidation: `admit_staged_spawn()` and `admit_staged_followup()` both receive `root_turn_id` and compare its HMAC tag with the locked snapshot before staged authority can be consumed; Hook identity is early rejection only.
- Sideband capability gate: routing readiness cannot be `COMPATIBLE` unless `router_stage_k1_exec` is positively evidenced.
- Root-turn gate: current persisted root turn is mandatory even when explicit root actor metadata is present; identity-free exact-runtime fallback remains compatible.
- Impossible-state invariant: active packet with neither child turn nor staged authority wire is rejected.
- Renderer source: Task 6 is fixed to `global_install_adapter.py`.
- No placeholders/TODO/TBD remain.
- Scope remains seven sequential tasks; no new subsystem beyond the approved one-shot sideband is introduced.
