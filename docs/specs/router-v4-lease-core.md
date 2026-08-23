# Router V4.0 Generation Lease Core

## Status

Frozen implementation scope for `hardening/router-v4-lease-core`.

## Problem

Router V3.3 couples native Luna worker lifecycle to Router authority lifecycle. A native worker can be completed or interrupted while Router retains `luna_agent_id`, `active_packet_id`, `active_child_turn_id`, and `QUIESCING`; because spawn admission rejects any existing binding, a missing or late `SubagentStop` can permanently block generation N+1.

The V4.0 goal is to make Router authority revocation independent of native worker termination.

## Runtime facts

Current Codex thread-spawned `PreToolUse` exposes native `session_id`, `turn_id`, `agent_id`, `agent_type`, and `tool_use_id`; these fields are suitable for mechanical actor fencing after a worker is correlated to the current lease. `SubagentStop` is not a reliable universal terminal oracle: interruption can terminate a child without dispatching `SubagentStop`. `PostToolUse` is also not a universal completion signal because it is emitted only after successful tool execution.

Current MultiAgent V2 does **not** expose a stable correlation identifier between the parent spawn result and `SubagentStart`: `spawn_agent` returns a task name (and optionally nickname), while `SubagentStart` carries `agent_id`, `agent_type`, `session_id`, and `turn_id` but no task name or spawn `tool_use_id`. `list_agents` exposes agent path/name plus status but not the exact `agent_id`. Therefore `SubagentStart` must never by itself grant V4 authority or bind an uncorrelated worker to a lease.

## Non-goals

V4.0 does not implement:

- Stable Dispatcher / hot backend switching.
- Permission or A1 redesign.
- Luna reuse or `followup_task` as the normal protocol.
- Worker pools, Router queues, or arbitrary concurrency.
- Auto-update or remote backend distribution.
- A replacement for Codex native agent capacity limits.
- Transactional rollback of a tool that already passed `PreToolUse`.

## Authority model

Create an independent V4 authority journal instead of extending the V3.3 snapshot.

Protocol: `codex-router/lease-control/v4.0`

Files:

- `lease-control-v4-0.json`
- `lease-control-v4-0.lock`

The V3 journal remains untouched and is diagnostic-only after migration.

### Session state

```text
task_epoch
root_session_tag
generation
active_lease | null
retired_worker_tags
```

### Lease

```text
lease_id
task_epoch
generation
root_session_tag
root_turn_tag
packet_id
authority_packet_wire
expected_task_name
spawn_tool_use_id | null
worker_agent_id | null
worker_task_path | null
child_turn_id | null
status = STAGED | ACTIVE
intended_write_scope
explicit_side_effect_authorizations
```

Native worker status is not authority state and must not gate generation admission.

## Invariants

1. Every staged job receives a unique `lease_id`.
2. `generation` increases monotonically within a task epoch.
3. At most one current authority lease exists per root session.
4. The current lease can be revoked atomically without `SubagentStop`, `close_agent`, or native terminal evidence.
5. After revocation, any later `PreToolUse` from that old worker is denied.
6. `SubagentStop` is optional reconciliation evidence, not an admission prerequisite.
7. Stale `SubagentStart`, `SubagentStop`, spawn result, and `PostToolUse` from generation N cannot mutate generation N+1.
8. Executor admission exact-matches current session, current lease capability, native worker identity, and child turn identity.
9. Spawn reservation belongs only to its lease; revoking the lease discards it and it cannot block N+1.
10. Native worker/path cleanup is independent from Router authority cleanup.
11. Missing or failed native cleanup must not block a new Router lease.
12. V3 state is never imported as trusted V4 authority.
13. `SubagentStart` is telemetry/reconciliation input only; it never grants authority or binds an uncorrelated `agent_id`.
14. The first worker-binding operation must present a lease-scoped bootstrap capability that a stale generation cannot satisfy.

## Revocation semantics

Revocation is a logical fencing operation.

```text
current lease -> REVOKE -> active_lease = null
```

After revocation, new tool admission from the old worker must fail mechanically at `PreToolUse`.

Revocation does **not** claim to roll back a tool that already passed `PreToolUse` and entered native execution. V4.0 must not implement a pseudo-transactional inflight scheduler. This limitation must be documented in user-visible architecture notes.

## Generation-scoped native task names

Keep `agent_type=luna_worker`, but stop requiring every generation to share the same native task name. The expected task name is derived from generation plus a lease-id prefix, for example:

```text
luna_g12_a1b2c3d4
```

The exact helper must be deterministic for a lease and validate the native task-name contract.

