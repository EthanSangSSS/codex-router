# Runtime Compatibility Layer Design

Status: approved direction, ready for human review

Date: 2026-08-19

Target branch: `hardening/native-luna-safety-v2`

Design base: `90c409d5fe8adf603fcd6104afd73ec088fbbcd8`

Related PR: #8

Approved approach: **Approach B — current-runtime compatibility layer**

## 1. Problem statement

The K1 sideband architecture is sound, but the installed PRIMARY contract assumes a native collaboration surface that the current Codex App does not expose consistently.

The authority model remains:

```text
PRIMARY                         = current Codex App/root agent
EXECUTOR                        = one persistent Router-managed Luna
canonical K1 plaintext          = authoritative control plane
native collaboration message   = trigger/data plane only
first executor tool attempt     = denied while Router injects canonical K1
```

The compatibility defects are at the runtime boundary:

1. PRIMARY must currently author a shell pipeline that builds a canonical K1 wire and streams it to `stage-k1`. A valid policy instruction does not make that multi-step serialization reliable on the first attempt.
2. Router requires the V2 `task_name`/`agent_type`/`fork_turns` spawn shape even when the App exposes the V1 `agent_type`/`fork_context` shape.
3. Hook tool-name canonicalization recognizes selected direct/current aliases but does not parse the observed `multi_agent_v1` namespace or the Hook-visible collapsed form reliably.
4. The installed policy assumes a persistent `followup_task` transport even when the current App exposes no compatible follow-up operation.

This amendment adds a narrow compatibility layer. It does not replace the authority design in [`2026-08-19-k1-control-plane-sideband-design.md`](./2026-08-19-k1-control-plane-sideband-design.md). Where the two documents overlap, the sideband design remains authoritative for K1, generation, identity, handshake, journal, and retirement semantics; this document governs only runtime staging and native-tool compatibility.

## 2. Production evidence

An isolated runtime diagnostic on the target App produced the following direct evidence.

### Generation 1 staging

The first stage attempt invoked `stage-k1` without a canonical wire on stdin:

```text
GEN1_STAGE_FIRST_ATTEMPT=FAIL
GEN1_STAGE_FIRST_USED_BUILDER=NO
GEN1_STAGE_FIRST_ERROR=Luna packet prefix is invalid
```

Independent recovery attempts proved that the installed `codex_router.protocol.build_luna_packet` path can stage generation 1 and generation 2 successfully. The defect is therefore PRIMARY first-attempt reliability, not the canonical builder, parser, capability verifier, or journal transition.

### Native spawn

The runtime exposed:

```text
multi_agent_v1__spawn_agent
```

The first call supplied:

```text
agent_type
fork_context
message
```

Router denied admission because it required the V2-only `task_name` and `fork_turns` fields. After adapting the call to Router's expected fields, one Luna was created. This proves the downstream reservation/binding path can work once the native schema is normalized.

### Executor handshake

The first-tool handshake passed unchanged:

```text
FIRST_PROBE=DENIED_WITH_K1
FIRST_TOOL_HANDSHAKE=PASS
SECOND_SAME_TURN_PWD=PASS
```

The executor handshake is not part of FIX5.

### Wait and follow-up

The App exposed:

```text
multi_agent_v1__wait_agent
```

The Hook observed/canonicalized it as `multi_agent_v1wait_agent` and denied it as an unknown lifecycle operation. This is a namespace-normalization failure.

Generation 2 structured authority could be staged, but the runtime exposed no supported `followup_task` transport:

```text
FOLLOWUP_RUNTIME_TOOL_NAME=NONE
FOLLOWUP_RESULT=TOOL_NOT_EXPOSED
```

No `send_input`, `resume_agent`, replacement spawn, or local PRIMARY fallback is an acceptable substitute.

## 3. Root causes

### 3.1 Model-serialized staging

The current rendered PRIMARY policy asks the model to assemble two programs and an exact byte stream:

```text
build_luna_packet stdout | stage-k1 stdin
```

The existing implementation correctly rejects missing, malformed, or noncanonical wire input. The reliability problem is placing byte-exact wire construction and shell composition in model-authored control flow.

### 3.2 Spawn schema conflation

The Hook has one internal spawn admission shape and assumes it is the native shape. V1 and V2 encode no-history spawning differently:

```text
V1: agent_type=luna_worker, fork_context=false
V2: task_name=luna_worker, agent_type=luna_worker, fork_turns=none
```

Requiring V2-only fields on a V1 surface makes a safe native call impossible without passing fields the native schema does not expose.

### 3.3 Fragile tool-name aliases

