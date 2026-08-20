# Router V3.2 Usability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Router reliably usable for normal Codex work by separating security failures from runtime capability failures, while preserving K1 as the sole Luna work authority.

**Architecture:** Replace model-assembled semantic staging argv with a single request-file staging interface, add a pure mechanical PRIMARY fallback-state classifier and exact strict marker, and change Luna bootstrap to an allowlisted read-only first probe that receives K1 without relying on a denial retry. Existing identity/generation/lifecycle fail-closed rules remain unchanged.

**Tech Stack:** Python 3, stdlib `argparse/json/pathlib/stat`, unittest, Codex lifecycle Hooks, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-20-router-v3-2-usability-hardening-design.md`

## Global Constraints

- K1 remains the sole authoritative Luna work packet.
- Native spawn/follow-up messages remain non-authoritative transport triggers.
- `send_input` and `resume_agent` remain forbidden; `send_message` remains QueueOnly.
- No wait-as-sync, polling/sleep security primitive, second control plane, daemon, or broad shell firewall.
- Automatic PRIMARY degradation is allowed only from mechanically `SAFE_LOCAL_FALLBACK` state and never authorizes A1/external side effects.
- Exact `[CODEX_ROUTER_STRICT]` disables capability degradation for that turn.
- Existing V1 and V2 exact normalization and identity correlation remain fail-closed.

---

### Task 1: Stable request-file K1 staging

**Files:**
- Modify: `src/codex_router/cli.py`
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `tests/test_runtime_operator_contract_v31.py`
- Modify: `tests/test_k1_sideband_v31.py`

**Interfaces:**
- Produces CLI: `stage-k1-request --installation-dir ... --session-id ... --root-turn-id ... --capability ... --request-file ...`
- Produces helper: strict seven-key request object -> canonical `build_luna_packet()` -> existing `stage_authority_packet()`.
- Hook context produces `K1_STAGE_REQUEST_PATH` and a complete `K1_STAGE_COMMAND`; PRIMARY appends no semantic packet flags.

- [ ] **Step 1: Write failing request-interface tests**

Add tests that assert:

```python
request = {
    "packet_id": "packet-1",
    "objective": "bounded work",
    "working_directory": str(self.installation),
    "intended_write_scope": ["README.md"],
    "explicit_side_effect_authorizations": [],
    "success_criteria": ["pass"],
    "stop_conditions": ["blocked"],
}
```

A request file with that exact schema stages generation 1. Extra keys, non-list list fields, relative working directory, symlink request path, request path outside the installation request namespace, and oversized content must return `invalid-input` with unchanged Router snapshot.

- [ ] **Step 2: Verify the new tests fail on V3.1**

Run the focused test module in CI/available execution and require failure because `stage-k1-request` and routed request-path context do not yet exist.

- [ ] **Step 3: Implement request parsing and staging**

In `cli.py`:

```python
K1_REQUEST_FIELDS = frozenset({
    "packet_id",
    "objective",
    "working_directory",
    "intended_write_scope",
    "explicit_side_effect_authorizations",
    "success_criteria",
    "stop_conditions",
})
```

Add parser arguments for `stage-k1-request`. Validate a regular non-symlink request file under the installation's derived `stage-requests` namespace, bounded by `MAX_HOOK_INPUT_BYTES`. Require current-user ownership; normalize a user-owned non-group/world-writable file to `0600` before reading so ordinary workspace file creation does not create a usability trap. Reject group/world-writable request files.

Parse exactly the seven keys and call the same canonical packet builder/state transition used by `stage-k1-fields`. Delete only the exact request file after successful staging.

- [ ] **Step 4: Render an exact request path and command**

In `hook.py`, derive a request filename from the keyed session tag and current root-turn tag under `<installation_dir>/stage-requests/`. Ensure the private directory exists with `0700` and is owned by the current user. Inject:

```text
K1_STAGE_REQUEST_PATH=<exact absolute path>
K1_STAGE_COMMAND=<complete stage-k1-request command>
```

Do not expose a model-extendable staging prefix.

- [ ] **Step 5: Update primary policy text**

Change `AGENTS_BLOCK_V3` so PRIMARY writes exactly the seven-field request JSON to `K1_STAGE_REQUEST_PATH` and runs `K1_STAGE_COMMAND` verbatim. Keep `stage-k1-fields` documented only as compatibility/legacy operator seam.

- [ ] **Step 6: Run focused staging tests and commit**

Expected: request-file tests and existing `stage-k1-fields` compatibility tests pass.

Commit: `feat: add stable K1 request staging`

---

### Task 2: Mechanical PRIMARY fallback and strict mode

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Modify: `src/codex_router/policy.py`
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `tests/test_primary_capability_v3.py`
- Modify: policy/hook tests containing route/direct markers

**Interfaces:**
- Produces `classify_primary_fallback(snapshot) -> str` with exact values `SAFE_LOCAL_FALLBACK`, `BLOCKED_ACTIVE_AUTHORITY`, `BLOCKED_PENDING_SPAWN`, `BLOCKED_TASK_STATE`.
- Produces policy property `strict_router: bool` from exact first-line `[CODEX_ROUTER_STRICT]`.
- Routed context adds `capability_failure_policy`, `primary_fallback_state`, and `strict_router`.

- [ ] **Step 1: Write failing fallback-state tests**

Test an active idle clear task as `SAFE_LOCAL_FALLBACK`; active packet/running state as `BLOCKED_ACTIVE_AUTHORITY`; pending spawn as `BLOCKED_PENDING_SPAWN`; terminal/retired task as `BLOCKED_TASK_STATE`.

- [ ] **Step 2: Write failing strict-marker tests**

Test:

```text
[CODEX_ROUTER_STRICT]
fix the tests
```

routes with `strict_router=True`, while ordinary substantive prompts route with `strict_router=False`. Existing DIRECT/bypass markers keep precedence and one-turn behavior.

- [ ] **Step 3: Implement the pure state classifier**

The classifier must not mutate the journal. `SAFE_LOCAL_FALLBACK` requires active logical task, IDLE execution, no active packet, no child turn, no staged wire, and no pending spawn. A bound idle Luna is allowed to remain.

- [ ] **Step 4: Extend policy decision without natural-language heuristics**

Add a `strict_router: bool = False` field to `PolicyDecision`. Recognize only the exact first non-empty line marker `[CODEX_ROUTER_STRICT]`; strip that marker only for classification of the remaining prompt, not for authorization semantics.

- [ ] **Step 5: Inject fallback state into routed context**

Add:

```text
capability_failure_policy=degrade_primary_safe_local
primary_fallback_state=<pure classifier result>
strict_router=<true|false>
```

- [ ] **Step 6: Update follow-up capability semantics**

Keep `native_surface_compatibility()` pure. Replace ordinary `BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` operator wording with a decision that can be interpreted as degraded-safe only when the Hook state is `SAFE_LOCAL_FALLBACK`; strict mode remains blocked.

Update `primary_model_is_admitted()` to use `native_surface_compatibility()` Gen1 readiness rather than requiring the complete V2 triad, so proven V1 Gen1 is admitted independently of persistent follow-up.

- [ ] **Step 7: Update PRIMARY instructions**

When follow-up is absent:

```text
if strict_router=true: block
elif primary_fallback_state=SAFE_LOCAL_FALLBACK: do not stage Gen2; continue bounded local PRIMARY work
else: block
```

Explicitly prohibit degraded fallback for deploy/publish/credentials/cloud mutation/A1 effects/agent creation.

- [ ] **Step 8: Run focused capability/policy tests and commit**

Commit: `feat: degrade safely on Router capability gaps`

---

### Task 3: Allowlisted first-tool bootstrap

**Files:**
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/luna_control_recovery.py`
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `tests/test_k1_sideband_v31.py`

