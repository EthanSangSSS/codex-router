# Native PRIMARY + Luna V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the user-facing Router control-plane path with a minimal native experience where Sol/PRIMARY directly delegates substantial local engineering work to one native `luna_worker`, reviews the result, and owns the final response.

**Architecture:** Add a parallel Native V1 installation module that manages only a short PRIMARY block in `AGENTS.md` and `agents/luna-worker.toml`. It installs no Router routing Hook and uses no K1, generation lease, HMAC bootstrap, request-file staging, prompt classifier, or Router journal in the normal path. Existing Router commands remain intact as an experimental compatibility path.

**Tech Stack:** Python >=3.12, stdlib only, existing Codex agent TOML format, existing safe filesystem helper primitives, `unittest`/`pytest`, setuptools wheel build.

**Spec:** `docs/superpowers/specs/2026-08-24-native-primary-luna-v1-design.md`

## Global Constraints

- Repository: `EthanSangSSS/codex-router`.
- Branch: `simplify/native-primary-luna-v1`.
- Base: `main@8fa458948ea0dc021096dc13b5eeec6c45628a40` unless GitHub shows `main` moved and an explicit rebase/update is separately chosen.
- Do not merge or mark a PR Ready during implementation/live acceptance.
- Do not modify PR #10 except optionally to note that it remains the experimental hard-authority prototype.
- Python remains `>=3.12`; add no runtime dependency.
- Normal Native V1 operation installs no Router `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`, or `SubagentStop` Hook.
- Normal Native V1 operation has no K1 packet, generation lease, HMAC bootstrap, request-file staging, prompt-provenance parser, root replay logic, or Router A1 packet.
- PRIMARY owns orchestration and final response.
- Luna is one disposable native execution subagent and has no descendants/nested Codex.
- Native sandbox/approval/workspace/tool exposure remain the hard execution boundary.
- If native spawn is unavailable/fails, PRIMARY continues locally instead of aborting the user's task solely because delegation failed.
- Interactive browser/user-session UI work stays with PRIMARY by instruction; Playwright/Cypress/headless/local browser engineering remains Luna-eligible.
- Native installation must preserve unrelated `AGENTS.md` content, unrelated hooks, unrelated agent files, and unrelated `config.toml` content.
- Existing Router global installation may be migrated only through its own reversible ownership evidence; ambiguous/modified Router state fails closed rather than deleting user files.

## Execution Preflight

- [ ] **Step 1: Verify remote branch reality**

```bash
git fetch origin
git rev-parse origin/main
git rev-parse origin/simplify/native-primary-luna-v1
git status --short
```

Require a clean isolated worktree on `simplify/native-primary-luna-v1`.

- [ ] **Step 2: Confirm the spec/plan exist at the branch head**

```bash
test -f docs/superpowers/specs/2026-08-24-native-primary-luna-v1-design.md
test -f docs/superpowers/plans/2026-08-24-native-primary-luna-v1.md
```

- [ ] **Step 3: Baseline regression**

```bash
python3 -m pytest -q
python3 -m compileall -q src tests
```

If baseline tests fail, use systematic debugging to separate pre-existing failure from current work. Do not weaken existing tests to make the new mode pass.

---

### Task 1: Add Native PRIMARY and Luna Renderers

**Files:**
- Create: `src/codex_router/native_primary_luna.py`
- Create: `tests/test_native_primary_luna.py`
- Read contracts: `src/codex_router/global_install.py`, `src/codex_router/global_install_adapter.py`

**Interfaces:**
- Produce constants:
  - `NATIVE_INSTALL_DIRECTORY_NAME = ".codex-native-primary-luna-v1"`
  - `NATIVE_INSTALL_STATE_PROTOCOL = "codex-native-primary-luna/install-state/v1"`
  - `NATIVE_AGENTS_BEGIN = "# BEGIN CODEX NATIVE PRIMARY LUNA V1"`
  - `NATIVE_AGENTS_END = "# END CODEX NATIVE PRIMARY LUNA V1"`