A stale native path may remain observable, but it must not block Router generation N+1. A real Codex `AgentLimitReached` remains a native capacity failure and must leave Router state recoverable.

## Spawn correlation and bootstrap capability

Because native V2 lacks `task_name <-> agent_id` correlation on the Hook/tool wire, V4.0 uses a generation-scoped bootstrap capability instead of binding on `SubagentStart`.

The capability is a domain-separated HMAC over the current lease identity using the installation secret. It must bind at least:

```text
root_session_tag
task_epoch
generation
lease_id
expected_task_name
```

The capability is delivered only in the current generation's opaque spawn message. The child must present it on its first benign bootstrap `PreToolUse`. A recommended command shape is:

```text
pwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4=<capability>
```

The command parser must be exact and anchored so the only shell operation is `pwd`; the suffix is a shell comment. The Hook validates the capability **before** binding `worker_agent_id` or `child_turn_id` and before injecting K1.

Consequences:

- a late `SubagentStart` from an unknown old worker is a no-op;
- a late old worker carrying an old capability cannot bind to the new lease;
- current worker authority starts only when native `PreToolUse.agent_id` presents the current lease capability;
- after first successful binding, later tools use exact native `agent_id + child_turn_id` fencing and do not need to resend the capability.

The capability is a correlation/fencing token, not a replacement for K1 intent authorization or native Codex permissions.

## Root supersession

For routed work, a new root user turn supersedes the prior current lease by logical revocation, not by transition to `QUIESCING`.

```text
active lease N
  -> new root turn
  -> revoke N
  -> stage N+1
```

No V4 authority state named `QUIESCING`, `PAUSED_SETTLED`, or `RETIRED` is permitted.

AUTO / DIRECT / STRICT prompt classification remains unchanged in V4.0 except where wiring must switch from V3 state to V4 lease authority.

## Executor fencing

For Luna `PreToolUse`, authorize only when all required current identities match.

For an unbound current lease, the first bootstrap must provide:

- current `session_id`;
- native `agent_id` and `agent_type=luna_worker`;
- native `turn_id`;
- exact current lease bootstrap capability in the benign bootstrap command.

Successful bootstrap atomically binds `worker_agent_id` and `child_turn_id`, marks the lease `ACTIVE`, and injects the canonical K1 `additionalContext` without an unsupported `permissionDecision=allow` shape.

For an already bound lease, all later Luna tools require exact current `worker_agent_id + child_turn_id`. A stale worker must never consume K1 for a new lease.

## Terminal reconciliation

Current exact `SubagentStop` may close the current lease only after that lease has been mechanically bound to the same `worker_agent_id` and `child_turn_id`.

Late or duplicate old-generation terminal events are explicit stale/no-op reconciliation. They must not clear or mutate a newer lease. An uncorrelated `SubagentStop` cannot be used to infer which lease a worker belonged to.

A current exact authority violation must not be silently converted into apparent successful cleanup.

## V3 migration boundary

On first V4 initialization for a session that has V3 state:

- Do not mutate or delete the V3 journal.
- Do not translate V3 `RUNNING`, `QUIESCING`, `PAUSED_SETTLED`, `luna_agent_id`, or `pending_spawn` into current V4 authority.
- Create a new V4 task epoch with `generation=0` and `active_lease=null`.
- Old V3 workers have no V4 lease and therefore fail V4 `PreToolUse` admission.

## Persistence requirements

Reuse the mature V3 persistence safety properties without copying V3 lifecycle semantics:

- owner-only directory and files;
- reject symlinks;
- validate regular files, owner, mode, and bounded size;
- `flock` around state mutation;
- strict schema validation;
- atomic temp-file replace;
- file fsync plus directory fsync;
- fail closed for corrupted authority state.

## Capacity failure

If native spawn returns an agent-capacity failure, V4 must leave no current pending authority that blocks later recovery. V4.0 does not implement a queue.

## Acceptance gates

Repository tests must prove:

- generation monotonicity and unique lease ids;
- revoke without terminal evidence;
- generation-scoped spawn reservation and task names;
- `SubagentStart` never grants uncorrelated authority;
- bootstrap capability changes with the lease and rejects stale generations;
- stale worker `PreToolUse` rejection;
- stale start/stop/spawn-result no-op behavior;
- missing `SubagentStop` does not block N+1;
- V3 authority import is none;
- no native cleanup prerequisite for N+1.

Live acceptance is separate and must later prove real Codex child identity wiring, current-capability bootstrap/K1 visibility, normal terminal, interrupted/missing-stop behavior, stale late-tool rejection, and capacity-failure recovery.
