# Minimal Agent-ID + Revocation V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep default `Sol plan -> one Luna work -> Sol review/final` routing and one-turn direct override while replacing unstable turn/transcript/process-parser assumptions with a minimal native-agent-id authorization model and a verifiable Luna execution boundary.

**Architecture:** `UserPromptSubmit` owns the current root scope; `PreToolUse(spawn_agent)` creates one pending Luna and mechanically requires packet-only context; `SubagentStart` binds the native child `agent_id` to that pending current scope without transcript parsing or child/root turn equality; child admission authorizes only that bound `agent_id` while the current scope is ACTIVE. Stop becomes revoke-only, the journal stores only current authorization state, and arbitrary Luna process execution is disabled unless an exact deployed Codex capability proves a stronger native child-scoped process boundary.

**Tech Stack:** Python 3.12 standard library, `unittest`, Codex command Hooks, TOML rendering, reversible global installer, GitHub Actions.

## Global Constraints

- Default substantive work remains `Sol plan -> one current Luna -> Sol review/final`.
- `[CODEX_ROUTER_DIRECT]` and first-line `本轮不用 Luna` apply only to the current turn and do not skip stale-root revocation.
- Primary Sol retains ordinary multi-agent authority; child restrictions are not applied globally.
- Exactly one pending/bound Router Luna exists for the current root scope.
- `ACTIVE -> REVOKED` is irreversible; missing old state never grants authorization.
- Child/root `turn_id` equality is removed from authorization.
- Transcript JSON is not a security identity source.
- Bound native `agent_id` is the Luna identity; if deployed Hooks cannot expose it on required surfaces, live activation is blocked.
- V2 `spawn_agent` must require `fork_turns="none"` so packet-only context is mechanical.
- Parent lifecycle targets must follow exact current tool schemas (`target`, `id`, `task_name`) rather than a generic guessed field.
- Stop is revoke-only and must not create a Router continuation.
- Cleanup state is not security authorization state.
- A home-grown shell parser is not accepted as the hard no-recursion boundary.
- Safe fallback V2 disables Luna arbitrary process execution; primary Sol performs unsupported build/test commands.
- Router reads/preflights primary capability but does not own the user's whole `config.toml`.
- No live `~/.codex` installation, Hook trust mutation, merge, or auto-merge in this implementation pass.

---

### Task 1: Correct the V2 parent tool contract and packet-only spawn

**Files:**
- Modify: `tests/test_native_lifecycle.py`
- Modify: `tests/test_router_authority_realign.py`
- Modify: `src/codex_router/native_lifecycle.py`
- Modify: `src/codex_router/hook.py`

**Interfaces:**
- Produces `parent_target(tool_name: str, tool_input: Mapping[str, Any]) -> str | None` or equivalent exact-schema normalization.
- Produces spawn admission that requires `task_name="luna_worker"` and `fork_turns="none"` before recording pending authorization.

- [ ] **Step 1: Write RED tests for exact V2 target fields**

Add cases equivalent to:

```python
self.assert_parent_allowed("send_message", {"target": "/root/luna_worker", "message": "fix"})
self.assert_parent_allowed("followup_task", {"target": "/root/luna_worker", "message": "fix"})
self.assert_parent_allowed("interrupt_agent", {"target": "/root/luna_worker"})
self.assert_parent_denied("send_message", {"target": "/root/other", "message": "x"})
```

Where legacy/V1 compatibility remains supported, test `resume_agent -> id` and `close_agent -> target` explicitly rather than routing them through the V2 path by accident.

- [ ] **Step 2: Write RED tests for packet-only spawn**

Prove:

```text
spawn_agent(task_name=luna_worker, fork_turns=none) -> admissible
spawn_agent(task_name=luna_worker, fork_turns missing) -> denied
spawn_agent(task_name=luna_worker, fork_turns=all) -> denied
spawn_agent(task_name=other, fork_turns=none) -> denied
```

- [ ] **Step 3: Run focused tests and observe RED**

Run:

```bash
python3.12 -m unittest tests.test_native_lifecycle tests.test_router_authority_realign -v
```

Expected failures: current target helper reads `task_name/agent_id`; current spawn gate does not require `fork_turns=none`.

- [ ] **Step 4: Implement the minimal schema adapter**

Use explicit tool contracts such as:

```python
_TARGET_FIELD = {
    "send_input": "target",
    "send_message": "target",
    "followup_task": "target",
    "interrupt_agent": "target",
    "close_agent": "target",
    "resume_agent": "id",
}
```

Do not silently infer unknown lifecycle targets. Unknown agent-reactivation/lifecycle operations fail closed for Router lifecycle authority.

Require `fork_turns == "none"` before pending Luna state is created.

- [ ] **Step 5: Run the focused tests and prove GREEN**

Commit only after the focused matrix is green.

---

### Task 2: Replace transcript/turn-equality binding with native agent-id binding

**Files:**
- Modify: `tests/test_native_lifecycle.py`
- Modify: `tests/test_router_authority_realign.py`
- Modify: `src/codex_router/native_lifecycle.py`
- Modify: `src/codex_router/hook.py`

**Interfaces:**
- Produces `bind_child(..., session_id: str, agent_id: str, agent_type: str)` or equivalent with no transcript metadata argument.
- Produces `authorize_luna(..., session_id: str, agent_id: str)` or equivalent that resolves only the current ACTIVE scope for that parent-shared session.

- [ ] **Step 1: Write RED identity tests**

Tests must prove:

```text
SubagentStart can bind the unique pending Luna without transcript parsing
child turn_id may differ from parent root turn_id and still authorize the bound agent_id
historical/unknown agent_id is denied
second agent_id cannot bind the same current scope
non-Luna agent_type cannot bind the pending Luna
partial/malformed child identity cannot gain primary lifecycle authority
```

- [ ] **Step 2: Run focused tests and observe RED**

Expected failures: current `SubagentStart` requires `transcript_path` metadata and `authorize_luna` keys by child `(session_id, turn_id)`.

- [ ] **Step 3: Remove transcript identity code**

Delete `_read_child_metadata` from authorization flow and remove `parent_thread_id` / `agent_path` transcript requirements.

Bind `event.agent_id` to the one pending Luna under the one current ACTIVE root scope for the parent-shared session. If that correlation is ambiguous, revoke/fail closed rather than choosing a candidate.

- [ ] **Step 4: Change Luna admission**

Authorization asks only whether the child `agent_id` equals the current ACTIVE bound Luna for the shared session. Do not compare child `turn_id` to the parent root turn.

`agent_type=luna_worker` may corroborate identity, but a historical role string alone cannot authorize an unbound child.

- [ ] **Step 5: Run identity/lifecycle tests and prove GREEN**

Record that live activation still requires exact deployed Hook-wire confirmation of child `agent_id` on the required events.

---

### Task 3: Simplify the journal and Stop semantics

**Files:**
- Modify: `tests/test_native_lifecycle.py`
- Modify: `tests/test_router_authority_realign.py`
- Modify: `src/codex_router/native_lifecycle.py`
- Modify: `src/codex_router/hook.py`

**Interfaces:**
- Security state contains only the current root scope, `ACTIVE|REVOKED`, optional pending spawn, and optional bound Luna.
- Stop performs durable revocation and returns normally.

- [ ] **Step 1: Write RED tests for revoke-only Stop**

Prove:

```text
Stop(ACTIVE) -> persisted REVOKED
Stop output does not request/block a continuation
second Stop remains non-looping
historical bound Luna remains unauthorized after the state is compacted/replaced by a new root scope
```

- [ ] **Step 2: Write RED tests for cheap reads and bounded state**

Instrument or stat the state file so an unchanged authorization read does not replace/rewrite it.

Add deterministic compaction tests proving old records are not retained indefinitely and that missing historical records never authorize an old `agent_id`.

Add an assertion that the containing directory is fsynced after a security-transition replace.

- [ ] **Step 3: Run lifecycle tests and observe RED**

