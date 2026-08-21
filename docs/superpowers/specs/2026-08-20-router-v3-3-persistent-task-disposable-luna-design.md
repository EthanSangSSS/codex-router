# Router V3.3: Persistent Task, Disposable Luna

## Status

Approved for implementation on 2026-08-20. This design supersedes the V3.2 persistent-worker lifecycle while retaining its request-file staging, exact Bash/pwd bootstrap, and mechanically bounded PRIMARY fallback.

## Architecture decision

Task continuity must not depend on worker identity.

- PRIMARY remains the persistent coordinator, reviewer, and final authority.
- Router task state, monotonic K1 generations, repository state, and local Git/test evidence carry durable continuity.
- Each active packet generation has at most one generation-scoped Luna worker.
- The exact terminal boundary forgets that worker. A later generation spawns a fresh worker and does not require the prior worker UUID, task path, memory, or native registry entry.
- K1 remains the sole Luna work authority. A native spawn message is transport only.

The compatibility fields `luna_agent_id`, `luna_task_path`, and `luna_epoch` remain in the V3.1 journal schema, but their authority is generation-local. `luna_epoch` rotates for every admitted generation spawn, and the agent/path binding is cleared at the exact terminal transition. The journal retains only an HMAC-tagged, bounded prior-worker rejection history; these tags are not usable bindings and exist solely to reject delayed lifecycle replays.

## Generation lifecycle

1. PRIMARY receives a routed turn and plans bounded work.
2. PRIMARY writes the strict seven-field request and runs the complete Router-injected `stage-k1-fields --request-file ...` command.
3. Router validates root/session/task/generation capability and stages canonical K1.
4. PRIMARY spawns one fresh `luna_worker` for the staged generation.
5. Router atomically commits the generation, rotates generation-local worker correlation, and reserves exactly one spawn.
6. Spawn result and `SubagentStart` bind only the reserved generation worker.
7. The exact first `Bash {"command":"pwd"}` bootstrap receives canonical K1; other substantive first tools remain denied.
8. The exact current `SubagentStop` terminal boundary records a one-way retired-worker tag, clears packet authority, child turn, staged wire, generation worker ID/path, and recovery metadata, returning execution to `IDLE`.
9. A later turn may stage generation N+1 and spawn a different worker without `followup_task`.

Late prior-generation `SubagentStart`, `PreToolUse`, and `SubagentStop` events are stale and cannot bind, consume, or mutate current authority. A second or ambiguously identified current-generation worker remains fail-closed.

## Fresh spawn capability and fallback

A supported fresh-spawn profile plus structured K1 staging is sufficient for the worker path. Persistent follow-up availability may remain as compatibility telemetry, but it is not readiness authority and never produces `BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` in the V3.3 path.

If fresh spawn is unavailable:

- non-strict + mechanically `SAFE_LOCAL_FALLBACK` permits only bounded workspace-local read/edit/test/build/lint/local-Git/debug work;
- strict mode blocks;
- active, pending, ambiguous, stale, or unsafe authority blocks.

Degraded PRIMARY mode never authorizes agent creation outside the failed Router attempt, deploy, publish, release, credentials, authentication changes, cloud/service mutation, package publication, external A1 effects, or other external state changes.

## Preserved V3.2 security properties

- exact private `stage-k1-fields --request-file` interface and strict seven-field schema;
- path, symlink, ownership, mode, size, UTF-8, schema, one-time capability, and same-inode cleanup protections;
- canonical K1 construction inside Router;
- exact Bash/pwd bootstrap and denial of other substantive first tools;
- root/session/current-generation checks and monotonic generation;
- no concurrent active authority and fail-closed ambiguous actor correlation;
- no Luna descendants or nested Codex orchestration;
- `send_message` QueueOnly, with `send_input` and `resume_agent` forbidden;
- no polling, sleeps, wait-as-sync, daemon, transcript recovery, or second control plane;
- Hard Authority Pause and separately gated A1 claims;
- K1 is an authority contract, not an OS sandbox.

Low-level follow-up parsing may remain for compatibility with historical callers, but model-visible V3.3 instructions never require or recommend it for task continuity.

## Readiness gates

Persistent reuse and persistent recovery correlation are removed from live-activation requirements. The worker-path gates become:

- `G1_CURRENT_GENERATION_SPAWN_CORRELATION`
- `G2_SETTLEMENT_OBSERVATION`
- `G3_ACTOR_ATTRIBUTION`
- `G4_NO_DESCENDANTS_EFFECTIVE_INVENTORY`
- `G5_NESTED_CODEX`
- `G6_NATIVE_AUTHORITY_PROFILE`
- `G7_A1_CAPABILITY_MATRIX`
- `G8_STALE_GENERATION_REJECTION`

Repository tests and disposable packaging checks do not prove live App activation. Live installation, Hook trust, and fresh-task runtime acceptance remain separate and are not part of this repository change.

## Acceptance contract

Automated tests must prove:

1. worker A can bind, bootstrap, run, and terminate in generation 1;
2. terminal transition clears generation-local worker binding;
3. generation 2 stages and spawns worker B where B differs from A;
4. generation 2 does not require follow-up or historical worker A;
5. late worker-A start/tool/stop events cannot bind, consume, or mutate generation 2;
6. simultaneous and ambiguous current-generation workers fail closed;
7. spawn failure degrades only from non-strict `SAFE_LOCAL_FALLBACK`;
8. request-file and exact Bash/pwd security regressions remain green;
9. rendered PRIMARY/Luna instructions contain no persistent-worker or normal follow-up requirement;
10. full unit, compile, diff, fake-adapter, wheel, fresh-install, offline self-test, outside-repository invocation, local secret scan, and exact-head GitHub checks pass.
