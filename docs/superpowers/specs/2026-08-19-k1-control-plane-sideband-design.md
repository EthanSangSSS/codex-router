# K1 Control-Plane Sideband Design

Status: approved architecture
Date: 2026-08-19
Target branch: `hardening/native-luna-safety-v2`
Related PR: #8
Starting PR head: `c5a6f744c8bbd8f23be27f1f826fe86ff6cf6660`

## Goal

Preserve Router's K1 authority guarantees on current Codex Multi-Agent V2 even though native collaboration `message` fields are encrypted/opaque at the Hook boundary.

The core contract becomes:

```text
K1 plaintext                         = Router authoritative control plane
native spawn/follow-up message       = trigger/data plane only
Router-injected developer K1 context = sole work authority for executor tool action
```

This design must remain model-name agnostic:

```text
PRIMARY  = current Codex App/root conversation agent
EXECUTOR = persistent Router-managed worker
```

Current model names such as Sol/Luna are configuration choices or legacy identifiers, not architecture identities.

## Why this change is required

Current Router admission assumes the parent can place plaintext K1 directly in:

```text
spawn_agent.message
followup_task.message
```

and that `PreToolUse` can parse the same plaintext.

Runtime evidence disproved that assumption:

- native Multi-Agent V2 registers `spawn_agent`, `followup_task`, and `send_message` message fields as encrypted;
- persisted native function-call arguments contain opaque token-like message strings rather than plaintext K1;
- Router therefore fails closed before Gen1 admission when it tries to parse the opaque value as K1;
- a separately reconstructed canonical K1 does not equal the native persisted message bytes;
- native V2 inter-agent communication is not a normal child `UserPromptSubmit` path, so child `UserPromptSubmit` cannot be the authoritative plaintext K1 gate.

No supported App/config/CLI switch was found that forces the current collaboration tools onto Codex's internal `DirectPlaintextMessage` compatibility branch.

Therefore Router must stop treating native collaboration message plaintext as observable or authoritative.

## Non-goals

This change does **not** add:

- a daemon;
- a socket service;
- an MCP server;
- a checkpoint/snapshot service;
- a packet history database;
- automatic model selection;
- a workspace transaction layer;
- a process supervisor;
- a generalized native-message decoder;
- any attempt to decrypt or infer opaque collaboration messages.

It also does not change the intended one-persistent-executor lifecycle, QueueOnly semantics, model-role decoupling, or current Hook count.

## Authority model

### Primary

The PRIMARY remains the root planner/controller/reviewer/final authority.

Its model is inherited from the actual Codex App session and is admitted by capability, not model name.

For this design the PRIMARY must have:

- Multi-Agent V2;
- `spawn_agent`;
- `followup_task`;
- `send_message`;
- an ordinary root execution surface capable of invoking the installed Router `stage-k1` command.

The final item is part of the sideband capability gate. Router must report the sideband unavailable rather than silently skipping K1 staging when the PRIMARY cannot invoke it.

### Executor

The EXECUTOR remains one persistent Router-managed worker for the current task epoch.

Its model and reasoning level remain explicit Router configuration.

Legacy implementation identifiers such as `luna`, `luna_worker`, and `local_sol` may remain temporarily for compatibility. They must not be interpreted as mandatory model names.

## Native collaboration message contract

For Router security decisions:

```text
native collaboration message = non-authoritative transport trigger
```

Router does not:

- parse it as K1;
- compare it byte-for-byte with K1;
- derive scope/A1/generation from it;
- attempt to decrypt it;
- search it for embedded K1 text.

PRIMARY instructions should send a bounded trigger message with semantics equivalent to:

```text
A Router-controlled work packet is staged.
Await Router authority context before performing tool work.
```

The exact trigger prose is not a security invariant.

## Sideband interface

Add exactly one narrow runtime interface:

```text
router stage-k1
```

The command accepts:

- one self-authenticating one-time stage capability;
- one canonical K1 packet on stdin.

It performs no native agent operation.

It must:

1. verify the capability;
2. parse the K1 with the existing canonical K1 parser;
3. verify the K1 generation is exactly the current generation + 1;
4. verify the capability belongs to the current root turn/task epoch;
5. validate scope and A1 categories using existing validators;
6. store exactly one current-generation staged authority packet;
7. return a bounded machine-readable success/failure result.