- Produce functions:
  - `render_primary_block() -> str`
  - `render_luna_agent_bytes(*, model: str, reasoning: str) -> bytes`
  - `_install_primary_block(original: bytes | None) -> bytes`
  - `_strip_primary_block(current: bytes) -> bytes | None`

- [ ] **Step 1: Write RED tests for the PRIMARY contract**

Add tests asserting `render_primary_block()` contains all of these behavioral requirements:

```text
PRIMARY is the persistent planner, coordinator, reviewer, and final responder
use Luna for substantial local engineering when useful
if the user explicitly asks not to use Luna, do not spawn Luna
interactive browser/user-session UI work stays in PRIMARY
Playwright/Cypress/headless browser engineering may be delegated
if native Luna spawn is unavailable or fails, continue locally
review Luna's result before the final response
```

And mechanically assert it does **not** contain any of:

```text
K1
generation lease
K1_STAGE_COMMAND
request-file
bootstrap capability
HMAC
sensitive_detected
route/direct/bypass
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -q tests/test_native_primary_luna.py
```

Expected: import/function failure because the module does not exist.

- [ ] **Step 3: Implement the short PRIMARY block**

Use this exact semantic content, with the native markers wrapping it:

```text
You are PRIMARY: the persistent planner, coordinator, reviewer, and final responder.
Use the native `luna_worker` execution subagent for substantial local engineering when useful; keep simple answers, planning, review, interactive browser/user-session UI work, and the final response in PRIMARY.
If the user explicitly asks not to use Luna for the current turn, do not spawn Luna.
Playwright, Cypress, headless browser tests, local E2E, and browser-code debugging are local engineering and may be delegated to Luna.
Use the native spawn surface actually exposed by the runtime. Do not invent unsupported spawn fields. Prefer one fresh Luna for one delegated execution task; do not rely on child-memory persistence, followup, resume, polling, or a Router protocol.
If native Luna spawn is unavailable or fails, continue the user's task locally when normal Codex tools allow it; delegation failure alone is not a reason to stop the task.
After Luna returns, inspect its evidence/results as needed and own the final answer.
```

Do not add lease/K1/security ceremony to this text.

- [ ] **Step 4: Write RED tests for Luna TOML**

Require parsed TOML exactly contains:

```python
{
    "name": "luna_worker",
    "description": <native executor description>,
    "model": "gpt-5.6-luna",
    "model_reasoning_effort": "max",
    "developer_instructions": <native Luna instructions>,
    "agents": {"enabled": False},
    "features": {"multi_agent": False, "multi_agent_v2": False},
}
```

The Luna instructions must permit ordinary local engineering and must contain explicit no-descendant/no-nested-Codex rules.

Assert the Luna instructions do not contain K1/generation/bootstrap/request-file language.

- [ ] **Step 5: Implement `render_luna_agent_bytes`**

Follow the existing stable TOML renderer pattern from `global_install_adapter.luna_agent_bytes`: JSON-quote scalar TOML values, append disabled descendant-agent sections, parse back with `tomllib`, and compare the parsed structure against the exact expected mapping before returning bytes.

Native Luna semantic instructions:

```text
You are Luna, a disposable native execution subagent of PRIMARY.
Execute the delegated task in the current Codex workspace using the normal native sandbox, approvals, and exposed tools.
You may inspect/search/read files; edit/create/delete task-related files; run shell/project tooling; build/test/lint/typecheck; run Playwright/Cypress/headless E2E; debug; refactor; retry; verify; and inspect local Git status/diff/log when relevant.
Do not spawn descendants or another Codex runtime. Do not intentionally daemonize persistent background work.
Do not perform unrelated destructive actions. Do not commit, push, mutate PRs, deploy/publish, communicate externally, mutate cloud resources, or perform system-level installation unless the delegated user objective explicitly requires that action and native platform controls permit/approve it.
Return concise implementation evidence, tests run, blockers, and remaining risks to PRIMARY.
```

