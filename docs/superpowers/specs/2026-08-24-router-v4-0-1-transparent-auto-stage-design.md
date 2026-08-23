# Router V4.0.1 Transparent Auto-Stage Design

## Status

Revised architecture design for PR #10 (`hardening/router-v4-lease-core`). The B direction is retained, but implementation is not approved until this revision is reviewed and accepted.

This revision closes the P1 child-transport gap discovered by live V1 probing: a spawned Luna child must be allowed to receive the current generation's Router transport trigger without that child `UserPromptSubmit` being mistaken for a new root turn.

The objective is to make Luna globally usable from ordinary new Codex conversations without requiring PRIMARY to manually author K1 JSON, run a staging CLI, remember V1/V2 wire details, or follow a long protocol manual. Router keeps mechanical authority fencing and native Codex safety controls.

## Context

V4.0 established the durable generation-lease authority model, including monotonic generation fencing, current-root supersession, HMAC bootstrap capability, first-child actor binding, stale-worker rejection, and V1/V2 native spawn compatibility.

Live integration exposed a repeated failure pattern at the PRIMARY/model protocol boundary:

1. runtime exposed V1 while the model-visible contract assumed V2;
2. K1 request-file fields were serialized with incorrect JSON types;
3. V2 parent `PreToolUse` exposed an encrypted opaque spawn message, making plaintext comparison invalid;
4. current `v4_hook.py::_handle_v4_root_prompt` blocks every `UserPromptSubmit` carrying child identity before the spawn message can reach Luna, leaving the lease `STAGED` with only a spawn reservation and no bootstrap attempt.

The current repository head already fixes the V2 encrypted-message boundary by treating the V2 parent message as opaque and deferring authority grant until the first child capability bootstrap. V4.0.1 must additionally separate root `UserPromptSubmit` semantics from child transport `UserPromptSubmit` semantics so the current generation's prepared spawn message can reach Luna without granting authority early.

## Goals

1. Any new ordinary Codex conversation under the managed global Router installation can route substantive work to Luna without a user-visible Router ceremony.
2. PRIMARY does not manually construct K1 packets, request files, generation identifiers, capabilities, or spawn protocol fields.
3. Router mechanically derives and stages the canonical K1 from the native root `UserPromptSubmit` event and current authority state.
4. Router returns prepared V1 and V2 spawn payloads; PRIMARY only selects the actually exposed native spawn surface and forwards the corresponding payload unchanged.
5. A current-generation Luna child can receive the exact Router-generated spawn transport trigger without causing root reclassification, root-turn mutation, lease revocation, or restaging.
6. Child transport admission never grants worker authority; authority still begins only at the first exact capability-bound child `PreToolUse`.
7. Preserve V4.0 generation lease, bootstrap, actor binding, stale-worker fencing, and native sandbox/approval boundaries.
8. Ordinary work inside the exact native validated `cwd` can inspect/edit/test/debug/retry/verify without additional Router permission ceremony when the derived K1 allows writes.
9. External or persistent A1 side effects are authorized only when deterministically supported by the original root user request; Luna cannot broaden them.
10. Failure of transparent routing or child transport must not permanently poison the conversation or require manual journal repair.

## Non-goals

V4.0.1 does not implement:

- Stable Dispatcher, daemon, MCP control plane, or a second authority service.
- Worker pools, queueing, Luna reuse, or concurrency-limit bypass.
- Nested Codex or Luna descendants.
- Transactional rollback of a tool already admitted by native execution.
- Automatic merging, deployment, publication, outbound communication, or remote mutation without explicit user intent and normal platform controls.
- Generic child-prompt bypass. Only the current reserved Luna generation's exact Router transport trigger is admissible.
- Early worker binding from `UserPromptSubmit`, V1 `PostToolUse.agent_id`, or `SubagentStart` telemetry.
- Guaranteed compatibility for already-running historical conversations whose prompt/model context contains stale managed instructions. New conversations are the release-critical surface.

## Core principle

Protocol correctness moves from model-authored instructions into Router code.

The model-visible contract should state intent, not wire mechanics:

```text
Router is globally available.

For decision=route, use the prepared Luna spawn payload supplied by Router for the native spawn surface that is actually exposed.
For decision=direct or bypass, continue locally.
Do not construct Router leases, capabilities, K1 packets, or spawn fields manually.
Router owns authority fencing. PRIMARY owns planning/review/final response. Luna executes the current bounded user objective subject to native Codex controls.
```

Generation, HMAC, K1 schema, request-file format, V1/V2 field differences, child-transport admission, and encrypted parent-message handling remain internal implementation details.

## Architecture

### 1. Transparent root auto-stage

Root and child `UserPromptSubmit` must be discriminated before any root policy action.

For a root `UserPromptSubmit` with no child identity:

1. validate the native event as today;
2. classify prompt as `route`, `direct`, or `bypass` using the existing policy entry point;
3. revoke any prior current V4 lease for the same root session;
4. for `direct` or `bypass`, clear current root authority and return the existing local decision;
5. for `route`, establish the current root turn and create the next canonical Luna packet internally;
6. call the existing V4 lease staging primitive directly inside Router code;
7. derive the current bootstrap capability;
8. return one route context containing the staged generation plus prepared V1/V2 spawn payloads.

PRIMARY no longer writes a private request file or runs `stage-k1-fields` during the normal path.

The existing request-file/CLI staging implementation remains available as a compatibility/diagnostic path during V4.0.1, but it is removed from the normal model-visible contract and must not be required for new-conversation success.

### 2. Child `UserPromptSubmit` transport admission

A child `UserPromptSubmit` is transport-plane input, not a root user turn.

If validated `UserPromptSubmit` carries `agent_id` and `agent_type`, Router must branch to child-transport validation before `classify_prompt`, root supersession, current-root mutation, or auto-stage logic.

A child transport trigger is admissible only when all of the following are true:

1. `agent_type` is exactly `luna_worker`;
2. the child event belongs to a session with a current V4 snapshot;
3. `active_lease` exists and its status is exactly `STAGED`;
4. the current lease already has a non-empty `spawn_tool_use_id`, proving parent `PreToolUse` reserved the native spawn before child admission;
5. the lease has not already bound `worker_agent_id` or `child_turn_id`;
6. the lease's `root_turn_tag` still equals the snapshot's current root-turn tag, so a superseded generation cannot admit transport;
7. Router derives the exact current bootstrap capability from that active lease and regenerates the exact current `spawn_message`;
8. the child `prompt` is exactly the Router-generated current `spawn_message` for that lease. The comparison must not accept an old-generation message, a partial command, a user-authored lookalike, or an arbitrary child prompt.

For an admissible child transport trigger:

- return a non-blocking child `UserPromptSubmit` result;
- do not call `classify_prompt`;
- do not run objective sanitization;
- do not revoke, stage, restage, or otherwise mutate generation/root authority;
- do not bind or trust `agent_id` at this stage;
- do not inject canonical K1 at `UserPromptSubmit`;
- leave the lease `STAGED` and byte-for-byte authority-equivalent until the first child tool attempt.

The child prompt's bootstrap capability is a transport correlation credential, not work authority. The native `agent_id` remains untrusted/unbound until the exact first child `PreToolUse` presents the same current capability. Only then may Router atomically bind `worker_agent_id + child_turn_id`, mark the lease `ACTIVE`, and inject canonical K1.

This distinction is necessary because V2 does not provide an authoritative parent-spawn-result to child-`agent_id` correlation before first child tool use, and V1 `PostToolUse.agent_id` remains telemetry-only. Therefore V4.0.1 must not invent an agent-id binding at child `UserPromptSubmit` merely to make transport admission convenient.

Unknown, foreign, duplicate, or stale child prompts fail closed. This includes:

- `agent_type != luna_worker`;
- no current V4 session;
- no active lease;
- active lease not `STAGED`;
- no current spawn reservation;
- already-bound/ACTIVE generation;
- root turn no longer current;
- child prompt not exactly equal to the current generation's Router-generated `spawn_message`.

A rejected child transport event must not mutate the journal and must not reveal the bootstrap capability in diagnostics.