Expected failures: current context manager writes on every normal exit, retains unbounded `bindings`, stores cleanup/stop state, and Stop returns a continuation blocker.

- [ ] **Step 4: Implement minimal state**

Prefer an explicit load/read path plus mutation transaction rather than a context manager that always commits.

Persist privacy-safe HMAC scope/session tags where practical. Do not persist prompt/transcript/model output. Raw `agent_id` may remain only if needed for target authorization and must stay in the private owner-only journal.

Security transitions must use file fsync + atomic replace + directory fsync.

- [ ] **Step 5: Remove cleanup authorization state**

Delete `cleanup` and `stop_blocked` from the hard journal. Native interrupt/close becomes optional resource cleanup and never changes authorization.

- [ ] **Step 6: Run lifecycle tests and prove GREEN**

---

### Task 4: Replace the shell-parser safety claim with a verifiable Luna execution mode

**Files:**
- Modify: `tests/test_global_install.py`
- Modify: `tests/test_router_authority_realign.py`
- Modify: `src/codex_router/global_install.py`
- Modify: `src/codex_router/hook.py`
- Modify or remove: `src/codex_router/command_intent.py`
- Modify or remove: `tests/test_command_intent.py`

**Interfaces:**
- Produces a generated Luna profile with an explicit execution mode.
- Hard-mode fallback exposes no arbitrary Luna process/shell surface.

- [ ] **Step 1: Write RED tests for hard-mode profile**

Without a verified native child process-deny capability, generated Luna configuration must disable the supported arbitrary process surfaces for the target Codex compatibility profile.

At repository level, express stable intent and keep exact-build feature keys behind a compatibility renderer rather than scattering them through policy prose.

- [ ] **Step 2: Write RED tests that remove the false hard guarantee from the parser**

Compound/dynamic shell examples such as these must no longer be treated as mechanically safe merely because the first token is benign:

```text
true && codex exec ...
echo ok; codex exec ...
echo "$(codex exec ...)"
python script.py
make
```

The preferred implementation is to make these unreachable to Luna in hard mode, not to grow a shell parser.

- [ ] **Step 3: Run focused tests and observe RED**

- [ ] **Step 4: Implement hard-mode reduced execution surface**

Remove `Bash`/`shell_command` from Luna ordinary allow semantics when the selected compatibility profile cannot prove a native child-scoped process boundary. Unknown process/executor surfaces fail closed.

Primary Sol remains allowed to run build/test/verification commands itself.

Retain `command_intent.py` only if it still has a narrow diagnostic/defense-in-depth purpose. If unused after hard-mode enforcement, delete it and its tests rather than keep dead security code.

- [ ] **Step 5: Run installer/hook tests and prove GREEN**

---

### Task 5: Add primary capability preflight and compatibility diagnostics

**Files:**
- Modify: `src/codex_router/global_install.py`
- Modify: `src/codex_router/cli.py`
- Modify: `tests/test_global_install.py`
- Modify: `tests/test_router_authority_realign.py`

**Interfaces:**
- Produces readiness/status classification equivalent to:

```text
COMPATIBLE
INCOMPATIBLE
UNKNOWN_REQUIRES_CAPABILITY_CHECK
```

- [ ] **Step 1: Write RED tests for primary incompatibility**

Synthetic effective config where primary multi-agent/agents capability is explicitly disabled must report incompatible/readiness blocked. Router must not rewrite that config.

Hooks disabled or required Luna execution capability unavailable must be visible as incompatible/unknown rather than `installed == ready`.

- [ ] **Step 2: Run focused tests and observe RED**

- [ ] **Step 3: Add read-only preflight/status logic**

Keep ownership minimal. Read the effective/static configuration evidence available to this installer/status command, report known incompatibility, and leave ambiguous layered runtime state as `UNKNOWN_REQUIRES_CAPABILITY_CHECK`.

Do not mutate user `config.toml`.

- [ ] **Step 4: Add execution-mode/status receipt**