- [ ] **Step 6: Write RED tests for append/strip boundaries**

Required cases:

```python
_install_primary_block(None)
_install_primary_block(b"# Existing\n")
```

must append exactly one managed block.

`_strip_primary_block()` must:

- remove exactly one exact managed block at the end;
- preserve the prefix byte-for-byte;
- return `None` when the managed block was the entire file and installer-owned creation should be removed;
- fail closed on duplicate markers, missing end marker, modified managed content, or a managed block not at file end.

- [ ] **Step 7: Implement append/strip helpers and run GREEN**

```bash
python3 -m pytest -q tests/test_native_primary_luna.py
```

- [ ] **Step 8: Commit Task 1**

```bash
git add src/codex_router/native_primary_luna.py tests/test_native_primary_luna.py
git commit -m "feat: add native primary luna contracts"
```

---

### Task 2: Add Reversible Native Installation State

**Files:**
- Modify: `src/codex_router/native_primary_luna.py`
- Modify: `tests/test_native_primary_luna.py`

**Interfaces:**
- Add dataclass:

```python
@dataclass(frozen=True)
class NativeStatus:
    state: str
    installation_dir: Path
    agents_managed: bool
    luna_agent_configured: bool
    router_hooks_present: bool
    new_session_required: bool
```

- Add public functions:
  - `native_install(codex_home: Path | str, *, luna_model: str = "gpt-5.6-luna", luna_reasoning: str = "max") -> NativeStatus`
  - `native_status(codex_home: Path | str) -> NativeStatus`
  - `native_uninstall(codex_home: Path | str) -> NativeStatus`

Use safe filesystem primitives already present in `global_install.py` rather than introducing a second low-level filesystem framework:

```text
_validate_codex_home
_home_lock
_read_target_file
_validate_agents_directory
_atomic_write
_replace_expected
_sha256
```

The Native V1 module owns its own install directory/state protocol and must not write into the legacy Router install-state directory.

- [ ] **Step 1: Write RED test for fresh install preserving unrelated content**

Fixture:

```text
AGENTS.md -> existing guidance
hooks.json -> unrelated SessionStart hook
agents/other-agent.toml -> unrelated agent
```

After `native_install`:

- unrelated files/content remain byte-for-byte;
- Native block occurs exactly once at end of AGENTS;
- Luna TOML matches `render_luna_agent_bytes`;
- hooks.json is byte-for-byte unchanged;
- state is `installed`;
- `router_hooks_present` is false.

- [ ] **Step 2: Define exact Native install-state shape**

Write `install-state.json` under:

```text
<codex_home>/.codex-native-primary-luna-v1/install-state.json
```

with canonical JSON:

```json
{
  "protocol": "codex-native-primary-luna/install-state/v1",
  "phase": "installed",
  "targets": {
    "AGENTS.md": {
      "existed": true,
      "original_sha256": "sha256:...",
      "original_mode": 420,
      "backup": "backups/AGENTS.md.original",
      "installed_block_sha256": "sha256:..."
    },
    "agents/luna-worker.toml": {
      "existed": false,
      "original_sha256": null,
      "original_mode": null,
      "backup": null,
      "installed_sha256": "sha256:...",
      "installed_mode": 384
    }
  }
}
```

For `AGENTS.md`, track the managed block digest separately rather than requiring the whole file to remain byte-identical after installation. For `luna-worker.toml`, whole-file digest remains authoritative.

- [ ] **Step 3: Implement private state helpers**

Add:

```python
_installation_dir(home: Path) -> Path
_load_state(home: Path) -> dict[str, Any] | None
_write_state(home: Path, state: Mapping[str, Any]) -> None
_router_hooks_present(home: Path) -> bool
```

`_router_hooks_present` detects only Router-owned markers/commands, using the existing `HOOK_MARKER` / `codex_router ... hook-*` identity. It must not classify unrelated user hooks as Router hooks.

- [ ] **Step 4: Implement fresh `native_install` transaction**

Algorithm:

```text
validate codex_home
acquire home lock
if exact Native install already exists and status=installed -> return current status
if Native state exists but targets are ambiguous/modified -> fail closed
create private install dir/backups with owner-only permissions
read AGENTS + Luna originals
render expected Native block + Luna file
backup originals when present
write prepared state
append Native block to AGENTS
write Luna file
verify both targets
write phase=installed
return status
```

Do not write hooks.json.

- [ ] **Step 5: Write RED tests for idempotent reinstall**

Calling `native_install` twice with the same model/reasoning must:

- not duplicate the AGENTS block;
- not rewrite unrelated files;
- return `installed` both times.

If installed with different requested Luna model/reasoning, fail with a bounded conflict telling the caller to uninstall/reinstall rather than silently changing the managed executor.

- [ ] **Step 6: Write RED tests for safe uninstall preserving post-install AGENTS prefix changes**

After install, simulate a user edit **before** the exact managed block. Then uninstall.

Require:

- only the Native block is removed;
- the user's prefix edit survives byte-for-byte;
- if Luna file was installer-created and still exact, it is deleted;
- if Luna file replaced a pre-existing exact file, the original backup is restored;
- unrelated hooks/other agents remain unchanged.

- [ ] **Step 7: Implement `native_uninstall`**

For AGENTS, use `_strip_primary_block(current)` rather than restoring the entire old AGENTS backup over current user edits.

For Luna file, require exact installed digest before restoring/deleting. A user-modified Luna file must cause a conflict, not overwrite the user's modification.

Write state `phase=uninstalled` after successful reversal.

- [ ] **Step 8: Implement `native_status`**

Status rules:

```text
no Native state + no Native markers -> absent
installed state + exact managed block + exact Luna file + no Router-owned hooks -> installed
uninstalled state + no Native managed block/file ownership -> uninstalled
otherwise -> modified
```

`new_session_required=true` only for a clean `installed` state.

- [ ] **Step 9: Run focused GREEN and commit**

```bash
python3 -m pytest -q tests/test_native_primary_luna.py

git add src/codex_router/native_primary_luna.py tests/test_native_primary_luna.py
git commit -m "feat: add reversible native primary luna install"
```

---

### Task 3: Migrate Existing Router Installation Safely

**Files:**
- Modify: `src/codex_router/native_primary_luna.py`
- Modify: `tests/test_native_primary_luna.py`
- Read contracts: `src/codex_router/global_install_adapter.py`, `tests/test_global_install.py`

**Interfaces:**
- Add private helper:
  - `_migrate_legacy_router_if_needed(home: Path) -> bool`
- Return `True` only when a legacy Router install was actually uninstalled during this call.

- [ ] **Step 1: Write RED migration test using the real legacy installer fixture**

In a temporary codex home:

1. install existing Router global policy through `global_install_adapter.global_install`;
2. verify Router hooks and old Router AGENTS block exist;
3. call `native_install`;
4. verify legacy Router managed hook entries are gone;
5. verify Native PRIMARY block exists exactly once;
6. verify Native Luna TOML is installed;
7. verify unrelated hook/AGENTS fixture content survives.

- [ ] **Step 2: Implement exact legacy-state migration**

Use the existing legacy adapter as the ownership authority:

```python
from . import global_install_adapter as legacy

status = legacy.global_status(home)
```

Rules:

```text
if status.state == "installed" and legacy managed targets are healthy:
    legacy.global_uninstall(home)
    verify Router-owned hook marker is absent
    continue Native install

if legacy reports no active managed targets:
    continue Native install

if legacy reports modified/ambiguous managed targets:
    fail closed
```

Do not manually delete arbitrary hook groups.

- [ ] **Step 3: Write RED ambiguous legacy-state test**

Modify one legacy managed target after legacy install, then call `native_install`.

Require conflict and zero Native writes.

- [ ] **Step 4: Add rollback ordering**

Legacy migration must complete before creating/writing Native state or targets. If legacy uninstall fails, Native install leaves no partial Native block/state.

