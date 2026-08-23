# Router V4.0.1 Transparent Auto-Stage Design

## Status

Approved architecture direction for the next Router increment on PR #10 (`hardening/router-v4-lease-core`). This document defines the implementation boundary before code changes.

The objective is to make Luna globally usable from ordinary new Codex conversations without requiring PRIMARY to manually author K1 JSON, run a staging CLI, remember V1/V2 wire details, or follow a long protocol manual. Router keeps mechanical authority fencing and native Codex safety controls.

## Context

V4.0 established the durable generation-lease authority model, including monotonic generation fencing, current-root supersession, HMAC bootstrap capability, first-child actor binding, stale-worker rejection, and V1/V2 native spawn compatibility.

Live integration exposed a repeated failure pattern at the PRIMARY/model protocol boundary:

1. runtime exposed V1 while the model-visible contract assumed V2;
2. K1 request-file fields were serialized with incorrect JSON types;
3. V2 parent `PreToolUse` exposed an encrypted opaque spawn message, making plaintext comparison invalid.

The current repository head already fixes the V2 encrypted-message boundary by treating the V2 parent message as opaque and deferring authority grant until the first child capability bootstrap. The remaining architectural weakness is that normal route correctness still depends on PRIMARY correctly performing too many protocol steps.

## Goals

1. Any new ordinary Codex conversation under the managed global Router installation can route substantive work to Luna without a user-visible Router ceremony.
2. PRIMARY does not manually construct K1 packets, request files, generation identifiers, capabilities, or spawn protocol fields.
3. Router mechanically derives and stages the canonical K1 from the native `UserPromptSubmit` event and current authority state.
4. Router returns prepared V1 and V2 spawn payloads; PRIMARY only selects the actually exposed native spawn surface and forwards the corresponding payload unchanged.
5. Preserve V4.0 generation lease, bootstrap, actor binding, stale-worker fencing, and native sandbox/approval boundaries.
6. Ordinary workspace-local inspect/edit/test/debug/retry/verify work is available without additional Router permission ceremony.
7. External or persistent A1 side effects are authorized only when deterministically supported by the original user request; Luna cannot broaden them.
8. Failure of transparent routing must not permanently poison the conversation or require manual journal repair.

## Non-goals

V4.0.1 does not implement:

- Stable Dispatcher, daemon, MCP control plane, or a second authority service.
- Worker pools, queueing, Luna reuse, or concurrency-limit bypass.
- Nested Codex or Luna descendants.
- Transactional rollback of a tool already admitted by native execution.
- Automatic merging, deployment, publication, outbound communication, or remote mutation without explicit user intent and normal platform controls.
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

Generation, HMAC, K1 schema, request-file format, V1/V2 field differences, and encrypted parent-message handling remain internal implementation details.

## Architecture

### 1. Transparent root auto-stage

For a root `UserPromptSubmit`:

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

### 2. Canonical K1 derivation

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

Use the normalized original user request after Router security processing. The objective must preserve the task meaning while preventing protected material from being copied into Luna context merely because routing is transparent.

Security processing should reuse the repository's existing security primitives rather than introduce a second scanner:

- sanitizable protected values are redacted before K1 construction;
- structurally unsafe material that the existing scanner cannot safely redact must not be propagated to Luna;
- an unsanitizable route degrades to PRIMARY-local execution for that turn with no V4 lease staged, rather than corrupting the Router journal or leaving a half-staged worker.

#### working_directory

Use the validated absolute `cwd` from the native `UserPromptSubmit` event.

#### intended_write_scope

Derive write authority conservatively from the original user request:

- explicit edit/implement/fix/create/delete/write intent -> current workspace root as the bounded write scope;
- review/research/inspect/compare/plan-only intent without an explicit write verb -> empty write scope;
- never infer a path outside current `cwd` from model reasoning.

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
- inferred categories are derived only from the original root user request, never Luna output, tool text, child memory, or prior generations;
- existing `validate_packet_authorizations` remains the final schema gate.

#### success_criteria

Router-generated defaults, not model-generated JSON. At minimum:

1. satisfy the user's stated objective within the current packet scope;
2. verify material changes/results using available local evidence before reporting success.

The implementation may add deterministic task-specific criteria when they can be derived without semantic privilege broadening, but V4.0.1 does not require a general planning DSL.

#### stop_conditions

Router-generated defaults. At minimum:

1. stop before an external/persistent A1 side effect not explicitly authorized by the original request;
2. stop before accessing unrelated data outside the bounded workspace unless the original request explicitly requires it and native platform controls permit it;
3. stop when the current generation lease is revoked/superseded or bootstrap/actor validation fails.