Status should expose enough information to distinguish installed policy from selected Luna execution mode and compatibility readiness. Do not claim current-turn routing telemetry that the local status command cannot independently observe.

- [ ] **Step 5: Run status/installer tests and prove GREEN**

---

### Task 6: Reduce Hook surface and synchronize policy/docs

**Files:**
- Modify: `src/codex_router/global_install.py`
- Modify: `src/codex_router/hook.py`
- Modify: `tests/test_global_install.py`
- Modify: `tests/test_hook.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-05-native-luna-worker-router-design.md`
- Modify: `docs/superpowers/plans/2026-08-05-native-luna-worker-router.md`

**Interfaces:**
- Minimum hard safety events: `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `SubagentStart`, `Stop`.
- `PostToolUse` is retained only if a verified pending-spawn failure/corroboration path needs it.
- `SubagentStop` is removed unless a concrete invariant is demonstrated in tests.

- [ ] **Step 1: Add RED installer tests for the minimum Hook set**

Assert Router-owned Hook events exactly match the implementation needs after Tasks 1-5.

- [ ] **Step 2: Remove unnecessary Hook semantics**

Delete `SubagentStop` registration/handler if no remaining invariant uses it. Narrow `PostToolUse` to the smallest verified pending-spawn use or remove it if the binding protocol no longer requires it.

- [ ] **Step 3: Synchronize generated policy**

Generated route context, `AGENTS.md`, Luna developer instructions, README, design, and plan must state:

```text
Sol plan -> one Luna -> Sol review/final
direct override is one-turn only
primary Sol retains management authority
agent-id binding, not transcript/child-turn equality
Stop is revoke-only
fork_turns=none / packet-only
hard-mode Luna does not run arbitrary process commands
ordinary blockers return control to Sol
```

Remove stale claims about `revoke_then_cleanup`, cleanup continuations, command-parser hard safety, or transcript binding.

- [ ] **Step 4: Run focused hook/installer/docs tests and prove GREEN**

---

### Task 7: Full verification and Draft PR handoff

**Files:**
- Tests/documentation only as required by observed failures.

- [ ] **Step 1: Run the full repository suite**

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
git diff --check
```

- [ ] **Step 2: Run package/legacy verification**

Build the package according to `pyproject`, install into a fresh temporary environment, run project self-tests and the existing legacy fake-adapter smoke. Do not touch live `~/.codex`.

- [ ] **Step 3: Review diff specifically for regressions**

Verify:

```text
no transcript parsing remains in security identity
no child/root turn equality remains in Luna authorization
no Stop-generated continuation remains
no unbounded lifecycle record history remains
no arbitrary Luna shell/process surface is claimed safe by command parsing
primary Sol management remains enabled by policy
no user config.toml mutation was introduced
legacy Router remains isolated
```

- [ ] **Step 4: Push only to the existing Draft PR #8 branch**

Keep PR Draft. Update its body with exact head, tests, architecture changes, selected hard-mode execution surface, and unresolved local capability gates.

- [ ] **Step 5: Stop before local/live migration**

Required handoff state:

```text
REPOSITORY_GREEN
DRAFT_REVIEW
LOCAL_CAPABILITY_VALIDATION_REQUIRED
LIVE_INSTALLATION_CHANGED=NO
HOOK_TRUST_CHANGED=NO
MERGED=NO
```

---

## Self-Review

- Spec coverage: exact V2 target schemas, packet-only spawn, native agent-id binding, removal of transcript/turn equality, minimal journal, revoke-only Stop, hard-mode process boundary, primary preflight, Hook reduction, documentation, and full verification are each assigned to a task.
- Placeholder scan: no TBD/TODO or unspecified implementation placeholders remain.
- Type consistency: root authority is created by UserPromptSubmit; pending spawn belongs only to current ACTIVE scope; SubagentStart binds native `agent_id`; later Luna admission uses that bound identity and does not key by child turn.
- Scope discipline: live installation, Hook trust mutation, goal-scoped reuse, replacement Luna, richer telemetry, generalized process parsing, and broad installer refactoring remain out of scope.
