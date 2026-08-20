# Router V3.2 Usability Hardening Design

## Status

Approved for implementation on 2026-08-20.

## Problem

Router V3.1 correctly fails closed on authority ambiguity, but several ordinary runtime capability failures are currently escalated into whole-task failure. Live records show three recurring usability failures:

1. PRIMARY must append many packet fields to an injected `stage-k1-fields` command prefix. A local/runtime version mismatch or model-authored extra flag can produce `invalid-input / unexpected arguments` before any packet or Luna exists.
2. The first Luna tool is intentionally denied so K1 can be injected through `PreToolUse.additionalContext`; execution then depends on the model interpreting the denial as a successful bootstrap and issuing another tool in the same turn.
3. If persistent `followup_task` is unavailable after Gen1, the policy currently returns `BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` and forbids PRIMARY from continuing, even when Router scheduling authority is already idle and no unsafe state exists.

The result is excessive operational fragility: a capability/compatibility failure is often treated like a security failure.

## Design Principle

**Fail closed on safety ambiguity; degrade gracefully on capability failure.**

Router keeps hard blocking semantics for authority and safety properties, while recoverable runtime capability failures may enter a mechanically bounded PRIMARY fallback mode.

### Hard-block class

The following remain fail-closed and may not fall back automatically:

- missing or ambiguous actor identity;
- stale or conflicting generation;
- mismatched Luna identity or target;
- overlapping active authority;
- pending or ambiguous spawn correlation;
- unverified A1 side-effect authorization;
- unsafe installation/journal state;
- any state in which Router cannot prove that Luna authority is idle and cleared.

### Capability-degradation class

The following may degrade only when the Router state is mechanically proven fallback-safe:

- structured staging interface incompatibility before authority mutation;
- persistent follow-up unavailable on the exact runtime;
- Luna capacity unavailable before a child is created;
- completed/closed Luna turn with no supported continuation primitive;
- runtime exposes a supported Gen1 surface but not the preferred V2 continuation surface.

A degradation is never evidence that the missing Router property exists.

## 1. Stable K1 request interface

### Goal

Remove model-authored semantic packet fields from the protected command argv.

### Interface

Add a new CLI subcommand:

`stage-k1-request`

The Hook injects a complete command containing only Router-owned identity arguments plus a Router-owned request-file path:

- `--installation-dir`
- `--session-id`
- `--root-turn-id`
- `--capability`
- `--request-file`

PRIMARY does not append packet flags to this command.

The request file contains exactly one UTF-8 JSON object with this schema:

```json
{
  "packet_id": "...",
  "objective": "...",
  "working_directory": "/absolute/path",
  "intended_write_scope": ["..."],
  "explicit_side_effect_authorizations": ["..."],
  "success_criteria": ["..."],
  "stop_conditions": ["..."]
}
```

No `generation`, session identity, task/luna epoch, capability, K1 wire, or native agent identity may appear in the request.

### Request-file safety

The Hook derives a request path under the private Router installation directory from keyed session/root-turn tags. It exposes that exact path in the routed context.

`stage-k1-request` must:

- require an absolute path inside the installation's dedicated `stage-requests` directory;
- reject symlinks and non-regular files;
- require the file to be owned by the current user and mode `0600`;
- enforce the existing hook input size bound;
- reject any schema key outside the seven packet-field keys;
- validate list/string types and the absolute working directory;
- construct canonical K1 inside Router;
- validate the one-time root/session/task/generation capability through existing `stage_authority_packet` logic;
- delete the request file after a successful stage;
- leave the request file in place on validation failure so diagnostics remain inspectable;
- never persist model-authored raw K1.

`stage-k1-fields` remains supported as a compatibility seam, but rendered policy and new Hook contexts use `stage-k1-request`.

## 2. Bootstrap handshake without denial dependency

### Goal

Remove the requirement that Luna must interpret a permission denial as a successful bootstrap signal.

### Mechanism

For the first bound-executor `PreToolUse` of a committed generation:

- Router validates exact current/pending Luna identity, current packet, and child turn as before;
- the first tool must be an exact harmless bootstrap probe;
- baseline probe is canonical `pwd` with no semantic work payload;
- Router atomically transitions execution to the current child turn and returns `permissionDecision=allow` plus canonical K1 in `additionalContext`;
- the probe itself may execute, but no substantive side effect may occur before K1 because only the exact allowlisted read-only probe is accepted as the first tool;
- any other first tool is denied and receives no authority relaxation.

After bootstrap, ordinary tools use the existing packet and policy path. The transient staged wire is cleared on the next authorized same-turn tool as today, or may be cleared immediately if tests prove the runtime preserves `additionalContext` on `allow` without needing a second wire-delivery state.

### Compatibility fallback

Because live support for `additionalContext` combined with `allow` must not be assumed, the implementation must include an offline contract test and a clearly separated runtime capability claim. If the exact App runtime later proves that `allow + additionalContext` is not delivered, Router must keep the old deny handshake as a compatibility mode rather than silently weakening authority.

The rendered policy must state which handshake mode is active. The default for V3.2 is `allowlisted_probe` only if the managed Hook contract accepts the output shape in tests; live hard claims remain acceptance evidence until observed.

## 3. Mechanically bounded PRIMARY fallback

### State classification

Add a pure helper that classifies current Router state for PRIMARY fallback:

- `SAFE_LOCAL_FALLBACK`
- `BLOCKED_ACTIVE_AUTHORITY`
- `BLOCKED_PENDING_SPAWN`
- `BLOCKED_TASK_STATE`

`SAFE_LOCAL_FALLBACK` requires all of:

- logical task is `ACTIVE`;
- execution is `IDLE`;
- `active_packet_id is None`;
- `active_child_turn_id is None`;
- `authority_packet_wire is None`;
- `pending_spawn is None`.

