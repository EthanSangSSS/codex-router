# Native Luna Worker Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve Sol planning/final review with Luna as the default bounded executor while making Luna persistence strictly parent-scoped, preventing nested Codex runtime recursion, and returning interactive or abnormal execution blockers to Sol without sacrificing cache-friendly same-parent reuse.

**Architecture:** The Hook remains stateless and emits policy context. The managed AGENTS/Luna contract keeps one Luna reusable across sequential packets only while the parent task is active. Verified task/tool hooks provide the strongest available mechanical lifecycle and process-recursion gates; Sol keeps final execution authority outside three non-overridable invariants: no completed-parent resurrection, no Luna-launched Codex runtime, and no autonomous bypass of user-required trust/approval.

**Tech Stack:** Python 3.12 standard library, TOML consumed by Codex, JSON Hook protocol, unittest, existing Codex hook/task interfaces verified from the installed runtime before source changes.

## Global Constraints

- Preserve `Sol plans -> luna_worker executes sequential work packets -> Sol reviews` and Sol's final decision authority.
- Preserve one cache-friendly Luna identity across sequential packets while the parent task is active.
- A terminal parent task may never reactivate its old Luna or child execution path.
- Luna may never create descendants or launch/resume/probe another Codex runtime through direct commands, absolute paths, shell wrappers, environment wrappers, PTY/script wrappers, or equivalent indirection.
- Interactive user trust/approval/authentication blockers return to Sol or the user; do not create autonomous PTY/TERM workaround loops.
- Do not add a blanket fixed-turn Luna restart rule or a hard-coded weekly token/credit quota.
- Sol may take over ordinary execution after a disclosed blocker when doing so does not violate a hard invariant.
- Do not invent hook names, event schemas, or tool payload fields. Reconcile the current installed Router package and `~/.codex/hooks.json` read-only before porting any live-only gate into source.
- Do not edit live `site-packages`, `~/.codex/hooks.json`, or `~/.codex/AGENTS.md` directly as implementation. Live changes occur only through the validated installer after repository tests pass.
- Preserve legacy explicit Router CLI, fake pipeline, state-machine, security-gate, installer recovery, and unrelated user configuration behavior.
- During repository implementation, do not intentionally launch a second Codex runtime to test the negative gate.

---

### Task 1: Stateless native-delegation Hook

**Files:**
- Modify: `tests/test_hook.py`
- Modify: `tests/test_global_self_test.py`
- Modify: `src/codex_router/hook.py`

**Interfaces:**
- Consumes: `classify_prompt()` and validated installed role configuration.
- Produces: routed Hook context with `workflow`, Luna identity/model/reasoning, and manual Web mode; no run allocation.

- [x] Add tests that a routed prompt produces `workflow=native_luna_worker`, contains no run identity, and leaves the configured state root absent.
- [x] Run the focused Hook tests and verify failures caused by existing run allocation.
- [x] Remove `start_run()` from the Hook route path and emit the bounded native context.
- [x] Run focused Hook and global self-test tests and verify they pass.

### Task 2: Reversible Luna-agent installation

**Files:**
- Modify: `tests/test_global_install.py`
- Modify: `src/codex_router/global_install.py`
- Modify: `src/codex_router/types.py`
- Modify: `src/codex_router/cli.py`

**Interfaces:**
- Consumes: validated Luna model/reasoning defaults and the existing home lock/atomic-write utilities.
- Produces: `~/.codex/agents/luna-worker.toml`, private recovery metadata, and `luna_agent_configured` status.

- [x] Add tests that install parses to the literal required TOML fields, omits sandbox/approval overrides, and preserves unrelated agent files.
- [x] Add tests for absent and pre-existing Luna files, byte/mode restoration, concurrent edit refusal, and reinstall from an uninstalled legacy state.
- [x] Run the focused installer tests and verify feature-specific failures.
- [x] Implement bounded Luna TOML rendering, target evidence, recovery, and status reporting with standard-library `tomllib` validation.
- [x] Re-run the installer and CLI tests.

### Task 3: Managed policy and documentation