It must fail closed on malformed, stale, cross-turn, cross-epoch, or replayed authority.

## Stage capability

The stage capability is self-authenticating under the existing installation secret.

It binds at minimum:

```text
current session scope
current root turn
current task epoch
next packet generation
```

The capability must not expose the installation secret.

Preferred shape: a compact token containing privacy-safe claims plus an HMAC. Exact encoding is an implementation detail, but verification must not require trusting model-provided identity fields.

The capability is supplied only in root Router additional context for the current routed turn. It is not included in the native executor message.

A capability for generation N becomes unusable after generation N is committed because the journal generation has advanced.

A repeated stage of the identical canonical K1 may be idempotent. A different packet for the same already-staged generation fails closed rather than silently replacing authority.

## Minimal journal change

Add one transient current-generation field to the existing control snapshot:

```text
authority_packet_wire: str | None
```

Properties:

- canonical K1 wire form only;
- at most one staged packet per current session/task epoch;
- owner-only private journal protection remains unchanged;
- no historical K1 retention;
- no unbounded packet list;
- cleared after the executor authority handshake completes;
- cleared on task cancellation/retirement/new root authority invalidation where the packet is no longer current.

The existing snapshot already carries generation, active packet id, scope, A1 authorization, executor identity, spawn reservation, and child turn identity. No second state machine is introduced.

## Root additional context

For a routed root turn, `UserPromptSubmit` continues to establish current root authority and inject Router policy context.

It additionally supplies bounded staging instructions equivalent to:

```text
K1_STAGE_CAPABILITY=<one-time token>
K1_STAGE_COMMAND=<installed router stage-k1 command>
```

The PRIMARY must:

1. plan the next bounded executor packet;
2. construct canonical K1;
3. call `stage-k1` before native work dispatch;
4. only after successful staging call `spawn_agent` or `followup_task`.

No native dispatch is admitted without a valid current staged packet.

## Gen1 admission

For the first executor generation:

```text
stage K1 generation 1
    -> spawn_agent PreToolUse
```

Parent `spawn_agent` admission requires:

- current root identity is valid;
- one current staged K1 exists;
- staged K1 generation is exactly next generation;
- `task_name == luna_worker` while that legacy protocol identifier remains in use;
- `agent_type == luna_worker` where required by the installed schema;
- `fork_turns == none`;
- no executor is already bound or pending.

The native opaque `message` is ignored for K1 parsing.

On successful admission Router atomically performs the existing logical actions:

```text
reserve_spawn(tool_use_id)
begin_packet(staged K1)
```

The existing `tool_use_id` correlation remains the native spawn reservation identity.

`SubagentStart` and `PostToolUse` continue to corroborate/bind the executor using native identity/task-path evidence.

## Gen2+ admission

For subsequent generations:

```text
stage K1 generation N
    -> followup_task(target=current executor)
```

Parent admission requires:

- current root identity is valid;
- one current staged K1 exists;
- generation is exactly previous generation + 1;
- target is exactly the currently bound executor id or canonical task path accepted by existing target authorization;
- current executor is idle/settled according to the existing turn-boundary contract.

The native opaque `message` is not parsed or compared to K1.

On successful admission Router commits the staged K1 using the existing packet-generation/state transition path and admits the native `followup_task`.

## `send_message` QueueOnly rule

`send_message` remains non-turn-triggering and cannot admit or advance K1.

If a would-be K1 dispatch is attempted through `send_message`:

```text
DENY
generation unchanged
staged K1 not consumed
no executor turn triggered by Router
```

This rule does not depend on native message plaintext.

## Executor authority handshake

The executor may receive an opaque native trigger before it has received authoritative K1 plaintext.

Therefore every newly committed generation begins with an execution handshake enforced by the executor's first `PreToolUse`.

### First executor `PreToolUse`

If all are true:

- actor is the currently bound executor;
- an active packet exists;
- `authority_packet_wire` is still present;
- no child turn has yet been bound for this generation;

Router must:

1. bind/start execution for the observed executor turn using the existing `active_child_turn_id` mechanism;
2. **deny the attempted tool action** so it cannot have side effects;
3. return the canonical K1 as Hook `additionalContext`;
4. label the block reason as an authority-handshake retry, not as task failure;
5. retain `authority_packet_wire` until the next same-turn PreToolUse confirms the model has been resampled with the developer context.

