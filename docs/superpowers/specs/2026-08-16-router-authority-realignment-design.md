# Router Authority Realignment Design

Status: approved routing target; implementation pending
Date: 2026-08-16
Target branch: `hardening/native-luna-safety-v2`
Related PR: #8

## Goal

Restore the Router to its intended operating contract while keeping the incident-driven safety guards:

```text
normal substantive request
    -> Sol plans/decomposes
    -> Sol creates or reuses exactly one current-turn luna_worker
    -> Luna performs bounded execution
    -> Sol reviews/corrects
    -> Sol gives the final answer

explicit one-turn direct request
    -> Sol executes directly
    -> no Luna is created or used for that turn
    -> the next normal turn returns to Router routing automatically
```

The safety plane exists to prevent Luna from escaping its scope. It must not remove the primary Sol's legitimate control authority.

## Routing contract

`UserPromptSubmit` remains the routing entry point.

For a normal substantive request, the Hook returns `decision=route` and injects the managed Router context. A routed model response may display `Router: active`; that display is a consequence of verified routed context, not telemetry by itself.

The routed context must declare semantics equivalent to:

```json
{
  "decision": "route",
  "workflow": "native_luna_worker",
  "sol_role": "plan_review_final_authority",
  "luna_role": "default_execution",
  "delegation_mode": "sequential_work_packets",
  "luna_agent": "luna_worker",
  "luna_lifecycle": "persistent_while_root_turn_active",
  "parent_terminal_policy": "revoke_then_cleanup",
  "capacity_failure_policy": "return_to_sol",
  "luna_descendant_policy": "forbidden",
  "luna_codex_runtime_policy": "forbidden",
  "interactive_blocker_policy": "return_to_sol_or_user",
  "initial_context_mode": "packet_only",
  "web_mode": "manual_operator"
}
```

The Router default is **route**, not direct, for substantive work when the Hook is active and trusted.

If the Router Hook is absent, untrusted, disabled, or otherwise not injected, Codex may execute directly as a degraded fallback, but that state is explicitly **Router inactive** and must never be represented as a successful routed turn.

## One-turn direct override

The user may force current-turn direct execution by placing either marker on the first non-empty line:

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
- does not bypass sandbox, approval, authentication, security, or other platform controls;
- does not skip lifecycle cleanup/revocation for a stale Luna from the previous turn.

Therefore the order is conceptually:

```text
UserPromptSubmit
    -> revoke any stale prior-turn Luna binding
    -> classify current prompt
        -> direct/bypass: Sol only for this turn
        -> route: normal Sol -> Luna -> Sol workflow
```

## Asymmetric authority model

### Primary Sol

Primary Sol remains the highest ordinary execution authority and must retain the Codex multi-agent capability required to manage the one Router-owned Luna.

Sol may:

- plan and decompose work;
- create the current-turn `luna_worker`;
- reuse that same Luna across sequential packets and bounded correction packets while the root turn remains active;
- send follow-up/correction work to that Luna;
- observe/wait for that Luna;
- perform one bounded cleanup/interrupt operation when terminating the binding;
- take over ordinary execution when Luna is unavailable or blocked, provided no hard invariant is bypassed;
- execute the whole turn directly when the user explicitly invokes a direct override;
- give the final review and response.

The Router must not globally disable the primary Sol's multi-agent feature. In particular, a top-level effective setting equivalent to `features.multi_agent=false` is incompatible with this design when it removes Sol's ability to create/reuse Luna.

### Luna

`luna_worker` is the default bounded execution worker, not a second coordinator.

Luna may perform the ordinary file/tool work explicitly delegated in the current packet and may run focused tests and verification within that scope.

Luna may not:

- create, spawn, fork, resume, relay to, or delegate to descendant agents;
- start or resume another Codex runtime through shell, PTY, subprocess, or wrapper indirection;
- request or bypass user-required trust/approval/authentication/security interaction;
- expand outside the latest delegated packet;
- reuse itself across a revoked parent/root-turn boundary.

The custom `luna-worker.toml` may disable descendant multi-agent capability for Luna. That restriction is intentionally child-specific and must not be applied to the primary Sol globally.

## Single-Luna rule

For each active Router root turn, the primary Sol may own at most one Router-managed `luna_worker` binding.

While the same root turn remains authorized:

- Luna packet completion/idle does not end the parent turn;
- Sol should reuse the already bound Luna instead of creating another Luna;
- correction packets should reuse the same Luna to preserve cache continuity.

After the binding becomes revoked:

- the historical Luna cannot receive new work;
- the historical Luna cannot be resumed or reused by a later turn;
- the same root-turn scope does not silently create a replacement worker in V2;
- Sol may take over, ask the user, or stop.

A later new root turn may create its own one Luna if routing is required.

## Lifecycle and safety boundaries

The incident-driven safety plane remains narrow and mechanical.

Hard invariants:

1. **No stale Luna resurrection.** A revoked or turn-mismatched Luna cannot receive follow-up, resume, process work, or new packets.
2. **No Luna process recursion.** Luna cannot start another Codex runtime.
3. **No interactive bypass.** Luna permission/trust/authentication requests fail closed and return control.

