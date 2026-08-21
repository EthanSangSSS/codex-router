# Persistent Luna Minimal Control Plane V3.1 Implementation Plan

> **Historical / superseded:** The active lifecycle is V3.3 “Persistent Task, Disposable Luna.” Persistent-worker identity and required-follow-up steps below are non-authoritative history; see [the V3.3 design](../specs/2026-08-20-router-v3-3-persistent-task-disposable-luna-design.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the V2 root-turn/revocation/hard-no-process policy with the approved V3.1 persistent-Luna Minimal Control Plane: one Luna per coherent task epoch, Full Executor ordinary capabilities, monotonic packet authority, Hard Authority Pause, narrow A1 authorization, and explicit live-activation acceptance gates.

**Architecture:** Create `luna_control.py` as the single V3.1 durable authority/state machine and keep `hook.py` as a narrow Codex-event adapter. Keep the mature global installer transaction/backup machinery, but replace its V2 rendering layer with a V3.1 profile that disables descendant agents without disabling ordinary shell/build/test tools. Properties the current App cannot prove remain explicit acceptance blockers; implementation must not fabricate equivalent guarantees with V2 broad policing.

**Tech Stack:** Python 3.12 standard library, `unittest`, Codex command Hooks, TOML/JSON rendering, reversible global installer, GitHub Actions.

## Global Constraints

- Design authority is `docs/superpowers/specs/2026-08-17-persistent-luna-minimal-control-plane-v3-1-design.md` plus `docs/superpowers/specs/2026-08-17-persistent-luna-hard-authority-pause-v3-1-addendum.md`; the addendum wins only where they conflict.
- Sol remains user-facing coordinator/planner/reviewer/controller/final responder; Luna is the default substantive Full Executor.
- P1 is one persistent Luna per coherent `task_epoch`; a root-turn boundary is not a Luna-lifecycle boundary.
- `native_workspace_boundary` is mechanical native authority for a Luna epoch; `intended_write_scope` is packet-level semantic write intent and may change without replacing Luna when it stays inside the same native boundary.
- Packet authority is monotonic by `packet_generation`; a new packet replaces prior packet authority rather than adding to it.
- Hard Authority Pause means immediate Router authority freeze, not guaranteed immediate OS/process/tool termination.
- `interrupt_agent` acknowledgment is never settlement. Generation N+1 must not execute while N remains `QUIESCING` and unsettled.
- Logical task state and execution/control state are independent. Cancellation during in-flight execution must preserve `logical_task_status=CANCELLED` with `execution_status=QUIESCING` until settlement.
- Stale prior-generation output may be logged but cannot complete the current packet, expand scope, authorize A1, replace Luna identity, or advance current authority.
- A1 authorization is packet-scoped and non-inheriting. Hard A1 claims require a proven pre-action mechanical gate for the exact enabled surface.
- Do not add a general shell parser, broad ordinary-tool positive allowlist, global `no_process` mode, periodic Sol polling, heartbeat loop, or Router-owned PID/process-group supervisor.
- Luna descendants remain mechanically disabled with the effective equivalent of `[agents] enabled=false`, `[features] multi_agent=false`, and `multi_agent_v2=false`, plus a narrow lifecycle defense-in-depth gate.
- Nested Codex remains prohibited by product policy; the strength of the mechanical claim is a target-runtime acceptance gate under Full Executor.
- Baseline managed Hooks are exactly `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, and `SubagentStart`. `PermissionRequest` is conditional and A1-specific only if runtime evidence proves it is needed and attributable. `Stop` is not a baseline V3.1 Hook.
- `PostToolUse` remains spawn-result reconciliation in the baseline design. Do not silently expand it into settlement observation; if exact-runtime evidence later requires another Hook responsibility, stop and amend the design before live activation.
- Persistent state remains owner-only, no-symlink, locked, bounded, atomically replaced, file-fsynced, and containing-directory-fsynced.
- New OAuth/device-auth solely for Router validation is forbidden. Standalone authenticated-root validation is not the normal path.
- Current-App smoke evidence may support product feasibility, but must not be promoted into unobserved G3-G8 hard guarantees.
- No live `~/.codex` installation, Hook trust change, PR ready-for-review transition, merge, or live activation is authorized by this plan.
- PR #8 remains Draft unless the user separately authorizes a state change.

## File Structure

Create:

- `src/codex_router/luna_control.py` — V3.1 durable task/Luna/generation state, spawn correlation, packet authority, quiescence, settlement, replacement, and recovery validation.
- `src/codex_router/a1.py` — canonical A1 categories, surface capability/readiness model, packet authorization validation, and hard-claim gating without shell parsing.
- `tests/test_luna_control_v3.py` — state machine, durability, persistent reuse, spawn-order, pause/settlement, stale-generation, recovery, and replacement tests.
- `tests/test_a1_v3.py` — A1 matrix, non-inheritance, conditional permission-gate, and no-false-hard-claim tests.
- `tests/test_router_v3.py` — synthetic Hook/control-plane integration tests.
- `tests/test_primary_capability_v3.py` — V3.1 profile/readiness assertions.

Modify:

- `src/codex_router/protocol.py` and `tests/test_protocol.py` — canonical K1 packet wire contract.
- `src/codex_router/hook.py`, `src/codex_router/cli.py`, `tests/test_hook.py`, `tests/test_cli.py` — V3.1 Hook bridge and status serialization.
- `src/codex_router/global_install_adapter.py`, `src/codex_router/global_install.py`, `src/codex_router/types.py`, `tests/test_global_install.py`, `tests/test_global_self_test.py` — V3.1 renderer/readiness while preserving installer transactions.
- `README.md` and `docs/superpowers/plans/2026-08-17-router-v3-1-exact-runtime-validation.md` — current architecture and acceptance workflow.

Delete only after equivalent V3 coverage is green and imports are gone:

- `src/codex_router/native_lifecycle.py`
- `tests/test_native_lifecycle.py`
- `tests/test_router_authority_realign.py`
- `tests/test_luna_hard_mode_v2.py`
- `tests/test_minimal_agent_id_v2.py`
- `tests/test_minimal_journal_v2.py`
- `tests/test_policy_surface_v2.py`
- `tests/test_primary_capability_v2.py`

Do not redesign or delete the legacy Local Sol → Web Sol → Luna pipeline/state subsystem; it remains regression-tested.

---

### Task 1: Build the V3.1 durable control-state model

**Files:**
- Create: `src/codex_router/luna_control.py`
- Create: `tests/test_luna_control_v3.py`

**Interfaces:**

```python
TaskStatus = Literal["ACTIVE", "COMPLETED", "CANCELLED"]
ExecutionStatus = Literal["IDLE", "RUNNING", "QUIESCING", "PAUSED_SETTLED", "RETIRED"]

@dataclass(frozen=True)
class ControlSnapshot:
    task_epoch: str
    luna_epoch: str
    root_session_tag: str
    native_parent_identity: str
    native_authority_profile: str
    luna_agent_id: str | None
    luna_task_path: str | None
    packet_generation: int
    active_packet_id: str | None
    active_child_turn_id: str | None
    logical_task_status: TaskStatus
    execution_status: ExecutionStatus
```

Public functions introduced in this task:

```python
new_task(...) -> ControlSnapshot
read_snapshot(...) -> ControlSnapshot | None
validate_snapshot(snapshot: ControlSnapshot) -> None
```

- [ ] **Step 1: Write RED tests for initial and dual-dimensional state**

```python
snapshot = control.new_task(
    directory=self.directory,
    secret=self.secret,
    session_id="root-session",
    native_parent_identity="root-parent",
    native_authority_profile="profile-A",
)
self.assertEqual(snapshot.logical_task_status, "ACTIVE")
self.assertEqual(snapshot.execution_status, "IDLE")
self.assertEqual(snapshot.packet_generation, 0)
self.assertIsNone(snapshot.luna_agent_id)
```

Construct an explicit cancellation/in-flight snapshot and prove it validates:

```python
cancelled_in_flight = control.ControlSnapshot(
    task_epoch=snapshot.task_epoch,
    luna_epoch=snapshot.luna_epoch,
    root_session_tag=snapshot.root_session_tag,
    native_parent_identity="root-parent",
    native_authority_profile="profile-A",
    luna_agent_id="agent-1",
    luna_task_path="/root/luna_worker",
    packet_generation=1,
    active_packet_id="packet-1",
    active_child_turn_id="child-turn-1",
    logical_task_status="CANCELLED",
    execution_status="QUIESCING",
)
control.validate_snapshot(cancelled_in_flight)
```

Reject `ACTIVE + RETIRED`, negative generation, malformed epoch IDs, unknown state keys on disk, Luna ID without task path, and `RUNNING/QUIESCING` without an active packet.

- [ ] **Step 2: Run the module and observe RED**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 -v
```

Expected: import failure because `codex_router.luna_control` does not exist.

- [ ] **Step 3: Implement the state types and deterministic validator**

Use collision-resistant IDs `task-<uuid>` and `luna-<uuid>`. Keep raw session IDs out of durable state; derive an HMAC session tag using the installation secret.

- [ ] **Step 4: Add owner-only journal persistence**

Use:

```python
PROTOCOL = "codex-router/luna-control/v3.1"
_STATE = "luna-control-v3-1.json"
_LOCK = "luna-control-v3-1.lock"
```

Port only the proven persistence mechanics from V2: current-user owner checks, `0600`, no symlink, `flock`, bounded schema, temp-file write, file fsync, atomic replace, directory fsync. Do not port the V2 `ACTIVE|REVOKED` schema.

- [ ] **Step 5: Add RED/green integrity tests**

Prove journal mode `0600`, unsafe symlink rejection, malformed schema fail-closed, unchanged reads do not rewrite the file, and mutating transitions call `os.fsync` for file and containing directory.

- [ ] **Step 6: Run focused tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 -v
git add src/codex_router/luna_control.py tests/test_luna_control_v3.py
git commit -m "feat: add V3.1 Luna control state"
```

---

### Task 2: Add order-independent spawn correlation and persistent Luna reuse

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `tests/test_luna_control_v3.py`

**Interfaces:**

```python
reserve_spawn(..., tool_use_id: str, task_name: str, fork_turns: str) -> ControlSnapshot
observe_spawn_result(..., tool_use_id: str, task_path: str) -> ControlSnapshot
observe_subagent_start(..., agent_id: str, agent_type: str) -> ControlSnapshot
current_luna(...) -> ControlSnapshot
authorize_parent_target(..., tool_name: str, target: str) -> None
```

`pending_spawn` stores `task_epoch`, `luna_epoch`, expected role, root session tag, expected parent, `tool_use_id`, observed task path, and observed `agent_id`.

- [ ] **Step 1: Write RED tests for both event orderings**

```text
reserve -> spawn result -> SubagentStart
reserve -> SubagentStart -> spawn result
```

The authoritative bind occurs only after available observations agree with the same reservation.

- [ ] **Step 2: Write RED ambiguity/stale tests**

Prove second simultaneous reservation, wrong role, wrong task path, wrong `tool_use_id`, and delayed start from a retired `luna_epoch` cannot bind. `fork_turns` must equal `"none"`.

- [ ] **Step 3: Write the P1 cross-root-turn test**

Use `turn-a` and `turn-b` under the same root session/task epoch. Neither reading nor routing the second turn may revoke or replace the bound Luna merely because `turn_id` changed.

- [ ] **Step 4: Implement reconciliation without transcript or child/root-turn equality**

Reservation example:

```python
{
    "task_epoch": task_epoch,
    "luna_epoch": luna_epoch,
    "expected_role": "luna_worker",
    "root_session_tag": root_session_tag,
    "expected_parent": native_parent_identity,
    "tool_use_id": tool_use_id,
    "task_path": None,
    "agent_id": None,
}
```

- [ ] **Step 5: Run focused tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 -v
git add src/codex_router/luna_control.py tests/test_luna_control_v3.py
git commit -m "feat: persist and reuse one Luna per task epoch"
```

---

### Task 3: Implement the K1 packet wire contract and stale-generation rejection

**Files:**
- Modify: `src/codex_router/protocol.py`
- Modify: `src/codex_router/luna_control.py`
- Modify: `tests/test_protocol.py`
- Modify: `tests/test_luna_control_v3.py`

**Interfaces:**

```python
LUNA_PACKET_PREFIX = "[CODEX_ROUTER_PACKET_V3_1] "
build_luna_packet(...) -> str
parse_luna_packet(message: str) -> dict[str, Any]
begin_packet(...) -> ControlSnapshot
start_execution(..., child_turn_id: str | None) -> ControlSnapshot
accept_result(..., generation: int, child_turn_id: str | None) -> Literal["CURRENT", "STALE"]
```

- [ ] **Step 1: Write RED protocol tests for exact K1 fields**

Canonical packet object:

```python
{
    "packet_id": "packet-1",
    "generation": 1,
    "objective": "Add multiply() and tests",
    "working_directory": "/workspace/repo",
    "intended_write_scope": ["src/math.py", "tests/test_math.py"],
    "explicit_side_effect_authorizations": [],
    "success_criteria": ["focused tests pass"],
    "stop_conditions": ["scope expansion required", "A1 authorization required"],
}
```

Reject missing/extra keys, relative working directory, empty objective, duplicate/non-text scope entries, malformed generation, and non-canonical JSON.

- [ ] **Step 2: Write RED generation replacement tests**

Generation N+1 must clear N's semantic scope and A1 authorizations unless restated. A delayed N result returns `"STALE"` and does not mutate current state.

- [ ] **Step 3: Implement packet encoding with `canonical_json_bytes()`**

Parse K1 only on Router parent→Luna lifecycle communication; do not inspect arbitrary shell commands or normal Luna tool inputs.

- [ ] **Step 4: Implement generation admission**

`begin_packet()` increments generation atomically. A normal `intended_write_scope` change inside the same native profile keeps the same Luna. `begin_packet()` must refuse when execution is `QUIESCING`.

- [ ] **Step 5: Run focused tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_protocol tests.test_luna_control_v3 -v
git add src/codex_router/protocol.py src/codex_router/luna_control.py tests/test_protocol.py tests/test_luna_control_v3.py
git commit -m "feat: add V3.1 packet generation authority"
```

---

### Task 4: Implement Hard Authority Pause and settlement gating

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `tests/test_luna_control_v3.py`
- Create: `tests/test_router_v3.py`

**Interfaces:**

```python
freeze_authority(..., reason: str, logical_cancel: bool = False) -> ControlSnapshot
record_interrupt_ack(..., previous_status: str) -> ControlSnapshot
observe_settlement(
    ...,
    source: Literal["verified_native_terminal"],
    terminal_status: Literal["completed", "failed", "interrupted", "cancelled"],
    child_turn_id: str | None,
) -> ControlSnapshot
```

- [ ] **Step 1: Write the real-smoke regression test**

```python
control.start_execution(..., child_turn_id="turn-1")
paused = control.freeze_authority(..., reason="user_pause")
self.assertEqual(paused.execution_status, "QUIESCING")

acked = control.record_interrupt_ack(..., previous_status="running")
self.assertEqual(acked.execution_status, "QUIESCING")

with self.assertRaises(RouterStateError):
    control.begin_packet(..., packet_id="packet-2", objective="replacement", ...)
```

`record_interrupt_ack()` must never produce `PAUSED_SETTLED`.

- [ ] **Step 2: Write natural-completion settlement test**

```python
settled = control.observe_settlement(
    ...,
    source="verified_native_terminal",
    terminal_status="completed",
    child_turn_id="turn-1",
)
self.assertEqual(settled.execution_status, "PAUSED_SETTLED")
```

This proves settlement may come from natural completion after the pause.

- [ ] **Step 3: Write the approved dual-status cancellation test**

```python
cancelled = control.freeze_authority(..., reason="user_cancel", logical_cancel=True)
self.assertEqual(cancelled.logical_task_status, "CANCELLED")
self.assertEqual(cancelled.execution_status, "QUIESCING")

settled = control.observe_settlement(..., source="verified_native_terminal", terminal_status="completed", child_turn_id="turn-1")
self.assertEqual(settled.logical_task_status, "CANCELLED")
self.assertEqual(settled.execution_status, "PAUSED_SETTLED")
```

- [ ] **Step 4: Implement freeze semantics atomically**

Freeze the current generation for future scheduling, preserve Luna identity, retain the old generation correlation tuple for stale rejection, and block N+1 until settlement. Do not add sleep-based settlement, polling loops, PID supervision, or immediate-kill claims.

- [ ] **Step 5: Keep the settlement source unbound until runtime acceptance**

`luna_control.py` accepts only the normalized `verified_native_terminal` observation. Baseline Hooks do not fabricate that observation. Until a later acceptance run proves a trustworthy native source and wires it through an approved adapter, live activation reports `G2_SETTLEMENT_OBSERVATION` blocked and an unsettled pause stays `QUIESCING` fail-closed.

- [ ] **Step 6: Run focused tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 tests.test_router_v3 -v
git add src/codex_router/luna_control.py tests/test_luna_control_v3.py tests/test_router_v3.py
git commit -m "feat: add V3.1 hard authority pause"
```

---

### Task 5: Replace V2 Hook behavior with the minimal V3.1 bridge

**Files:**
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/cli.py`
- Modify: `tests/test_hook.py`
- Modify: `tests/test_router_v3.py`

**Interfaces:**

- `UserPromptSubmit`: route/direct control context; no root-turn Luna revocation.
- `PreToolUse`: parent lifecycle admission, K1 packet admission, and Luna descendant-lifecycle denial only.
- `PostToolUse`: spawn-result reconciliation only in the baseline implementation.
- `SubagentStart`: spawn reservation identity reconciliation.
- Legacy CLI entry points for `hook-stop` / `hook-permission-request` may remain callable for safe upgrade compatibility, but the V3 renderer does not register them by default.

- [ ] **Step 1: Write RED V3 route-context tests**

```python
self.assertEqual(context["workflow"], "persistent_native_luna")
self.assertEqual(context["luna_lifecycle"], "persistent_task_epoch")
self.assertEqual(context["pause_semantics"], "hard_authority_pause")
self.assertEqual(context["sol_supervision"], "event_driven")
self.assertEqual(context["luna_execution_mode"], "full_executor")
```

A second routed root turn must not revoke the same task-epoch Luna solely because its `turn_id` differs.

- [ ] **Step 2: Write RED Full Executor tests**

For a correctly bound Luna, Router must return no denial solely because the ordinary tool is `Read`, `apply_patch`, `Bash`, `shell_command`, `exec_command`, or an unknown non-lifecycle web/MCP/plugin tool. Luna lifecycle/delegation attempts such as `spawn_agent`, descendant `send_message`, and descendant `resume_agent` remain denied.

- [ ] **Step 3: Replace all `native_lifecycle` calls with `luna_control`**

Remove `revoke_stale()` from `handle_user_prompt`. Map exact parent lifecycle fields only. Unknown lifecycle operations fail closed for Router authority; unknown ordinary executor tools remain under native Codex controls.

- [ ] **Step 4: Keep G3 actor attribution honest**

For security-sensitive lifecycle operations, missing/ambiguous actor identity must not be silently treated as primary Sol. Unit tests use synthetic actor fields, while `global-status` continues to report `G3_ACTOR_ATTRIBUTION` blocked until exact runtime evidence exists.

- [ ] **Step 5: Run Hook integration tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_hook tests.test_router_v3 -v
git add src/codex_router/hook.py src/codex_router/cli.py tests/test_hook.py tests/test_router_v3.py
git commit -m "feat: narrow Router hooks for V3.1"
```

---

### Task 6: Render the V3.1 Full Executor profile and four baseline Hooks

**Files:**
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `src/codex_router/global_install.py` only where the adapter contract requires new V3 fields.
- Modify: `tests/test_global_install.py`
- Modify: `tests/test_global_self_test.py`
- Create: `tests/test_primary_capability_v3.py`

**Interfaces:**

```python
LUNA_EXECUTION_MODE = "full_executor_v3_1"
BASELINE_HOOK_EVENTS = (
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
)
```

- [ ] **Step 1: Write RED profile tests**

Require:

```toml
[agents]
enabled = false

[features]
multi_agent = false
multi_agent_v2 = false
```

Assert the Router renderer no longer forces V2 restrictions such as `shell_tool=false`, `unified_exec=false`, `code_mode_only=false`, `apps=false`, `plugins=false`, or `web_search="disabled"` merely to enforce Router policy.

- [ ] **Step 2: Write RED Hook-set tests**

Baseline rendered managed Hooks must equal exactly the four-event tuple above. `Stop` and `PermissionRequest` must be absent from the baseline.

- [ ] **Step 3: Replace V2 generated policy text**

`AGENTS.md` and Luna developer instructions must encode:

```text
persistent Luna per task epoch
Full Executor ordinary inspect/research/edit/test/debug/retry/verify
no descendants
no nested Codex delegation
packet generation replaces prior authority
Hard Authority Pause freezes Router authority immediately
no N/N+1 overlap before settlement
A1 hard claims only on proven pre-action surfaces
```

Remove current-policy claims for `hard_mode_no_process`, per-root-turn persistence, and revoke-only terminal semantics.

- [ ] **Step 4: Preserve installer transactions**

Use the existing `global_install_adapter.py` seam. Do not rewrite backup names, rollback records, drift detection, target hashing, or uninstall restoration unless a focused failing test proves a direct incompatibility.

- [ ] **Step 5: Run renderer/self-test suites and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_global_install tests.test_global_self_test tests.test_primary_capability_v3 -v
git add src/codex_router/global_install_adapter.py src/codex_router/global_install.py tests/test_global_install.py tests/test_global_self_test.py tests/test_primary_capability_v3.py
git commit -m "feat: render V3.1 full executor profile"
```

---

### Task 7: Add A1 capability/readiness modeling without shell parsing

**Files:**
- Create: `src/codex_router/a1.py`
- Create: `tests/test_a1_v3.py`
- Modify: `src/codex_router/protocol.py`
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/global_install_adapter.py`

**Interfaces:**

```python
A1_CATEGORIES = (
    "git_push",
    "remote_collaboration_mutation",
    "deploy_release_publish",
    "outbound_user_communication",
    "cloud_resource_mutation",
    "system_level_install",
    "comparable_external_persistent_mutation",
)

SurfaceEnforcement = Literal[
    "PROVEN_PRE_ACTION",
    "BASELINE_WITHHELD",
    "COOPERATIVE_ONLY",
    "UNVERIFIED",
]

@dataclass(frozen=True)
class A1SurfaceCapability:
    category: str
    surface: str
    enforcement: SurfaceEnforcement
    gate: str | None
    actor_attribution: str

validate_packet_authorizations(values: Iterable[str]) -> tuple[str, ...]
hard_claim_ready(matrix: Iterable[A1SurfaceCapability], category: str) -> bool
```

- [ ] **Step 1: Write RED category/non-inheritance tests**

Generation N A1 authorizations must not appear in N+1 unless explicitly restated. Unknown categories are rejected at K1 parsing/admission.

- [ ] **Step 2: Write RED hard-claim tests**

```python
surface = A1SurfaceCapability(
    category="git_push",
    surface="shell",
    enforcement="UNVERIFIED",
    gate=None,
    actor_attribution="UNVERIFIED",
)
self.assertFalse(hard_claim_ready((surface,), "git_push"))
```

`COOPERATIVE_ONLY` also returns false.

- [ ] **Step 3: Prove there is no general command parser**

`a1.py` must not parse arbitrary Bash strings such as `git push`, `curl`, or compound shell syntax. It operates on explicit packet authorization plus runtime capability/surface metadata only.

- [ ] **Step 4: Implement conditional `PermissionRequest` registration**

The renderer may add `PermissionRequest` only when an exact-runtime compatibility record marks a specific A1 surface `PROVEN_PRE_ACTION`, identifies `PermissionRequest` as its gate, and marks actor attribution proven. Otherwise baseline remains four Hooks and the corresponding hard A1 claim remains blocked/withheld.

- [ ] **Step 5: Run A1/Hook/renderer tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_a1_v3 tests.test_hook tests.test_global_install -v
git add src/codex_router/a1.py src/codex_router/protocol.py src/codex_router/hook.py src/codex_router/global_install_adapter.py tests/test_a1_v3.py
git commit -m "feat: model V3.1 A1 capability gates"
```

---

### Task 8: Add controlled replacement, recovery, and honest readiness status

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `src/codex_router/types.py`
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `src/codex_router/cli.py`
- Modify: `tests/test_luna_control_v3.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_global_install.py`

**Interfaces:**

```python
retire_luna(..., reason: Literal[
    "unrecoverable_runtime_identity",
    "new_task_epoch",
    "native_authority_profile_change",
    "runtime_validated_context_reset",
]) -> ControlSnapshot

start_new_task_epoch(...) -> ControlSnapshot
reconcile_recovery(...) -> ControlSnapshot
```

Extend `GlobalStatus` with exact fields:

```python
router_design: str = "v3.1"
live_activation: str = "BLOCKED_ACCEPTANCE_GATES"
live_activation_blockers: tuple[str, ...] = ()
deferred_acceptance_evidence: tuple[str, ...] = ()
```

- [ ] **Step 1: Write RED controlled-replacement tests**

An `intended_write_scope` change inside the same native profile must not replace Luna. A native authority-profile change must freeze/settle the old execution before retirement and replacement.

- [ ] **Step 2: Write RED recovery/race tests**

Reject recovery for wrong parent, role, agent ID, authority-profile identity, retired epoch, or ambiguous candidates. Resumability alone is not authority. A delayed SubagentStart from epoch E must not bind over pending E+1.

- [ ] **Step 3: Implement controlled replacement**

```text
freeze old authority if running
require trusted settlement observation
mark old Luna RETIRED
create new task/luna epoch or profile
reserve one replacement spawn
```

Do not replace merely because Luna is idle/completed or a root turn changed.

- [ ] **Step 4: Write RED status/readiness tests**

Before target-runtime acceptance, `live_activation_blockers` must include applicable safety/correctness gates such as:

```text
G1_STRONG_IDENTITY_PROFILE
G2_SETTLEMENT_OBSERVATION
G3_ACTOR_ATTRIBUTION
G4_NO_DESCENDANTS_EFFECTIVE_INVENTORY
G5_NESTED_CODEX
G6_NATIVE_AUTHORITY_PROFILE
G7_A1_CAPABILITY_MATRIX
G8_RECOVERY_CORRELATION
```

`G9_ECONOMICS` belongs in `deferred_acceptance_evidence`, not in the live-activation safety blocker list.

- [ ] **Step 5: Update CLI/global self-test semantics**

Offline self-test may return pass for repository/install invariants while `live_activation` remains `BLOCKED_ACCEPTANCE_GATES`. Do not equate offline green with runtime acceptance.

- [ ] **Step 6: Run focused tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 tests.test_cli tests.test_global_install tests.test_global_self_test -v
git add src/codex_router/luna_control.py src/codex_router/types.py src/codex_router/global_install_adapter.py src/codex_router/cli.py tests
git commit -m "feat: add V3.1 recovery and readiness gates"
```

---

### Task 9: Remove the superseded V2 control path and synchronize documentation

**Files:**
- Delete after V3 focused suites pass: `src/codex_router/native_lifecycle.py`
- Delete after equivalent coverage: the V2-only test files listed in File Structure.
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-17-router-v3-1-exact-runtime-validation.md`
- Modify: any remaining imports/current-policy assertions found by search.

- [ ] **Step 1: Prove V3 focused suites are green before deleting V2 code**

```bash
PYTHONPATH=src python3.12 -m unittest \
  tests.test_luna_control_v3 \
  tests.test_router_v3 \
  tests.test_a1_v3 \
  tests.test_hook \
  tests.test_primary_capability_v3 -v
```

- [ ] **Step 2: Search current code/tests for superseded semantics**

```bash
grep -R "native_lifecycle\|native-luna-safety-v2\|hard_mode_no_process\|persistent_while_root_turn_active\|revoke_only_security_boundary" -n src tests
```

Port any still-useful regression to V3 tests, then remove the active V2 implementation and conflicting V2 tests. Do not leave two live authorization state machines.

- [ ] **Step 3: Rewrite runtime validation normal path**

The validation plan must state:

```text
NEW_OAUTH_FOR_VALIDATION=FORBIDDEN
STANDALONE_AUTHENTICATED_ROOT=NORMAL_PATH_DROPPED
CURRENT_APP_SMALL_TASK_SMOKE=PREFERRED_FOR_PRODUCT_RUNTIME_FEASIBILITY
TARGET_PROFILE_ACCEPTANCE=REQUIRED_FOR_PROFILE_DEPENDENT_HARD_CLAIMS
```

Record current evidence accurately:

```text
P1_PRODUCT_RUNTIME_FEASIBILITY=PASS
INTERRUPT_ACK_AS_SETTLEMENT=REJECTED_BY_RUNTIME_EVIDENCE
G9_SHORT_CONTEXT_REUSE=PASS
G2_SETTLEMENT_OBSERVATION=ACCEPTANCE_GATE
G3_G8_HIDDEN_RUNTIME_FIELDS=ACCEPTANCE_GATE
G4_G7_TARGET_PROFILE_PROPERTIES=ACCEPTANCE_GATE
G9_ECONOMICS=DEFERRED_SOAK_EVIDENCE
```

- [ ] **Step 4: Update README/current generated-policy documentation**

Document persistent task-epoch Luna, Full Executor, Hard Authority Pause, no descendants, A1 pre-action hard-claim rule, and live-activation blockers. Historical V2 docs may remain historical but must not be described as current authority.

- [ ] **Step 5: Run full unit suite and commit cleanup/docs**

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
git diff --check
git add -A src tests README.md docs/superpowers/plans/2026-08-17-router-v3-1-exact-runtime-validation.md
git commit -m "refactor: complete V3.1 control-plane migration"
```

---

### Task 10: Full repository verification and Draft-PR handoff

**Files:**
- Modify only files required by observed verification failures.
- Do not change PR body/state unless the user separately authorizes that GitHub mutation.

- [ ] **Step 1: Run CI-equivalent checks**

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
git diff --check
```

- [ ] **Step 2: Run the legacy fake-adapter smoke**

```bash
state_dir="$(mktemp -d)"
output="$(PYTHONPATH=src python3.12 -m codex_router run \
  --task "Return exactly ROUTER_MVP_OK" \
  --adapter-mode fake \
  --state-dir "$state_dir")"
test "$output" = "ROUTER_MVP_OK"
```

- [ ] **Step 3: Build and install a fresh wheel**

```bash
rm -rf dist
python3.12 -m pip wheel . --no-deps --wheel-dir dist
wheel_env="$(mktemp -d)/venv"
python3.12 -m venv "$wheel_env"
"$wheel_env/bin/python" -m pip install --no-deps dist/codex_router-*.whl
```

- [ ] **Step 4: Run disposable offline global install/self-test/uninstall**

```bash
codex_home="$(mktemp -d)"
policy_state="$(mktemp -d)"
synthetic_codex="$(mktemp)"
printf '%s\n' 'synthetic codex binary' > "$synthetic_codex"
chmod 700 "$synthetic_codex"

"$wheel_env/bin/router" global-install \
  --codex-home "$codex_home" \
  --state-dir "$policy_state" \
  --codex-bin "$synthetic_codex" > /tmp/router-v3-install.json
"$wheel_env/bin/router" global-self-test \
  --codex-home "$codex_home" > /tmp/router-v3-self-test.json
"$wheel_env/bin/router" global-uninstall \
  --codex-home "$codex_home" > /tmp/router-v3-uninstall.json
```

Use only temporary paths; never point these commands at live `~/.codex`.

- [ ] **Step 5: Run semantic anti-regression scans**

```bash
grep -R "hard_mode_no_process\|persistent_while_root_turn_active\|revoke_only_security_boundary" -n src tests README.md || true
grep -R "Stop\|PermissionRequest" -n src/codex_router/global_install_adapter.py
```

Interpretation:

```text
no current-policy hard_mode_no_process claim
no per-root persistent-lifetime claim
no revoke-only root terminal semantics
baseline renderer contains no Stop
PermissionRequest appears only in conditional A1 logic or safe migration compatibility code
```

- [ ] **Step 6: Verify the approved design boundaries manually against the diff**

```text
P1 persistent reuse is the normal path
logical CANCELLED may coexist with execution QUIESCING
interrupt ACK cannot settle
N+1 cannot execute before N settles
stale N output cannot advance authority
intended_write_scope change does not automatically replace Luna
ordinary Full Executor tools are not Router-allowlisted
Luna descendant capability is disabled in the rendered profile
A1 hard claims are gated per surface
no new OAuth validation path exists
standalone authenticated root is not required
live activation remains blocked on unresolved G1-8 acceptance gates
G9 economics remains deferred soak evidence
```

- [ ] **Step 7: Re-run affected tests after any verification-driven fix and stop before activation**

Final handoff must report observed evidence using:

```text
REPOSITORY_IMPLEMENTATION=V3_1_IMPLEMENTED_OFFLINE
OFFLINE_TESTS=PASS
FULL_EXECUTOR_PROFILE_RENDERED=YES
P1_CONTROL_MODEL=IMPLEMENTED
HARD_AUTHORITY_PAUSE=IMPLEMENTED
LIVE_ACTIVATION=BLOCKED_ACCEPTANCE_GATES
PR_DRAFT=YES
PR_READY_OR_MERGE=BLOCKED
LIVE_CODEX_HOME_CHANGED=NO
HOOK_TRUST_CHANGED=NO
NEW_OAUTH_CREATED=NO
```

Do not install to live `~/.codex`, change Hook trust, mark PR ready, merge, or claim runtime acceptance without the later current-App/target-profile evidence.

---

## Self-Review

### Spec coverage

- P1 persistent Luna and root-turn non-boundary: Tasks 2, 3, 8.
- Identity/epoch/generation correlation and stale rejection: Tasks 1-3, 8.
- `native_workspace_boundary` vs `intended_write_scope`: Tasks 3, 8, 10.
- K1 packet: Task 3.
- Hard Authority Pause and logical/execution dual state: Task 4.
- Event-driven Sleeping Sol / no polling: Tasks 4, 5, 10.
- E2 remains generated policy behavior; Task 6 synchronizes it without adding orchestration machinery.
- A1 hard-claim discipline: Task 7.
- No descendants and Full Executor: Tasks 5-7.
- Four baseline Hooks: Tasks 5-7.
- Controlled replacement/recovery: Task 8.
- Durable state integrity: Tasks 1, 2, 8.
- Runtime-gate staging / no new OAuth: Tasks 8-10.
- Live-activation and merge-ready blockers: Tasks 8-10.
- G9 economics is deferred soak evidence, not silently promoted to a safety hard claim.

### Type/interface consistency

- `logical_task_status` and `execution_status` are independent everywhere.
- `packet_generation` is the monotonic packet-authority version.
- `pending_spawn` is structured reservation state, never a boolean.
- `record_interrupt_ack()` never settles; only `observe_settlement()` may leave `QUIESCING`.
- `accept_result()` returns exactly `CURRENT` or `STALE`.
- A1 authorizations use canonical `A1_CATEGORIES` and never inherit across generations.
- `PostToolUse` baseline responsibility remains spawn reconciliation.
- `hook.py` consumes `luna_control.py`; after Task 9 there is no second active V2 authorization state machine.

### Placeholder and scope check

All implementation-facing interfaces used by a task are defined in that task or an earlier task. The plan contains no unresolved implementation placeholders. The work is one subsystem—the native persistent-Luna global Router control plane—while the legacy pipeline is preserved only as a regression boundary. Runtime acceptance is staged after implementation rather than expanded into a new authentication or live-migration project.
