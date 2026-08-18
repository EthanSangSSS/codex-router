# K1 Control-Plane Sideband Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move K1 authority off opaque native V2 collaboration messages into a one-shot authenticated Router sideband while preserving generation, scope/A1, persistent-executor, QueueOnly, and fail-closed guarantees.

**Architecture:** PRIMARY stages canonical K1 through a new `router stage-k1` command using a one-time HMAC capability bound to the current root turn/task epoch/next generation. Native `spawn_agent`/`followup_task` messages become trigger-only. The first EXECUTOR `PreToolUse` for each generation is blocked and receives the staged canonical K1 as developer `additionalContext`; the second same-turn tool attempt proceeds under existing policy and clears the transient staged wire.

**Tech Stack:** Python 3, stdlib `argparse`/`json`/`hmac`/`hashlib`, existing Router journal/HMAC/Hook infrastructure, `unittest`, Codex managed Hooks.

**Spec:** `docs/superpowers/specs/2026-08-19-k1-control-plane-sideband-design.md`

## Global Constraints

- K1 plaintext is the Router authoritative control plane; native collaboration message plaintext is not an authority source.
- PRIMARY model selection remains inherited/capability-based; EXECUTOR model/reasoning remain explicit configuration.
- Keep exactly the existing five live Hooks: `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`.
- Do not add a daemon, socket, MCP server, packet-history database, checkpoint service, automatic model selection, or encrypted-message decoder.
- Keep `send_message` QueueOnly: it cannot consume staged K1, advance generation, or trigger an authorized new turn.
- Keep one persistent EXECUTOR per task epoch and existing native spawn binding via `tool_use_id` + `SubagentStart`/`PostToolUse` evidence.
- Keep PR #8 open, Draft, unmerged, and not ready for review.
- No live `~/.codex` mutation, reinstall, Hook trust change, live agent spawn, or production smoke during repository implementation.

---

### Task 1: Add authenticated stage-capability primitives

**Files:**
- Modify: `src/codex_router/protocol.py`
- Test: `tests/test_k1_sideband_v31.py`

**Interfaces:**
- Produces: `build_k1_stage_capability(secret: bytes, *, session_tag: str, root_turn_tag: str, task_epoch: str, generation: int) -> str`
- Produces: `verify_k1_stage_capability(token: str, secret: bytes, *, session_tag: str, root_turn_tag: str, task_epoch: str, generation: int) -> None`
- Consumes existing: `canonical_json_bytes`, `parse_luna_packet`, `ProtocolError`

- [ ] **Step 1: Write failing capability tests**

Add tests that require exact success for a current token and fail closed for changed session tag, root-turn tag, task epoch, generation, malformed token, and tampered MAC.

```python
class K1StageCapabilityTests(unittest.TestCase):
    def test_stage_capability_is_bound_to_current_authority(self):
        token = build_k1_stage_capability(
            b"s" * 32,
            session_tag="a" * 64,
            root_turn_tag="b" * 64,
            task_epoch="task-" + "1" * 32,
            generation=2,
        )
        verify_k1_stage_capability(
            token,
            b"s" * 32,
            session_tag="a" * 64,
            root_turn_tag="b" * 64,
            task_epoch="task-" + "1" * 32,
            generation=2,
        )

    def test_stage_capability_rejects_generation_replay(self):
        token = build_k1_stage_capability(
            b"s" * 32,
            session_tag="a" * 64,
            root_turn_tag="b" * 64,
            task_epoch="task-" + "1" * 32,
            generation=2,
        )
        with self.assertRaises(ProtocolError):
            verify_k1_stage_capability(
                token,
                b"s" * 32,
                session_tag="a" * 64,
                root_turn_tag="b" * 64,
                task_epoch="task-" + "1" * 32,
                generation=3,
            )
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```bash
python -m unittest tests.test_k1_sideband_v31.K1StageCapabilityTests -v
```

Expected: FAIL because the capability functions do not exist.

- [ ] **Step 3: Implement the minimal token format**

Use canonical JSON claims plus HMAC-SHA256. A compact acceptable wire shape is:

```text
base64url(canonical_json(claims)) + "." + hex_hmac
```

Claims must contain only:

```python
{
    "v": 1,
    "session_tag": session_tag,
    "root_turn_tag": root_turn_tag,
    "task_epoch": task_epoch,
    "generation": generation,
}
```

Verification must use `hmac.compare_digest` and exact claim equality. Do not add timestamps or a new persistence layer; freshness comes from current root/task/generation state.

- [ ] **Step 4: Re-run focused tests and confirm GREEN**

Run the same unittest command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/protocol.py tests/test_k1_sideband_v31.py
git commit -m "feat: add authenticated K1 stage capabilities"
```