The current exact alias map covers `collaboration...` labels but not explicit `multi_agent_v1__...` labels or the observed separator-collapsed Hook label. Generic punctuation stripping would be unsafe because it could turn an unknown lifecycle operation into an authorized one.

### 3.4 Follow-up availability assumed rather than classified

The policy treats `followup_task` as universally present. On a Gen1-only native surface, that assumption either strands staged generation 2 or pressures PRIMARY toward a forbidden legacy substitute.

## 4. Goals and non-goals

### Goals

FIX5 must:

- make K1 staging a single Router-owned structured operation;
- keep `build_luna_packet` as the only canonical K1 serializer;
- preserve strict `parse_luna_packet` handling for all wire input;
- distinguish supported V1 and V2 spawn schemas explicitly;
- normalize exact supported lifecycle names without generic name munging;
- make wait/list operations root-only and observe-only;
- expose a fail-closed Gen2 availability result when no compatible follow-up exists;
- retain one persistent bound Luna whenever the runtime provides a compatible follow-up transport;
- render a PRIMARY contract that can succeed mechanically on its first staging attempt.

### Non-goals

FIX5 does not change:

- the K1 prefix, schema, canonical JSON encoding, or parser strictness;
- stage-capability claims, HMAC construction, or verification;
- generation monotonicity or idempotency rules;
- `authority_packet_wire`, `active_packet_id`, or `active_child_turn_id` semantics;
- first-tool deny/inject/retry behavior;
- root-turn supersession, cancellation, settlement, retirement, or recovery architecture;
- QueueOnly `send_message`;
- the prohibition on `send_input` and `resume_agent` advancing K1;
- descendant or nested-Codex prohibitions;
- A1 capability semantics;
- the five installed Hook events;
- Hook trust or global-install transaction architecture;
- live-activation gate definitions.

FIX5 does not add a daemon, service, socket, MCP server, polling supervisor, shell parser, workspace transaction layer, broad tool firewall, or second control plane.

## 5. Compatibility model

The compatibility layer separates three concepts that must not be conflated:

```text
raw runtime tool name  -> exact string received or reported by the App
native surface profile -> supported version/schema contract
canonical operation    -> Router lifecycle operation
```

The Hook uses a pure, table-driven normalizer with this immutable result:

```python
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
```

This descriptor is ephemeral. It is recomputed for each Hook event and is not added to the Luna journal. `tool_use_id` remains the cross-event spawn correlation identity.

Supported surface profiles are:

- `direct_v2`: direct V2 function names and the strict V2 spawn schema;
- `collaboration_v2`: existing current-App `collaboration...` aliases and the strict V2 spawn schema;
- `multi_agent_v1`: the observed V1 namespace/schema;
- `collapsed_v1_spawn`: only the narrowly observed case where the App reports canonical `spawn_agent` but the input is unambiguously V1.

Unknown names, unknown versions, ambiguous schemas, and hybrid V1/V2 inputs fail closed before any lifecycle state transition.

No normalizer may authorize by deleting punctuation, removing arbitrary namespace text, using suffix-only matching, or accepting every name ending in `_agent`.

The adapter adds one pure classifier with an exact internal API:

```text
NativeSurfaceCompatibility(
    spawn_profile,
    primary_gen1_readiness,
    persistent_followup_availability,
    reason_code,
)
```

It trusts only explicitly supplied current-runtime tool/capability inventory; Router CLI must not claim to independently know the App inventory when no such evidence was supplied. Missing or incomplete evidence is `UNKNOWN`, never inferred as unavailable merely because a tool was not observed. An explicit negative dominates aliases.

The classifier produces two independent readiness dimensions:

- `primary_gen1_readiness` is `PASS`, `INCOMPATIBLE`, or `UNKNOWN`. It is non-authorizing runtime-surface readiness only: `PASS` requires explicit evidence of sideband structured K1 staging availability and one explicitly supported native spawn profile (including a proven safe `multi_agent_v1` profile). It does not add a root/Hook telemetry bit or grant Hook authority.
- `persistent_followup_availability` is exactly `AVAILABLE`, `UNAVAILABLE`, or `UNKNOWN`. It describes only whether a supported persistent follow-up transport is evidenced, not whether a safe Gen1 spawn can run.

For example, a supported V1 spawn plus available sideband staging and no supported follow-up is `primary_gen1_readiness=PASS` and `persistent_followup_availability=UNAVAILABLE`; a complete proven V2 surface is `PASS` and `AVAILABLE`. The classifier is pure evidence classification: it does not mutate installation config or journal state and it does not authorize a Hook event. Every Hook event independently validates its exact native name/profile, input schema, actor identity, current root turn, target where applicable, and Router state.

