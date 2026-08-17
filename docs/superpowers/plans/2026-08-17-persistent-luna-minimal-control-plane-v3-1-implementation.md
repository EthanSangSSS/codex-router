# Persistent Luna Minimal Control Plane V3.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the V2 root-turn/revocation/hard-no-process control model with the approved V3.1 persistent-Luna Minimal Control Plane: one Luna per coherent task epoch, Full Executor ordinary capabilities, packet-generation authority, Hard Authority Pause, narrow A1 authorization, and fail-closed live-activation gates.

**Architecture:** Add a focused `luna_control.py` module for durable V3.1 task/Luna/generation state and transitions, and keep `hook.py` as a narrow Codex-event adapter. Keep the mature global installer transaction/backup machinery, but replace its V2 rendering layer with a V3.1 profile that disables descendant agents without disabling ordinary shell/build/test tools. Runtime properties that the current App cannot prove remain explicit acceptance blockers rather than being guessed or replaced with V2 broad policing.

**Tech Stack:** Python 3.12 standard library, `unittest`, Codex command Hooks, TOML/JSON rendering, reversible global installer, GitHub Actions.

## Global Constraints

- Target authority is `docs/superpowers/specs/2026-08-17-persistent-luna-minimal-control-plane-v3-1-design.md` plus `docs/superpowers/specs/2026-08-17-persistent-luna-hard-authority-pause-v3-1-addendum.md`; the addendum wins only where they conflict.
- Sol remains user-facing coordinator/planner/reviewer/controller/final responder; Luna is the default substantive Full Executor.
- P1 is one persistent Luna per coherent `task_epoch`, not one Luna per root turn and not one Luna forever across unrelated tasks.
- A root-turn boundary is not a Luna-lifecycle boundary.
- `native_workspace_boundary` is mechanical native authority for a Luna epoch; `intended_write_scope` is packet-level semantic write intent and may change without replacing Luna when it stays inside the same native boundary.
- Packet authority is monotonic by `packet_generation`; a new packet replaces prior packet authority rather than adding to it.
- Hard Authority Pause means immediate Router authority freeze, not guaranteed immediate OS/process/tool termination.
- `interrupt_agent` acknowledgment is never settlement.
- No generation N+1 work may begin while generation N remains `QUIESCING` and unsettled.
- Logical task state and execution/control state are separate dimensions. In particular, cancellation while execution is still in flight must preserve an equivalent of `logical_task_status=CANCELLED` plus `execution_status=QUIESCING` until settlement.
- Stale prior-generation output may be logged but cannot complete the current packet, expand scope, authorize A1, replace Luna identity, or advance current authority.
- A1 authorization is packet-scoped and non-inheriting. Hard A1 claims require a proven pre-action mechanical gate for the specific enabled surface.
- Do not add a general shell parser, broad ordinary-tool positive allowlist, global `no_process` mode, periodic Sol polling, heartbeat loop, or Router-owned PID/process-group supervisor.
- Luna descendants remain mechanically disabled with the effective equivalent of `[agents] enabled=false`, `[features] multi_agent=false`, and `multi_agent_v2=false`, plus a narrow lifecycle defense-in-depth gate.
- Nested Codex remains prohibited by product policy, but the mechanical strength of that claim is an acceptance gate under Full Executor.
- Baseline managed Hooks are `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, and `SubagentStart`. `PermissionRequest` is conditional and A1-specific only if runtime evidence proves it is needed and attributable. `Stop` is not a baseline V3.1 Hook.
- Persistent state remains owner-only, no-symlink, locked, bounded, atomically replaced, file-fsynced, and containing-directory-fsynced.
- New OAuth/device-auth solely for Router validation is forbidden. Standalone authenticated-root validation is not the normal path.
- Current-App smoke evidence may support product feasibility, but must not be promoted into unobserved G3-G8 hard guarantees.
- No live `~/.codex` installation, Hook trust change, PR ready-for-review transition, merge, or live activation is authorized by this implementation plan.
- PR #8 remains Draft throughout implementation unless the user separately authorizes a state change.

## File Structure

Create:

- `src/codex_router/luna_control.py` — V3.1 durable control-state schema, locking/persistence, spawn correlation, packet authority, quiescence, settlement, replacement, and recovery validation.
- `src/codex_router/a1.py` — canonical A1 categories, per-surface capability/readiness model, packet authorization validation, and hard-claim gating without shell parsing.
- `tests/test_luna_control_v3.py` — state machine, durability, dual-status cancellation, persistent reuse, spawn-order, stale-generation, recovery, and replacement tests.
- `tests/test_a1_v3.py` — A1 matrix, non-inheritance, conditional permission-gate, and no-false-hard-claim tests.
- `tests/test_router_v3.py` — end-to-end synthetic Hook flow for current V3.1 route/spawn/reuse/pause/stale-result semantics.

Modify:

- `src/codex_router/protocol.py` — canonical K1 packet marker/schema and parser/validator.
- `src/codex_router/hook.py` — replace V2 lifecycle journal calls and broad Luna tool policing with V3.1 control-plane calls.
- `src/codex_router/global_install_adapter.py` — render Full Executor V3.1 Luna profile, four baseline Hooks, V3.1 policy text, and acceptance/readiness metadata.
- `src/codex_router/global_install.py` — only where the stable transaction core needs new V3.1 config/status fields; do not rewrite backup/rollback machinery.
- `src/codex_router/types.py` — expose V3.1 activation/readiness fields in `GlobalStatus`.
- `src/codex_router/cli.py` — serialize new status fields; retain legacy hook subcommands only where required for safe upgrade compatibility.
- `README.md` — document V3.1 semantics and acceptance blockers.
- `docs/superpowers/plans/2026-08-17-router-v3-1-exact-runtime-validation.md` — replace standalone-auth normal-path assumptions with current-App/target-profile acceptance staging.
- `.github/workflows/ci.yml` — only if needed to make the new offline V3.1 self-test explicit; keep Python 3.12 and existing package smoke coverage.

Delete after equivalent V3 coverage is green and imports are gone:

- `src/codex_router/native_lifecycle.py`
- V2-only tests whose required behavior conflicts with approved V3.1 semantics, including `tests/test_luna_hard_mode_v2.py`, `tests/test_minimal_agent_id_v2.py`, `tests/test_minimal_journal_v2.py`, and `tests/test_policy_surface_v2.py`.

Do not delete legacy Local Sol → Web Sol → Luna pipeline/state files merely because V3.1 changes the native global Router control plane.

---

### Task 1: Introduce the V3.1 control-state types and dual-status contract

**Files:**
- Create: `src/codex_router/luna_control.py`
- Create: `tests/test_luna_control_v3.py`

**Interfaces:**
- Produces `TaskStatus = Literal["ACTIVE", "COMPLETED", "CANCELLED"]`.
- Produces `ExecutionStatus = Literal["IDLE", "RUNNING", "QUIESCING", "PAUSED_SETTLED", "RETIRED"]`.
- Produces `ControlSnapshot` with independent logical and execution states.
- Produces `new_task(...)`, `read_snapshot(...)`, and validation helpers used by later tasks.

- [ ] **Step 1: Write RED tests for the dual-dimensional state model**

Add tests equivalent to:

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

And explicitly prove the approved cancellation representation is legal:

```python
cancelled = control._validated_snapshot(
    {
        **base_record,
        "logical_task_status": "CANCELLED",
        "execution_status": "QUIESCING",
    }
)
self.assertEqual(cancelled.logical_task_status, "CANCELLED")
self.assertEqual(cancelled.execution_status, "QUIESCING")
```

Reject impossible combinations such as `ACTIVE + RETIRED`, negative generation, malformed epoch IDs, unknown fields, or an active child-turn ID while execution is `IDLE`.

- [ ] **Step 2: Run the new test module and observe RED**

Run:

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 -v
```

