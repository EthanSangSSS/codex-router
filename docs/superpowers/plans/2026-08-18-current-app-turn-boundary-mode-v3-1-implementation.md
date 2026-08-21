# Current-App Turn-Boundary Mode V3.1 Implementation Plan

> **Historical / superseded:** The active lifecycle is V3.3 “Persistent Task, Disposable Luna.” Persistent-worker identity and required-follow-up steps below are non-authoritative history; see [the V3.3 design](../specs/2026-08-20-router-v3-3-persistent-task-disposable-luna-design.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the approved current-App turn-boundary contract into the existing V3.1 Router so one persistent Luna can be used safely for normal work without claiming physical OS/process settlement.

**Architecture:** Keep the existing control journal and Hook architecture. Add `SubagentStop` as the fifth baseline Hook, start execution from exact bound-Luna `PreToolUse`, freeze active authority on supersession/interrupt, and close scheduling authority through one explicit `observe_turn_boundary()` transition. Do not add process supervision, polling, shell parsing, or workspace orchestration.

**Tech Stack:** Python 3.12+, stdlib only, `unittest`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-18-current-app-turn-boundary-mode-v3-1-addendum.md`

## Global Constraints

- Current-App mode is `TURN_BOUNDARY`.
- Hard settlement domain is Router scheduling authority only.
- `SubagentStop` is a native Luna turn boundary, not process-death proof.
- Baseline managed Hook set is exactly `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`.
- `PermissionRequest` remains conditional/A1-specific; `Stop` is not baseline.
- Interrupt acknowledgement is never settlement.
- Missing/ambiguous lifecycle identity fails closed.
- Existing quarantined recovery remains the exception path.
- No PID/process supervisor, polling loop, shell parser, workspace orchestrator, V2 no-process restoration, PR ready/merge, or live `~/.codex` mutation.

---

### Task 1: Control-plane turn-boundary transition

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Test: `tests/test_luna_control_v3.py`
- Test: focused new/adjacent V3.1 lifecycle tests as appropriate

**Interfaces:**
- Consumes: existing `ControlSnapshot`, `start_execution()`, `freeze_authority()`, `accept_result()` semantics.
- Produces: `observe_turn_boundary(directory, secret, session_id, *, child_turn_id) -> Literal["CURRENT", "STALE"]`.

- [ ] **Step 1: Write failing tests** covering no-tool `IDLE + active_packet`, `RUNNING + matching turn`, `QUIESCING + matching turn`, stale/no-packet events, and conflicting non-null turn id.
- [ ] **Step 2: Run focused tests** and confirm failures are only the missing turn-boundary behavior.
- [ ] **Step 3: Implement `observe_turn_boundary()` minimally** using the existing locked state and snapshot validation; clear packet metadata for normal completion, retain packet identity for `PAUSED_SETTLED`, return `STALE` for historical/no-active-packet states, and fail closed on a conflicting active turn id.
- [ ] **Step 4: Run focused tests** and confirm green.
- [ ] **Step 5: Commit** as `feat: add Luna turn-boundary transition`.

### Task 2: Runtime Hook lifecycle wiring

**Files:**
- Modify: `src/codex_router/hook.py`
- Test: `tests/test_hook.py`
- Test: `tests/test_v31_control_plane_corrections.py` or focused lifecycle test file

**Interfaces:**
- Consumes: `luna_control.start_execution()`, `freeze_authority()`, `observe_turn_boundary()`, exact bound-Luna identity helper.
- Produces: runtime transitions from `PreToolUse`, `UserPromptSubmit`, `interrupt_agent`, and `SubagentStop`.

- [ ] **Step 1: Write failing Hook tests** proving bound-Luna ordinary `PreToolUse` starts execution once, repeated same-turn events are idempotent, conflicting turn id denies, and bound-Luna ordinary tools without an active K1 packet deny.
- [ ] **Step 2: Add failing freeze tests** proving new `UserPromptSubmit` freezes `RUNNING` authority before processing the new prompt and parent `interrupt_agent` freezes before native cleanup dispatch.
- [ ] **Step 3: Add failing `SubagentStop` tests** proving exact current Luna closes normal/no-tool/quiescing turns while stale, unbound, historical, or mismatched events cannot mutate current authority.
- [ ] **Step 4: Run focused tests** and record the exact RED failures.
- [ ] **Step 5: Implement the minimal Hook wiring** without adding new state or a new subsystem.
- [ ] **Step 6: Run focused tests** and confirm green.
- [ ] **Step 7: Commit** as `feat: wire current-App Luna turn lifecycle`.

### Task 3: Fifth baseline Hook and packaged CLI path

**Files:**
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `src/codex_router/cli.py`
- Test: `tests/test_global_install.py`
- Test: `tests/test_global_self_test.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: existing Hook renderer and CLI `hook-*` dispatch.
- Produces: exact five-Hook baseline and executable `hook-subagent-stop` command in editable and wheel installs.

- [ ] **Step 1: Write failing tests** for exact five baseline events and rendered `SubagentStop -> hook-subagent-stop` command.
- [ ] **Step 2: Write failing CLI test** proving `hook-subagent-stop` is parsed and dispatched through `handle_hook_event()`.
- [ ] **Step 3: Run focused tests** and confirm RED.
- [ ] **Step 4: Add `SubagentStop` to `BASELINE_HOOK_EVENTS`, renderer mapping, and CLI event table** only.
- [ ] **Step 5: Run focused installer/CLI tests** and confirm green.
- [ ] **Step 6: Commit** as `feat: install SubagentStop turn-boundary hook`.

### Task 4: Product/status wording

**Files:**
- Modify: `README.md`
- Modify: `src/codex_router/global_install_adapter.py` only if status labels require narrowing
- Test: existing status/documentation assertions

**Interfaces:**
- Produces: accurate current-App guarantee language: hard Router scheduling authority, no physical OS/process settlement claim.

- [ ] **Step 1: Update README/manual acceptance wording** to five baseline Hooks and current-App turn-boundary semantics.
- [ ] **Step 2: Remove or narrow any live status wording that still implies physical process settlement.** Do not add a new activation/evidence subsystem.
- [ ] **Step 3: Run relevant tests** and fix only stale expected strings.
- [ ] **Step 4: Commit** as `docs: document current-App turn-boundary mode`.

### Task 5: Full offline verification and review

**Files:**
- No feature expansion.

- [ ] **Step 1: Run complete unit suite:** `python -m unittest discover -s tests -v`.
- [ ] **Step 2: Run static checks:** `python -m compileall -q src tests` and `git diff --check`.
- [ ] **Step 3: Run fake adapter smoke** and require `ROUTER_MVP_OK`.
- [ ] **Step 4: Build wheel, install in fresh Python 3.12 venv, and rerun fake-adapter smoke.**
- [ ] **Step 5: Run disposable `global-install -> global-self-test -> global-uninstall`; never use live `~/.codex`.**
- [ ] **Step 6: Confirm quarantine recovery regressions remain green and `Interrupted` remains non-settling.**
- [ ] **Step 7: Review the final diff for YAGNI/scope creep and exact guarantee wording.**
- [ ] **Step 8: Verify GitHub Actions CI and Secret Scan for the exact final head.**
- [ ] **Step 9: Keep PR #8 Draft and unmerged. Do not mutate live Codex state.**