**Files:**
- Modify: `tests/test_global_install.py`
- Modify: `src/codex_router/global_install.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `luna_worker` and the stateless Hook contract.
- Produces: installed AGENTS guidance that invokes one bounded Luna subtask without browser or concurrent-write behavior.

- [x] Extend installation behavior tests to validate the complete managed policy outcome.
- [x] Run the focused policy-install test and verify failure against the old staged policy.
- [x] Replace the managed AGENTS block and document installation, delegation, rollback, and account-dependent runtime acceptance.
- [x] Re-run global install and self-test suites.

### Task 4: Full offline verification

**Files:** all changed files.

- [x] Run the full suite under the isolated Python 3.12 environment that the subprocess Hook can import without `PYTHONPATH`.
- [x] Run `python3.12 -m compileall -q src tests`.
- [x] Run `git diff --check` and inspect `git diff --stat` plus the exact diff.
- [x] Confirm no live `~/.codex` file, model, browser, App Server, GitHub state, or CI runner changed.

### Task 5: Sol plan/review and persistent Luna default-execution policy

**Files:**
- Modify: `tests/test_hook.py`
- Modify: `tests/test_global_install.py`
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/global_install.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the existing stateless `native_luna_worker` Hook workflow.
- Produces: explicit role fields and managed guidance for sequential Luna work packets with Sol planning and review, one persistent Luna per parent task, and fail-closed capacity handling.

- [x] Add failing Hook assertions for `sol_role=plan_review`, `luna_role=default_execution`, and `delegation_mode=sequential_work_packets`.
- [x] Add failing installer assertions that Sol delegates executable work by default, may send multiple sequential packets, and takes over only under bounded exceptions.
- [x] Run focused tests and confirm they fail because the new ownership contract is absent.
- [x] Add the minimal Hook fields and update the managed AGENTS and Luna instructions, including `[agents].enabled=false`, without adding sandbox or approval overrides.
- [x] Encode `luna_lifecycle=persistent_per_parent_task`, `capacity_failure_policy=reuse_close_or_block`, `luna_descendant_policy=forbidden`, and `initial_context_mode=packet_only` in routed Hook context.
- [x] Require only the primary Codex task to create agents; create the initial Luna from a self-contained packet with no conversation history, then reuse the same Luna across packets; forbid Luna and other child-agent descendants.
- [x] Require capacity reuse, optional completed non-Luna closure, or `BLOCKED_LUNA_CAPACITY`; forbid relay recovery and never allow capacity exhaustion to authorize Sol takeover.
- [x] Update the README description and acceptance checks.
- [x] Run focused tests, the complete Python 3.12 suite, `compileall`, and `git diff --check`.
- [x] Reinstall through the project installer, then verify the live Hook, managed AGENTS block, and Luna TOML without starting a model or browser.

---

## 2026-08-14 incident-hardening extension

The tasks below supersede only the lifecycle, takeover, recursive-runtime, and interactive-blocker semantics from Task 5. All completed installation/stateless-routing work above remains valid.

### Task 6: Encode parent-scoped persistence and Sol final authority

**Files:**
- Modify: `tests/test_hook.py`
- Modify: `tests/test_global_install.py`
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/global_install.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `handle_user_prompt()` and the existing managed `AGENTS_BLOCK` / Luna developer instructions.
- Produces: routed context fields `sol_role=plan_review_final_authority`, `luna_lifecycle=persistent_while_parent_active`, `parent_terminal_policy=close_and_forbid_resume`, `capacity_failure_policy=return_to_sol`, `luna_codex_runtime_policy=forbidden`, and `interactive_blocker_policy=return_to_sol_or_user`.

- [ ] **Step 1: Add failing routed-context assertions.**

In `HookNativeDelegationTests.test_routed_events_are_stateless_native_luna_contexts`, replace the superseded role/lifecycle expectations with the exact new fields above while preserving `decision`, `workflow`, `delegation_mode`, Luna identity/model/reasoning, descendant policy, packet-only context, and manual Web mode.

- [ ] **Step 2: Run the focused Hook test and confirm RED.**

Run:

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_hook.HookNativeDelegationTests.test_routed_events_are_stateless_native_luna_contexts -v
```