Expected: import failure because `codex_router.luna_control` does not exist.

- [ ] **Step 3: Add the minimal public state types**

Use explicit names and no V2 `ACTIVE|REVOKED` authorization enum:

```python
from dataclasses import dataclass
from typing import Literal

TaskStatus = Literal["ACTIVE", "COMPLETED", "CANCELLED"]
ExecutionStatus = Literal[
    "IDLE",
    "RUNNING",
    "QUIESCING",
    "PAUSED_SETTLED",
    "RETIRED",
]

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

Epochs must use collision-resistant Router-generated IDs such as `task-<uuid>` and `luna-<uuid>`. Keep raw session IDs out of the durable record; derive a keyed session tag from the installation secret.

- [ ] **Step 4: Encode state invariants in one validator**

The validator must enforce at least:

```text
packet_generation >= 0
no Luna agent_id without a Luna task path
RUNNING/QUIESCING requires an active packet
a CANCELLED task may remain QUIESCING or PAUSED_SETTLED
RETIRED cannot accept a current packet
unknown schema keys fail closed
```

- [ ] **Step 5: Run the focused tests and prove GREEN**

Run the same unittest command. Commit:

```bash
git add src/codex_router/luna_control.py tests/test_luna_control_v3.py
git commit -m "feat: add V3.1 Luna control state model"
```

---

### Task 2: Implement the durable V3.1 journal without V2 root-turn revocation

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `tests/test_luna_control_v3.py`

**Interfaces:**
- Produces owner-only `luna-control-v3-1.json` plus `luna-control-v3-1.lock` under the Router installation directory.
- Produces `mutate_control(...)` and `read_snapshot(...)` with locking, bounded schema, atomic replace, file fsync, and directory fsync.
- Persists one bounded current control record per session key; does not retain unbounded historical packet/Luna records.

- [ ] **Step 1: Write RED filesystem-integrity tests**

Cover:

```text
journal mode is 0600
lock is a regular current-user-owned file
journal symlink is rejected
wrong-owner simulation is rejected where testable
unknown/malformed schema fails closed
unchanged reads do not rewrite the journal
security/control transitions fsync the replacement and containing directory
```

Use `unittest.mock.patch("os.fsync")` for deterministic fsync assertions rather than relying on filesystem timing.

- [ ] **Step 2: Write RED bounded-state tests**

Create more than the configured session capacity with retired/settled records and prove compaction removes only non-current historical records. Prove an absent historical record never authorizes an old Luna.

- [ ] **Step 3: Run focused tests and observe RED**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 -v
```