The first tool must never execute.

### Authority precedence

Codex records Hook `additionalContext` as developer context. The executor contract therefore becomes:

```text
native encrypted collaboration message = trigger only
Router developer K1 context            = sole work authority
```

Executor instructions must explicitly state that it may not treat native collaboration message prose as scope/side-effect authority.

### Second same-turn `PreToolUse`

On the next tool attempt for the same bound executor turn:

- child turn id must match the active child turn;
- current packet/generation must still be active;
- normal executor tool/lifecycle/A1 policy is evaluated;
- `authority_packet_wire` is cleared once the same-turn authority handshake is established;
- the tool is admitted only if all existing policy checks pass.

A mismatched child turn fails closed.

## Ordering with forbidden executor tools

Handshake injection precedes ordinary executor tool admission.

If the executor's first attempted tool is itself forbidden, Router still:

1. blocks it;
2. injects authoritative K1;
3. binds the current executor turn.

On the next attempt, ordinary lifecycle/descendant/A1 policy applies and the forbidden operation remains denied.

This prevents a forbidden first tool from bypassing K1 delivery while preserving the existing prohibition.

## Child `UserPromptSubmit`

Child `UserPromptSubmit` is no longer a hard K1 authority gate.

If an exact runtime emits a child `UserPromptSubmit`, Router may verify bound child identity, but execution authority begins at the first bound-executor `PreToolUse` handshake.

Do not require child prompt text to equal K1, because native V2 inter-agent communication does not provide that contract.

## Pure-text executor turns

A routed executor turn that produces only text and invokes no tool will not trigger the `PreToolUse` authority handshake.

This design deliberately does not add a Stop supervisor or separate message-inspection mechanism solely to cover that case.

Security consequence:

- no executor tool side effect can occur before authoritative K1 injection;
- pure-text executor output is advisory/non-authoritative and remains subject to PRIMARY review/final authority.

Executor instructions should require the normal routed work path to perform the Router tool handshake before substantive tool work.

## Stale and replay behavior

The following fail closed:

- stage capability for an old root turn;
- stage capability for an old task epoch;
- generation not equal to current + 1;
- second different K1 staged for the same pending generation;
- dispatch without a staged K1;
- dispatch to a non-current executor;
- child PreToolUse from an unbound/historical executor;
- child turn mismatch after handshake begins;
- attempt to advance generation through `send_message`.

New user/root authority invalidation must make any prior unused stage capability and staged packet unusable.

## Failure behavior

### Stage failure

No native agent call is attempted. State remains at the previous committed generation.

### Invalid native dispatch after staging

The staged K1 remains available for a corrected retry in the same current root authority unless the failure itself invalidates the task epoch.

### Native dispatch accepted, native tool later fails

Existing pending-spawn/current-packet recovery semantics remain authoritative. This design does not add a new recovery engine.

### First executor tool blocked for handshake

This is expected protocol behavior, not a production failure. Codex must resample the executor with the injected developer K1 before tool work continues.

## Security properties retained

The design retains:

- one Router scheduling authority;
- one authorized persistent executor per task epoch;
- monotonic packet generation;
- stale generation rejection;
- current executor target authorization;
- current root-turn authorization;
- packet-id/scope/A1 authority from canonical K1;
- Gen1 native spawn correlation through `tool_use_id` plus native child binding;
- QueueOnly `send_message` semantics;
- descendant/lifecycle prohibition;
- ambiguous identity fail-closed;
- no executor tool side effect before Router developer K1 injection.

## Security property intentionally removed

Router no longer claims:

```text
native encrypted collaboration message plaintext == staged K1 bytes
```

The current Codex Hook surface does not expose plaintext needed to prove that equality.

This is no longer an authority invariant because native message content is explicitly non-authoritative.

## Hook surface

Keep the currently installed five-Hook surface:

```text
UserPromptSubmit
PreToolUse
PostToolUse
SubagentStart
SubagentStop
```

No new Hook event is required.

Responsibilities:

- `UserPromptSubmit`: root authority + stage capability/context;
- `PreToolUse`: parent native dispatch gate + executor first-tool K1 handshake + ordinary tool policy;
- `PostToolUse`: narrow spawn-result reconciliation;
- `SubagentStart`: native executor identity binding;
- `SubagentStop`: turn-boundary settlement for persistent executor reuse.