For V2 specifically, the existing encrypted-parent-message rule remains unchanged: parent `PreToolUse` may see only encrypted opaque message data, while child `UserPromptSubmit` is the first place where Router may require the actual current plaintext transport trigger. If a native surface wraps or transforms the child message rather than delivering the exact prepared message, that surface is not silently generalized; it requires a separately evidenced deterministic adapter.

### 3. Canonical K1 derivation

Router constructs the existing canonical eight-field Luna packet without changing the packet protocol:

- `packet_id`
- `generation`
- `objective`
- `working_directory`
- `intended_write_scope`
- `explicit_side_effect_authorizations`
- `success_criteria`
- `stop_conditions`

Derivation rules:

#### packet_id

Generate an opaque Router-owned identifier from current V4 authority material, such as the next generation plus a bounded digest/tag derived from the current root turn. Do not embed raw session IDs, user text, credentials, or filesystem paths.

#### objective

Use the original root user request after a single, explicit security pipeline. V4.0.1 must reuse the existing `codex_router.security.secure_web_payload` API as the redaction/blocking engine; it must not add a second secret scanner or a parallel regex policy for objective sanitization.

The exact objective pipeline is:

1. start from the already validated root `UserPromptSubmit.prompt`;
2. before security scanning, canonicalize only references to the exact validated native `cwd` (and descendants under that exact path boundary) into `<cwd>` plus the relative suffix, so a task such as `fix /Users/.../repo/src/x.py` can retain the meaningful `src/x.py` portion without propagating the private absolute path;
3. call `secure_web_payload({"objective": candidate})` exactly once as the objective sanitization authority;
4. if the result status is `allow` or `redacted`, require the returned payload to contain a string `objective` and use that returned string in canonical K1;
5. if the result status is `block`, the payload/objective shape is invalid, or sanitization otherwise cannot produce a valid objective, do not stage a lease and degrade to bounded PRIMARY-local execution for that turn.

No arbitrary absolute path outside validated `cwd` is canonicalized away before scanning; the existing security API decides whether it is redacted or blocked. The exact native `cwd` itself remains separately available as `working_directory` and is not copied from the sanitized objective.

The classifier may continue using its existing protected-material detection to choose the route reason, but that classification check is not a second objective transformation and must not determine the text placed in K1.

#### working_directory

Use the exact validated absolute `cwd` from the native root `UserPromptSubmit` event.

#### intended_write_scope

Derive write authority conservatively from the original root user request:

- explicit edit/implement/fix/create/delete/write intent -> `[validated_cwd]`, where `validated_cwd` is exactly the absolute `cwd` accepted from the native root `UserPromptSubmit` event;
- review/research/inspect/compare/plan-only intent without an explicit write verb -> `[]`;
- do not discover, infer, replace, or broaden `validated_cwd` to a Git root, repository root, parent directory, workspace container, or model-inferred path;
- never infer a write path outside exact validated `cwd` from model reasoning.

The phrase "workspace root" is not an authority term in V4.0.1. The write-scope authority boundary is the exact native validated `cwd` value.

Current packet/path enforcement remains authoritative. Native sandbox controls remain an additional boundary.

#### explicit_side_effect_authorizations

Default to `[]`.

Add an A1 category only when a deterministic positive-intent matcher finds an explicit user request for that class of external persistent mutation. Reuse the existing A1 category vocabulary:

- `git_push`
- `remote_collaboration_mutation`
- `deploy_release_publish`
- `outbound_user_communication`
- `cloud_resource_mutation`
- `system_level_install`
- `comparable_external_persistent_mutation`

Requirements for authorization inference:

- positive explicit intent only; ambiguity yields no category;
- reviewing or discussing a PR does not imply PR mutation;
- discussing deployment does not imply deployment;
- installing project-local dependencies does not automatically imply `system_level_install`;
- inferred categories are derived only from the original root user request, never Luna output, tool text, child memory, child transport prompt, or prior generations;
- existing `validate_packet_authorizations` remains the final schema gate.

#### success_criteria

Router-generated defaults, not model-generated JSON. At minimum:

1. satisfy the user's stated objective within the current packet scope;
2. verify material changes/results using available local evidence before reporting success.