- [ ] **Step 5: Run focused GREEN and commit**

```bash
python3 -m pytest -q tests/test_native_primary_luna.py tests/test_global_install.py

git add src/codex_router/native_primary_luna.py tests/test_native_primary_luna.py
git commit -m "feat: migrate router install to native primary luna"
```

---

### Task 4: Add Native CLI and Offline Self-Test

**Files:**
- Modify: `src/codex_router/cli.py`
- Modify: `src/codex_router/native_primary_luna.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_native_primary_luna.py`
- Modify: `README.md`

**Interfaces:**
- CLI commands:
  - `native-install --codex-home PATH [--luna-model gpt-5.6-luna] [--luna-reasoning max]`
  - `native-status --codex-home PATH`
  - `native-uninstall --codex-home PATH`
  - `native-self-test --codex-home PATH`
- Add `native_self_test(codex_home: Path | str) -> dict[str, Any]`.

- [ ] **Step 1: Write RED CLI parser tests**

Require all four commands parse with no Router `state-dir`, `codex-bin`, local/web model, or K1 arguments.

- [ ] **Step 2: Add exact Native status JSON payload**

CLI output:

```json
{
  "state": "installed",
  "installation_dir": ".../.codex-native-primary-luna-v1",
  "agents_managed": true,
  "luna_agent_configured": true,
  "router_hooks_present": false,
  "new_session_required": true,
  "mode": "native_primary_luna_v1"
}
```

- [ ] **Step 3: Wire commands into `cli.main`**

Do not alter the existing `global-*` command behavior.

- [ ] **Step 4: Write RED self-test cases**

`native_self_test` must return explicit booleans for:

```text
NATIVE_PRIMARY_BLOCK
LUNA_AGENT_CONFIG
ROUTER_ROUTING_HOOK_ABSENT
NO_K1_LEASE_CEREMONY
NO_LUNA_DESCENDANTS
INSTALL_STATE_CONSISTENT
```

Self-test must be read-only against the real codex home. It must not launch Luna, browser, network, or a Hook subprocess.

- [ ] **Step 5: Implement self-test**

The `NO_K1_LEASE_CEREMONY` check scans only the Native managed block and Native Luna developer instructions for forbidden protocol terms; it does not fail because historical Router source files exist in the package.

- [ ] **Step 6: Update README**

Add a short section making Native V1 the recommended user-facing mode:

```text
router native-install ...
```

Explain:

- Sol/PRIMARY remains main agent;
- Luna is a native disposable executor;
- no Router routing Hook/K1/lease normal path;
- `global-*` commands remain the experimental hard-authority Router path.

Do not delete historical Router documentation.

- [ ] **Step 7: Run GREEN and commit**

```bash
python3 -m pytest -q tests/test_cli.py tests/test_native_primary_luna.py tests/test_global_install.py

git add src/codex_router/cli.py src/codex_router/native_primary_luna.py tests/test_cli.py tests/test_native_primary_luna.py README.md
git commit -m "feat: expose native primary luna mode"
```

---

### Task 5: Full Repository and Package Verification

**Files:**
- No required production changes unless verification exposes a defect.

- [ ] **Step 1: Full test suite**

```bash
python3 -m pytest -q
```

- [ ] **Step 2: Compile**

```bash
python3 -m compileall -q src tests
```

- [ ] **Step 3: Diff hygiene**

```bash
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git diff origin/main...HEAD
```

Review specifically for accidental changes to existing Router `global-*` semantics.

- [ ] **Step 4: Build exact wheel**

```bash
python3 -m build --wheel
sha256sum dist/*.whl || shasum -a 256 dist/*.whl
```

Record exact wheel filename and SHA-256.

- [ ] **Step 5: Fresh wheel smoke**

Create a clean temporary venv, install the wheel, create a temporary codex home, and run:

```bash
router native-install --codex-home <temp-home>
router native-status --codex-home <temp-home>
router native-self-test --codex-home <temp-home>
router native-uninstall --codex-home <temp-home>
```