---

### Task 2: Extend the control snapshot with one staged authority packet

**Files:**
- Modify: `src/codex_router/luna_control.py`
- Test: `tests/test_k1_sideband_v31.py`

**Interfaces:**
- Add `ControlSnapshot.authority_packet_wire: str | None = None`
- Produces: `stage_authority_packet(directory, secret, session_id, *, root_turn_id, capability, packet_wire) -> ControlSnapshot`
- Produces: `commit_staged_packet(directory, secret, session_id) -> ControlSnapshot`
- Produces: `clear_staged_authority(directory, secret, session_id) -> ControlSnapshot`
- Add/read current-root-turn HMAC tag through an existing or minimal helper; do not persist raw root turn text if a tag is sufficient.

- [ ] **Step 1: Write failing journal/state tests**

Cover:

```python
def test_stage_packet_accepts_exact_next_generation(...): ...
def test_identical_stage_retry_is_idempotent(...): ...
def test_different_duplicate_stage_is_denied(...): ...
def test_new_root_authority_invalidates_unused_stage(...): ...
def test_retire_or_cancel_clears_staged_authority(...): ...
def test_commit_staged_packet_uses_existing_begin_packet_semantics(...): ...
```

Assertions must prove the staged wire is exactly canonical K1, packet generation is unchanged while merely staged, and only `commit_staged_packet()` advances the generation/state through existing packet logic.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
python -m unittest tests.test_k1_sideband_v31.K1SidebandStateTests -v
```

Expected: FAIL on missing snapshot field/functions.

- [ ] **Step 3: Implement minimal snapshot/schema migration**

Extend backward-compatible snapshot loading so old current snapshots without `authority_packet_wire` deserialize as `None`.

Do not add a second journal. Preserve existing locking, atomic replacement, file fsync, directory fsync, owner/mode/symlink checks, and bounded state size.

`stage_authority_packet()` must:

```python
packet = parse_luna_packet(packet_wire)
expected_generation = snapshot.packet_generation + 1
verify_k1_stage_capability(... generation=expected_generation ...)
if packet["generation"] != expected_generation:
    raise RouterStateError(...)
if snapshot.authority_packet_wire is None:
    store packet_wire
elif snapshot.authority_packet_wire != packet_wire:
    raise RouterStateError(...)
# identical retry returns current snapshot
```

`commit_staged_packet()` must parse the stored wire, call the existing `begin_packet(...)` semantics exactly once, and preserve the staged wire until the executor handshake clears it.

- [ ] **Step 4: Run focused state tests and existing control tests**

```bash
python -m unittest tests.test_k1_sideband_v31.K1SidebandStateTests -v
python -m unittest discover -s tests -p 'test_*control*.py' -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/luna_control.py tests/test_k1_sideband_v31.py
git commit -m "feat: stage K1 authority in control journal"
```

---

### Task 3: Add `router stage-k1` and root staging context

**Files:**
- Modify: `src/codex_router/cli.py`
- Modify: `src/codex_router/hook.py`
- Test: `tests/test_k1_sideband_v31.py`
- Test: existing CLI/global-install tests as affected

**Interfaces:**
- New CLI: `router stage-k1 --installation-dir PATH --session-id ID --root-turn-id ID --capability TOKEN`, K1 packet on stdin
- Root Hook additional context includes the exact installed command template and current one-time capability.

- [ ] **Step 1: Write failing CLI/root-context tests**

Tests must prove:

```python
def test_routed_root_context_contains_stage_capability_and_command(...): ...
def test_stage_k1_cli_reads_one_packet_from_stdin_and_stages_it(...): ...
def test_stage_k1_cli_rejects_stale_capability(...): ...
def test_direct_or_bypass_context_does_not_issue_stage_authority(...): ...
```

Do not expose installation secret or raw HMAC key material in output/context.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
python -m unittest tests.test_k1_sideband_v31.K1StageCliTests -v
```

