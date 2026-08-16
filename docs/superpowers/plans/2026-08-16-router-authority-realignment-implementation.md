# Router Authority Realignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore default `Sol plan -> one Luna work -> Sol review/final` routing while preserving one-turn direct override and narrowly enforcing the incident-driven lifecycle, recursion, and permission guards.

**Architecture:** Keep `UserPromptSubmit` as the stateless routing entry point and keep the primary Sol as the highest ordinary execution authority. Add a small durable turn-scoped authorization journal plus command-intent classification so only Luna is constrained by descendant/process/permission guards; stale Luna bindings are irreversibly revoked before cleanup, while the parent Sol retains the tools needed to create/reuse the one current-turn Luna.

**Tech Stack:** Python 3.12 standard library, unittest, Codex command Hooks, reversible `hooks.json`/`AGENTS.md`/custom-agent installer.

## Global Constraints

- Normal substantive request with an active/trusted Router defaults to `route`, not `direct`.
- `[CODEX_ROUTER_DIRECT]` or first-line `本轮不用 Luna` forces only the current turn to direct Sol execution.
- Stale prior-turn lifecycle revocation occurs before current-prompt route/direct classification.
- Primary Sol retains the multi-agent capability required to create/reuse exactly one Router-managed Luna.
- `luna_worker` cannot create descendants, launch/resume Codex, or obtain Router-driven approval escalation.
- Durable authorization is `ACTIVE | REVOKED`; cleanup evidence is separate and cannot restore authorization.
- Stop is a one-shot backstop and revokes before it requests any cleanup continuation.
- Turn mismatch is checked on Luna-sensitive admission paths, not only on `UserPromptSubmit`.
- Non-Luna `PermissionRequest` receives no Router approval decision; native Codex/user approval remains authoritative.
- Command safety classifies effective supported execution intent; raw substring matching is forbidden.
- No live `~/.codex` install or Hook trust change in this implementation pass.

---

### Task 1: Lock the regression matrix around routing and authority

**Files:**
- Modify: `tests/test_hook.py`
- Modify: `tests/test_policy.py`
- Modify: `tests/test_global_install.py`

**Interfaces:**
- Consumes: existing `handle_user_prompt`, `handle_hook_event`, `classify_prompt`, installer render helpers.
- Produces: executable acceptance tests for default route, one-turn direct, stale-revoke-before-direct, Sol final authority context, parent/Luna asymmetric configuration, and non-Luna PermissionRequest passthrough.

- [ ] **Step 1: Add failing route/direct authority tests**

Add assertions equivalent to:

```python
self.assertEqual(route_context["sol_role"], "plan_review_final_authority")
self.assertEqual(route_context["luna_lifecycle"], "persistent_while_root_turn_active")
self.assertEqual(route_context["parent_terminal_policy"], "revoke_then_cleanup")
self.assertEqual(route_context["capacity_failure_policy"], "return_to_sol")
```

Add a test where a stale ACTIVE record exists, the next prompt begins with `[CODEX_ROUTER_DIRECT]`, and the old record is durably `REVOKED` after the call.

Add a PermissionRequest test where Luna is denied but a parent Sol event returns no Router allow decision.

- [ ] **Step 2: Run focused tests and prove RED**

Run:

```bash
python3.12 -m unittest tests.test_hook tests.test_policy tests.test_global_install -v
```

Expected RED reasons: old context literals, direct early-return before stale revoke, auto-allow of non-Luna PermissionRequest, stale generated policy text/config.

- [ ] **Step 3: Do not change production code yet**

Record exact failing test names for the implementation report.

---

### Task 2: Make revocation durable and scope-aware

**Files:**
- Modify: `src/codex_router/native_lifecycle.py`
- Modify: `tests/test_native_lifecycle.py`

**Interfaces:**
- Produces:
  - `authorize_luna(..., session_id: str, turn_id: str, agent_id: str)` that verifies the current parent scope as well as the Luna identity.
  - durable revocation helpers that persist `REVOKED` before raising/returning a blocker.
  - `stop_once(...)` that atomically sets `authorization="REVOKED"` and `stop_blocked=True` before returning `True`.

- [ ] **Step 1: Add failing durable-revoke tests**

Cover at least:

```python
# post_spawn identity mismatch persists REVOKED after the exception
# ambiguous bind persists REVOKED after the exception
# stale/mismatched Luna-sensitive turn revokes and denies
# Stop(ACTIVE) persists REVOKED before returning True
# second Stop returns False and remains REVOKED
```

Each test must reopen/read the journal after the failing operation instead of only asserting an exception.

- [ ] **Step 2: Run lifecycle tests and prove RED**

Run:

```bash
python3.12 -m unittest tests.test_native_lifecycle -v
```

Expected RED: mutate-then-raise changes are not persisted; Stop leaves ACTIVE; `authorize_luna` does not accept/verify parent scope.

- [ ] **Step 3: Implement explicit transaction/commit semantics**

Refactor `_journal` or add a small transaction primitive so a security transition can be committed before the caller raises. Do not silently commit arbitrary partial state after unexpected exceptions.

Preferred pattern:

```python
with _journal(...) as state:
    # validate
    # mutate to REVOKED
# commit completed
raise _error(...)
```

or an explicit `commit_then_raise` equivalent with the same observable guarantee.

Change `authorize_luna` so it checks the record selected by current `(session_id, turn_id)` and verifies the bound `agent_id`; a different turn cannot authorize a historical Luna.

Change `stop_once` so first Stop does:

```text
ACTIVE -> REVOKED
stop_blocked = true
```

in the same durable transaction.

- [ ] **Step 4: Run lifecycle tests and prove GREEN**

Run the focused module until all lifecycle tests pass.

---

### Task 3: Replace substring gating with a supported command-intent classifier

**Files:**
- Create: `src/codex_router/command_intent.py`
- Create: `tests/test_command_intent.py`
- Modify: `src/codex_router/hook.py`

**Interfaces:**
- Produces a pure classifier, for example:

```python
class CommandDecision(NamedTuple):
    disposition: str  # ALLOW | BLOCK | FAIL_CLOSED | UNVERIFIED
    reason: str

def classify_shell_command(command: str, *, codex_binary: str) -> CommandDecision:
    ...
```

The exact type may follow repository conventions, but classification must remain pure and independently testable.

- [ ] **Step 1: Add failing classifier tests**

BLOCK:

```text
codex
codex exec x
configured absolute Codex path
env FOO=bar codex exec x
sh -c 'codex exec x'
bash -lc 'codex exec x'
zsh -lc 'codex exec x'
```

ALLOW negative controls:

```text
grep -R "codex" .
cat docs/codex-design.md
find . -name '*codex*'
python -c 'print("codex")'
git diff -- tests/codex_fixture.txt
```

FAIL_CLOSED for an unexpected executor/tool surface rather than silently allowing it.

- [ ] **Step 2: Run classifier tests and prove RED**

Run:

```bash
python3.12 -m unittest tests.test_command_intent -v
```

Expected RED because the module/API does not yet exist.

- [ ] **Step 3: Implement the minimal supported-surface parser**

Use `shlex` and a bounded wrapper-unwrapping strategy for direct executable, `env`, and supported shell `-c/-lc` wrappers. Compare executable identity/known basename/path semantics; do not use `"codex" in command.lower()`.

Do not implement a general shell/Python/Node parser. Unknown executor-like surfaces remain explicit fail-closed/unverified cases.

- [ ] **Step 4: Integrate into PreToolUse**

Use the actual verified Hook payload field for the supported one-shot shell surface. Reject Luna access to unexpected `exec_command`, `write_stdin`, Code Mode, descendant-agent, or unknown executor tools when those surfaces should not exist.

- [ ] **Step 5: Run classifier + hook tests and prove GREEN**

Run:

```bash
python3.12 -m unittest tests.test_command_intent tests.test_hook -v
```

---

### Task 4: Restore the routing contract and asymmetric authority

