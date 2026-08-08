# Native Luna Worker Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace automatic staged Hook runs with stateless native Luna delegation and install one reversible global `luna_worker` custom agent.

**Architecture:** The Hook emits a bounded native-delegation context and never writes Router run state. The existing installer gains an independently recoverable Luna-agent target while preserving its Hook and AGENTS ownership boundaries; explicit legacy CLI state-machine paths remain unchanged.

**Tech Stack:** Python 3.12 standard library, TOML consumed by Codex, JSON Hook protocol, unittest.

## Global Constraints

- Do not launch a model, App Server, second Codex App, browser, daemon, network workflow, CI runner, or GitHub write action.
- Do not add dependencies or modify unrelated Codex configuration.
- Preserve legacy explicit Router CLI, fake pipeline, state-machine, and security-gate behavior.
- Do not commit, push, create a PR, or mutate the live global installation in this implementation pass.

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
