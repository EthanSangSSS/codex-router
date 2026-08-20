# Router Authority Realignment Design

Status: approved Minimal Agent-ID + Revocation V2 architecture
Date: 2026-08-16
Target branch: `hardening/native-luna-safety-v2`
Related PR: #8

## Goal

Preserve the intended product contract while making the native safety layer smaller and more defensible:

```text
normal substantive request
    -> Sol plans/decomposes
    -> Sol creates exactly one current-root-turn luna_worker
       or reuses the already-bound Luna for that root turn
    -> Luna performs bounded work within the admitted capability surface
    -> Sol reviews/corrects/takes over when needed
    -> Sol gives the final answer

explicit one-turn direct request
    -> stale prior binding is revoked first
    -> Sol executes directly for this turn
    -> no Luna is created or used for this turn
    -> the next normal substantive turn returns to Router routing automatically
```

The safety plane exists only to prevent stale Luna resurrection, Luna recursive Codex execution, and Luna security/permission bypass. It must not remove primary Sol's legitimate authority.

## Product contract

### Default route

When the managed `UserPromptSubmit` Hook is active and trusted, substantive or ambiguous work defaults to `route`.

Managed route context must communicate semantics equivalent to:

```json
{
  "decision": "route",
  "workflow": "native_luna_worker",
  "sol_role": "plan_review_final_authority",
  "luna_role": "default_execution",
  "delegation_mode": "sequential_work_packets",
  "luna_agent": "luna_worker",
  "luna_lifecycle": "persistent_while_root_turn_active",
  "parent_terminal_policy": "revoke_only_security_boundary",
  "capacity_failure_policy": "return_to_sol",
  "luna_descendant_policy": "forbidden",
  "luna_codex_runtime_policy": "forbidden",
  "interactive_blocker_policy": "return_to_sol_or_user",
  "initial_context_mode": "packet_only",
  "web_mode": "manual_operator"
}
```

A routed model response may display `Router: active`, but model prose is not independent telemetry. If the Hook is absent, untrusted, disabled, incompatible, or skipped, execution may fall back to direct Codex behavior but must be treated as **Router inactive/degraded**, not as a successful routed turn.

### One-turn direct override

The user may force current-turn direct execution by placing either exact marker on the first non-empty line:

```text
[CODEX_ROUTER_DIRECT]
```

or:

```text
本轮不用 Luna
```

The override:

- applies only to the current turn;
- prevents Luna creation/use for that turn;
- does not persistently disable Router;
- does not bypass sandbox, trust, approval, authentication, or other platform controls;
- does not skip stale prior-turn revocation.

The processing order is:

```text
UserPromptSubmit
    -> revoke previous active root scope for the same session
    -> classify current prompt
        -> direct/bypass: Sol only
        -> route: normal Sol -> Luna -> Sol
```

## Asymmetric authority

### Primary Sol

Primary Sol is the highest ordinary execution authority and must retain the Codex multi-agent capability required to manage the one Router-owned Luna.

Sol may:

- plan and decompose;
- create the current `luna_worker`;
- reuse the same bound Luna for sequential/correction packets while the current root scope remains ACTIVE;
- communicate with and observe the current Luna using verified current tool schemas;
- perform optional best-effort cleanup/cancellation;
- take over ordinary execution when Luna is unavailable, capacity-blocked, or unable to perform an operation safely;
- execute the current turn directly when the user invokes the direct override;
- give final review and acceptance.

Router does not own the user's whole primary `config.toml`. It may read/preflight effective primary capability. If primary multi-agent is known disabled, status/readiness must report incompatibility instead of silently claiming Router is ready.

### Luna

`luna_worker` is the default bounded execution worker, not a second coordinator.

Luna may perform only work inside the capability surface admitted by the exact deployed Codex build and the latest Sol packet.

Luna may not:

- create/spawn/resume/relay to descendants;
- start or resume another Codex runtime;
- bypass or automatically obtain user-required trust, approval, authentication, or permission escalation;
- act after Router authorization is revoked;
- broaden scope beyond the latest packet.

Child restrictions are intentionally Luna-specific and must not be applied globally to primary Sol.

## Single-Luna rule

For one current Router root scope there may be at most one pending/bound Router Luna.

While the root scope remains ACTIVE:

- packet completion/idle does not end parent authority;
- Sol reuses the already-bound Luna for correction/follow-up work;
- a second Luna creation is denied.

After revocation:

- the old Luna cannot receive new work;
- the old Luna cannot be resumed/rebound;
- a missing historical record never implies authorization;
- the same root scope does not silently create a replacement Luna in V2;
- Sol may take over, ask the user, or stop.

A later root turn may create its own Luna.

## Minimal identity model

### Root scope

`UserPromptSubmit` establishes the current root authority using the parent Hook's verified:

```text
session_id + root UserPromptSubmit turn_id
```

Persist privacy-safe scope tags derived from the installation secret rather than raw prompt/transcript content. Raw session/turn IDs are not security history and should not be persisted when an HMAC-derived scope tag is sufficient.

### Pending spawn