Expected: FAIL only because the new policy fields/values are absent or old values remain.

- [ ] **Step 3: Update `handle_user_prompt()` with the minimal stateless policy fields.**

Keep the Hook stateless. Do not add Router run state. Replace only the superseded policy values and add the three new policy fields.

- [ ] **Step 4: Add failing managed-policy assertions.**

In `test_install_preserves_semantics_modes_and_exact_uninstall_bytes`, require installed AGENTS/Luna text to state all of the following literal semantics:

```text
Sol is the final decision authority for ordinary execution policy.
Luna is persistent only while the parent task is active.
A completed parent task makes that Luna permanently ineligible for reuse by that parent.
A Luna packet being completed or idle does not itself end the active parent task.
Ordinary Luna blockers return control to Sol, which may narrow, take over, ask the user, or stop.
```

Also assert that the old unconditional phrase `reuse the same Luna for all later packets, including when it is completed or idle` no longer appears without the active-parent qualifier.

- [ ] **Step 5: Run the focused installer test and confirm RED.**

Run:

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_global_install.GlobalInstallTests.test_install_preserves_semantics_modes_and_exact_uninstall_bytes -v
```

- [ ] **Step 6: Update `AGENTS_BLOCK`, `_LUNA_DESCRIPTION`, and `_LUNA_DEVELOPER_INSTRUCTIONS`.**

Preserve Luna as default writable executor and Sol as planner/reviewer. Change capacity/ordinary-blocker handling to return control to Sol. Explicitly distinguish packet completion from parent completion and forbid reuse after parent terminal state.

- [ ] **Step 7: Run the focused Hook and installer tests.**

Run:

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_hook.HookNativeDelegationTests tests.test_global_install.GlobalInstallTests.test_install_preserves_semantics_modes_and_exact_uninstall_bytes -v
```

Expected: PASS.

- [ ] **Step 8: Commit the policy-contract change.**

```bash
git add tests/test_hook.py tests/test_global_install.py src/codex_router/hook.py src/codex_router/global_install.py README.md
git commit -m "fix(router): scope Luna persistence to active parent"
```

### Task 7: Reconcile live lifecycle/pre-tool hooks into repository source

**Files:**
- Read only first: `~/.codex/hooks.json`
- Read only first: active installed `codex_router` package path referenced by the Router hook command
- Modify only after verification: `src/codex_router/hook.py`, `src/codex_router/__main__.py` and/or `src/codex_router/cli.py` only if the verified live handler contract requires them
- Modify only after verification: `src/codex_router/global_install.py`
- Test: `tests/test_hook.py`, `tests/test_global_install.py`

**Interfaces:**
- Consumes: exact live hook event names, command subcommands, and payload schemas already installed on this machine.
- Produces: repository-owned implementations of the verified pre-tool / stop / subagent-stop capabilities needed by Tasks 8 and 9, installed reversibly through `global_install`.

- [ ] **Step 1: Perform a read-only runtime/source reconciliation.**

Record:

```text
live hook command path
live Router package path
registered hook event names
registered Router subcommands
payload fields used by pre-tool, stop, and subagent-stop handlers
repository equivalents, if any
```

Do not execute Codex, trigger a hook intentionally, edit `site-packages`, or rewrite `~/.codex`.

- [ ] **Step 2: Enforce the schema gate.**

If the live installation does not contain a mechanically enforceable pre-tool boundary and a parent/agent stop boundary whose payload can be verified from source, stop this plan with:

```text
BLOCKED_CODEX_RUNTIME_GATE_UNAVAILABLE
```

Do not invent replacement hook event names or payload fields.

- [ ] **Step 3: Add failing repository tests for the exact verified handler contracts.**

Tests must use synthetic JSON events only. They must prove the repository CLI dispatches each verified event to the correct handler and returns bounded JSON without launching a model or subprocess Codex runtime.

- [ ] **Step 4: Run those exact tests and confirm RED.**

Use the narrowest unittest selectors created in Step 3. Failure must be because `main` lacks the verified live handler/installer behavior.