Require all success states and exact reversal of fixture bytes.

- [ ] **Step 6: Whole-branch review**

Use the most capable reviewer and inspect:

- no Hook registration in Native mode;
- no K1/lease/bootstrap language in Native managed policy;
- safe migration ordering;
- no unrelated hooks/config overwritten;
- user-edited AGENTS prefix preservation;
- modified Luna file fail-closed behavior;
- spawn failure policy says PRIMARY fallback, not STOP;
- Luna descendants disabled.

- [ ] **Step 7: Push branch and create/update Draft PR**

```bash
git push origin simplify/native-primary-luna-v1
```

Open/keep a Draft PR against `main`. Do not mark Ready or merge.

Verify remote PR head equals locally tested HEAD and inspect Actions for that exact SHA.

---

### Task 6: Target-Mac Native Live Acceptance

**Files:**
- Real managed Codex home through supported `native-install` only.

- [ ] **Step 1: Verify exact tested artifact identity**

Record:

```text
REPO_HEAD=
WHEEL_FILE=
WHEEL_SHA256=
```

Install that exact wheel/build.

- [ ] **Step 2: Migrate/install Native V1**

Run supported `native-install` against the real Codex home.

Then require:

```text
native-status.state=installed
router_hooks_present=false
agents_managed=true
luna_agent_configured=true
native-self-test=PASS
```

Do not manually edit `~/.codex` to make acceptance pass.

- [ ] **Step 3: Fresh conversation A — ordinary local engineering**

Prompt:

```text
fix the failing tests in this project and verify the result
```

Require observed flow:

```text
PRIMARY_ACTIVE=YES
LUNA_NATIVE_SPAWN_ATTEMPTED=YES
LUNA_NATIVE_SPAWN_SUCCEEDED=YES
LUNA_EXECUTION_OBSERVED=YES
LUNA_LOCAL_ENGINEERING=YES
LUNA_RESULT_RETURNED=YES
PRIMARY_REVIEWED=YES
PRIMARY_FINAL_RESPONSE=YES
NO_K1_OR_LEASE_CEREMONY=YES
```

If native spawn fails, debug the native agent/config/surface directly. Do not add a Router control plane to fix it.

- [ ] **Step 4: Fresh conversation B — explicit no Luna**

Prompt with a clear first-turn instruction not to use Luna.

Require:

```text
LUNA_NATIVE_SPAWN_ATTEMPTED=NO
PRIMARY_CONTINUED_LOCALLY=YES
```

This is behavioral acceptance. Do not add a Hook regex if the model misses it; first tighten the short PRIMARY instruction and retest.

- [ ] **Step 5: Fresh conversation C — interactive browser/UI**

Require PRIMARY to own the browser operation and not delegate that browser step to Luna.

- [ ] **Step 6: Fresh conversation D — Playwright/headless engineering**

Prompt:

```text
run Playwright tests and fix the failures
```

Require Luna delegation remains available.

- [ ] **Step 7: Delegation failure fallback**

Safely simulate or reproduce spawn unavailability. Require PRIMARY to continue locally and not emit a Router protocol stop.

- [ ] **Step 8: Final report**

Report at minimum:

```text
BRANCH=simplify/native-primary-luna-v1
BASE_SHA=
FINAL_HEAD=
DRAFT_PR=
UNIT_TESTS=
COMPILEALL=
DIFF_CHECK=
WHEEL_FILE=
WHEEL_SHA256=
FRESH_WHEEL_SELF_TEST=
NATIVE_INSTALL=
ROUTER_ROUTING_HOOK_ABSENT=
ORDINARY_LUNA_DELEGATION=
EXPLICIT_NO_LUNA=
BROWSER_PRIMARY=
HEADLESS_BROWSER_LUNA=
PRIMARY_FALLBACK_WHEN_SPAWN_UNAVAILABLE=
LIVE_ACCEPTANCE=
```

Keep the PR Draft. Do not merge or mark Ready.