- [ ] **Step 4: Reuse the proven persistence mechanics, not the V2 authorization schema**

Port the safe parts of `native_lifecycle.py` (`O_NOFOLLOW` where available, owner/mode validation, flock, temp file, atomic replace, fsync) into `luna_control.py`, but use a new protocol and schema:

```python
PROTOCOL = "codex-router/luna-control/v3.1"
_STATE = "luna-control-v3-1.json"
_LOCK = "luna-control-v3-1.lock"
```

Do not persist prompts, model output, transcripts, tokens, credentials, or unbounded history.

- [ ] **Step 5: Prove unchanged reads are cheap and mutations durable**

Run the focused test suite again and commit:

```bash
git add src/codex_router/luna_control.py tests/test_luna_control_v3.py
git commit -m "feat: persist V3.1 Luna control state safely"
```

---

### Task 3: Add order-independent spawn reservation and persistent Luna binding

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `tests/test_luna_control_v3.py`

**Interfaces:**
- Produces `reserve_spawn(...)`.
- Produces `observe_spawn_result(...)`.
- Produces `observe_subagent_start(...)`.
- Produces `current_luna(...)` / `authorize_parent_target(...)`.
- `pending_spawn` includes `task_epoch`, `luna_epoch`, expected role, root/session tag, expected parent, `tool_use_id`, optional observed task path, and optional observed `agent_id`.

- [ ] **Step 1: Write RED tests for both native event orderings**

Prove both are valid:

```text
PreToolUse(spawn) -> PostToolUse(spawn result) -> SubagentStart
PreToolUse(spawn) -> SubagentStart -> PostToolUse(spawn result)
```

Binding commits only when the available observations agree on the same pending reservation.

- [ ] **Step 2: Write RED ambiguity and stale-event tests**

Prove:

```text
second simultaneous pending spawn -> denied
wrong role -> denied
wrong task path -> fail closed
late SubagentStart from retired luna_epoch -> cannot bind
spawn result with wrong tool_use_id -> cannot bind
an existing bound Luna prevents a replacement spawn unless controlled replacement has retired it
```

- [ ] **Step 3: Write RED persistence/reuse test across root turns**

Use two different `turn_id` values while keeping the same session/task epoch. Prove no state transition revokes the bound Luna merely because a root turn changed.

- [ ] **Step 4: Implement reservation reconciliation**

Use a record shaped like:

```python
pending_spawn = {
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

`fork_turns` remains mechanically required to equal `"none"`. Do not infer correlation from transcript text or child/root turn equality.

- [ ] **Step 5: Run focused tests and prove GREEN**

Commit:

```bash
git add src/codex_router/luna_control.py tests/test_luna_control_v3.py
git commit -m "feat: add persistent Luna spawn correlation"
```

---

### Task 4: Define the K1 packet wire contract and monotonic generation authority

**Files:**
- Modify: `src/codex_router/protocol.py`
- Modify: `src/codex_router/luna_control.py`
- Modify: `tests/test_luna_control_v3.py`
- Modify: `tests/test_protocol.py` if present; otherwise add packet cases to `tests/test_luna_control_v3.py`.

**Interfaces:**
- Produces `LUNA_PACKET_PREFIX = "[CODEX_ROUTER_PACKET_V3_1] "`.
- Produces `build_luna_packet(...) -> str` and `parse_luna_packet(...) -> dict[str, Any]`.
- Produces `begin_packet(...)` which atomically advances `packet_generation` only when execution state permits a new packet.
- Produces `accept_result(...)` / equivalent correlation check that rejects stale generation or child-turn identities.

- [ ] **Step 1: Write RED schema tests for the exact K1 fields**

Required canonical payload:

```python
{
    "packet_id": "packet-...",
    "generation": 1,
    "objective": "Add multiply() and tests",
    "working_directory": "/workspace/repo",
    "intended_write_scope": ["src/math.py", "tests/test_math.py"],
    "explicit_side_effect_authorizations": [],
    "success_criteria": ["focused tests pass"],
    "stop_conditions": ["scope expansion required", "A1 authorization required"],
}
```

Reject missing/extra keys, non-monotonic generation, relative working directory, empty objective, duplicate or non-text scope entries, unknown A1 categories, and non-canonical JSON.

- [ ] **Step 2: Write RED authority-replacement tests**

Prove generation 2 replaces generation 1 rather than inheriting authorization:

```python
p1 = begin_packet(..., intended_write_scope=("src/auth/**",), a1=("git_push",))
p2 = begin_packet(..., intended_write_scope=("src/api/**",), a1=())
self.assertEqual(p2.generation, p1.generation + 1)
self.assertEqual(p2.explicit_side_effect_authorizations, ())
```

A delayed result from generation 1 must return a stale/non-authoritative disposition and must not mutate current state.

- [ ] **Step 3: Implement the canonical packet marker**

Use the existing `canonical_json_bytes()` helper so Sol/Luna packet identity is deterministic. The packet marker is parsed only on Router lifecycle communication (`send_message`/`followup_task`), not on arbitrary shell commands or Luna output.

- [ ] **Step 4: Implement generation admission**

Normal intended-write-scope changes inside the same native authority profile must not replace Luna. `begin_packet` must deny new execution while control state is `QUIESCING`.

- [ ] **Step 5: Run focused tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 -v
git add src/codex_router/protocol.py src/codex_router/luna_control.py tests
git commit -m "feat: add V3.1 packet generation authority"
```