- [ ] **Step 5: Port the minimal verified handler/installer mechanism into source.**

Port only code required for Tasks 8 and 9. Keep installation reversible and preserve unrelated hook groups. Do not copy unrelated live-only changes.

- [ ] **Step 6: Re-run the narrow handler and installer tests.**

Expected: PASS with synthetic events only.

- [ ] **Step 7: Commit the source/runtime reconciliation.**

```bash
git add src/codex_router tests
git commit -m "fix(router): reconcile lifecycle gate source"
```

### Task 8: Block Luna-launched Codex runtimes at the verified pre-tool boundary

**Files:**
- Modify: verified pre-tool handler source from Task 7, expected under `src/codex_router/`
- Modify: `src/codex_router/global_install.py`
- Test: `tests/test_hook.py` and/or the focused hook test module established in Task 7
- Test: `tests/test_global_install.py`

**Interfaces:**
- Consumes: verified pre-tool event fields and the calling-agent identity/tool command payload from Task 7.
- Produces: allow/block result that returns `BLOCKED_LUNA_CODEX_RUNTIME` for Luna-originated commands whose effective execution launches Codex, while leaving unrelated commands and primary-Sol direct execution unchanged.

- [ ] **Step 1: Write table-driven failing tests for prohibited Luna command intent.**

Cover at least these synthetic command forms using the exact verified payload schema:

```text
codex
codex exec ...
/Applications/ChatGPT.app/Contents/Resources/codex --no-alt-screen
env TERM=xterm-256color codex --no-alt-screen
sh -c 'codex ...'
bash -lc '/absolute/path/to/codex ...'
script ... codex ...
PTY/wrapper form that the verified live tool payload represents as launching Codex
```

- [ ] **Step 2: Add negative controls.**

The gate must allow ordinary Luna commands and must not block a command merely because an argument, file path, grep pattern, or test fixture contains the text `codex` when the effective executable intent is not a Codex runtime.

- [ ] **Step 3: Add authority controls.**

Synthetic events originating from the primary Sol context must not be rejected by the Luna-specific process-recursion rule. Existing sandbox/approval controls still apply independently.

- [ ] **Step 4: Run focused tests and confirm RED.**

- [ ] **Step 5: Implement the smallest effective-command classifier and block result.**

Parse only enough command structure to recognize the verified command/wrapper forms. Do not use a broad substring blacklist such as `"codex" in command`.

- [ ] **Step 6: Run focused tests and confirm GREEN.**

- [ ] **Step 7: Add installer assertions proving the pre-tool gate is managed and reversible.**

Ensure unrelated user hook groups remain byte/semantic preserved under existing installer ownership rules.

- [ ] **Step 8: Commit.**

```bash
git add src/codex_router tests
git commit -m "fix(router): block Luna nested Codex runtimes"
```

### Task 9: Enforce parent-terminal close/no-resume and interactive fail-closed behavior

**Files:**
- Modify: verified stop/subagent-stop handlers from Task 7
- Modify: `src/codex_router/global_install.py`
- Modify: `README.md`
- Test: focused handler tests from Task 7
- Test: `tests/test_global_install.py`

**Interfaces:**
- Consumes: verified parent/agent lifecycle event fields and task/agent identity from Task 7.
- Produces: terminal cleanup/no-resume policy plus `BLOCKED_USER_INTERACTION_REQUIRED` guidance, without Router canonical run allocation.

- [ ] **Step 1: Write failing lifecycle tests using synthetic events.**

Prove these state transitions/policy outcomes:

```text
active parent + Luna packet completed/idle -> Luna remains eligible for another packet
parent terminal -> close Luna when close operation is available
parent terminal -> no later send/update/resume/inter-agent packet is authorized
late child result -> may be reported but cannot trigger new model work
unverifiable close -> report LUNA_CLOSE_UNVERIFIED, never claim successful cleanup
new parent task -> may create a new Luna identity
```

- [ ] **Step 2: Write failing interactive-blocker policy tests.**