## 6. Deterministic staging interface

### 6.1 Public interface

Add one Router-owned command:

```text
router stage-k1-fields
```

The Hook-generated protected command prefix contains the existing authority arguments:

```text
router stage-k1-fields
  --installation-dir <managed installation>
  --session-id <current session>
  --root-turn-id <current root turn>
  --capability <current one-time capability>
```

PRIMARY appends only structured packet data:

```text
--packet-id <text>
--objective <text>
--working-directory <absolute path>
[--intended-write-scope <path>]...
[--explicit-side-effect-authorization <A1 category>]...
[--success-criterion <text>]...
[--stop-condition <text>]...
```

The generation is not model-supplied. The helper reads the current snapshot and derives `packet_generation + 1`; the existing locked staging transition independently verifies that the capability and generated wire target exactly that generation. A concurrent generation change therefore fails closed rather than being repaired.

Repeated options preserve input order. Omitting a repeated option represents an empty list. The CLI rejects duplicate singleton fields, unknown options, malformed UTF-8, over-limit values, non-absolute working directories, and unsupported A1 categories using existing bounded error conventions.

The interface accepts no `wire`, `packet_json`, `prefix`, or arbitrary JSON argument. It therefore cannot accept noncanonical K1 JSON and then normalize or repair it.

### 6.2 Internal flow

The command performs exactly this flow:

```text
validate bounded structured fields
    -> derive expected next generation from current snapshot
    -> codex_router.protocol.build_luna_packet(...)
    -> existing luna_control.stage_authority_packet(...)
    -> bounded JSON result
```

`build_luna_packet` remains the only serializer. `stage_authority_packet` remains the only authority state transition. `parse_luna_packet` still validates the generated wire inside the existing transition.

The helper must not catch a builder/parser error and retry with altered data. It must not sort, strip, coerce, infer, or repair user packet fields beyond the validation already performed by `build_luna_packet` and existing A1 validators.

### 6.3 Existing `stage-k1` compatibility

The existing command remains available and unchanged:

```text
router stage-k1 <canonical wire on stdin>
```

It continues to reject missing prefixes, malformed/noncanonical JSON, stale generations, replayed capabilities, and different duplicate packets. Existing callers and focused parser tests remain valid. The new PRIMARY policy uses `stage-k1-fields`; it does not weaken or silently redirect `stage-k1`.

### 6.4 Capability handling

The stage capability remains the current root-turn/task-epoch/generation-bound token. The Hook still creates it and embeds it only in the protected `K1_STAGE_COMMAND` prefix supplied as developer context.

PRIMARY does not transcribe the token into packet fields, packet content, native messages, reports, or telemetry. Router command output and errors never echo argv values or the capability. Diagnostic representations must replace it with `<REDACTED>`.

This tranche does not claim to hide the injected command from host-level App/tool-call auditing; that visibility already exists in the approved sideband design. Its security bound is the capability's one-time, root/session/epoch/generation scope plus non-disclosure by Router-generated output. Eliminating host-level command trace visibility would require a new secret-delivery channel and is not part of FIX5.

### 6.5 Preserving `K1_STAGE_COMMAND` authority

`K1_STAGE_COMMAND` changes only in its subcommand selection from `stage-k1` to `stage-k1-fields`. The Hook continues to render the interpreter path, installation directory, session id, root turn id, and capability. PRIMARY must use that protected prefix verbatim and may append only the documented packet-data options.

Installer/self-test validation compares the rendered protected prefix exactly and separately validates the allowed packet option schema. A model-authored or altered interpreter, installation path, session, root turn, capability, alternate subcommand, shell pipeline, or extra control option is unsupported and must fail the operator-contract tests. This is deterministic rendering and contract validation, not a cryptographic or runtime attestation of the rendered Python interpreter path. Runtime authority remains based on managed-installation identity, the installation secret, the session/root/task-epoch/generation-bound capability, and existing state-transition validation.

## 7. Native tool normalization

### 7.1 Exact accepted names

The normalizer uses an explicit table. The minimum accepted mappings are:

| Raw or Hook-visible name | Surface | Canonical operation |
|---|---|---|
| `spawn_agent` | schema-discriminated direct/V1 compatibility | `spawn_agent` |
| `collaborationspawn_agent` | `collaboration_v2` | `spawn_agent` |
| `multi_agent_v1__spawn_agent` | `multi_agent_v1` | `spawn_agent` |
| `multi_agent_v1spawn_agent` | `multi_agent_v1` collapsed label | `spawn_agent` |
| `wait_agent` | `direct_v2` | `wait_agent` |
| `collaborationwait_agent` | `collaboration_v2` | `wait_agent` |
| `multi_agent_v1__wait_agent` | `multi_agent_v1` | `wait_agent` |
| `multi_agent_v1wait_agent` | `multi_agent_v1` collapsed label | `wait_agent` |
| `list_agents` | `direct_v2` | `list_agents` |
| `collaborationlist_agents` | `collaboration_v2` | `list_agents` |
| `followup_task` | `direct_v2` | `followup_task` |
| `collaborationfollowup_task` | `collaboration_v2` | `followup_task` |
| `send_message` | `direct_v2` | `send_message` |
| `collaborationsend_message` | `collaboration_v2` | `send_message` |
| `interrupt_agent` | `direct_v2` | `interrupt_agent` |
| `collaborationinterrupt_agent` | `collaboration_v2` | `interrupt_agent` |
| `close_agent` | `direct_v2` | `close_agent` |

The table does not claim that every listed name is exposed by every runtime. It only defines how a call is interpreted when that exact name reaches the Hook.

Legacy `send_input` and `resume_agent`, including exact `multi_agent_v1` names/collapsed labels, normalize only to explicit forbidden legacy operations. They never normalize to `followup_task`.

### 7.2 Unknown names

Any unlisted collaboration namespace, malformed separator form, suffix variation, version other than an explicitly supported profile, or lifecycle-looking name returns the existing fail-closed unknown-lifecycle decision. Ordinary non-lifecycle tools are unaffected.

### 7.3 Identity ordering

Normalization determines whether an event is lifecycle-sensitive, but it does not establish actor authority. The existing checks still run in this order:

1. validate Hook event identity fields;
2. normalize the exact tool surface/name/schema;
3. require the current root actor and current root turn for parent lifecycle operations;
4. reject child/ambiguous/unbound identities;
5. authorize the exact current Luna target where the operation has a target;
6. perform the existing atomic spawn/follow-up/cleanup transition.

Normalization cannot bypass `_root_lifecycle_identity`, exact bound-Luna checks, or child lifecycle prohibition.

## 8. V1 and V2 spawn semantics

### 8.1 V1 spawn

For exact `multi_agent_v1` names, Router admits only this security-relevant no-history shape:

```text
agent_type = luna_worker
fork_context = false
message = opaque transport trigger
```

The exact `multi_agent_v1` upstream contract proves that `fork_context=false` and omission both request no history. Therefore exact `multi_agent_v1` accepts either an explicit `false` or omission, and denies `true`. This rule is selected by `surface_profile`, not by treating a missing value as false. When a raw namespace has already been collapsed to plain `spawn_agent`, omission is ambiguous and fails closed; `fork_context=false` is required to select `collapsed_v1_spawn`.

V1 rejects:

- `agent_type` missing or different;
- `fork_context=true`;
- V2-only `task_name` or `fork_turns` fields;
- hybrid V1/V2 security fields;
- an unknown or ambiguous input shape.

After validation, the adapter supplies the existing internal canonical reservation values:

```text
task_name = luna_worker
agent_type = luna_worker
fork_turns = none
```

Those values are internal admission data, not fabricated native V1 arguments. `tool_use_id` remains the reservation correlation key.

V1 `PostToolUse` may return `agent_id`/`nickname` rather than a V2 task path. The adapter may record the exact `agent_id` in the existing pending reservation, but it must not treat `nickname` as identity or invent a task path. `SubagentStart` with the same agent id and `agent_type=luna_worker` remains the final native binding evidence.

### 8.2 V2 spawn

Direct/current V2 spawn retains the existing strict contract:

```text
task_name = luna_worker
agent_type = luna_worker
fork_turns = none
message = opaque transport trigger
```

`fork_context` is not accepted in the V2 schema. Missing, malformed, or mixed fields fail closed.

### 8.3 Plain `spawn_agent` discriminator

When the App erases the V1 namespace before the Hook, plain `spawn_agent` is classified by an exact mutually exclusive schema:

- all three V2 fields and no `fork_context` -> `direct_v2`;
- `agent_type=luna_worker`, `fork_context=false`, no `task_name`, and no `fork_turns` -> `collapsed_v1_spawn`;
- every other combination -> ambiguous/unknown and denied.

This is explicit schema discrimination, not silent V1/V2 mixing.

## 9. Wait and observe semantics

`wait_agent` and `list_agents` remain observe-only. They do not require staged K1, consume `authority_packet_wire`, increment generation, start an executor turn, or change execution status.