These guards do not prohibit primary Sol from legitimately creating/reusing the current authorized Luna.

Lifecycle authority must be durable and fail closed. If a transition to `REVOKED` is required because of a mismatch or security failure, that revocation must be committed durably before the Hook returns an error/block. A mutate-then-raise path that skips persistence is invalid.

A turn mismatch on a Luna-sensitive admission path revokes the stale binding and denies that Luna operation. `UserPromptSubmit` stale cleanup is defense-in-depth, not the only enforcement point.

## Cleanup semantics

For the deployed Multi-Agent V2 surface, `interrupt_agent` is best-effort cleanup/cancellation of current work. It is not permanent authorization revocation and is not proof of full process termination.

Router authorization is revoked before any cleanup attempt.

A successful observed interrupt may record cleanup evidence as `OBSERVED`; otherwise cleanup remains `UNVERIFIED`. No cleanup result may reactivate authorization.

The Stop Hook is a one-shot backstop only. If it encounters an ACTIVE binding, it must atomically revoke that binding before requesting one cleanup continuation. It must not create a repeated Stop/cleanup loop.

## Capacity and blocker behavior

Capacity exhaustion and ordinary execution blockers must not deadlock the Router into "Luna or nothing".

For a normal routed turn:

```text
Luna unavailable/capacity/blocker
    -> return control to Sol
```

Sol then chooses among reuse, narrower work, direct takeover, asking the user, or stopping. The choice is adaptive and evidence-based.

Only the three hard invariants above are non-overridable.

## Permission behavior

Any `PermissionRequest` attributable to Luna is denied with an explicit user-interaction blocker.

For primary Sol or unrelated execution, Router must not auto-approve the request. It returns no Router approval decision so the native Codex approval/user-interaction flow remains authoritative.

## Process-recursion gate

The Luna process-recursion gate must classify supported effective command intent rather than use a raw substring rule such as `"codex" in command`.

The supported V2 surface must distinguish:

- BLOCK: direct Codex executable, configured/known Codex absolute path, `env ... codex`, supported shell wrapper whose effective command launches Codex;
- ALLOW: reading/searching/diffing files or text that merely contain the string `codex`;
- FAIL_CLOSED: unknown executor-like tool unexpectedly exposed to Luna;
- UNVERIFIED: dynamic execution forms outside the explicitly supported classifier.

The guarantee is `LUNA_CODEX_GATE_VERIFIED_FOR_SUPPORTED_COMMAND_SURFACE`, not kernel-level denial.

## Runtime configuration contract

Primary Sol and Luna configurations are intentionally asymmetric.

```text
Primary Sol:
    multi-agent management needed for the one Luna = enabled

luna_worker:
    descendant multi-agent creation = disabled
    user permission escalation = denied
    nested Codex runtime = denied by Router admission gate
```

The implementation must verify the exact deployed Codex version/tool surface before live activation. Configuration keys that disable an executor for Luna must not accidentally remove the parent Sol's required management tools.

## Documentation and generated-policy consistency

The following surfaces must express the same authority model:

- Hook routed context;
- generated Router block in `AGENTS.md`;
- generated Luna developer instructions;
- README;
- design and implementation plan;
- tests.

Stale semantics such as these must be removed from current policy surfaces:

```text
sol_role=plan_review
persistent_per_parent_task
capacity exhaustion does not authorize Sol takeover
reuse_close_or_block
```

Current semantics are:

```text
sol_role=plan_review_final_authority
persistent_while_root_turn_active
capacity_failure_policy=return_to_sol
parent_terminal_policy=revoke_then_cleanup
```

## Acceptance criteria

Offline tests must prove at minimum:

1. normal substantive prompt => `route`;
2. routed context gives Sol final authority and Luna default execution;
3. `[CODEX_ROUTER_DIRECT]` => current-turn direct only;
4. `本轮不用 Luna` => current-turn direct only;
5. a following normal prompt returns to `route`;
6. stale previous-turn binding is revoked even when the new turn is direct;
7. primary Sol remains able to create the one Luna;
8. same active root turn reuses the one bound Luna;
9. second Luna creation for the same root turn is denied;
10. Luna cannot create descendants;
11. turn mismatch durably revokes stale Luna before returning a block;
12. first Stop with ACTIVE Luna durably revokes before its one continuation; second Stop does not loop;
13. Luna PermissionRequest is denied; primary Sol is not auto-approved;
14. process gate blocks effective Codex launches but permits textual/file references to `codex`;
15. normal Luna capacity/blocker returns control to Sol rather than forcing a deadlock;
16. Hook context, AGENTS policy, Luna instructions, README, and installer output all agree;
17. legacy explicit Router workflow remains compatible.

## Live acceptance

Live migration remains separate from repository implementation.

After repository review and installation/trust, a new App task must demonstrate:

```text
normal task
    -> Router route context observed
    -> Router: active
    -> Sol plans
    -> one Luna performs work
    -> Sol reviews/finalizes

explicit direct task
    -> direct context observed
    -> no Luna used
    -> Sol completes directly

following normal task
    -> Router routing returns automatically
```

The live acceptance must also prove the primary Sol still exposes the management capability required to create/reuse its one Luna, while the spawned `luna_worker` cannot create descendants.