The implementation may add deterministic task-specific criteria when they can be derived without semantic privilege broadening, but V4.0.1 does not require a general planning DSL.

#### stop_conditions

Router-generated defaults. At minimum:

1. stop before an external/persistent A1 side effect not explicitly authorized by the original root request;
2. stop before accessing unrelated data outside exact validated `cwd` unless the original request explicitly requires it and native platform controls permit it;
3. stop when the current generation lease is revoked/superseded or bootstrap/actor validation fails.

### 4. Prepared spawn payloads

The route context exposes prepared payloads rather than prose telling PRIMARY how to construct them.

Conceptual shape:

```json
{
  "decision": "route",
  "workflow": "generation_lease_v4_transparent",
  "generation": 12,
  "task_name": "luna_g12_a1b2c3d4",
  "prepared_spawn": {
    "v2": {
      "task_name": "luna_g12_a1b2c3d4",
      "agent_type": "luna_worker",
      "fork_turns": "none",
      "message": "<current bootstrap message>"
    },
    "v1": {
      "agent_type": "luna_worker",
      "fork_context": false,
      "message": "<current bootstrap message>"
    }
  }
}
```

Exact field names may be adjusted to fit current Hook context conventions, but the semantics are fixed:

- Router constructs all values;
- PRIMARY chooses only the actually exposed native transport;
- PRIMARY passes the selected payload unchanged;
- both V1 and V2 prepared payloads carry the same exact current-generation Router `spawn_message`;
- that exact message is the only child `UserPromptSubmit` transport trigger accepted for the current reserved generation;
- no static `luna_worker` task name substitutes for the generation-scoped V2 task name;
- V1 retains the current internal generation-scoped lease identity even though the native V1 tool does not carry `task_name`.

### 5. V2 encrypted parent boundary

Keep the current exact-head behavior:

- V2 parent `PreToolUse` treats `message` as encrypted opaque transport data;
- parent validation checks the current generation/task envelope and expected structural fields;
- parent spawn reservation never grants Luna authority;
- child `UserPromptSubmit` must receive and match the exact current plaintext Router `spawn_message` before transport is admitted;
- authority remains unbound until the child presents the exact current HMAC bootstrap capability on first `PreToolUse`;
- stale capability, stale agent, stale child turn, or superseded generation fails closed.

Do not reintroduce plaintext equality checks for the V2 parent message. Plaintext transport validation belongs at the child `UserPromptSubmit` boundary, where the actual current trigger must be delivered.

### 6. V1 transport

Keep V1 compatibility:

- exact `agent_type=luna_worker`;
- `fork_context=false` where the exposed schema supports/requires it;
- exact Router-generated bootstrap message;
- child `UserPromptSubmit` must receive and match that current message before transport admission;
- V1 `PostToolUse.agent_id` remains telemetry/correlation only and is not required for child transport admission because native ordering may place child startup before parent post-result processing;
- authority still starts at the first child capability bootstrap.

### 7. Luna executor contract

Luna keeps the current full-executor model after K1 appears:

Allowed within current K1 and native controls:

- inspect;
- research over locally available material;
- edit within exact derived write scope;
- build;
- test;
- debug;
- retry;
- verify.

Still mechanically forbidden:

- descendants;
- nested Codex;
- stale-generation work;
- authority recovery through `send_input`, `resume_agent`, polling, or old child identity;
- A1 side effects outside the current packet authorization set.

The managed Luna instructions should describe these invariants concisely and should not expose PRIMARY-side staging mechanics.

### 8. Minimal managed PRIMARY contract

Replace the current long V4 PRIMARY protocol block with a short contract centered on prepared spawn payloads.

Remove from PRIMARY-facing instructions:

- seven-field request-file construction;
- `K1_REQUEST_SCHEMA` authoring requirements;
- `K1_STAGE_COMMAND` execution;
- manual generation bookkeeping;
- manual bootstrap-capability handling;
- hand-authored V1/V2 spawn field rules beyond selecting the corresponding prepared payload;
- explanations of V2 encrypted-message implementation details unless needed for diagnostics.

Keep visible:

- route/direct/bypass meaning;
- prepared-payload selection rule;
- PRIMARY remains planner/reviewer/final authority;
- Router owns lease/fencing and child transport admission;
- native platform controls still apply.

## Failure semantics

### Auto-stage construction failure

If Router cannot safely construct the canonical K1 before lease creation:

- do not stage a lease;
- do not spawn Luna;
- keep the journal recoverable;
- return a bounded local/degraded decision so PRIMARY can continue without Router for that turn;
- expose a machine-readable reason suitable for diagnostics without leaking protected material.

### Child transport rejection

If a child `UserPromptSubmit` does not exactly match the current reserved generation's transport admission contract:

- fail closed for that child;
- do not classify it as a root prompt;
- do not revoke or restage anything;
- do not bind `agent_id`;
- do not expose the expected bootstrap capability/message in diagnostics;
- leave current authority state unchanged.

If a valid native spawn never delivers the expected child transport trigger, no bootstrap can occur and the lease remains `STAGED`; that is an acceptance failure, not a reason to weaken child admission. A later root turn may supersede the staged lease under existing V4 semantics.

### Stage persistence failure

If lease persistence or authority validation fails:

- fail closed for routed Luna execution;
- do not pretend the route succeeded;
- do not leave a pending spawn reservation;
- next root turn must be able to supersede/recover according to existing V4 rules once persistent state is valid.

### Native spawn failure

Keep existing V4 capacity semantics:

- no old authority is restored;
- failed native cleanup cannot become Router authority;
- a later root turn may supersede the attempt;
- no queue is introduced in V4.0.1.

## Security invariants retained

V4.0.1 must not weaken the following:

1. installation secret ownership/mode/symlink validation;
2. V4 journal atomicity and strict schema validation;
3. monotonic generation fencing;
4. root-turn HMAC binding;
5. child `UserPromptSubmit` is transport-only and cannot mutate root/generation authority;
6. only the current reserved generation's exact Router `spawn_message` is admitted as child transport;
7. child transport admission does not bind worker identity or inject K1;
8. first-child capability-bound actor binding remains the only authority grant;
9. exact current `agent_id + child_turn_id` fencing remains required after bind;
10. stale worker and stale/foreign child transport are denied;
11. late lifecycle telemetry cannot clear newer authority;
12. native sandbox/approval remains independent and authoritative;
13. A1 side effects cannot be invented by PRIMARY or Luna;
14. no descendant/nested-Codex control plane;
15. V3 state is not imported as V4 authority.

The design intentionally removes brittle model-side protocol rules; it does not remove platform safety controls or Router authority fencing.

## Implementation boundaries

Expected primary files:

- `src/codex_router/v4_hook.py`
  - discriminate root vs child `UserPromptSubmit` before root handling;
  - child transport admission for the current reserved generation;
  - root auto-stage orchestration;
  - route context with prepared spawn payloads;
  - preserve V1/V2 parent validation and first-child bootstrap authority.

- `src/codex_router/v4_request_staging.py`
  - refactor reusable packet/staging helpers out of CLI-only request-file flow;
  - preserve request-file path as compatibility/diagnostic surface.

- `src/codex_router/v4_install_adapter.py`
  - shorten managed PRIMARY contract;
  - keep concise Luna executor invariants;
  - update live-activation naming/status if needed.

Likely supporting files only if required by TDD:

- `src/codex_router/policy.py`
  - deterministic write-intent and A1 explicit-intent helpers, if they do not belong in a new focused V4 derivation module.

- `src/codex_router/security.py`
  - do not add a new scanner; consume existing `secure_web_payload` behavior as-is unless TDD reveals a defect in that existing API itself.

- a new focused module such as `src/codex_router/v4_auto_stage.py`
  - preferred for objective `cwd` canonicalization, K1 derivation, explicit-intent extraction, and prepared payload construction if putting those responsibilities in `v4_hook.py` would materially reduce clarity.

A narrowly scoped lease-control helper may be added if needed to keep child transport validation atomic and avoid duplicating snapshot invariants in `v4_hook.py`; it must not bind `agent_id` or create a second authority path.

No unrelated refactor is authorized.