They still require the current root actor/current root turn. Luna, another child, or an ambiguous actor cannot invoke them through Router authority.

For V1 `wait_agent` (`input_schema=v1_wait`):

- `targets` must be a bounded list of nonempty agent IDs;
- every target must be the exact current bound `luna_agent_id`; a canonical Luna task path is not a V1 wait target and fails closed;
- optional timeout fields are transport data and do not affect Router authority;
- an empty, malformed, or unrelated target list fails closed.

V1 and V2 wait schemas remain separate. V2 `wait_agent` has no target field: its only supported transport input is optional `timeout_ms`. A V2 wait that carries V1 `targets` is a schema mismatch and fails closed. This document defines no V2 exact-target wait contract.

`list_agents` has no work-dispatch authority. Its output is diagnostic inventory only and cannot establish completion, settlement, descendant absence, or executor identity without the existing corroborating Hook/state evidence.

The observed `multi_agent_v1wait_agent` label must normalize to `wait_agent` before lifecycle/actor checks. It must no longer fall into unknown-name denial merely because the App collapsed separators.

## 10. Generation 2 follow-up availability

### 10.1 Supported follow-up

Only exact `followup_task` and `collaborationfollowup_task` profiles are compatible in this tranche. Admission still requires:

- current root identity and root turn;
- exact current bound Luna target;
- idle or settled persistent executor;
- valid staged next-generation K1;
- existing atomic `admit_staged_followup` transition.

No native message content contributes authority.

### 10.2 No compatible follow-up

Runtime capability classification distinguishes:

```text
PERSISTENT_FOLLOWUP_AVAILABLE
PERSISTENT_FOLLOWUP_UNAVAILABLE
PERSISTENT_FOLLOWUP_UNKNOWN
```

These values are the `persistent_followup_availability` result of `native_surface_compatibility`. When PRIMARY has explicitly supplied, complete current-App inventory proving no supported `followup_task`, PRIMARY/readiness and the rendered PRIMARY contract return the exact reason code:

```text
BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE
```

It must do so before staging generation 2 whenever that explicit evidence is available. Hook.py receives no authoritative App inventory in this tranche: no runtime inventory is introduced into Hook configuration or journal, and Hook does not branch on `persistent_followup_availability`. This does not downgrade an otherwise proven Gen1 path: `primary_gen1_readiness=PASS` remains valid when `persistent_followup_availability=UNAVAILABLE`. Missing or incomplete inventory remains `UNKNOWN`, and an explicit negative dominates any alias. Gen1 may still complete, but Router must not claim persistent multi-generation capability.

`send_input`, `resume_agent`, `send_message`, another spawn, and local PRIMARY execution remain forbidden substitutes. A staged K1 does not change that result.

### 10.3 Already-staged generation 2

If generation 2 was staged before the follow-up surface became unavailable or before availability was classified:

- no generation is committed;
- `authority_packet_wire` is not consumed;
- no executor turn starts;
- `send_input` and `resume_agent` receive their existing explicit legacy-forbidden denials, and `send_message` receives its existing QueueOnly denial; none consumes the stage or proves that follow-up is unavailable;
- the same root turn may use the stage only if a supported follow-up surface becomes available and all existing checks pass;
- otherwise the next root-turn supersession clears the unused staged wire through the existing `set_current_root_turn` behavior.

No `send_input`, `resume_agent`, `send_message`, replacement Luna, or local PRIMARY fallback may consume that stage. No new cancel command, poison flag, packet history, or retirement path is introduced. Existing root supersession ensures an unused stage is not permanent. Cancellation/retirement continue to clear authority in their existing locked transitions.

## 11. Security invariants

FIX5 preserves these invariants:

1. Canonical K1 is the sole work authority.
2. `build_luna_packet` is the sole K1 serializer.
3. `parse_luna_packet` remains byte-strict and rejects noncanonical JSON.
4. Stage capabilities remain bound to session, current root turn, task epoch, and next generation.
5. Packet generation remains monotonic and commits only during admitted native dispatch.
6. Identical pending stage retry may remain idempotent; a different same-generation stage fails closed.
7. Native messages remain opaque and non-authoritative.
8. V1 and V2 schemas are mutually exclusive.
9. Unknown lifecycle names and shapes fail closed.
10. Parent lifecycle calls retain exact actor/root-turn attribution.
11. Spawn/follow-up target and reservation checks remain exact.
12. Wait/list are observation only.
13. `send_message` remains QueueOnly.
14. `send_input` and `resume_agent` never advance K1.
15. The first executor tool remains denied before canonical K1 injection.
16. Luna has no descendants and cannot start nested Codex.
17. No live activation gate is relaxed or inferred from configuration alone.