---

### Task 5: Implement Hard Authority Pause and fail-closed settlement state

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `tests/test_luna_control_v3.py`
- Create/Modify: `tests/test_router_v3.py`

**Interfaces:**
- Produces `freeze_authority(...)`.
- Produces `record_interrupt_ack(...)` as diagnostic-only state that cannot settle execution.
- Produces `observe_settlement(...)` which accepts only a normalized trusted terminal observation supplied by a verified runtime adapter.
- Produces `resume_after_settlement(...)` / `begin_packet(...)` enforcement that refuses N+1 while N is unsettled.

- [ ] **Step 1: Write RED tests reproducing the real smoke finding**

Model the observed sequence:

```python
running = start_execution(..., generation=1)
quiescing = freeze_authority(..., reason="user_pause")
self.assertEqual(quiescing.execution_status, "QUIESCING")

acked = record_interrupt_ack(..., previous_status="running")
self.assertEqual(acked.execution_status, "QUIESCING")

with self.assertRaises(RouterStateError):
    begin_packet(..., generation=2)
```

The test must make it impossible for interrupt acknowledgment alone to produce `PAUSED_SETTLED`.

- [ ] **Step 2: Write RED tests for natural completion after pause**

A trusted terminal observation may settle even if the native interrupt did not kill the process:

```python
settled = observe_settlement(
    ...,
    source="verified_native_terminal",
    terminal_status="completed",
    child_turn_id="turn-n",
)
self.assertEqual(settled.execution_status, "PAUSED_SETTLED")
```

The same API must accept native terminal outcomes such as `failed`, `interrupted`, or `cancelled` only after the runtime adapter has normalized them into the trusted terminal-observation interface.

- [ ] **Step 3: Write the non-blocking review requirement as an executable test**

Prove cancellation does not erase in-flight execution truth:

```python
cancelled = freeze_authority(..., reason="user_cancel", logical_cancel=True)
self.assertEqual(cancelled.logical_task_status, "CANCELLED")
self.assertEqual(cancelled.execution_status, "QUIESCING")

settled = observe_settlement(..., terminal_status="completed")
self.assertEqual(settled.logical_task_status, "CANCELLED")
self.assertEqual(settled.execution_status, "PAUSED_SETTLED")
```

- [ ] **Step 4: Implement the exact transition rules**

`freeze_authority` must atomically:

```text
mark current generation non-runnable
preserve current Luna identity
set execution_status=QUIESCING
optionally set logical_task_status=CANCELLED
retain enough current-generation identity to reject late output
```

Do not add sleeps, timeout-based settlement, PID inspection, or polling loops.

- [ ] **Step 5: Implement a deliberately narrow settlement-observation API**

The core module must not guess raw Codex response shapes. Accept a normalized terminal observation only from the Hook/runtime adapter and verify it matches the current task/luna/generation/child-turn tuple to the strongest exposed degree. If no verified runtime source exists, the state remains `QUIESCING` and live activation remains blocked.

- [ ] **Step 6: Run focused tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 tests.test_router_v3 -v
git add src/codex_router/luna_control.py tests/test_luna_control_v3.py tests/test_router_v3.py
git commit -m "feat: add V3.1 hard authority pause"
```

---

### Task 6: Replace the V2 Hook policy with the minimal V3.1 control-plane bridge

**Files:**
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/cli.py`
- Modify: `tests/test_hook.py`
- Modify: `tests/test_router_v3.py`
- Modify: `tests/test_router_authority_realign.py` or replace its conflicting cases with V3 assertions.

**Interfaces:**
- `UserPromptSubmit` surfaces V3.1 route context but does not revoke Luna because `turn_id` changed.
- `PreToolUse` controls Router lifecycle calls and denies Luna descendant-lifecycle attempts; it does not police ordinary Luna shell/read/write/build/test tools.
- `PostToolUse` reconciles spawn results and only accepts additional settlement evidence after an exact runtime adapter is proven; it is not a general tool-output firewall.
- `SubagentStart` records/reconciles native Luna identity.
- Legacy `hook-stop` / `hook-permission-request` CLI entry points may remain temporarily callable for transactional upgrade compatibility, but V3.1 baseline rendering does not register them.

- [ ] **Step 1: Write RED route-context tests**

Expected V3 context includes:

```python
self.assertEqual(context["workflow"], "persistent_native_luna")
self.assertEqual(context["luna_lifecycle"], "persistent_task_epoch")
self.assertEqual(context["pause_semantics"], "hard_authority_pause")
self.assertEqual(context["sol_supervision"], "event_driven")
self.assertEqual(context["luna_execution_mode"], "full_executor")
```