### 3. Prepared spawn payloads

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
- no static `luna_worker` task name substitutes for the generation-scoped V2 task name;
- V1 retains the current internal generation-scoped lease identity even though the native V1 tool does not carry `task_name`.

### 4. V2 encrypted parent boundary

Keep the current exact-head behavior:

- V2 parent `PreToolUse` treats `message` as encrypted opaque transport data;
- parent validation checks the current generation/task envelope and expected structural fields;
- parent spawn reservation never grants Luna authority;
- authority remains unbound until the child presents the exact current HMAC bootstrap capability on first `PreToolUse`;
- stale capability, stale agent, stale child turn, or superseded generation fails closed.

Do not reintroduce plaintext equality checks for the V2 parent message.

### 5. V1 transport

Keep V1 compatibility:

- exact `agent_type=luna_worker`;
- `fork_context=false` where the exposed schema supports/requires it;
- exact Router-generated bootstrap message;
- V1 `PostToolUse.agent_id` remains telemetry/correlation only;
- authority still starts at the first child capability bootstrap.

### 6. Luna executor contract

Luna keeps the current full-executor model after K1 appears:

Allowed within current K1 and native controls:

- inspect;
- research over locally available material;
- edit within write scope;
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

### 7. Minimal managed PRIMARY contract

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
- Router owns lease/fencing;
- native platform controls still apply.

## Failure semantics

### Auto-stage construction failure

If Router cannot safely construct the canonical K1 before lease creation:

- do not stage a lease;
- do not spawn Luna;
- keep the journal recoverable;
- return a bounded local/degraded decision so PRIMARY can continue without Router for that turn;
- expose a machine-readable reason suitable for diagnostics without leaking protected material.

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
5. first-child capability-bound actor binding;
6. exact current `agent_id + child_turn_id` fencing after bind;
7. stale worker denial;
8. late lifecycle telemetry cannot clear newer authority;
9. native sandbox/approval remains independent and authoritative;
10. A1 side effects cannot be invented by PRIMARY or Luna;
11. no descendant/nested-Codex control plane;
12. V3 state is not imported as V4 authority.

The design intentionally removes brittle model-side protocol rules; it does not remove platform safety controls or Router authority fencing.

## Implementation boundaries

Expected primary files:

- `src/codex_router/v4_hook.py`
  - root auto-stage orchestration;
  - route context with prepared spawn payloads;
  - preserve V1/V2 parent validation and child bootstrap authority.

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

- a new focused module such as `src/codex_router/v4_auto_stage.py`
  - preferred if root K1 derivation would otherwise make `v4_hook.py` materially harder to understand/test.

No unrelated refactor is authorized.

## Test strategy

Implementation is test-driven. Add RED tests before each behavioral change.

### Auto-stage unit tests

Prove that a substantive root prompt:

- produces `decision=route`;
- stages exactly one next-generation lease during `UserPromptSubmit`;
- exposes no required request-file or `K1_STAGE_COMMAND` step;
- returns prepared V1 and V2 spawn payloads;
- uses exact current generation-scoped V2 task name;
- uses the same current bootstrap message for V1/V2;
- leaves worker authority unbound before child bootstrap.

### Scope derivation tests

Examples must cover:

- `review this PR` -> empty write scope;
- `fix the failing tests` -> workspace write scope;
- `research why this fails` -> empty write scope;
- mixed explicit `fix and verify` -> workspace write scope;
- no derived path outside native `cwd`.

### Security processing tests

Cover:

- ordinary objective passes unchanged after normalization;
- sanitizable token/email/private-path-like material is redacted before Luna K1;
- unredactable high-risk material does not stage a lease and degrades locally;
- no sensitive diagnostic string is echoed in failure output.

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
ACTOR_BOUND_BY_CAPABILITY=YES
K1_DELIVERED=YES
WORKSPACE_SCOPE_CORRECT=YES
LUNA_COMPLETED=YES
NORMAL_TERMINAL=YES
```

Then open a second fresh conversation and repeat with a different bounded task to prove global new-conversation availability rather than one-session state luck.

Also retain adversarial live gates:

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
6. run transparent happy-path and fencing acceptance;
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
4. ordinary local executor work is not blocked by Router protocol ceremony;
5. sensitive input is not automatically copied into Luna context;
6. external persistent side effects remain explicit-intent bounded;
7. generation/actor/stale-worker safety properties remain mechanically enforced;
8. repository CI/secret scan pass on exact HEAD;
9. target-Mac live acceptance passes on exact HEAD in at least two new conversations;
10. PR remains Draft until those live gates are verified.