## 12. Failure semantics

| Condition | Required result | State effect |
|---|---|---|
| Structured field validation fails | bounded `invalid-input` | none |
| Capability/root/session/epoch/generation mismatch | existing fail-closed stage error | none |
| Builder rejects packet fields | bounded `invalid-input` | none |
| Manual/malformed wire sent to legacy `stage-k1` | existing parser error | none |
| Different packet already staged for generation | existing conflict | staged packet unchanged |
| Unknown lifecycle namespace/name | unknown lifecycle fail-closed | none |
| V1/V2 spawn shape ambiguous or hybrid | spawn schema fail-closed | staged K1 unchanged |
| V1 identity or no-fork constraint invalid | spawn identity fail-closed | staged K1 unchanged |
| Wait/list actor or target invalid | lifecycle identity/target denial | none |
| PRIMARY/readiness has complete explicit inventory proving no follow-up, before Gen2 staging | `BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` | no Gen2 stage is created |
| `send_input`/`resume_agent` attempted | explicit legacy denial | staged K1 unconsumed; generation unchanged |
| `send_message` used for K1 dispatch | existing QueueOnly denial | staged K1 unconsumed; generation unchanged |
| Supported follow-up targets another agent | existing exact-target denial | staged K1 unchanged |
| First executor tool under new generation | handshake retry denial + canonical K1 context | no tool side effect |

Errors and telemetry must never include the capability token, installation secret, full K1 wire, native opaque message, cookies, credentials, or unrelated input.

## 13. Migration and install implications

### Rendered PRIMARY contract

`global_install_adapter.AGENTS_BLOCK_V3` changes from a model-authored builder pipeline to:

1. use the exact injected `stage-k1-fields` protected command prefix;
2. append only structured packet fields;
3. require staging success before spawn/follow-up;
4. select the explicit native surface/schema actually exposed;
5. return `BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` when persistent follow-up is unavailable;
6. retain QueueOnly and legacy-operation prohibitions.

`global-status` compatibility evidence may include the selected non-sensitive `spawn_profile`, `primary_gen1_readiness`, `persistent_followup_availability`, and reason code only when runtime inventory was explicitly supplied. It must not persist or print K1 capabilities, packet wire, or opaque native messages. In the absence of supplied inventory, it reports unknown rather than claiming the Router CLI independently observed the App surface.

The rendered contract no longer instructs PRIMARY to import `build_luna_packet`, write Python serialization code, construct K1 prefixes/JSON, or create a shell pipeline.

### Compatibility retained

The following remain supported:

- legacy strict `router stage-k1` wire input;
- direct V2 `spawn_agent`/`followup_task`/`send_message`;
- existing `collaboration...` current-App aliases;
- current journal migration and recovery paths;
- the five-Hook installation;
- existing wheel/install/status/self-test transaction behavior.

### Installation boundary

Unit tests use disposable installation directories and must not mutate live `~/.codex`. A future implementation/release task may refresh the installed policy only after repository tests, wheel tests, disposable-home self-test, and separately authorized live activation steps pass.

This design phase does not reinstall Router or alter Hook trust.

## 14. Test matrix

Implementation must be test-driven. Add `tests/test_runtime_operator_contract_v31.py` for the production regression contract and extend focused protocol/CLI/Hook tests only where the behavior naturally belongs.

### A. Deterministic Gen1 staging

- Invoke `stage-k1-fields` with structured fields and no model-authored wire.
- Assert first invocation stages generation 1 and returns bounded packet id/generation evidence.
- Assert the stored wire equals `build_luna_packet` output for the same fields.

### B. Malformed/manual wire

- Preserve legacy `stage-k1` prefix and canonical JSON rejection.
- Assert no structured interface accepts a `wire`/`packet_json` escape hatch.
- Assert malformed structured fields are rejected rather than repaired.

### C. V1 spawn

- Exact `multi_agent_v1__spawn_agent` with `agent_type=luna_worker`, `fork_context=false` or omitted `fork_context`, and opaque message is admitted after valid staged Gen1.
- The collapsed V1 label and unambiguous V1 shape are admitted.
- PostToolUse `agent_id` is correlated without trusting nickname; matching `SubagentStart` binds the executor.

### D. V1 wrong/missing identity

- Missing/wrong `agent_type`, `fork_context=true`, ambiguous omission on collapsed plain name, V2-only fields, and hybrid shapes fail closed; collapsed V1 requires explicit `fork_context=false`.
- No failure consumes staged K1 or creates more than one reservation.