## Model/configuration contract

No model name is hard-coded into admission.

PRIMARY:

```text
model = inherit current App session
admission = capability-based
```

EXECUTOR:

```text
model = explicit Router configuration
reasoning = explicit Router configuration
```

Changing future model names must require configuration/UI selection only when capabilities remain compatible.

## Expected implementation scope

Implementation should remain concentrated in:

```text
src/codex_router/protocol.py
src/codex_router/luna_control.py
src/codex_router/hook.py
src/codex_router/cli.py
executor/generated agent instructions
focused tests
README/current design docs only where needed
```

Do not refactor unrelated installer machinery or legacy explicit pipeline code.

## TDD acceptance requirements

Focused tests must prove at minimum:

1. opaque native `spawn_agent.message` is admitted only when a valid staged Gen1 K1 exists;
2. no staged K1 -> spawn fails closed;
3. invalid task/agent/fork identity still fails closed even with a valid stage;
4. stage capability is root-turn/task-epoch/generation bound;
5. stale/replayed stage capability fails closed;
6. identical stage retry is idempotent;
7. different duplicate stage for same generation is denied;
8. opaque native `followup_task.message` is admitted only for the exact bound executor with a valid next staged K1;
9. `send_message` cannot consume staged K1 or increment generation;
10. first executor tool attempt is denied and receives authoritative K1 as additional developer context;
11. first executor tool has no side effect in the fake/runtime fixture;
12. second same-turn executor tool attempt may proceed under normal policy and clears transient staged wire;
13. mismatched executor child turn after handshake starts fails closed;
14. forbidden lifecycle tool remains forbidden after handshake;
15. current scope/A1 metadata are derived from staged canonical K1, never native opaque message;
16. child `UserPromptSubmit` plaintext K1 is not required for native V2 authority;
17. new root turn invalidates unused old stage authority;
18. existing Gen1 spawn binding/PostToolUse/SubagentStart ordering tests remain green;
19. existing SubagentStop persistent reuse tests remain green;
20. model-role decoupling tests remain green;
21. full existing unit/compile/diff/fake-adapter/fresh-wheel checks remain green.

## Live acceptance

After repository Reality Audit and controlled live update, final runtime smoke must prove:

```text
PRIMARY_MODEL=<observed runtime model>
PRIMARY_MULTI_AGENT_VERSION=V2
PRIMARY_REQUIRED_SURFACE=PASS
SIDEBAND_STAGE=PASS

GEN1 native tool=spawn_agent
Gen1 staged K1 generation=1
first executor tool=BLOCKED_FOR_K1_HANDSHAKE
second executor tool=admitted under K1
SubagentStop boundary=PASS

GEN2 native tool=followup_task
same persistent executor=PASS
Gen2 staged K1 generation=2
first executor tool=BLOCKED_FOR_K1_HANDSHAKE
second executor tool=admitted under K1
SubagentStop boundary=PASS

send_message would-be Gen3=DENIED
generation remains 2
identity mismatch=FAIL_CLOSED
executor descendants=NONE
nested Codex=NONE
A1 live mutation probe=NO
```

Production success remains contingent on fresh runtime evidence, not model prose.

## Explicitly deferred

Do not add in this change:

- automatic executor replacement;
- cross-task executor reuse;
- packet history/telemetry service;
- native encrypted-message equality proof;
- generic custom control-plane framework;
- automatic capability/model discovery beyond the current narrow readiness checks;
- pure-text executor-turn supervision beyond PRIMARY review.

## Final architecture

```text
User prompt
   |
   v
PRIMARY plans
   |
   |  canonical K1 + one-time root capability
   v
router stage-k1
   |
   |  validate + stage current-generation authority
   v
native V2 spawn_agent / followup_task
   |
   |  opaque encrypted trigger only
   v
EXECUTOR starts turn
   |
   | first PreToolUse
   v
Router BLOCKS first tool
+ injects authoritative K1 as developer context
   |
   | model resamples under K1 authority
   v
second PreToolUse
   |
   | existing identity/scope/A1/lifecycle checks
   v
allowed executor tool work
   |
   v
SubagentStop boundary
   |
   v
PRIMARY review / next generation / final answer
```

This is the minimum design that preserves K1 as real authority without depending on plaintext visibility that current native Multi-Agent V2 does not provide.