Expected: FAIL because `stage-k1` and context fields are absent.

- [ ] **Step 3: Implement the CLI command**

Add parser entry and main dispatch. Read stdin once with the same UTF-8/size discipline used for Hook input; reject empty/multiple/non-canonical packets through existing parser behavior.

Machine-readable success should be bounded, for example:

```json
{"status":"staged","generation":2,"packet_id":"..."}
```

Do not print the packet body or capability secret material.

- [ ] **Step 4: Inject staging instructions into routed root context**

Generate the one-time capability from the current snapshot/root turn and include only current-turn staging guidance. Keep model-role terminology generic in new text (`PRIMARY`, `EXECUTOR`); legacy state keys may remain internal.

- [ ] **Step 5: Run focused + CLI/global-install regression tests**

```bash
python -m unittest tests.test_k1_sideband_v31.K1StageCliTests -v
python -m unittest discover -s tests -p 'test_*cli*.py' -v
python -m unittest discover -s tests -p 'test_*global_install*.py' -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/codex_router/cli.py src/codex_router/hook.py tests/test_k1_sideband_v31.py
git commit -m "feat: expose one-shot K1 staging command"
```

---

### Task 4: Change parent native dispatch to consume staged authority, not message plaintext

**Files:**
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/luna_control.py` only if a narrow helper is needed
- Test: `tests/test_k1_sideband_v31.py`
- Test: existing exact-root/control-plane tests

**Interfaces:**
- Parent `spawn_agent` and `followup_task` admission call `commit_staged_packet(...)` after native identity/target checks.
- Native `tool_input.message` is never passed to `parse_luna_packet` for V2 `spawn_agent`/`followup_task`/`send_message` admission.

- [ ] **Step 1: Write RED tests using opaque native messages**

Use token-like strings that are definitely not K1:

```python
OPAQUE = "enc_01J9opaque_native_payload"
```

Required tests:

```python
def test_spawn_accepts_opaque_message_with_valid_staged_gen1(...): ...
def test_spawn_without_stage_fails_closed(...): ...
def test_spawn_identity_fields_still_fail_closed(...): ...
def test_followup_accepts_opaque_message_for_exact_bound_executor(...): ...
def test_followup_wrong_target_fails_closed_even_with_stage(...): ...
def test_send_message_cannot_consume_stage_or_advance_generation(...): ...
```

- [ ] **Step 2: Run focused tests and confirm RED on current message parser**

```bash
python -m unittest tests.test_k1_sideband_v31.K1ParentDispatchTests -v
```

Expected: opaque-message positive cases FAIL with current K1-prefix admission error.

- [ ] **Step 3: Implement minimal parent admission change**

For `spawn_agent`:

```text
validate task_name / agent_type / fork_turns
require current staged authority
reserve_spawn(tool_use_id)
commit_staged_packet()
allow
```

For `followup_task`:

```text
authorize exact current executor target
require current staged authority
commit_staged_packet()
allow
```

For `send_message`:

```text
authorize target
DENY QueueOnly K1 dispatch
DO NOT commit staged authority
DO NOT increment generation
```

Do not add generic encrypted-message branching or string heuristics.

- [ ] **Step 4: Run focused + exact-root/control-plane regressions**

```bash
python -m unittest tests.test_k1_sideband_v31.K1ParentDispatchTests -v
python -m unittest discover -s tests -p 'test_v31_exact_root*.py' -v
python -m unittest discover -s tests -p 'test_*control_plane*.py' -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/hook.py src/codex_router/luna_control.py tests/test_k1_sideband_v31.py
git commit -m "fix: decouple K1 admission from encrypted V2 messages"
```

---

### Task 5: Enforce the executor first-tool K1 handshake

**Files:**
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/luna_control.py`
- Test: `tests/test_k1_sideband_v31.py`
- Test: existing SubagentStart/SubagentStop/identity tests

