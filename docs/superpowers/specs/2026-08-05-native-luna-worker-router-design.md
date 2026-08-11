# Native Luna Worker Router Design

Status: approved
Date: 2026-08-05
Amended: 2026-08-11
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

A new packet restates its packet id, working directory, allowed paths, forbidden
operations, validation, stop conditions, and required output; the previous
packet's path authorization expires automatically, and Luna obeys only the
latest explicit boundary. The first and only child Agent permitted by Router
policy is one persistent `luna_worker`; no policy path creates, closes, or
relays through a completed non-Luna child.

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

The installer keeps the `UserPromptSubmit` handler and adds one `PreToolUse`
group matching `^(Agent|spawn_agent)$`. The guard checks each spawn request for
the explicit `luna_worker` type and valid local function arguments, allows a
well-formed Luna request with empty output, and denies non-Luna, malformed, or
oversized input with the official bounded PreToolUse denial. It does not claim
to enforce singleton state or repair runtime capacity accounting.

## Delegation policy

For routed work, Sol plans and decomposes the task, then delegates each
executable work packet to the persistent `luna_worker` sequentially. Sol may
perform the read-only inspection needed to plan or review, but does not
implement the planned changes by default. If Luna's result fails review, Sol
sends a bounded correction packet back to the same Luna.

Capacity exhaustion does not authorize Sol takeover. Reuse the existing Luna;
do not depend on creating, closing, or relaying through a completed non-Luna
child. Use `BLOCKED_LUNA_CAPACITY` only when visible open blockers exist. Use
`BLOCKED_LUNA_RUNTIME_CAPACITY_DESYNC` only when the Agent tree has no reusable
Luna, a known Luna cannot be addressed, but `spawn_agent` reports capacity full.
Neither state authorizes Sol writable takeover or relay. Never archive the task
as recovery. Router cannot repair Codex runtime capacity accounting. Only
`direct` or `bypass`, an unresolved architecture decision that cannot be safely
decomposed, or a non-capacity Luna execution blocker permits a bounded Sol
takeover, which must disclose its reason.

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

The installer owns only its two Hook entries, bounded AGENTS block, installation
metadata, and `agents/luna-worker.toml`. Existing unrelated hooks, AGENTS text,
and agent files are preserved.

It preserves every unrelated Hook group, including an unrelated group with the
same matcher. A marker or related Router command conflict fails closed. Before
any managed user-file write, installation preflight exercises both handlers:
explicit Luna is allowed, non-Luna is denied, and malformed input is denied.

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
preservation and recovery of pre-existing user files, both subprocess Hook
protocols, the persistent-per-parent Luna reuse policy and its two bounded
capacity classifications, mechanical descendant-agent disablement, packet-only
initial context, no configured-state pollution, and legacy CLI/fake
compatibility.

This patch is limited to offline local validation. It does not perform live
installation, Hook trust, or real model, browser, or network testing. Codex
runtime-owned capacity accounting desync remains outside Router's repair
authority. Within its bounded scope, Router can prevent self-induced
exhaustion, classify the two conditions accurately, and fail safely; it does
not claim to activate or validate a runtime guard in a live Codex task.

## Amendment: 2026-08-11

The approved policy replaces the former helper-creation and completed-child
closure recovery path. Router permits exactly one persistent `luna_worker`
child Agent and requires reuse of that Luna; capacity exhaustion never permits
Sol writable takeover, relay, or task archiving as recovery. The two
classification-only states are mutually bounded: use `BLOCKED_LUNA_CAPACITY`
only for visible open blockers, and use
`BLOCKED_LUNA_RUNTIME_CAPACITY_DESYNC` only when the Agent tree has no reusable
Luna, a known Luna cannot be addressed, and `spawn_agent` reports capacity full.
Router cannot repair Codex runtime capacity accounting.

The global installation now manages one `UserPromptSubmit` handler and one
`PreToolUse` guard matching `^(Agent|spawn_agent)$`. The guard fail-closes each
request by requiring explicit `luna_worker` input and does not enforce
singleton state or runtime accounting. Installation preflight and offline
self-test exercise Luna allow, non-Luna deny, and malformed deny subprocess
paths without changing `config.toml` or activating a live runtime.
