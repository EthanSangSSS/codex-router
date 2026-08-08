# Native Luna Worker Router Design

Status: approved
Date: 2026-08-05
Target branch: `feat/global-auto-router-policy-v1`

## Objective

Replace the unusable automatic `Local Sol -> Web Sol -> Luna` per-prompt run
with a lightweight native Codex delegation policy:

```text
Sol plans -> luna_worker executes sequential work packets -> Sol reviews
```

Web Sol is entirely operator-managed copy/paste and is outside the automatic
Router path. The existing canonical state machine and fake pipeline remain
available only through explicit CLI commands.

## Native Luna worker

The global installer manages exactly one custom agent file:

```text
~/.codex/agents/luna-worker.toml
```

Its identity and model contract are:

```toml
name = "luna_worker"
model = "gpt-5.6-luna"
model_reasoning_effort = "max"

[agents]
enabled = false
```

The file intentionally omits `sandbox_mode`, approval policy, MCP, and skill
overrides so the child inherits the parent task's effective controls. Its
instructions require bounded scope, evidence-first work, no browser or Web Sol
operation, no authentication access, and no GitHub/install/release mutations.
The `[agents]` gate mechanically disables Luna's multi-Agent tools. Luna must
never create, spawn, fork, relay, resume, or delegate a child or descendant; a
packet that requires recursive delegation returns
`BLOCKED_LUNA_RECURSIVE_DELEGATION`.

Luna is the default execution owner for every routed work packet that Sol can
state with explicit scope and acceptance criteria. Each parent Codex task has
at most one persistent `luna_worker`; only the primary Codex task may create an
Agent, and Luna or any other child may not create descendants. Sol queries the
task tree before every packet. When the interface supports it, the initial Luna
is created from a self-contained packet with no conversation history; later
packets follow up with the same Luna, including when it is completed or idle.
It may inspect, edit, test, and correct multiple files inside the
delegated boundary. During execution, Luna is the sole writer for that file set
until it returns. Sol remains the coordinator and final decision-maker.

Before creating any helper non-Luna child Agent, Sol must ensure that Luna
exists and reserve capacity for it. A new packet restates its packet id,
working directory, allowed paths, forbidden operations, validation, stop
conditions, and required output; the previous packet's path authorization
expires automatically, and Luna obeys only the latest explicit boundary.

## Stateless global Hook

`UserPromptSubmit` continues to classify each prompt as `direct`, `bypass`, or
`route`. A routed response contains only bounded policy context:

```json
{
  "decision": "route",
  "workflow": "native_luna_worker",
  "luna_agent": "luna_worker",
  "luna_model": "gpt-5.6-luna",
  "luna_reasoning": "max",
  "luna_lifecycle": "persistent_per_parent_task",
  "capacity_failure_policy": "reuse_close_or_block",
  "luna_descendant_policy": "forbidden",
  "initial_context_mode": "packet_only",
  "web_mode": "manual_operator"
}
```

It does not allocate a `run_id`, create state directories, launch a model, or
touch the browser. Legacy explicit Router CLI runs keep their current state
authority, transition, digest, and recovery semantics.

## Delegation policy

For routed work, Sol plans and decomposes the task, then delegates each
executable work packet to the persistent `luna_worker` sequentially. Sol may
perform the read-only inspection needed to plan or review, but does not
implement the planned changes by default. If Luna's result fails review, Sol
sends a bounded correction packet back to the same Luna.

Luna capacity exhaustion never authorizes Sol to take over. The ordered
fallback is: reuse the existing Luna; if the interface supports it, close an
unused completed non-Luna Agent; otherwise return `BLOCKED_LUNA_CAPACITY`.
Relay-based recovery is forbidden. Only `direct` or
`bypass`, an unresolved architecture decision that cannot be safely decomposed,
or a non-capacity Luna execution blocker permits a bounded Sol takeover, which
must disclose its reason.

Sol may take over writable execution only when the user selects `direct` or
`bypass`, Luna reports a concrete non-capacity blocker, or the work cannot be
decomposed safely without an unresolved architectural decision. The takeover
and reason must be disclosed. Multiple sequential Luna packets are allowed;
concurrent writes to the same file set are not.

Every delegation packet states objective, readable and writable paths,
forbidden actions, validation, stop conditions, and required output. Luna never
decides workflow transitions, creates descendants, or performs Web work. Its
multi-Agent tools are mechanically disabled, and recursive work fails with
`BLOCKED_LUNA_RECURSIVE_DELEGATION`. The Hook context records `sol_role=plan_review`,
`luna_role=default_execution`, `delegation_mode=sequential_work_packets`,
`luna_lifecycle=persistent_per_parent_task`, and
`capacity_failure_policy=reuse_close_or_block`,
`luna_descendant_policy=forbidden`, and `initial_context_mode=packet_only` so
the initial packet is self-contained and this ownership split does not depend
on conversation memory.

## Installer ownership and recovery

The installer owns only its Hook entry, bounded AGENTS block, installation
metadata, and `agents/luna-worker.toml`. Existing unrelated hooks, AGENTS text,
and agent files are preserved.

For a fresh install, an absent `agents/` directory may be created privately.
For an existing `luna-worker.toml`, installation records and backs up exact
bytes and mode before replacement; uninstall restores them. A conflicting
post-install user edit fails closed.

The current two-target installation is upgraded only through the safe sequence:

1. existing installer performs `global-uninstall` and restores its originals;
2. the new package is installed;
3. the new installer reuses the uninstalled installation directory, prepares
   current managed outputs, and installs the Hook, AGENTS block, and Luna agent.

No live migration is performed during this code implementation pass.

## Validation and limitations

Offline tests must prove Hook statelessness, exact Luna TOML semantics,
preservation and recovery of pre-existing user files, subprocess Hook protocol,
the persistent-per-parent reuse/close/block policy, mechanical descendant-agent
disablement, packet-only initial context, no configured-state pollution, and
legacy CLI/fake compatibility.

The current account is deactivated. Offline configuration can be validated,
but actual Luna availability, account authorization, token consumption, and a
successful spawned model turn remain unverified until the account is restored
and a new Codex task is started.