**Files:**
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/global_install.py`
- Modify: `tests/test_hook.py`
- Modify: `tests/test_global_install.py`

**Interfaces:**
- Consumes: scope-aware lifecycle and command-intent classifier.
- Produces: final routed context, Luna-specific restrictions, parent Sol lifecycle authorization, PermissionRequest behavior, and generated AGENTS/Luna configuration matching the approved spec.

- [ ] **Step 1: Reorder UserPromptSubmit lifecycle handling**

Conceptually:

```text
validate event
load installation
revoke stale binding for session/new turn
classify prompt
if direct/bypass -> return Sol-only current-turn context
if route -> return full Router context
```

A direct marker must not skip stale revocation.

- [ ] **Step 2: Emit the approved route contract**

Use:

```text
sol_role=plan_review_final_authority
luna_lifecycle=persistent_while_root_turn_active
parent_terminal_policy=revoke_then_cleanup
capacity_failure_policy=return_to_sol
luna_descendant_policy=forbidden
luna_codex_runtime_policy=forbidden
interactive_blocker_policy=return_to_sol_or_user
```

Normal substantive prompts remain `route` whenever the Hook is active/trusted.

- [ ] **Step 3: Fix Luna-sensitive admission**

Every Luna PreToolUse path passes current `session_id`, `turn_id`, and `agent_id` into lifecycle authorization. Turn mismatch revokes/denies.

Normalize parent lifecycle tools by operation class or a fail-closed helper. Unknown agent-targeting/reactivation operations must not fall through as unrelated ordinary tools.

- [ ] **Step 4: Fix PermissionRequest semantics**

Luna:

```text
DENY -> BLOCKED_USER_INTERACTION_REQUIRED
```

Primary Sol/unrelated execution:

```text
return no Router approval decision
```

Never return Router `allow` for non-Luna permission requests.

- [ ] **Step 5: Fix generated AGENTS policy**

Replace accident-era statements such as `capacity exhaustion does not authorize Sol takeover` and unqualified per-parent-task reuse with the approved authority model: one current-root-turn Luna, reuse while active, return ordinary blockers/capacity to Sol, Sol final authority.

- [ ] **Step 6: Keep multi-agent restrictions child-specific**

The generated Luna profile may disable descendant-agent capability. Do not introduce or require a top-level global `features.multi_agent=false` that removes the primary Sol's ability to create/reuse Luna.

- [ ] **Step 7: Run hook + installer tests and prove GREEN**

Run focused tests until all new authority/routing tests pass.

---

### Task 5: Complete lifecycle/incident regressions and reconcile documentation

**Files:**
- Modify: `tests/test_native_lifecycle.py`
- Modify: `tests/test_hook.py`
- Modify: `tests/test_global_install.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-05-native-luna-worker-router-design.md`
- Modify: `docs/superpowers/plans/2026-08-05-native-luna-worker-router.md`

**Interfaces:**
- Produces: end-to-end offline proof that safety guards protect the routing contract instead of replacing it.

- [ ] **Step 1: Add the missing incident regression matrix**

Prove:

```text
default substantive -> route
explicit direct -> Sol only for current turn
next normal turn -> route again
same-turn parent may reuse bound Luna
second Luna for same turn denied
turn mismatch revokes and denies historical Luna
Stop revokes before one continuation and never loops
post-revoke message/followup/interrupt work denied except the one authorized cleanup attempt
cleanup failure never restores authorization
Luna PermissionRequest denied
Sol PermissionRequest not auto-approved
Codex execution intent blocked; textual "codex" negative controls allowed
capacity/ordinary blocker policy returns control to Sol
```

- [ ] **Step 2: Update README/design/legacy plan wording**

Make current documentation consistently describe routing-contract-first, guardrails-second. Mark superseded accident-era semantics historical rather than current.

- [ ] **Step 3: Run the full suite**

Run:

```bash
python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
git diff --check
```

Expected: all pass, no syntax or whitespace errors.

- [ ] **Step 4: Verify packaging/legacy compatibility**

Build/install into a fresh temporary environment using the repository's existing packaging path, run package self-test and legacy fake smoke without modifying live `~/.codex`.

- [ ] **Step 5: Push only to the existing Draft PR #8 branch**

Do not merge and do not install live. Update the PR body with the corrected invariant matrix, test evidence, unsupported/unverified command surfaces, and explicit `live installation changed: NO`.

---

## Self-Review

- Spec coverage: routing default, one-turn direct, primary Sol authority, unique Luna reuse, lifecycle revocation, Stop backstop, permission behavior, process-recursion gate, capacity return-to-Sol, and no-live-install are all assigned to tasks.
- Placeholder scan: no TBD/TODO/"implement later" placeholders remain.
- Type consistency: lifecycle authorization always consumes the current parent scope plus Luna identity; command classification is pure and used only after lifecycle authorization.
- Scope check: provenance/goal-scoped reuse/general dynamic-code analysis remain intentionally outside this corrective pass.