Before primary Sol calls `spawn_agent`, Router records one pending Luna spawn for the current ACTIVE root scope.

The V2 spawn gate must mechanically require:

```text
task_name = luna_worker
agent_type = luna_worker where the deployed schema exposes/accepts it
fork_turns = none
```

`fork_turns=none` is required to make `initial_context_mode=packet_only` real rather than documentation-only.

### Child binding

`SubagentStart` binds the native child `agent_id` to the unique pending Luna for the current parent-shared session.

Hard requirements:

- exactly one current ACTIVE root scope in that session is eligible;
- exactly one pending Luna exists;
- `agent_type` must identify `luna_worker` when available;
- the `agent_id` from the native Hook becomes the Router child identity;
- no transcript JSON parsing is used for authorization;
- child `turn_id == parent root turn_id` is **not** an authorization requirement.

If the exact deployed Codex build does not expose a trustworthy child `agent_id` on the Luna-sensitive Hook surfaces needed for enforcement, native V2 activation is blocked as `BLOCKED_RUNTIME_CAPABILITY` rather than falling back to transcript internals.

### Child admission

After binding, Luna-sensitive Hook admission asks only:

```text
Is this native agent_id the one Luna bound to the current ACTIVE root scope?
```

A historical, unknown, malformed, or unbound child identity receives no Router lifecycle authority and cannot be treated as primary Sol.

## Authorization state

The security-critical state is intentionally minimal:

```text
ACTIVE
REVOKED
```

Only transition:

```text
ACTIVE -> REVOKED
```

No path may restore a revoked root scope.

Runtime child status (`running`, `idle`, `completed`, `interrupted`, `shutdown`, etc.) is telemetry and does not grant authorization.

## Minimal journal

The journal should contain only what is required to authorize the current root scope:

```text
protocol/version
current root scope tag
session tag if required for correlation
authorization = ACTIVE|REVOKED
optional pending spawn identity
optional bound Luna agent_id
```

Cleanup state, Stop-loop state, transcript metadata, prompt text, packet contents, model output, and unbounded historical binding records are not part of the security state.

Requirements:

- owner-only/private path;
- symlink/ownership/type checks;
- process-safe locking for mutations;
- atomic replacement;
- file fsync and directory fsync for security transitions;
- read-only admission must not rewrite/fsync unchanged state;
- bounded storage / deterministic compaction;
- malformed state fails closed for Router child authority;
- missing old state never authorizes a historical Luna.

## Lifecycle

### New user turn

A new `UserPromptSubmit` for the same Router session invalidates the previous current root authority before classifying the new prompt.

### Normal completion

Authorization safety does not depend on cleanup.

When Sol is done with Luna, Router may revoke explicitly through the normal parent terminal path if a verified lifecycle operation is available; otherwise Stop is the final backstop. Optional native interrupt/close is resource cleanup only.

### Stop

Stop is **revoke-only**.

If the current root scope is ACTIVE:

```text
Stop
    -> atomically ACTIVE -> REVOKED
    -> return normally
```

No Router-generated continuation prompt. No autonomous cleanup/wait/retry loop. No `stop_blocked` state.

### Cleanup

`interrupt_agent`/`close_agent` semantics are runtime-version dependent and never define Router authorization. If primary Sol performs cleanup, the target must be the currently bound Luna using the exact deployed tool schema.

A failed or absent cleanup operation cannot reactivate authorization and does not block Sol from finalizing once Router authority is revoked.

## Parent lifecycle tool adapter

Router must normalize exact verified schemas rather than assume one generic target field.

Current V2 examples to validate at runtime/source pin:

```text
send_message      -> target
followup_task     -> target
interrupt_agent   -> target
send_input V1     -> target
resume_agent V1   -> id
close_agent V1    -> target
spawn_agent V2    -> task_name + message + fork_turns (+ agent_type where exposed)
```

Unsupported or unknown agent-reactivation/lifecycle operations must fail closed for Router lifecycle authority rather than fall through as ordinary parent work.

## Permission behavior

`PermissionRequest` attributed to the currently bound Luna is denied with `BLOCKED_USER_INTERACTION_REQUIRED`.

Primary Sol or unrelated requests receive no Router allow decision; native Codex/user approval remains authoritative.

Luna identification must prefer the bound native `agent_id`. `agent_type=luna_worker` is corroborating metadata, not the sole durable identity.

Malformed partial child identity fails closed only for Router lifecycle/permission authority and must not globally break unrelated root work.

## Process-recursion boundary

A home-grown shell parser is not a hard process boundary and must not be expanded into one.

The repository may retain a small detector for diagnostics/defense-in-depth, but live V2 hard safety requires one of these verified execution modes:

### Preferred: native child-scoped process denial

If the exact deployed Codex build exposes a documented/verified child-specific policy that can prevent Luna from launching Codex while retaining the required safe process surface, use it and verify it locally before activation.

### Safe fallback: hard-mode reduced Luna executor

If no such native process boundary exists, Luna arbitrary process execution is disabled:

```text
Luna descendants      OFF
Luna Unified Exec     OFF
Luna shell/process    OFF
Luna Code Mode        OFF
Luna permission ask   OFF/Hook DENY
```

