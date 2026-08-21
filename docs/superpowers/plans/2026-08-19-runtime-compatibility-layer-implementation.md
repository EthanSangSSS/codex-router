# Runtime Compatibility Layer Implementation Plan

> **Historical / superseded:** The active lifecycle is V3.3 “Persistent Task, Disposable Luna.” Persistent-worker identity and required-follow-up steps below are non-authoritative history; see [the V3.3 design](../specs/2026-08-20-router-v3-3-persistent-task-disposable-luna-design.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Implement FIX5 current-runtime compatibility without changing the canonical K1 authority or state-machine architecture.

**Architecture:** A Router-owned structured staging command builds canonical K1 and calls the current stage transition. The Hook normalizes only exact runtime surfaces and maps V1 inputs into the existing internal admission shape; the adapter separates Gen1 evidence from persistent follow-up evidence without granting runtime authority.

**Tech Stack:** Python, argparse, existing codex_router control and protocol modules, unittest, disposable installation fixtures.

**Spec:** docs/superpowers/specs/2026-08-19-runtime-compatibility-layer-design.md

## Global Constraints

- protocol.build_luna_packet remains the canonical serializer.
- parse_luna_packet remains strict and legacy stage-k1 remains wire-only.
- stage_authority_packet remains the authority transition.
- No journal schema change: stop for human review if one is necessary.
- Do not mutate live ~/.codex, reinstall Router, or run live agent testing.
- send_message remains QueueOnly; send_input and resume_agent never advance K1.
- Luna descendants/nested Codex remain forbidden.
- PR #8 remains Draft/unmerged.

---

### Task 1: Deterministic structured K1 staging

**Files:**
- Create: tests/test_runtime_operator_contract_v31.py
- Modify: src/codex_router/cli.py
- Modify: tests/test_cli.py and tests/test_k1_sideband_v31.py

**Interfaces:**
- Consumes: build_luna_packet with packet id, generation, objective, working directory, scope, A1, success, and stop fields; the current snapshot reader; and stage_authority_packet.
- Produces: stage-k1-fields with singleton --packet-id/--objective/--working-directory, repeating scope/A1/success/stop options, and bounded JSON {status, packet_id, generation}.

- [ ] **Step 1: Write the failing test**

~~~~python
def test_stage_k1_fields_stages_canonical_generation_one(self) -> None:
    result = self.run_stage_fields(packet_id="gen1")
    self.assertEqual(result, {"status": "staged", "packet_id": "gen1", "generation": 1})
    self.assertEqual(
        self.snapshot().authority_packet_wire,
        build_luna_packet(**self.packet_fields(generation=1)),
    )

def test_stage_k1_fields_rejects_escape_hatches_and_duplicate_singletons_before_state_mutation(self) -> None:
    before = self.snapshot()
    self.assert_error("--packet-id", "one", "--packet-id", "two")
    self.assert_error("--objective", "one", "--objective", "two")
    self.assert_error("--working-directory", "/one", "--working-directory", "/two")
    self.assertEqual(self.snapshot(), before)
    self.assert_error("--wire", "[CODEX_ROUTER_PACKET_V3_1]{}")
    self.assert_error("--packet-json", "{}")
~~~~

Cover derived generation, malformed fields, non-absolute working directory, duplicate singleton fields, capability redaction in normal/error output, and unchanged strict legacy stage-k1 parsing.

- [ ] **Step 2: Run test to verify it fails**

Run: python -m unittest tests.test_runtime_operator_contract_v31.RuntimeOperatorContractTests.test_stage_k1_fields_stages_canonical_generation_one -v

Expected: FAIL because stage-k1-fields is not registered.

- [ ] **Step 3: Write minimal implementation**

~~~~python
stage = subcommands.add_parser("stage-k1-fields")
stage.add_argument("--installation-dir", type=Path, required=True)
stage.add_argument("--session-id", required=True)
stage.add_argument("--root-turn-id", required=True)
stage.add_argument("--capability", required=True)
class _UniqueStore(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(self, f"{option_string} may occur once")
        setattr(namespace, self.dest, value)

stage.add_argument("--packet-id", action=_UniqueStore, required=True)
stage.add_argument("--objective", action=_UniqueStore, required=True)
stage.add_argument("--working-directory", action=_UniqueStore, required=True)
stage.add_argument("--intended-write-scope", action="append", default=[])
stage.add_argument("--explicit-side-effect-authorization", action="append", default=[])
stage.add_argument("--success-criterion", action="append", default=[])
stage.add_argument("--stop-condition", action="append", default=[])
~~~~

Use this deterministic argparse action for exactly `--packet-id`, `--objective`, and `--working-directory`; its second-occurrence `ArgumentError` occurs during argument parsing, before any installation/state read or mutation. Validate bounded UTF-8 fields and an absolute working directory; then load the existing installation, derive snapshot.packet_generation + 1, build K1 with build_luna_packet, and call only stage_authority_packet. Do not accept a generation, wire, JSON, alternate command, parser repair, or serializer retry.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_cli tests.test_k1_sideband_v31 -v

Expected: PASS; legacy stage-k1 remains byte-strict.

- [ ] **Step 5: Commit**

~~~~bash
git add src/codex_router/cli.py tests/test_runtime_operator_contract_v31.py tests/test_cli.py tests/test_k1_sideband_v31.py
git commit -m "feat: add deterministic structured K1 staging"
~~~~

Commit boundary: Add deterministic structured K1 staging.

### Task 2: Exact native tool normalization

**Files:**
- Modify: src/codex_router/hook.py
- Modify: tests/test_runtime_operator_contract_v31.py, tests/test_v31_exact_root_hook_identity.py, tests/test_hook.py

**Interfaces:**
- Consumes: raw Hook tool name and input mapping.
- Produces: internal NativeToolMatch(raw_name, surface_profile, canonical_operation, input_schema), or an existing fail-closed unknown-lifecycle decision.

Task 2 defines the exact immutable production representation:

~~~~python
@dataclass(frozen=True)
class NativeToolMatch:
    raw_name: str
    surface_profile: Literal[
        "direct_v2",
        "collaboration_v2",
        "multi_agent_v1",
        "collapsed_v1_spawn",
        "forbidden_legacy",
    ]
    canonical_operation: str
    input_schema: Literal["v2", "v1_spawn", "v1_wait", "none"]
~~~~

- [ ] **Step 1: Write the failing test**

~~~~python
def test_v1_normalization_is_exact_and_v1_list_aliases_are_unknown(self) -> None:
    self.assert_match("multi_agent_v1__spawn_agent", "multi_agent_v1", "spawn_agent")
    self.assert_match("multi_agent_v1wait_agent", "multi_agent_v1", "wait_agent")
    self.assert_unknown("multi_agent_v1__list_agents")
    self.assert_unknown("multi_agent_v1list_agents")

def test_v1_legacy_operations_are_explicitly_forbidden(self) -> None:
    self.assert_legacy_denied("multi_agent_v1__send_input")
    self.assert_legacy_denied("multi_agent_v1resume_agent")
~~~~

Cover direct/current V2 names, existing collaboration aliases, V1 spawn/wait exact names and collapsed forms, malformed separators, suffix tricks, unknown versions, forbidden V1 send_input/resume_agent, and ordinary non-lifecycle tools.

- [ ] **Step 2: Run test to verify it fails**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_v31_exact_root_hook_identity tests.test_hook -v

Expected: FAIL because V1 names are not normalized.

- [ ] **Step 3: Write minimal implementation**

~~~~python
_EXACT_NATIVE_TOOL_NAMES = {
    "multi_agent_v1__spawn_agent": NativeToolMatch(
        "multi_agent_v1__spawn_agent", "multi_agent_v1", "spawn_agent", "v1_spawn"),
    "multi_agent_v1spawn_agent": NativeToolMatch(
        "multi_agent_v1spawn_agent", "multi_agent_v1", "spawn_agent", "v1_spawn"),
    "multi_agent_v1__wait_agent": NativeToolMatch(
        "multi_agent_v1__wait_agent", "multi_agent_v1", "wait_agent", "v1_wait"),
    "multi_agent_v1wait_agent": NativeToolMatch(
        "multi_agent_v1wait_agent", "multi_agent_v1", "wait_agent", "v1_wait"),
}
~~~~

Retain direct list_agents and existing collaborationlist_agents only. Do not add V1 list_agents aliases. Do not strip punctuation, suffix-match, or guess a namespace. Map exact V1 send_input/resume_agent only to forbidden legacy operations; never map either to followup_task.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_v31_exact_root_hook_identity tests.test_hook -v

Expected: PASS; unknown lifecycle-looking names fail before state mutation.

- [ ] **Step 5: Commit**

~~~~bash
git add src/codex_router/hook.py tests/test_runtime_operator_contract_v31.py tests/test_v31_exact_root_hook_identity.py tests/test_hook.py
git commit -m "feat: normalize native collaboration tool surfaces"
~~~~

Commit boundary: Normalize native collaboration tool surfaces.

### Task 3: V1/V2 spawn admission and V1 result binding

**Files:**
- Modify: src/codex_router/hook.py
- Modify: src/codex_router/luna_control.py only if an existing reservation field can be minimally reused
- Modify: tests/test_runtime_operator_contract_v31.py, tests/test_v31_exact_root_hook_identity.py, tests/test_k1_sideband_v31.py

**Interfaces:**
- Consumes: NativeToolMatch, staged Gen1, current root identity, existing reservation transition, PostToolUse output, and SubagentStart.
- Produces: V1 projection to internal task_name=luna_worker, agent_type=luna_worker, fork_turns=none; returned V1 agent_id is correlation only.

- [ ] **Step 1: Write the failing test**

~~~~python
def test_exact_v1_spawn_projects_only_a_no_history_luna(self) -> None:
    result = self.pretool("multi_agent_v1__spawn_agent",
        {"agent_type": "luna_worker", "fork_context": False, "message": "opaque"})
    self.assertEqual(result["decision"], "allow")

def test_exact_v1_spawn_omits_fork_context_as_no_history(self) -> None:
    result = self.pretool("multi_agent_v1__spawn_agent",
        {"agent_type": "luna_worker", "message": "opaque"})
    self.assertEqual(result["decision"], "allow")

def test_v1_result_agent_id_is_not_binding_without_subagent_start(self) -> None:
    self.posttool_v1({"agent_id": "native-17", "nickname": "luna"})
    self.assertFalse(self.snapshot().luna_bound)
    self.subagent_start(agent_id="native-17", agent_type="luna_worker")
    self.assertTrue(self.snapshot().luna_bound)
~~~~

Deny wrong/missing agent_type, fork_context=true, V2 fields on V1, V1 fields on V2, every hybrid, and plain/collapsed V1 without fork_context=false. Exact `multi_agent_v1` accepts omission and explicit `fork_context=false`; collapsed/plain V1 requires explicit false. Assert denials neither consume K1 nor duplicate a reservation.

- [ ] **Step 2: Run test to verify it fails**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_v31_exact_root_hook_identity tests.test_k1_sideband_v31 -v

Expected: FAIL because V1 schema admission is absent.

- [ ] **Step 3: Write minimal implementation**

~~~~python
def _v1_spawn_projection(
    data: Mapping[str, Any], surface_profile: Literal["multi_agent_v1", "collapsed_v1_spawn"]
) -> dict[str, str]:
    if {"task_name", "fork_turns"} & data.keys():
        raise _invalid("V1 spawn schema is mixed")
    if data.get("agent_type") != "luna_worker" or data.get("fork_context") is True:
        raise _invalid("V1 spawn must be no-history luna_worker")
    if surface_profile == "collapsed_v1_spawn" and data.get("fork_context") is not False:
        raise _invalid("collapsed V1 spawn requires explicit fork_context=false")
    return {"task_name": "luna_worker", "agent_type": "luna_worker", "fork_turns": "none"}
~~~~

The helper explicitly consumes `surface_profile`; its exact-V1 branch accepts an omitted value independently of its collapsed-V1 explicit-false branch. Keep V2 exactly task_name=luna_worker, agent_type=luna_worker, fork_turns=none and reject fork_context. Store only the exact V1 returned agent_id in an existing pending-reservation correlation seam; nickname never binds and a task path is never fabricated. Stop for human review if doing so needs journal serialization.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_v31_exact_root_hook_identity tests.test_k1_sideband_v31 tests.test_luna_control_v3 -v

Expected: PASS; schemas are mutually exclusive and SubagentStart remains final binding evidence.

- [ ] **Step 5: Commit**

~~~~bash
git add src/codex_router/hook.py src/codex_router/luna_control.py tests/test_runtime_operator_contract_v31.py tests/test_v31_exact_root_hook_identity.py tests/test_k1_sideband_v31.py
git commit -m "feat: add version-aware Luna spawn admission"
~~~~

Commit boundary: Add version-aware Luna spawn admission.

### Task 4: V1 wait observe-only behavior

**Files:**
- Modify: src/codex_router/hook.py
- Modify: tests/test_runtime_operator_contract_v31.py and tests/test_v31_exact_root_hook_identity.py

**Interfaces:**
- Consumes: exact V1 wait match, current root identity/turn, and snapshot.luna_agent_id; V2 wait accepts optional timeout_ms only.
- Produces: V1 observation allow only for targets=[exact luna_agent_id], with timeout_ms transport-only; V2 rejects any targets field.

- [ ] **Step 1: Write the failing test**

~~~~python
def test_v1_wait_accepts_only_exact_bound_agent_id_without_state_change(self) -> None:
    before = self.snapshot()
    decision = self.pretool("multi_agent_v1__wait_agent",
        {"targets": [before.luna_agent_id], "timeout_ms": 1000})
    self.assertEqual(decision["decision"], "allow")
    self.assertEqual(self.snapshot(), before)

def test_v1_wait_rejects_task_path_and_unrelated_targets(self) -> None:
    self.assert_wait_denied({"targets": ["/root/luna_worker"]})
    self.assert_wait_denied({"targets": ["other-agent"]})
    self.assert_wait_denied({"targets": []})

def test_v2_wait_has_no_target_contract(self) -> None:
    self.assert_wait_allowed("wait_agent", {"timeout_ms": 1000})
    self.assert_wait_denied("wait_agent", {"targets": ["native-17"]})
~~~~

Cover collapsed V1 wait, malformed targets, V2 targets-as-schema-mismatch, child/ambiguous/stale-root actors, direct and collaboration list observe-only behavior, and V1 list forms remaining unknown. Snapshot equality includes generation, staged wire, active packet, and execution state.

- [ ] **Step 2: Run test to verify it fails**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_v31_exact_root_hook_identity -v

Expected: FAIL because V1 wait has no agent-ID-only validator and V2 has no timeout-only schema enforcement.

- [ ] **Step 3: Write minimal implementation**

~~~~python
def _validate_v1_wait_targets(data: Mapping[str, Any], luna_agent_id: str) -> None:
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        raise _invalid("V1 wait targets are invalid")
    if any(not isinstance(value, str) or not value or value != luna_agent_id for value in targets):
        raise _invalid("V1 wait target is not the bound Luna agent id")
~~~~

Apply this only to `input_schema=v1_wait`. For V2, reject `targets` if present and accept only optional `timeout_ms`; do not add or describe a V2 exact-target contract. Do not consume staged K1, increment generation, start execution, or change Router state.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_v31_exact_root_hook_identity tests.test_v31_turn_boundary_mode -v

Expected: PASS; only V1 exact agent IDs allow root observation and V2 permits no target field.

- [ ] **Step 5: Commit**

~~~~bash
git add src/codex_router/hook.py tests/test_runtime_operator_contract_v31.py tests/test_v31_exact_root_hook_identity.py
git commit -m "feat: support V1 observe-only wait surface"
~~~~

Commit boundary: Support V1 observe-only wait surface.

### Task 5: Split Gen1 readiness from persistent follow-up availability

**Files:**
- Modify: src/codex_router/global_install_adapter.py
- Modify: tests/test_primary_capability_v3.py, tests/test_global_install.py, tests/test_runtime_operator_contract_v31.py

**Interfaces:**
- Consumes: explicitly supplied runtime_capabilities only.
- Produces: native_surface_compatibility(runtime_capabilities)->NativeSurfaceCompatibility with primary_gen1_readiness (PASS|INCOMPATIBLE|UNKNOWN) and persistent_followup_availability (AVAILABLE|UNAVAILABLE|UNKNOWN).

- [ ] **Step 1: Write the failing test**

~~~~python
def test_v1_gen1_ready_and_followup_unavailable_are_independent(self) -> None:
    value = native_surface_compatibility({
        "sideband_structured_k1_staging": True,
        "multi_agent_v1__spawn_agent": True,
        "followup_task": False,
    })
    self.assertEqual(value.primary_gen1_readiness, "PASS")
    self.assertEqual(value.persistent_followup_availability, "UNAVAILABLE")

def test_incomplete_inventory_is_unknown(self) -> None:
    value = native_surface_compatibility({"router_stage_k1_exec": True})
    self.assertEqual(value.primary_gen1_readiness, "UNKNOWN")
    self.assertEqual(value.persistent_followup_availability, "UNKNOWN")
~~~~

Cover full V2 PASS/AVAILABLE, explicit unsupported spawn INCOMPATIBLE, explicit negative dominating aliases, pure no-mutation behavior, and a Hook test proving classification does not authorize a lifecycle operation. The classifier consumes only explicit current runtime-surface inventory: it must not require or invent a root/Hook capability telemetry bit.

- [ ] **Step 2: Run test to verify it fails**

Run: python -m unittest tests.test_primary_capability_v3 tests.test_global_install tests.test_runtime_operator_contract_v31 -v

Expected: FAIL because current readiness is V2-only and conflates follow-up.

- [ ] **Step 3: Write minimal implementation**

~~~~python
@dataclass(frozen=True)
class NativeSurfaceCompatibility:
    spawn_profile: str | None
    primary_gen1_readiness: str
    persistent_followup_availability: str
    reason_code: str

def native_surface_compatibility(runtime_capabilities: Any) -> NativeSurfaceCompatibility:
    evidence = _collect_explicit_runtime_inventory(runtime_capabilities)
    spawn = _classify_supported_spawn_profile(evidence)
    stage = evidence.sideband_structured_k1_staging
    gen1 = _classify_gen1_readiness(stage=stage, spawn=spawn, evidence=evidence)
    followup = _classify_persistent_followup(evidence)
    return NativeSurfaceCompatibility(spawn.profile, gen1, followup, evidence.reason_code)
~~~~

Define the three private classifier helpers in this task: `_collect_explicit_runtime_inventory` records only supplied positive/negative facts, `_classify_supported_spawn_profile` returns the exact supported V1/V2 profile or unknown/incompatible, and `_classify_persistent_followup` returns `AVAILABLE`, `UNAVAILABLE`, or `UNKNOWN`. Treat a proven V1 spawn plus explicit sideband structured K1 staging as Gen1-ready. `primary_gen1_readiness` is non-authorizing surface readiness only; every Hook call retains its independent authority checks. Never infer UNAVAILABLE from omission in incomplete inventory; explicit negative dominates aliases. Keep the classifier pure and keep evidence telemetry free of K1 capability/token values.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m unittest tests.test_primary_capability_v3 tests.test_global_install tests.test_runtime_operator_contract_v31 -v

Expected: PASS; classifier output has no authority effect.

- [ ] **Step 5: Commit**

~~~~bash
git add src/codex_router/global_install_adapter.py tests/test_primary_capability_v3.py tests/test_global_install.py tests/test_runtime_operator_contract_v31.py
git commit -m "feat: split Gen1 readiness from followup availability"
~~~~

Commit boundary: Split Gen1 readiness from followup availability.

### Task 6: PRIMARY Gen2 unavailable boundary

**Files:**
- Modify: src/codex_router/global_install_adapter.py
- Modify: tests/test_runtime_operator_contract_v31.py, tests/test_k1_sideband_v31.py, tests/test_v31_turn_boundary_mode.py

**Interfaces:**
- Consumes: PRIMARY's explicitly supplied complete App inventory and the pure availability classification before Gen2 staging.
- Produces: BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE from PRIMARY/readiness before Gen2 staging; Hook legacy behavior remains independently fail-closed.

- [ ] **Step 1: Write the failing test**

~~~~python
def test_primary_blocks_known_unavailable_followup_before_gen2_staging(self) -> None:
    decision = self.primary_gen2_readiness(explicit_inventory_without_followup())
    self.assertEqual(decision["code"], "BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE")
    self.assertIsNone(self.snapshot().authority_packet_wire)

def test_legacy_denials_do_not_consume_an_already_staged_gen2(self) -> None:
    before = self.stage_generation_two()
    self.assert_legacy_forbidden("send_input", {"target": before.luna_agent_id, "message": "opaque"})
    self.assert_legacy_forbidden("resume_agent", {"target": before.luna_agent_id})
    self.assert_queue_only("send_message", {"target": before.luna_agent_id, "message": "opaque"})
    self.assertEqual(self.snapshot().authority_packet_wire, before.authority_packet_wire)

def test_root_supersession_clears_unused_stage(self) -> None:
    self.stage_generation_two()
    self.new_root_turn()
    self.assertIsNone(self.snapshot().authority_packet_wire)
~~~~

Cover supported exact-target followup atomic admission, legacy-forbidden resume/send_input, QueueOnly send_message, no replacement spawn, no local fallback, and existing root-supersession cleanup. A send_input attempt alone must not be relabeled as follow-up unavailability.

- [ ] **Step 2: Run test to verify it fails**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_k1_sideband_v31 tests.test_v31_turn_boundary_mode -v

Expected: FAIL because PRIMARY/readiness has no pre-stage unavailable boundary.

- [ ] **Step 3: Write minimal implementation**

Implement the pre-stage PRIMARY/readiness result in `global_install_adapter.py` only when explicit complete inventory proves `persistent_followup_availability == "UNAVAILABLE"`. Do not add a Hook compatibility source, Hook inventory branch, Hook config, or journal field. Hook continues its existing exact behavior: send_input and resume_agent are explicit legacy-forbidden denials, send_message is QueueOnly, and exact-target followup_task uses existing staged admission. If Gen2 was staged earlier, legacy calls do not consume it or advance generation; existing root supersession/cancellation/retirement clears unused authority.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_k1_sideband_v31 tests.test_v31_turn_boundary_mode tests.test_luna_control_v3 -v

Expected: PASS; PRIMARY blocks known-unavailable Gen2 before staging, and only supported exact-target followup consumes a previously staged Gen2.

- [ ] **Step 5: Commit**

~~~~bash
git add src/codex_router/global_install_adapter.py tests/test_runtime_operator_contract_v31.py tests/test_k1_sideband_v31.py tests/test_v31_turn_boundary_mode.py
git commit -m "feat: fail closed when persistent followup is unavailable"
~~~~

Commit boundary: Enforce the PRIMARY followup-unavailable boundary.

### Task 7: Rendered PRIMARY/install compatibility

**Files:**
- Modify: src/codex_router/global_install_adapter.py
- Modify: tests/test_global_install.py, tests/test_global_self_test.py, tests/test_runtime_operator_contract_v31.py

**Interfaces:**
- Consumes: generated protected K1_STAGE_COMMAND prefix, native compatibility classification, and disposable-home installer fixtures.
- Produces: PRIMARY guidance for stage-k1-fields plus exact V1/V2 schemas and no legacy Gen2 fallback.

- [ ] **Step 1: Write the failing test**

~~~~python
def test_primary_contract_uses_structured_staging_not_model_wire_assembly(self) -> None:
    rendered = AGENTS_BLOCK_V3
    self.assertIn("stage-k1-fields", rendered)
    self.assertNotIn("build_luna_packet", rendered)
    self.assertNotIn("[CODEX_ROUTER_PACKET_V3_1]", rendered)

def test_prefix_contract_does_not_claim_runtime_interpreter_attestation(self) -> None:
    self.assertIn("protected prefix", AGENTS_BLOCK_V3)
    self.assertNotIn("cryptographically attests the Python interpreter", AGENTS_BLOCK_V3)
~~~~

Cover deterministic prefix rendering, explicit V1/V2 guidance, no send_input/resume_agent/send_message fallback, redacted telemetry, and disposable install/self-test isolation from live ~/.codex.

- [ ] **Step 2: Run test to verify it fails**

Run: python -m unittest tests.test_global_install tests.test_global_self_test tests.test_runtime_operator_contract_v31 -v

Expected: FAIL because current contract directs PRIMARY to build and pipe a K1 wire.

- [ ] **Step 3: Write minimal implementation**

~~~~text
Use the injected stage-k1-fields protected command prefix verbatim.
Append only packet-id, objective, working-directory, scope, A1, success, and stop options.
Do not build K1 wire bytes, JSON, a prefix, a shell pipeline, or an alternate control command.
~~~~

Render exact V1 `agent_type=luna_worker` plus `fork_context=false` or omission, collapsed V1's required explicit false, and V2 task_name=luna_worker, agent_type=luna_worker, fork_turns=none. State that V2 wait accepts optional timeout_ms only and has no targets field. Explain deterministic prefix contract validation without claiming cryptographic/runtime attestation of the interpreter path.

- [ ] **Step 4: Run test to verify it passes**

Run: python -m unittest tests.test_global_install tests.test_global_self_test tests.test_runtime_operator_contract_v31 tests.test_primary_capability_v3 -v

Expected: PASS; all installer evidence remains disposable and redacted.

- [ ] **Step 5: Commit**

~~~~bash
git add src/codex_router/global_install_adapter.py tests/test_global_install.py tests/test_global_self_test.py tests/test_runtime_operator_contract_v31.py
git commit -m "feat: render current-runtime compatibility contract"
~~~~

Commit boundary: Render current-runtime compatibility contract.

### Task 8: Full regression and package verification

**Files:**
- Modify: no source file unless a listed regression fails; return to the owning task’s RED/GREEN cycle for a narrow correction.
- Test: test_runtime_operator_contract_v31, K1 sideband, turn-boundary, recovery, global install/adapter, and full unit suites.

**Interfaces:**
- Consumes: Tasks 1-7 and existing package/install harnesses.
- Produces: local reproducible evidence only; no live installation or agent execution.

- [ ] **Step 1: Write the final missing regression only if necessary**

~~~~python
def test_no_legacy_operation_dispatches_k1(self) -> None:
    self.assert_no_k1_dispatch_via("send_input")
    self.assert_no_k1_dispatch_via("resume_agent")
    self.assert_queue_only("send_message")
~~~~

If Tasks 1-7 already prove this, do not duplicate behavior. If it fails, add one focused RED assertion naming the actual existing seam, then complete that owner task’s GREEN cycle.

- [ ] **Step 2: Run focused regressions**

Run: python -m unittest tests.test_runtime_operator_contract_v31 tests.test_k1_sideband_v31 tests.test_v31_turn_boundary_mode tests.test_v31_quarantined_recovery tests.test_global_install tests.test_primary_capability_v3 -v

Expected: PASS with no capability, full K1 wire, native opaque message, or live-home material in output fixtures.

- [ ] **Step 3: Run complete local/package verification**

~~~~bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
python -m codex_router run --adapter-mode fake --task "FIX5 offline adapter smoke"
DIST="$(mktemp -d /tmp/codex-router-fix5-dist.XXXXXX)"
VENV="$(mktemp -d /tmp/codex-router-fix5-wheel-venv.XXXXXX)"
python -m build --outdir "$DIST"
python -m venv "$VENV"
"$VENV/bin/pip" install "$DIST"/*.whl
(cd /tmp && "$VENV/bin/python" -m codex_router global-self-test --codex-home /tmp/codex-router-fix5-disposable-home)
gitleaks detect --source . --no-git --redact
~~~~

Build into the fresh `DIST` directory, install only the exact wheel produced there into the fresh `VENV`, and run the self-test from outside the repository using `"$VENV/bin/python"`. Do not use source `python -m codex_router`, do not glob repository `dist/`, and never substitute live ~/.codex.

- [ ] **Step 4: Audit exact GitHub reality after separately authorized pushes**

~~~~bash
git fetch origin --prune
git rev-parse HEAD
git rev-parse origin/hardening/native-luna-safety-v2
gh pr view 8 --repo EthanSangSSS/codex-router --json state,isDraft,mergedAt,headRefOid,url
~~~~

Expected: pushed exact head equals PR head; PR remains OPEN, Draft, and unmerged. Do not mark ready or merge.

- [ ] **Step 5: Commit only a necessary regression correction**

~~~~bash
git add tests/test_runtime_operator_contract_v31.py tests/test_k1_sideband_v31.py tests/test_v31_turn_boundary_mode.py tests/test_v31_quarantined_recovery.py tests/test_global_install.py tests/test_primary_capability_v3.py
git commit -m "test: verify runtime compatibility regression contract"
~~~~

Commit boundary: Full regression/package verification; omit this commit when Task 8 adds no files.

## Plan Self-Review

- All amended requirements map to Tasks 1-7: structured staging with duplicate-singleton rejection, exact names and immutable match type, surface-profile-aware V1/V2 schemas, V1 agent-ID-only wait with V2 timeout-only semantics, no V1 list aliases, independent non-authorizing Gen1/follow-up evidence, PRIMARY-only no-followup boundary, and narrow protected-prefix language.
- Task 8 retains parser, target, recovery, package, and hygiene guarantees.
- Every task supplies exact files, interfaces, RED before GREEN, a focused verification command, and a reviewable commit boundary.
- No task adds journal state, a control plane, live ~/.codex mutation, Router reinstallation, or live agent testing.
- primary_gen1_readiness and persistent_followup_availability originate in Task 5 and are consumed by PRIMARY/readiness and rendered guidance in Tasks 6-7, never by Hook inventory/state.