**Interfaces:**
- Produces a narrow executor pretool handshake outcome: first current-generation tool is denied with canonical K1 `additionalContext`; second same-turn tool proceeds and clears staged wire.
- Existing `start_execution(... child_turn_id=...)` remains the child-turn binder.

- [ ] **Step 1: Write failing handshake tests**

Required tests:

```python
def test_first_executor_tool_is_blocked_and_receives_exact_k1_context(...): ...
def test_first_tool_does_not_clear_staged_wire(...): ...
def test_second_same_turn_tool_clears_staged_wire_and_runs_normal_policy(...): ...
def test_second_different_turn_fails_closed(...): ...
def test_forbidden_lifecycle_tool_remains_forbidden_after_handshake(...): ...
def test_unbound_executor_cannot_trigger_handshake(...): ...
```

Assert Hook output contains a blocking decision **and** `additionalContext == authority_packet_wire` for the first tool.

- [ ] **Step 2: Run handshake tests and confirm RED**

```bash
python -m unittest tests.test_k1_sideband_v31.K1ExecutorHandshakeTests -v
```

Expected: FAIL because current executor PreToolUse immediately evaluates/starts execution without the two-step authority handshake.

- [ ] **Step 3: Implement handshake-before-policy ordering**

Pseudo-flow in bound-executor PreToolUse:

```python
snapshot = read_snapshot(...)
if snapshot.active_packet_id is not None and snapshot.authority_packet_wire is not None:
    if snapshot.active_child_turn_id is None:
        start_execution(... child_turn_id=base["turn_id"])
        return block_with_additional_context(
            reason="Router authority packet injected; retry tool under K1 authority",
            context=snapshot.authority_packet_wire,
        )
    if snapshot.active_child_turn_id != base["turn_id"]:
        return deny("Router executor turn identity mismatch")
    clear_staged_authority(...)
# then run existing ordinary executor lifecycle/A1/tool policy
```

Do not clear the wire on the first blocked attempt; clearing only on the second same-turn PreToolUse is the evidence that Codex has had a resampling boundary with injected developer context.

- [ ] **Step 4: Remove child-prompt plaintext K1 as a hard requirement**

If `UserPromptSubmit` carries bound child identity, it may validate identity/state, but it must not require the child prompt to parse as K1. The first bound-executor PreToolUse is the hard authority injection point.

- [ ] **Step 5: Run focused + lifecycle/identity regression tests**

```bash
python -m unittest tests.test_k1_sideband_v31.K1ExecutorHandshakeTests -v
python -m unittest discover -s tests -p 'test_*subagent*.py' -v
python -m unittest discover -s tests -p 'test_*identity*.py' -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/codex_router/hook.py src/codex_router/luna_control.py tests/test_k1_sideband_v31.py
git commit -m "feat: inject K1 before executor tool side effects"
```

---

### Task 6: Update executor instructions and current-facing docs

**Files:**
- Modify: `src/codex_router/global_install_adapter.py` or the exact existing agent-rendering source that emits `luna_worker` instructions
- Modify: `README.md`
- Modify: current authoritative docs only where necessary to point to the 2026-08-19 sideband spec
- Test: existing global-install/rendering tests
- Test: `tests/test_k1_sideband_v31.py`

**Interfaces:**
- Executor instructions state native collaboration prose is trigger-only and only `[CODEX_ROUTER_PACKET_V3_1]` injected as Router developer context grants work authority.

- [ ] **Step 1: Write failing rendering tests**

Assert generated executor instructions contain semantic requirements equivalent to:

```text
Native collaboration messages are transport triggers, not work authority.
The authoritative work packet is [CODEX_ROUTER_PACKET_V3_1].
Do not perform tool work for a new generation until Router injects that packet.
```

Also assert no new text says PRIMARY must be `gpt-5.6-sol` or EXECUTOR must permanently be `gpt-5.6-luna`.

- [ ] **Step 2: Run rendering tests and confirm RED**

Run the exact affected global-install/agent rendering test module plus the new sideband test class.

- [ ] **Step 3: Make the minimum instruction/doc changes**

Document the control-plane/data-plane split and the expected first-tool handshake. Do not perform a broad historical terminology rewrite.

