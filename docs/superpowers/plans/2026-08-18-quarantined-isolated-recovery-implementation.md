# Quarantined Isolated Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal fail-closed `QUARANTINED` execution state and a narrow independent-Git-repository recovery path without expanding Router into a workspace/process supervisor.

**Architecture:** Extend `luna_control.py` only. An active packet opportunistically records a clean Git baseline; inability to record a baseline does not block ordinary execution. A quiescing execution may be quarantined, making the old Luna permanently non-current. Replacement is allowed only when the current packet has no A1 authorization and a caller-supplied replacement workspace is mechanically verified as clean, independent Git metadata, disjoint path, and exact baseline commit.

**Tech Stack:** Python 3.12 standard library, `subprocess` Git inspection, existing unittest suite.

**Spec:** `docs/superpowers/specs/2026-08-18-quarantined-isolated-recovery-v3-1-addendum.md`

## Global Constraints

- Keep PR #8 Draft and unmerged.
- Do not modify live `~/.codex`, Hook trust, OAuth/device auth, or live Router installation.
- Do not add PID/process-group supervision, polling, broad shell parsing, workspace epochs, snapshot services, or promotion/salvage engines.
- `Interrupted` is not valid settlement evidence.
- Normal execution must remain available for dirty or non-Git work; only automatic isolated recovery becomes unavailable.
- Automatic recovery must deny any quarantined packet carrying explicit A1 authorization.

---

### Task 1: Quarantine state and optional clean-Git baseline

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Test: `tests/test_v31_quarantined_recovery.py`
- Modify: `tests/test_luna_control_v3.py`

**Interfaces:**
- Produces: `RecoveryBaseline`, optional `ControlSnapshot.recovery_baseline`, `quarantine_execution(...)`.
- Existing `begin_packet(...)` opportunistically captures a clean Git baseline from `working_directory`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_v31_quarantined_recovery.py` with tests that:

```python
# dirty/non-Git work still begins normally but has recovery_baseline is None
# clean Git work records canonical workspace root, HEAD commit, and git common dir
# QUIESCING -> QUARANTINED succeeds
# QUARANTINED rejects current_luna/parent work/start_execution and old result is STALE
# observe_settlement(... terminal_status="interrupted") raises RouterStateError
```

Update existing tests that used `terminal_status="interrupted"` as successful settlement to use `completed` where the test is about another invariant.

- [ ] **Step 2: Verify RED**

Run the full GitHub Actions CI on the test-only commit. Expected: failures for missing `QUARANTINED`, missing recovery baseline, and acceptance of `Interrupted`.

- [ ] **Step 3: Implement minimal state changes**

In `luna_control.py`:

```python
@dataclass(frozen=True)
class RecoveryBaseline:
    workspace_root: str
    head_commit: str
    git_common_dir: str
```

Add `recovery_baseline: RecoveryBaseline | None = None` to `ControlSnapshot` with backward-compatible disk decoding.

Add `QUARANTINED` to `ExecutionStatus` and validation. `RUNNING`, `QUIESCING`, and `QUARANTINED` require an active packet.

Add a private Git inspection helper using argument-vector `subprocess.run` with no shell. It returns `None` for non-Git/dirty/unborn/unavailable workspaces and returns `RecoveryBaseline` only when:

```text
git status --porcelain=v1 == empty
git rev-parse HEAD succeeds
git rev-parse --git-common-dir succeeds
```

`begin_packet()` records the resulting optional baseline.

Add:

```python
def quarantine_execution(directory, secret, session_id, *, reason) -> ControlSnapshot:
```

It accepts only `QUIESCING`, preserves packet/generation/child-turn/baseline metadata, and sets `execution_status="QUARANTINED"`.

`current_luna()` and work dispatch reject a quarantined Luna. `accept_result()` treats quarantine as stale. `start_execution()` rejects quarantine.

Remove `interrupted` from accepted settlement terminal statuses. Permit a later verified settlement to transition either `QUIESCING` or `QUARANTINED` to `PAUSED_SETTLED`.

- [ ] **Step 4: Run tests GREEN**

Run targeted tests then full CI. Expected: all tests pass.

- [ ] **Step 5: Commit**

Commit message:

```text
feat: quarantine unobservable Luna execution
```

---

### Task 2: Independent clean-repository replacement

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Test: `tests/test_v31_quarantined_recovery.py`

**Interfaces:**
- Produces:

```python
def replace_quarantined_luna_epoch(
    directory,
    secret,
    session_id,
    *,
    replacement_workspace,
    native_parent_identity,
    native_authority_profile,
    tool_use_id=None,
    expected_agent_id=None,
) -> ControlSnapshot:
```

- [ ] **Step 1: Write failing recovery-proof tests**

Add tests proving replacement fails closed for:

```text
missing recovery baseline
dirty replacement repo
wrong HEAD commit
same workspace path
linked Git worktree / same git common directory
active explicit A1 authorization
same native authority profile
```

Add one positive test creating two independent temporary Git repositories where the replacement repository is clean and points at the exact captured baseline commit. Assert:

```text
task_epoch unchanged
luna_epoch changed
packet_generation unchanged
active_packet_id is None
execution_status == IDLE
recovery_baseline is None
pending spawn matches fresh Luna epoch when tool_use_id is supplied
```

Then begin the next packet and assert generation increments monotonically.

- [ ] **Step 2: Verify RED**

Run CI on the test-only commit. Expected: replacement API missing/failing tests.

- [ ] **Step 3: Implement the proof and replacement**

Reuse the Git inspection helper. Require the previous snapshot to be `ACTIVE + QUARANTINED`, bound to a Luna, with a non-`None` recovery baseline and no explicit A1 authorizations.

Canonicalize the replacement path and verify:

```text
replacement root != old root
neither root contains the other
replacement HEAD == baseline HEAD
replacement git common dir != baseline git common dir
replacement worktree/index clean
new native authority profile != old native authority profile
```

On success create a fresh `luna_epoch`, preserve `task_epoch` and `packet_generation`, clear old packet/execution metadata and recovery baseline, set `IDLE`, and optionally create a fresh spawn reservation.

Do not mark the old Luna `RETIRED`; quarantine is intentionally distinct from settled retirement.

- [ ] **Step 4: Run tests GREEN**

Run targeted tests then full GitHub Actions CI, compileall, diff check, fake adapter, wheel/fresh-install smoke, and disposable global install/self-test/uninstall workflow.

- [ ] **Step 5: Commit**

Commit message:

```text
feat: add isolated recovery for quarantined Luna
```

---

### Task 3: Final verification and status documentation

**Files:**
- Modify only if required by failed assertions: runtime/design documentation; no PR metadata update unless separately requested.

**Interfaces:**
- Consumes the completed Task 1/2 implementation.
- Produces final offline disposition only.

- [ ] **Step 1: Run full verification**

Require all repository tests, compileall, diff check, fake adapter, wheel install, fresh-wheel adapter, disposable install/self-test/uninstall, and secret scan to pass at the final head.

- [ ] **Step 2: Re-audit the final diff**

Check that no broad process supervisor, polling loop, live config/auth mutation, linked-worktree hard-isolation claim, or `Interrupted` settlement path was introduced.

- [ ] **Step 3: Freeze disposition**

Expected final status:

```text
QUARANTINED_RECOVERY_MODEL=GREEN_OFFLINE
INTERRUPTED_AS_SETTLEMENT=REJECTED
LIVE_ACTIVATION=BLOCKED_ACCEPTANCE_GATES
PR_DRAFT=KEEP
MERGE=NO
```

No ready-for-review or merge action is part of this plan.