A second routed root turn in the same session must not revoke the existing Luna solely because `turn_id` differs.

- [ ] **Step 2: Write RED Full Executor Hook tests**

After a bound Luna is recognized, ordinary tools such as these must not be denied by Router merely because they are executable:

```text
Read
apply_patch
Bash
shell_command
exec_command
web/MCP/plugin tool names not recognized as agent lifecycle
```

Agent lifecycle/delegation remains denied for Luna:

```text
spawn_agent
send_message to descendants
resume_agent descendant path
other agent_* / *_agent lifecycle variants
```

Do not test or implement a positive allowlist for ordinary tools.

- [ ] **Step 3: Replace V2 root-turn revocation calls**

Remove `native_lifecycle.revoke_stale(...)` from `handle_user_prompt`. Load/read the current V3 task control record and expose enough state for Sol to decide reuse versus controlled task-epoch replacement.

- [ ] **Step 4: Replace V2 lifecycle calls with `luna_control` calls**

Map only exact known parent lifecycle schemas. Unknown lifecycle operations fail closed for Router authority; unknown ordinary executor tools are not denied merely because Router does not recognize them.

- [ ] **Step 5: Keep actor-specific claims honest**

If a Hook event does not expose trustworthy child actor identity, do not silently classify it as root for a security-sensitive lifecycle action. Return a fail-closed lifecycle decision or an acceptance-readiness blocker according to the event class. Ordinary non-lifecycle tool calls remain governed by native Codex controls.

- [ ] **Step 6: Run focused Hook tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_hook tests.test_router_v3 -v
git add src/codex_router/hook.py src/codex_router/cli.py tests
git commit -m "feat: narrow Router hooks for V3.1"
```

---

### Task 7: Render the Full Executor Luna profile and exactly four baseline Hooks

**Files:**
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `src/codex_router/global_install.py` only where the adapter contract requires it.
- Modify: `tests/test_global_install.py`
- Modify: `tests/test_global_self_test.py`
- Modify: `tests/test_primary_capability_v2.py` into version-neutral/V3 readiness assertions.

**Interfaces:**
- Produces `LUNA_EXECUTION_MODE = "full_executor_v3_1"`.
- Produces V3.1 Luna TOML with descendant disable triad but no V2 shell/process disable block.
- Produces four baseline Router-managed Hook registrations: `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`.

- [ ] **Step 1: Write RED profile-rendering tests**

The rendered Luna profile must include:

```toml
[agents]
enabled = false

[features]
multi_agent = false
multi_agent_v2 = false
```

And must **not** force these V2 restrictions solely for Router policy:

```text
shell_tool = false
unified_exec = false
code_mode_only = false
apps = false
plugins = false
web_search = "disabled"
```

If the exact Codex profile schema later requires explicit keys for a capability, add them only from verified target-runtime evidence; do not invent them in this task.

- [ ] **Step 2: Write RED Hook-count tests**

Assert the baseline managed Hook set is exactly:

```python
{
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
}
```

`Stop` and `PermissionRequest` must not appear in baseline rendered hooks.

- [ ] **Step 3: Replace V2 generated policy text**

Generated `AGENTS.md` and Luna developer instructions must say:

```text
one persistent Luna per coherent task epoch
root turn is not Luna lifecycle boundary
Full Executor ordinary inspect/research/edit/test/debug/retry/verify
no descendants
no nested Codex delegation
packet generation replaces prior authority
Hard Authority Pause freezes Router authority immediately
old and new packet execution cannot overlap before settlement
A1 requires current-packet authorization and only has a hard claim where a pre-action gate is proven
```

Remove `hard_mode_no_process`, `revoke_only_security_boundary` root-turn semantics, and broad allowed-tool language.

- [ ] **Step 4: Keep transaction/rollback mechanics unchanged**

Use the existing adapter seam around `global_install.py`; do not rewrite backup names, rollback state, target hashing, drift detection, or uninstall restoration unless a failing V3 test demonstrates a direct incompatibility.

- [ ] **Step 5: Run installer/self-test suites and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_global_install tests.test_global_self_test -v
git add src/codex_router/global_install_adapter.py src/codex_router/global_install.py tests
git commit -m "feat: render V3.1 full executor profile"
```

---

### Task 8: Add A1 capability/readiness modeling without a shell firewall

**Files:**
- Create: `src/codex_router/a1.py`
- Create: `tests/test_a1_v3.py`
- Modify: `src/codex_router/protocol.py`
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/global_install_adapter.py`

**Interfaces:**
- Produces canonical A1 category names.
- Produces `SurfaceEnforcement = Literal["PROVEN_PRE_ACTION", "BASELINE_WITHHELD", "COOPERATIVE_ONLY", "UNVERIFIED"]`.
- Produces `A1SurfaceCapability` and `A1CapabilityMatrix`.
- Produces `validate_packet_authorizations(...)` and `hard_claim_ready(...)`.
- `PermissionRequest` registration/handling is enabled only for a matrix entry whose exact surface and actor attribution are proven to require/use it.

- [ ] **Step 1: Write RED category and non-inheritance tests**

Canonical categories:

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
```