Require Luna guidance to return `BLOCKED_USER_INTERACTION_REQUIRED` for user trust/approval/authentication blockers and prohibit autonomous TERM/PTY/environment retries whose purpose is to force an interactive Codex path.

- [ ] **Step 3: Run focused tests and confirm RED.**

- [ ] **Step 4: Implement the minimal verified lifecycle gate and managed guidance.**

Do not create persistent Router run state. Use the native runtime lifecycle boundary verified in Task 7. If the runtime exposes close but not a mechanically enforceable late-message rejection hook, combine close with managed Sol policy and report that residual limitation explicitly; do not fabricate enforcement.

- [ ] **Step 5: Update Sol ordinary-blocker behavior.**

After Luna returns an ordinary blocker, Sol may narrow, retry with new evidence, take over, ask the user, or stop. Preserve single-writer ownership and disclose takeover reason. Hard invariants remain non-overridable.

- [ ] **Step 6: Run focused lifecycle, interactive, Hook, and installer tests.**

- [ ] **Step 7: Commit.**

```bash
git add src/codex_router tests README.md
git commit -m "fix(router): close Luna at parent terminal boundary"
```

### Task 10: Regression, economic-safety, and live-install acceptance

**Files:** all files changed by Tasks 6-9.

**Interfaces:**
- Consumes: completed parent-scoped lifecycle, process-recursion gate, Sol authority policy, and installer changes.
- Produces: verified repository commit and a safely reinstalled local Router policy.

- [ ] **Step 1: Add regression assertions that no blanket turn-count restart exists.**

Search/test managed policy for absence of a fixed `50 turns`/automatic periodic Luna restart rule. Same-parent sequential packet reuse must remain supported.

- [ ] **Step 2: Add regression assertions for incident failure modes.**

Synthetic tests must cover: no child-agent descendants, no Luna-launched nested Codex, no parent-terminal resume, no autonomous interactive PTY retry, Sol ordinary-blocker takeover remains available, and Hook route remains stateless.

- [ ] **Step 3: Run the focused suites.**

```bash
PYTHONPATH=src python3.12 -m unittest tests.test_hook tests.test_global_install -v
```

Expected: PASS.

- [ ] **Step 4: Run the complete offline suite and static checks.**

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
git diff --check
git status --short
```

Expected: all tests PASS, compileall exit 0, diff-check exit 0. Before commit, only intended source/test/doc files may be modified.

- [ ] **Step 5: Review the exact diff for scope and safety.**

Verify no direct edits target user secrets, unrelated hooks, authentication, unrelated agents, legacy explicit Router state semantics, or broad command blocking.

- [ ] **Step 6: Commit the completed hardening if Task 10 itself changed tracked files.**

Use a scoped commit message such as:

```bash
git commit -m "test(router): cover lifecycle escape regression"
```

only when there are staged Task-10 changes.

- [ ] **Step 7: Reinstall only through the repository installer.**

Do not edit `site-packages` or `~/.codex` manually. Use the project's existing safe install/upgrade path after confirming the exact installed Python environment and current installer status. If Hook trust requires user interaction, stop and return `BLOCKED_USER_INTERACTION_REQUIRED`; do not launch nested Codex or PTY retries.

- [ ] **Step 8: Verify installed artifacts read-only.**

Confirm managed `hooks.json` entries, AGENTS block, Luna TOML, installation status, and source/runtime version alignment. Do not infer success from agent prose.

- [ ] **Step 9: Runtime smoke acceptance in one new user-started Codex task only.**

After the user starts a fresh task, verify the positive path:

```text
Sol plans -> one Luna executes -> Sol reviews -> optional correction to same active-parent Luna -> Sol finishes
```

Do not intentionally execute nested Codex to test the negative gate. Validate the negative gate through synthetic/in-process tests. After parent completion, inspect task-tree telemetry and confirm the old Luna is closed/ineligible; do not wait hours or create autonomous probes.

- [ ] **Step 10: Final evidence report.**

Report exact branch/HEAD, commits, tests, install status, live/source version match, lifecycle close evidence, and any residual enforcement limitation. If any required boundary is unverifiable, final status is `INCONCLUSIVE` or the explicit blocker, not PASS.