## Test strategy

Implementation is test-driven. Add RED tests before each behavioral change.

### Auto-stage unit tests

Prove that a substantive root prompt:

- produces `decision=route`;
- stages exactly one next-generation lease during root `UserPromptSubmit`;
- exposes no required request-file or `K1_STAGE_COMMAND` step;
- returns prepared V1 and V2 spawn payloads;
- uses exact current generation-scoped V2 task name;
- uses the same current bootstrap message for V1/V2;
- leaves worker authority unbound before child bootstrap.

### Child transport tests

Add integrated route/spawn/child tests proving:

- a current `STAGED` lease with an existing spawn reservation accepts child `UserPromptSubmit` when `agent_type=luna_worker` and `prompt` is exactly the current Router-generated `spawn_message`;
- accepted child transport does not call root classification, does not revoke/restage, does not change generation/current-root authority, does not bind `worker_agent_id`, and does not inject K1;
- child transport for no lease, no reservation, ACTIVE/already-bound lease, wrong `agent_type`, wrong session, superseded root/generation, old capability/message, arbitrary prompt, or partial/bootstrap lookalike is rejected without journal mutation;
- V1 prepared `message` round-trips unchanged through the simulated native spawn into child `UserPromptSubmit` and is admitted;
- V2 prepared `message` remains opaque at parent `PreToolUse`, but the same Router-generated plaintext message round-trips into child `UserPromptSubmit` and is admitted;
- after admitted child transport, the child's first substantive-capable tool attempt is still denied unless it is the exact `pwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4=<current capability>` bootstrap;
- the exact current bootstrap as the first child tool atomically binds the observed `agent_id + child_turn_id`, marks the lease `ACTIVE`, and delivers canonical K1;
- a stale-generation bootstrap remains denied even if a stale child transport event is replayed.

Repository tests model the native child event contract; actual native delivery remains a separate live acceptance gate.

### Scope derivation tests

Examples must cover:

- `review this PR` -> `[]` write scope;
- `fix the failing tests` -> `[validated_cwd]` exactly;
- `research why this fails` -> `[]`;
- mixed explicit `fix and verify` -> `[validated_cwd]` exactly;
- a Git/repository root above or below `validated_cwd` is never substituted for the native value;
- no derived write path exists outside exact validated `cwd`.

### Security processing tests

Cover the exact objective pipeline:

- `secure_web_payload({"objective": candidate})` is the single redaction/blocking API used for objective sanitization;
- ordinary objective passes unchanged after the existing API returns `allow`;
- an exact validated-`cwd` path reference is canonicalized to `<cwd>` while retaining its relative suffix before scanning;
- an absolute private path outside validated `cwd` is not pre-whitelisted and is handled by `secure_web_payload`;
- sanitizable token/email/private-path-like material is redacted before Luna K1;
- an existing API `block` result does not stage a lease and degrades locally;
- no sensitive diagnostic string or bootstrap capability is echoed in failure output;
- no second objective scanner or model-authored sanitization path is consulted.

### A1 intent tests

For every A1 category, include positive and negative cases. Critical negatives include:

- `review PR #10` != remote mutation authorization;
- `explain deployment` != deploy authorization;
- `why did push fail?` != git-push authorization;
- Luna/model output mentioning a side effect cannot add an authorization.

### Transport regression tests

Keep and extend existing tests for:

- V2 encrypted opaque parent message;
- V1 namespaced spawn;
- collapsed V1 spawn where supported;
- child `UserPromptSubmit` transport admission;
- PostToolUse telemetry only;
- first-child capability bootstrap;
- stale-generation capability rejection;
- normal terminal;
- missing-stop supersession.

### Installer/contract tests

Prove managed `AGENTS.md`:

- contains the minimal prepared-payload contract;
- does not instruct PRIMARY to construct K1 JSON/request files;
- does not require `K1_REQUEST_SCHEMA` knowledge;
- does not instruct PRIMARY or Luna to work around child transport Hook admission;
- preserves direct/bypass behavior;
- preserves Luna no-descendant/no-nested-Codex invariants.

### Compatibility tests