**Interfaces:**
- First current Luna tool may bootstrap only if canonical operation is exact `pwd` and input is empty/equivalent harmless shape.
- Successful bootstrap output is `permissionDecision=allow` with exact K1 `additionalContext`.
- Any other first tool remains `deny` and cannot execute before K1.

- [ ] **Step 1: Write failing handshake tests**

Replace the old expectation that the exact first harmless probe is denied. Assert instead:

```python
output["hookSpecificOutput"]["permissionDecision"] == "allow"
output["hookSpecificOutput"]["additionalContext"] == exact_packet_wire
```

Assert a first `shell`/write/lifecycle/substantive tool is denied before any execution state is authorized. Assert a different child turn remains denied.

- [ ] **Step 2: Verify tests fail against V3.1 deny-retry handshake**

Expected failure: current code returns `deny` for the first harmless probe.

- [ ] **Step 3: Split handshake state transition from general authorization**

Keep identity/generation checks in `authorize_executor_tool`, but expose whether a call is the first bootstrap. The Hook decides whether the requested tool is the exact harmless probe before returning `allow + additionalContext`.

Do not allow arbitrary tools merely because K1 wire exists.

- [ ] **Step 4: Update Luna developer instructions**

Luna should issue one exact harmless `pwd` bootstrap probe. Router allows only that probe while injecting K1. Substantive work starts only after the canonical packet is present. Unexpected absence of K1 remains fail-closed.

- [ ] **Step 5: Preserve compatibility claim boundary**

Docs/tests must not claim the current App has live-proven `allow + additionalContext` until post-install acceptance observes it. Repository contract can be complete while live runtime remains acceptance-gated.

- [ ] **Step 6: Run focused K1/Hook tests and commit**

Commit: `feat: make Luna bootstrap continuation reliable`

---

### Task 4: Documentation, regression and packaging verification

**Files:**
- Modify: `README.md`
- Modify: the V3.2 spec if implementation evidence requires wording corrections
- Modify: tests only for discovered regressions

- [ ] **Step 1: Update operational documentation**

Document the three operational states:

```text
ROUTER_ACTIVE
ROUTER_DEGRADED_PRIMARY
ROUTER_BLOCKED_SAFETY
```

Clarify that install/uninstall/trust/profile changes require a new Codex task, while ordinary capability failures do not.

- [ ] **Step 2: Run full verification**

Run/mirror:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
```

Also require fake-adapter smoke, wheel build, fresh disposable wheel install, offline self-test, and package invocation from outside the repo.

- [ ] **Step 3: Security regression review**

Review changed lifecycle/staging/fallback code specifically for fail-open paths. Confirm no fallback is possible with active authority, pending spawn, ambiguous identity, or A1 external effects.

- [ ] **Step 4: Open/update PR and exact-head GitHub verification**

Require exact-head `CI` and `Secret Scan` success. PR body must explicitly distinguish repository completion from post-merge live acceptance of the new bootstrap behavior.

- [ ] **Step 5: Final commit if docs changed**

Commit: `docs: document Router V3.2 degradation semantics`