### E. V2 spawn

- Existing strict `task_name=luna_worker`, `agent_type=luna_worker`, `fork_turns=none` behavior remains green.
- V1-only `fork_context` is rejected on V2 names.

### F. V1 wait

- `multi_agent_v1__wait_agent` and `multi_agent_v1wait_agent` normalize to `wait_agent`.
- V1 current-root observation succeeds only for `targets=[exact luna_agent_id]`; a canonical Luna task path is denied for V1.
- V2 wait accepts only optional `timeout_ms`; carrying V1 `targets` on V2 fails closed.
- Direct `list_agents` and the existing `collaborationlist_agents` alias remain observe-only; the unproven V1 `list_agents` namespace forms fail closed.
- Generation, staged authority, active packet, and execution state remain unchanged.

### G. Unknown namespace/name

- Malformed separators, unknown versions, suffix tricks, and unlisted collaboration lifecycle names fail closed.
- Ordinary non-lifecycle tool names remain unaffected.

### H. Child/ambiguous lifecycle actor

- V1 and V2 lifecycle operations from Luna, another child, a stale root turn, mixed actor/agent fields, or incomplete identity fail closed before state mutation.

### I. No follow-up surface

- Explicit complete capability inventory with supported V1 spawn and no supported follow-up yields `primary_gen1_readiness=PASS` and `persistent_followup_availability=UNAVAILABLE`; PRIMARY/readiness reports `BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` before Gen2 staging.
- Missing or incomplete capability inventory yields `UNKNOWN`; absence from incomplete evidence is not evidence of unavailable.
- No `send_input`, `resume_agent`, `send_message`, replacement spawn, or local fallback advances generation; their Hook denials remain legacy-forbidden or QueueOnly rather than evidence of unavailable follow-up.
- An already-staged generation 2 remains unconsumed and is cleared by existing root supersession.

### J. Compatible follow-up

- Direct/current supported `followup_task` requires the exact bound Luna and a valid staged next generation.
- Existing atomic `admit_staged_followup` behavior and generation increment remain unchanged.

### K. First-tool handshake

- Existing first-tool deny + canonical K1 `additionalContext` + same-turn second-tool behavior remains unchanged for V1 and V2 spawn paths.
- The first tool has no side effect.

### L. Package/install renderer

- Installed PRIMARY text selects `stage-k1-fields` and contains no manual `build_luna_packet stdout | stage-k1 stdin` instructions.
- Protected-prefix rendering for interpreter/installation/session/root/capability remains exact; this does not claim runtime interpreter-path attestation.
- Capability values are absent from result/error telemetry fixtures.
- Disposable-home global install/self-test remains isolated from live `~/.codex`.

The focused suite must also retain existing K1 sideband, exact-root identity, turn-boundary, recovery, unit, compileall, diff-check, fake-adapter, and fresh-wheel coverage.

## 15. Live acceptance plan

Live acceptance is a later, separately authorized phase. It must use a fresh App task and preserve first-attempt evidence.

Minimum evidence:

```text
PRIMARY_STAGE_INTERFACE=stage-k1-fields
GEN1_STAGE_FIRST_ATTEMPT=PASS
GEN1_STAGE_FIRST_USED_MODEL_AUTHORED_WIRE=NO
PRIMARY_GEN1_READINESS=PASS

SPAWN_RUNTIME_SURFACE=<exact observed name>
SPAWN_SURFACE_PROFILE=<multi_agent_v1|direct_v2|collaboration_v2>
SPAWN_SCHEMA_MATCH=PASS
BOUND_EXECUTOR_ID=<observed id>

GEN1_FIRST_TOOL=DENIED_WITH_K1
GEN1_SECOND_SAME_TURN_TOOL=PASS
GEN1_SUBAGENT_STOP=PASS

WAIT_RUNTIME_SURFACE=<exact observed name>
WAIT_CANONICAL_OPERATION=wait_agent
WAIT_OBSERVE_ONLY=PASS

PERSISTENT_FOLLOWUP_AVAILABILITY=<AVAILABLE|UNAVAILABLE|UNKNOWN>
```

If follow-up is available, acceptance continues:

```text
GEN2_STAGE_FIRST_ATTEMPT=PASS
FOLLOWUP_TARGET=SAME_BOUND_EXECUTOR
GEN2_FIRST_TOOL=DENIED_WITH_K1
GEN2_SECOND_SAME_TURN_TOOL=PASS
GEN2_SUBAGENT_STOP=PASS
```

If follow-up is unavailable, acceptance requires:

```text
GEN2_RESULT=BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE
SEND_INPUT_FALLBACK=NO
RESUME_AGENT_FALLBACK=NO
REPLACEMENT_SPAWN=NO
LOCAL_PRIMARY_FALLBACK=NO
GENERATION_UNCHANGED=PASS
UNUSED_STAGE_CLEARED_ON_ROOT_SUPERSESSION=PASS
```

Live evidence records only raw tool name, selected surface profile, canonical operation, bounded decision code, packet id/generation, exact target identity, and state-transition result. It must redact capability/token material and must not record the full K1 wire or native opaque message.

Production success still requires all existing G1-G8 live activation gates. This compatibility tranche does not turn a successful Gen1 handshake into proof of complete activation.

## 16. Explicit guarantees and non-guarantees

### Guarantees when implemented and verified

- PRIMARY no longer authors K1 wire bytes or a builder/stager shell pipeline.
- Canonical K1 construction remains centralized in `build_luna_packet`.
- Manual/malformed wire remains strictly rejected.
- Supported V1 and V2 spawn schemas are explicit and mutually exclusive.
- The observed V1 wait labels normalize to observe-only `wait_agent`, whose V1 targets are exact bound agent IDs only.
- Gen1 readiness and persistent follow-up availability are independent evidence classifications; missing inventory remains unknown.
- Unknown lifecycle names/shapes remain fail-closed.
- Missing persistent follow-up produces an explicit blocked state with no legacy fallback.
- Existing authority, handshake, generation, target, QueueOnly, descendant, nested-Codex, cancellation, and retirement semantics remain intact.

### Not guaranteed by this tranche

- a V1 `followup_task` transport where the App exposes none;
- arbitrary future collaboration namespaces or schemas;
- pure-text executor-turn supervision;
- host-level secrecy of the App-injected command from App/tool-call audit traces;
- completion of G1-G8 live activation gates;
- executor replacement, cross-task reuse, or a second control plane;
- any production behavior before package/install refresh and fresh-session runtime acceptance are separately authorized and completed.

## Responsibility boundaries

Expected implementation ownership remains narrow:

```text
src/codex_router/protocol.py
    canonical builder/parser remain authoritative and preferably unchanged

src/codex_router/cli.py
    stage-k1-fields structured CLI and bounded result/error handling

src/codex_router/hook.py
    exact native-name normalization, schema discrimination, spawn result mapping,
    and observe-only wait/list; no App-inventory or follow-up-availability logic

src/codex_router/global_install_adapter.py
    rendered PRIMARY contract and runtime surface/followup capability classification

src/codex_router/luna_control.py / luna_control_recovery.py
    existing transitions reused; change only if a focused test proves a small
    compatibility seam is required, with no journal-format expansion

tests/test_runtime_operator_contract_v31.py
    A-L production regression contract
```

No new module or abstraction is justified unless the CLI or Hook implementation cannot remain focused and testable in its existing file.

## Design self-review resolution

- **Sideband contradiction:** none; this amendment preserves K1 authority and changes only how canonical input reaches the existing stage transition.
- **Accidental `send_input` authority:** explicitly prohibited in normalization, failure behavior, tests, and live acceptance.
- **Parser weakening:** none; legacy wire parsing is unchanged and the new interface accepts fields, not wire/JSON escape hatches.
- **Architecture expansion:** no service, daemon, supervisor, extra control plane, or new journal state.
- **V1/V2 ambiguity:** exact name table plus mutually exclusive schema discriminator; ambiguous/hybrid shapes fail closed.
- **V1 wait targets:** V1 accepts only the exact current `luna_agent_id`; a canonical task path is denied for V1.
- **Unproven V1 list aliases:** `multi_agent_v1__list_agents` and `multi_agent_v1list_agents` are not accepted by the normalizer and remain fail-closed unknown lifecycle names.
- **Readiness split:** proven safe V1 Gen1 readiness is independent from persistent follow-up availability; missing or incomplete inventory is unknown and explicit negative evidence dominates aliases.
- **Evidence provenance:** the compatibility classifier reads only explicitly supplied App tool/capability inventory and remains a pure, non-authorizing classification.
- **Protected prefix:** deterministic protected-prefix rendering is tested exactly without claiming runtime or cryptographic interpreter-path attestation.
- **Staged Gen2 cleanup:** availability is checked before staging when known; an already-staged wire remains unconsumed and is cleared by existing root supersession/cancellation/retirement.
- **Completeness:** command name, field schema, mappings, blocked code, state behavior, test matrix, and non-guarantees are explicit.