The existing `stage-k1-fields --request-file` path remains syntactically valid for diagnostics/rollback during V4.0.1 but is not exercised by the normal new-conversation route.

## Live acceptance

Repository CI is necessary but not sufficient.

Before PR #10 can be marked Ready, validate on the target Mac with a freshly installed exact HEAD and a new Codex conversation.

Release-critical happy path:

```text
User: fix the failing tests in this project
```

User should not need to mention Router, Luna, K1, generation, V1/V2, request files, or bootstrap capabilities.

Required evidence:

```text
ROUTE=YES
AUTO_STAGE=YES
REQUEST_FILE_REQUIRED=NO
LEASE_CREATED=YES
PREPARED_SPAWN_SELECTED=YES
LUNA_SPAWNED=YES
SPAWN_MESSAGE_DELIVERED=YES
BOOTSTRAP_ATTEMPT_OBSERVED=YES
ACTOR_BOUND_BY_CAPABILITY=YES
K1_DELIVERED=YES
WRITE_SCOPE_EQUALS_VALIDATED_CWD=YES
LUNA_COMPLETED=YES
NORMAL_TERMINAL=YES
```

`SPAWN_MESSAGE_DELIVERED=YES` requires actual native child evidence that the Router-prepared message reached the spawned Luna child; a parent spawn success alone is insufficient.

`BOOTSTRAP_ATTEMPT_OBSERVED=YES` requires actual child tool telemetry showing the first child tool attempt used the current capability-bound bootstrap command. A lease remaining `STAGED` with only `spawn_tool_use_id` is a failure of this gate.

Run the happy path against each actually exposed native transport that can be selected in the target runtime. At minimum, the currently observed V1 path must pass; V2 must pass whenever the target runtime exposes V2 during acceptance. Repository tests remain responsible for both transport contracts regardless of live surface availability.

Then open a second fresh conversation and repeat with a different bounded task to prove global new-conversation availability rather than one-session state luck.

Also retain adversarial live gates:

- stale/foreign child transport is denied without state mutation;
- missing `SubagentStop` does not block the next root/generation;
- stale worker later tool activity is denied;
- stale terminal events cannot clear a new lease;
- native capacity failure leaves Router recoverable;
- V2 parent encrypted-message handling remains non-authoritative.

Historical-conversation resume remains compatibility evidence, not a release blocker for the stated V4.0.1 goal.

## Rollout and rollback

Rollout:

1. implement on the existing PR #10 branch;
2. keep PR Draft during repository and live acceptance;
3. install the exact tested PR HEAD into the managed Hook Python;
4. refresh managed global files;
5. start a new Codex conversation;
6. run transparent happy-path, child-transport, and fencing acceptance;
7. only then consider Ready/merge.

Rollback:

- reinstall the previous known-good V4.0 package/head and refresh managed policy;
- V4.0.1 must not destructively migrate or delete the existing V4 journal format unless a separately reviewed schema migration becomes unavoidable;
- if no journal schema change is needed, rollback is package/policy replacement only.

## Completion criteria

V4.0.1 is complete when all of the following are true:

1. a new ordinary conversation can route Luna without manual Router terminology;
2. PRIMARY no longer authors K1/request-file/spawn protocol fields;
3. V1 and V2 both consume Router-prepared payloads;
4. the current reserved child's exact spawn message is admitted through child `UserPromptSubmit` without root-side effects;
5. stale/foreign child transport is rejected without authority mutation;
6. the first child tool is the exact current capability bootstrap before K1/work authority;
7. ordinary local executor work inside exact validated `cwd` is not blocked by Router protocol ceremony;
8. sensitive input is not automatically copied into Luna context, and objective sanitization uses existing `secure_web_payload` rather than a new scanner;
9. external persistent side effects remain explicit-intent bounded;
10. generation/actor/stale-worker safety properties remain mechanically enforced;
11. repository CI/secret scan pass on exact HEAD;
12. target-Mac live acceptance passes on exact HEAD in at least two new conversations, including `SPAWN_MESSAGE_DELIVERED=YES` and `BOOTSTRAP_ATTEMPT_OBSERVED=YES`;
13. PR remains Draft until those live gates are verified.