Generation N authorization must not appear in N+1 unless explicitly restated.

- [ ] **Step 2: Write RED hard-claim tests**

Examples:

```python
unverified = A1SurfaceCapability(
    category="git_push",
    surface="shell",
    enforcement="UNVERIFIED",
    gate=None,
    actor_attribution="UNVERIFIED",
)
self.assertFalse(hard_claim_ready((unverified,), "git_push"))
```

A cooperative developer instruction alone must never return hard-ready.

- [ ] **Step 3: Write RED tests proving there is no broad command parser**

Do not classify arbitrary Bash strings such as `git push`, `curl`, or compound shell commands in `a1.py`. The module operates on capability/surface metadata and explicit packet authorization, not shell syntax.

- [ ] **Step 4: Implement conditional `PermissionRequest` support**

The installer may add `PermissionRequest` only when the exact runtime compatibility profile says a specific A1 surface uses a proven attributable pre-action permission event. Otherwise baseline Hooks remain four and the corresponding hard A1 readiness remains blocked/withheld.

- [ ] **Step 5: Run A1/Hook/installer tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_a1_v3 tests.test_hook tests.test_global_install -v
git add src/codex_router/a1.py src/codex_router/protocol.py src/codex_router/hook.py src/codex_router/global_install_adapter.py tests/test_a1_v3.py tests
git commit -m "feat: model V3.1 A1 capability gates"
```

---

### Task 9: Implement controlled replacement and durable recovery validation

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `tests/test_luna_control_v3.py`
- Modify: `tests/test_router_v3.py`

**Interfaces:**
- Produces `retire_luna(...)`, `start_new_task_epoch(...)`, and `reconcile_recovery(...)`.
- Controlled replacement reasons are restricted to `unrecoverable_runtime_identity`, `new_task_epoch`, `native_authority_profile_change`, and a later runtime-validated context reset reason.
- Recovery requires the strongest available parent/role/agent/profile evidence; resumability alone is not authority.

- [ ] **Step 1: Write RED replacement-reason tests**

Prove ordinary `intended_write_scope` change inside the same profile does not replace Luna. Prove a native authority-profile change cannot start a new Luna until the old execution is settled/retired.

- [ ] **Step 2: Write RED recovery tests**

Given a persisted record, reject recovery if any available authoritative field conflicts:

```text
wrong native parent
wrong Luna role
wrong agent_id
wrong authority-profile hash
retired luna_epoch
ambiguous multiple candidates
```

A candidate that merely exists or is resumable must not bind.

- [ ] **Step 3: Write RED delayed-event race tests**

Simulate a delayed SubagentStart from Luna epoch E while E+1 has a pending reservation. It must not bind or overwrite E+1.

- [ ] **Step 4: Implement controlled replacement**

Replacement flow is:

```text
freeze old authority if execution is running
wait for trusted settlement observation
mark old Luna RETIRED
create new task/luna epoch or new authority profile
reserve exactly one replacement spawn
```

Do not replace merely because Luna is idle/completed or because a root turn changed.

- [ ] **Step 5: Run focused tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_luna_control_v3 tests.test_router_v3 -v
git add src/codex_router/luna_control.py tests/test_luna_control_v3.py tests/test_router_v3.py
git commit -m "feat: add V3.1 Luna recovery and replacement"
```

---

### Task 10: Expose honest V3.1 readiness and acceptance blockers

**Files:**
- Modify: `src/codex_router/types.py`
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `src/codex_router/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_global_install.py`
- Modify: `tests/test_global_self_test.py`

**Interfaces:**
- Extend `GlobalStatus` with version/readiness information without claiming current-turn telemetry.
- Suggested fields:

```python
router_design: str = "v3.1"
live_activation: str = "BLOCKED_ACCEPTANCE_GATES"
acceptance_blockers: tuple[str, ...] = ()
```

- Status must distinguish repository implementation readiness from live activation readiness.

- [ ] **Step 1: Write RED status tests**

An offline installed V3.1 candidate with no target-runtime proof must report blockers including the unresolved applicable gates, for example:

```text
G2_SETTLEMENT_OBSERVATION
G3_ACTOR_ATTRIBUTION
G4_NO_DESCENDANTS_EFFECTIVE_INVENTORY
G5_NESTED_CODEX
G6_NATIVE_AUTHORITY_PROFILE
G7_A1_CAPABILITY_MATRIX
G8_RECOVERY_CORRELATION
G9_ECONOMICS
```

Do not list G1 product feasibility as failed; distinguish its stronger identity/profile acceptance subclaim if still unresolved.

- [ ] **Step 2: Preserve primary capability diagnostics**

Keep `COMPATIBLE | INCOMPATIBLE | UNKNOWN_REQUIRES_CAPABILITY_CHECK`. V3.1 status may be repository-green while live activation remains blocked.

- [ ] **Step 3: Update CLI JSON serialization**

Example output fields:

```json
{
  "router_design": "v3.1",
  "luna_execution_mode": "full_executor_v3_1",
  "live_activation": "BLOCKED_ACCEPTANCE_GATES",
  "acceptance_blockers": ["G2_SETTLEMENT_OBSERVATION", "G4_NO_DESCENDANTS_EFFECTIVE_INVENTORY"]
}
```

- [ ] **Step 4: Make offline self-test verify claims, not erase blockers**

`global-self-test` may pass repository/install invariants while returning live-activation blockers separately. A passing offline self-test must not imply target runtime acceptance.

- [ ] **Step 5: Run status/CLI tests and commit**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_cli tests.test_global_install tests.test_global_self_test -v
git add src/codex_router/types.py src/codex_router/global_install_adapter.py src/codex_router/cli.py tests
git commit -m "feat: report V3.1 activation readiness"
```

---

### Task 11: Replace obsolete V2 tests/module only after V3 parity is green

**Files:**
- Delete: `src/codex_router/native_lifecycle.py`
- Modify/Delete: `tests/test_native_lifecycle.py`
- Modify/Delete: `tests/test_router_authority_realign.py`
- Delete after equivalent V3 coverage: `tests/test_luna_hard_mode_v2.py`
- Delete after equivalent V3 coverage: `tests/test_minimal_agent_id_v2.py`
- Delete after equivalent V3 coverage: `tests/test_minimal_journal_v2.py`
- Delete after equivalent V3 coverage: `tests/test_policy_surface_v2.py`
- Modify: any remaining imports found by repository search.

**Interfaces:**
- No runtime code imports `native_lifecycle` after this task.
- Equivalent durability, agent binding, target validation, and fail-closed lifecycle tests exist under V3 names before V2 files are removed.

- [ ] **Step 1: Prove V3 focused suites are green before deleting V2 code**

```bash
PYTHONPATH=src python3.12 -m unittest \
  tests.test_luna_control_v3 \
  tests.test_router_v3 \
  tests.test_a1_v3 \
  tests.test_hook -v
```

- [ ] **Step 2: Search for V2-only imports and semantic labels**

Run:

```bash
grep -R "native_lifecycle\|native-luna-safety-v2\|hard_mode_no_process\|persistent_while_root_turn_active\|revoke_only_security_boundary" -n src tests
```

Every remaining match must be either deliberate historical compatibility text in a migration test or removed in this task.

- [ ] **Step 3: Delete V2 lifecycle implementation and conflicting tests**

Do not retain two active authorization state machines. Preserve useful test cases by porting them to V3 tests before deletion.

- [ ] **Step 4: Run all unit tests**

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
```

- [ ] **Step 5: Commit the migration cleanup**

```bash
git add -A src tests
git commit -m "refactor: remove superseded V2 Luna control path"
```

---

### Task 12: Synchronize runtime-acceptance guidance and public documentation

**Files:**
- Modify: `docs/superpowers/plans/2026-08-17-router-v3-1-exact-runtime-validation.md`
- Modify: `README.md`
- Modify: generated policy constants in `src/codex_router/global_install_adapter.py` if documentation review finds mismatch.
- Modify: tests that assert generated documentation/policy text.

**Interfaces:**
- Runtime validation normal path uses the currently authenticated Codex App and controlled target-profile evidence; it does not require new OAuth or a standalone authenticated root.
- Acceptance remains staged and blocks live claims until the relevant gates are closed.

- [ ] **Step 1: Rewrite the validation topology section**

The validation plan must explicitly state:

```text
NEW_OAUTH_FOR_VALIDATION=FORBIDDEN
STANDALONE_AUTHENTICATED_ROOT=NORMAL_PATH_DROPPED
CURRENT_APP_SMALL_TASK_SMOKE=PREFERRED_FOR_PRODUCT_RUNTIME_FEASIBILITY
TARGET_PROFILE_ACCEPTANCE=REQUIRED_FOR_G4_G7_AND_OTHER_PROFILE_DEPENDENT_CLAIMS
```

Retain the historical standalone-auth attempt only as historical context if needed; it must not remain a prerequisite.

- [ ] **Step 2: Encode the current evidence disposition**

Document:

```text
P1_PRODUCT_RUNTIME_FEASIBILITY=PASS
INTERRUPT_ACK_AS_SETTLEMENT=REJECTED_BY_RUNTIME_EVIDENCE
G9_SHORT_CONTEXT_REUSE=PASS
G2_SETTLEMENT_OBSERVATION=ACCEPTANCE_GATE
G3_G8_HIDDEN_RUNTIME_FIELDS=ACCEPTANCE_GATE
G4_G7_TARGET_PROFILE_PROPERTIES=ACCEPTANCE_GATE
```

Do not claim native numeric IDs or Hook actor fields that the current App surface did not expose.

- [ ] **Step 3: Update README architecture and safety semantics**

README must describe one persistent Luna per task epoch, Full Executor ordinary capability, Hard Authority Pause, A1 pre-action requirement, no descendants, and live-activation blockers. Remove V2 hard-no-process and per-root revocation claims from current documentation; keep historical docs clearly historical.