A bound idle Luna identity may remain; fallback does not retire or replace it.

### Allowed fallback scope

When Router capability is unavailable and state is `SAFE_LOCAL_FALLBACK`, PRIMARY may continue only ordinary workspace-local development work:

- read/inspect repository files;
- edit files inside the current workspace;
- run tests/builds/linters;
- inspect local Git state;
- perform bounded local debugging.

Automatic degraded fallback does not authorize:

- deploy/publish/release;
- credential, token, cookie, private-key access;
- cloud/service mutation;
- package publication;
- external A1 side effects;
- privilege or authentication changes;
- new agent creation/delegation.

Those remain blocked unless the user explicitly bypasses Router/directly authorizes a separate flow under native controls.

### Routed context

`UserPromptSubmit` adds:

- `capability_failure_policy=degrade_primary_safe_local`
- `primary_fallback_state=<classification>`
- `strict_router=<true|false>`

PRIMARY may use degraded local execution only if the exact injected classification is `SAFE_LOCAL_FALLBACK`.

## 4. Strict Router mode

Add an exact first-line marker:

`[CODEX_ROUTER_STRICT]`

It still classifies the prompt as routed work, but sets `strict_router=true`.

In strict mode any Router capability failure remains fail-closed. There is no automatic PRIMARY fallback.

Natural-language phrases such as "must use Router" are not parsed as authority markers; only the exact marker changes this security behavior.

Existing direct/bypass markers keep their current one-turn semantics.

## 5. Follow-up unavailable semantics

`native_surface_compatibility()` continues to report persistent follow-up independently of Gen1 readiness.

`primary_gen2_readiness()` must no longer use `BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` as the ordinary operational instruction. It should produce a capability classification that distinguishes:

- `AVAILABLE`
- `UNAVAILABLE_DEGRADE_ALLOWED`
- `UNAVAILABLE_STRICT_BLOCK`
- `UNKNOWN`

The pure capability helper itself must not authorize fallback; fallback authorization always requires the current Router state classification from the Hook context.

Rendered PRIMARY instructions become:

- if follow-up is available, stage the next K1 and reuse the same Luna;
- if follow-up is unavailable and `strict_router=false` and `primary_fallback_state=SAFE_LOCAL_FALLBACK`, do not stage Gen2 and continue bounded local work as PRIMARY;
- if strict or state is not fallback-safe, stop fail-closed.

No `send_input`, `resume_agent`, `send_message`, replacement-spawn loop, polling, or wait-as-sync fallback is introduced.

## 6. Staging/spawn/bootstrap failure semantics

A capability failure may degrade only when the state is mechanically safe:

- staging request fails before any authority mutation: safe local fallback may be used if injected state classification allows it;
- no-followup after a completed Luna turn: safe local fallback may be used if state is idle/clear;
- spawn ambiguity, pending reservation, or active staged authority: block until authority is cleared by existing safe lifecycle handling;
- bootstrap failure while a Luna turn is active: block; after an exact bound `SubagentStop` clears Router scheduling authority, a later user turn may classify as safe fallback.

No new "clear state because it is inconvenient" command is added.

## 7. Session/new-task requirements

A new Codex task remains required for session-loaded configuration changes:

- global install/uninstall;
- Hook trust changes;
- AGENTS/profile changes from a refreshed live installation.

Ordinary runtime capability failures do not require a new task:

- stage request validation failure;
- no follow-up capability;
- Luna capacity failure;
- completed Luna turn;
- safe bootstrap failure after lifecycle closure.

## 8. Compatibility/readiness cleanup

Unify model admission/readiness with `native_surface_compatibility()` so a proven supported V1 Gen1 surface is not rejected merely because a complete V2 triad is absent.

Persistent follow-up remains a separate capability and must never be inferred from Gen1 readiness.

## 9. Non-goals

V3.2 does not:

- weaken actor/identity correlation;
- make native messages authoritative;
- authorize pending identity as a general lifecycle target;
- use `wait_agent` as binding synchronization;
- make `send_message` a work channel;
- restore `send_input` or `resume_agent`;
- add polling/sleep retry as a security primitive;
- add a daemon/supervisor;
- claim K1 scope is an OS sandbox;
- claim nested Codex is mechanically impossible from an unrestricted shell;
- automatically perform A1 side effects during degraded PRIMARY mode.

## 10. Verification

Required automated coverage:

1. `stage-k1-request` stages an exact canonical packet from the seven-field request schema.
2. Unknown request keys, unsafe path, symlink, wrong mode, invalid type, oversized file, and replay leave Router authority unchanged.
3. Rendered routed context contains a complete exact stage command plus request path; it no longer tells PRIMARY to append semantic packet flags.
4. First Luna bootstrap accepts only the exact harmless probe and injects K1; any substantive first tool is denied.
5. Safe fallback classification is pure and requires idle/cleared state.
6. Follow-up unavailable maps to degraded PRIMARY instructions only when non-strict and fallback-safe.
7. Strict marker prevents degradation.
8. Existing fail-closed identity, generation, V1/V2 normalization, send-message QueueOnly, and no-descendant tests continue to pass.
9. V1 Gen1 model/readiness admission remains compatible when sideband staging is proven, independently of follow-up.
10. Full unit suite, compileall, diff check, fake adapter smoke, wheel build, fresh wheel install/offline self-test, and exact-head GitHub CI/Secret Scan pass.

## 11. Live rollout

Repository landing and live activation remain separate.

After merge, refresh the live installation from the landed `main`, review/trust managed Hook changes, then start a new Codex task. Existing tasks must not be used to validate session-loaded V3.2 instructions.