In hard mode, Luna performs bounded editing/non-process work. Primary Sol runs build/test/verification commands and remains final reviewer.

Do not claim `Luna cannot launch Codex` while simultaneously allowing unrestricted shell/process execution guarded only by `shlex`/regex classification.

## Luna configuration

Separate stable documented configuration from exact-build compatibility settings.

Stable/readable intent includes:

- child descendant multi-agent disabled;
- Unified Exec disabled where supported;
- shell/process disabled in hard-mode fallback;
- Code Mode disabled using the canonical schema for the exact deployed build;
- permission escalation denied by Hook, with tool hiding only defense-in-depth.

Version-sensitive/experimental keys must be validated against the deployed build rather than treated as permanent Router API.

## Primary capability preflight

Router does not rewrite primary configuration merely to make itself work.

Status/readiness should inspect enough effective configuration to classify:

```text
COMPATIBLE
INCOMPATIBLE
UNKNOWN_REQUIRES_CAPABILITY_CHECK
```

Known incompatible examples:

- primary `features.multi_agent=false` when it removes required Sol management tools;
- primary agent capability explicitly disabled;
- Hooks disabled/unavailable;
- required child identity Hook fields unavailable;
- Luna profile cannot enforce the selected execution mode.

## Hook surface

Target minimum hard-safety surface:

- `UserPromptSubmit`: route/direct classification and previous-root revocation;
- `PreToolUse`: primary lifecycle gate + bound-Luna admission + reduced executor gate;
- `PermissionRequest`: bound-Luna deny;
- `SubagentStart`: bind native child `agent_id`;
- `Stop`: revoke-only terminal backstop.

`PostToolUse` may remain narrowly for clearing/corroborating failed pending spawn where required by verified event ordering, but it must not be the root identity authority.

`SubagentStop` is removed unless a concrete invariant requires it.

## Capacity and blockers

Ordinary capacity/dependency/tool blockers return control to Sol. Router does not enforce Luna-or-nothing behavior.

Sol may narrow work, reuse the current authorized Luna, run unsupported build/test commands itself, take over execution, ask the user, or stop.

Only stale-Luna resurrection, Luna process recursion, and Luna interactive-security bypass are hard guards.

## Observability

`Router: active` is a human/model-facing status line, not proof.

Minimum diagnostics should distinguish:

```text
installed
hook configured
hook trust/load unknown or verified where observable
primary capability compatible/incompatible/unknown
selected Luna execution mode
current route receipt/version where available
```

Do not add a daemon solely for Router observability.

## Legacy Router

Keep the legacy explicit staged Router workflow, but isolate its run state and naming from native root-turn authorization. Native Hook routing must not create/resume legacy canonical runs implicitly.

## V2 acceptance criteria

Repository tests must prove at minimum:

1. normal substantive prompt routes by default;
2. direct markers apply only to the current turn;
3. stale previous-root authority is revoked before direct/route classification;
4. primary Sol remains the only root actor with Router lifecycle authority;
5. one pending/bound Luna maximum per current root scope;
6. V2 spawn admission requires `fork_turns=none`;
7. `SubagentStart` binds native `agent_id` without transcript parsing;
8. child `turn_id` equality is not required for bound-Luna admission;
9. unknown/historical child `agent_id` cannot act as Luna or primary Sol;
10. current V2 `target`/`id` lifecycle schemas normalize correctly;
11. bound Luna PermissionRequest is denied and primary Sol is not Router-auto-approved;
12. Stop durably revokes and returns without Router continuation;
13. read-only admission does not rewrite the journal;
14. journal security transitions fsync the file and containing directory;
15. journal storage is bounded/compacted without making missing old state authorized;
16. selected Luna execution mode has no unsupported hard no-recursion claim;
17. primary multi-agent incompatibility is surfaced by readiness/status without Router owning the user's full config;
18. generated Hook context, AGENTS policy, Luna instructions, README, design, plan, and tests express the same contract;
19. legacy explicit Router tests remain compatible.

## Live capability gate

Live installation remains separate from repository implementation.

Before activation, the exact deployed Codex build must prove:

- required Hook events and child `agent_id` wire fields;
- SubagentStart ordering/correlation sufficient for the unique pending-Luna binding;
- exact V2 lifecycle tool schemas;
- primary multi-agent capability is available;
- `fork_turns=none` behaves as packet-only;
- generated Luna profile produces the intended tool inventory;
- selected process-recursion boundary is real: native child process denial or hard-mode no arbitrary process surface;
- macOS/ChatGPT runtime behavior matches the repository fixtures.

If any hard capability cannot be established, Router native V2 remains inactive rather than promoting transcript internals or command parsing into a security contract.

## Deferred to V2.1

- goal-scoped/cross-turn Luna reuse;
- same-root replacement Luna after revocation;
- richer telemetry/history;
- same-line direct-marker convenience;
- restoring Luna arbitrary shell execution if and only if a real child-scoped process boundary is proven;
- broader installer refactoring beyond a compact Codex compatibility adapter.