- [ ] **Step 4: Run documentation/policy tests and whitespace checks**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_global_install tests.test_hook -v
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers/plans/2026-08-17-router-v3-1-exact-runtime-validation.md src/codex_router/global_install_adapter.py tests
git commit -m "docs: align V3.1 runtime acceptance workflow"
```

---

### Task 13: Full repository verification and Draft-PR implementation handoff

**Files:**
- Modify only files required by observed verification failures.
- Do not change PR body/state in this task unless the user separately authorizes that GitHub mutation.

- [ ] **Step 1: Run the complete CI-equivalent unit and compile checks**

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
git diff --check
```

Expected: all tests pass, compile exits 0, diff check exits 0.

- [ ] **Step 2: Run the fake-adapter legacy smoke**

```bash
state_dir="$(mktemp -d)"
output="$(PYTHONPATH=src python3.12 -m codex_router run \
  --task "Return exactly ROUTER_MVP_OK" \
  --adapter-mode fake \
  --state-dir "$state_dir")"
test "$output" = "ROUTER_MVP_OK"
```

This proves V3.1 native-global-policy work did not break the legacy pipeline command.

- [ ] **Step 3: Build and install a fresh wheel in a temporary virtualenv**

```bash
rm -rf dist
python3.12 -m pip wheel . --no-deps --wheel-dir dist
wheel_env="$(mktemp -d)/venv"
python3.12 -m venv "$wheel_env"
"$wheel_env/bin/python" -m pip install --no-deps dist/codex_router-*.whl
```

- [ ] **Step 4: Run disposable offline global install/self-test/uninstall**

Use only fresh temporary paths and a synthetic executable; do not point at live `~/.codex`:

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

Verify offline self-test success is separate from `live_activation=BLOCKED_ACCEPTANCE_GATES`.

- [ ] **Step 5: Run the anti-regression semantic scan**

```bash
grep -R "hard_mode_no_process\|persistent_while_root_turn_active\|revoke_only_security_boundary" -n src tests README.md || true
grep -R "PermissionRequest\|Stop" -n src/codex_router/global_install_adapter.py
```

Interpretation:

```text
no current-policy hard_mode_no_process claim
no per-root persistent lifetime claim
no revoke-only root terminal semantics
baseline Hook renderer contains no Stop
PermissionRequest appears only in conditional A1-specific logic or compatibility code
```

- [ ] **Step 6: Review the implementation against each approved design boundary**

Confirm:

```text
P1 persistent reuse is the normal path
logical CANCELLED can coexist with execution QUIESCING
interrupt ACK cannot settle
N+1 cannot execute before N settles
stale N output cannot advance authority
intended_write_scope change does not automatically replace Luna
Full Executor ordinary tools are not Router-allowlisted
no descendant capability is rendered in Luna profile
A1 hard claims are gated by per-surface evidence
no new OAuth validation path exists
standalone authenticated root is not required
live activation remains blocked on unresolved acceptance gates
```

- [ ] **Step 7: Commit only verification-driven fixes, then stop before live activation**

If verification required code changes, use one final focused commit after rerunning the affected tests. Final implementation handoff must report exact evidence using:

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

Do not install to live `~/.codex`, change Hook trust, mark PR ready, merge, or claim G2-G8 acceptance without the later target-runtime evidence.

---

## Self-Review

### Spec coverage

- P1 persistent Luna: Tasks 3, 4, 9.
- Four authority/correlation dimensions and stale-result rejection: Tasks 1, 3, 4, 9.
- `native_workspace_boundary` vs `intended_write_scope`: Tasks 4, 9, 13.
- K1 minimal packet: Task 4.
- Hard Authority Pause and dual cancellation/execution state: Task 5.
- Event-driven Sleeping Sol / no polling: Tasks 5, 6, 13.
- E2 remains prompt/policy behavior and is synchronized in Tasks 7 and 12; no new broad escalation machinery is introduced.
- A1 hard-claim discipline: Task 8.
- No descendants and Full Executor: Tasks 6, 7.
- Minimal four-Hook baseline: Tasks 6, 7.
- Controlled replacement/recovery: Task 9.
- Durable state integrity: Tasks 1, 2, 9.
- Runtime-gate staging / no new OAuth: Tasks 10, 12, 13.
- Live-activation and merge-ready blockers: Tasks 10, 12, 13.

### Type/interface consistency

- `logical_task_status` and `execution_status` are independent throughout the plan.
- `packet_generation` is monotonic and is the packet-authority version everywhere.
- `pending_spawn` is a structured reservation, not a boolean.
- Settlement is represented by `observe_settlement(...)`; `record_interrupt_ack(...)` never settles.
- A1 authorization uses canonical category names from `a1.py`; packet generations never inherit them.
- The Hook layer consumes `luna_control.py`; no second active V2 authorization state machine remains after Task 11.

### Scope check

The tasks form one implementation sequence around a single product subsystem: the native persistent-Luna global Router control plane. Legacy pipeline behavior is preserved and tested but not redesigned. Runtime acceptance is deliberately staged after implementation rather than expanded into an unrelated authentication or live-migration project.