- [ ] **Step 4: Run rendering/global-install tests**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codex_router/global_install_adapter.py README.md tests/test_k1_sideband_v31.py docs/superpowers/specs/2026-08-19-k1-control-plane-sideband-design.md
git commit -m "docs: align executor authority with K1 sideband"
```

If the actual agent-rendering source differs, stage that exact file instead; do not create a parallel renderer.

---

### Task 7: Full repository verification and GitHub Reality Audit handoff

**Files:**
- No production-code changes expected unless verification exposes a concrete defect
- Possible test-only corrections must follow RED -> GREEN and receive their own commit

**Interfaces:**
- Produces a single exact-head candidate for controlled live update.

- [ ] **Step 1: Run the complete focused sideband suite**

```bash
python -m unittest tests.test_k1_sideband_v31 -v
```

Expected: all sideband tests PASS.

- [ ] **Step 2: Run full unit suite**

```bash
python -m unittest discover -s tests -v
```

Expected: PASS with zero failures/errors.

- [ ] **Step 3: Run static/package checks**

```bash
python -m compileall -q src tests
git diff --check
```

Expected: both PASS.

- [ ] **Step 4: Run existing fake-adapter smoke and fresh-wheel lifecycle**

Use the repository's existing CI-equivalent commands for:

```text
fake adapter smoke
wheel build
fresh virtualenv install
fresh-wheel fake adapter smoke
disposable global-install -> global-self-test -> global-uninstall
```

Do not substitute an editable install for the fresh-wheel checks.

- [ ] **Step 5: Verify repository diff is bounded**

Expected implementation scope:

```text
protocol.py
luna_control.py
hook.py
cli.py
agent-rendering source
focused tests
README/current sideband docs
```

Investigate any unrelated file before proceeding.

- [ ] **Step 6: Push normally to the existing PR branch**

```bash
git push origin hardening/native-luna-safety-v2
```

No force push.

- [ ] **Step 7: Verify exact-head GitHub state**

Require:

```text
PR #8 = OPEN
PR #8 = DRAFT
PR #8 = UNMERGED
PR head = local HEAD
CI exact head = SUCCESS
Secret Scan exact head = SUCCESS
```

Do not mark ready for review or merge.

- [ ] **Step 8: Return the implementation evidence report**

Return exactly these fields:

```text
SYNC_GATE=
SPEC_HEAD=
IMPLEMENTATION_HEAD=

SIDE_BAND_CAPABILITY=
STAGE_K1_CLI=
STAGED_PACKET_JOURNAL=
OPAQUE_SPAWN_ADMISSION=
OPAQUE_FOLLOWUP_ADMISSION=
SEND_MESSAGE_QUEUE_ONLY=
EXECUTOR_FIRST_TOOL_HANDSHAKE=
CHILD_PROMPT_K1_DEPENDENCY_REMOVED=
MODEL_ROLE_DECOUPLING_PRESERVED=

FOCUSED_TESTS=
FULL_UNIT_TESTS=
COMPILEALL=
DIFF_CHECK=
FAKE_ADAPTER=
FRESH_WHEEL_TEST=

PATCH_FILES=
COMMIT_SHA=
PR_HEAD_AFTER=
CI_RESULT=
SECRET_SCAN_RESULT=

LIVE_CODEX_HOME_TOUCHED=NO
LIVE_REINSTALL_PERFORMED=NO
AGENT_SPAWNED=NO
NESTED_CODEX=NO
PR_DRAFT=YES
PR_MERGED=NO

BLOCKERS=
FINAL_DISPOSITION=
```

Success disposition:

```text
K1_SIDEBAND_READY_FOR_GITHUB_REALITY_AUDIT
```

## Plan self-review

- Spec coverage: capability, transient staged wire, root staging context, Gen1/Gen2+ opaque-message admission, QueueOnly denial, executor first-tool handshake, child-prompt decoupling, model-role decoupling, bounded docs, full verification, and no-live-mutation constraints are all assigned to tasks.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation steps remain.
- Type/interface consistency: capability functions feed `stage_authority_packet`; `stage-k1` invokes the same staging function; parent admission uses `commit_staged_packet`; executor handshake uses `authority_packet_wire` and `clear_staged_authority`. No second state machine or alternate packet store is introduced.
