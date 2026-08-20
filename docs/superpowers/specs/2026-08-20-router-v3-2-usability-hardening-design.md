# Router V3.2 Usability Hardening Design

## Status

Approved for implementation on 2026-08-20. This document reflects the final implementation contract rather than the initial spike shape.

## Problem

Router V3.1 correctly fails closed on authority ambiguity, but several ordinary runtime capability failures were escalated into whole-task failure:

1. PRIMARY had to append many semantic packet flags to an injected `stage-k1-fields` prefix. Version drift, quoting, or one model-authored extra flag could fail staging before any packet or Luna existed.
2. Luna bootstrap intentionally denied the first harmless tool to inject K1, so progress depended on the model treating a denial as successful bootstrap and issuing a second same-turn tool.
3. When persistent `followup_task` was unavailable after a completed Gen1, Router blocked the entire Codex task even when scheduling authority was mechanically idle and clear.

The product rule for V3.2 is:

**Fail closed on safety ambiguity; degrade gracefully on capability failure.**

## Safety failures versus capability failures

### Hard-block class

These remain fail-closed and never authorize automatic PRIMARY fallback:

- missing or ambiguous actor identity;
- stale/conflicting generation or K1 capability;
- mismatched Luna identity or lifecycle target;
- active/overlapping authority;
- pending or ambiguous spawn correlation;
- unsafe installation or journal state;
- unverified A1/external side-effect authority;
- any state in which Router cannot prove scheduling authority is idle and cleared.

### Capability-degradation class

These may degrade only when Router mechanically proves `SAFE_LOCAL_FALLBACK`:

- request-file staging validation/compatibility failure before authority mutation;
- persistent follow-up unavailable after a completed Luna turn;
- Luna capacity unavailable before a child is created;
- supported Gen1 runtime without the preferred continuation primitive.

Degradation never proves or emulates the missing Router capability.

## 1. Stable `stage-k1-fields --request-file` mode

V3.2 keeps the public `stage-k1-fields` operator name. The active Hook injects one **complete** command; PRIMARY does not append semantic packet flags.

The command contains only Router-owned identity/capability arguments plus:

```text
--request-file <exact-private-path>
```

PRIMARY writes one UTF-8 JSON object to the exact path carried by that complete command:

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

No generation, session identity, task/luna epoch, capability, native agent identity, or K1 wire may appear in the request.

The original flag-based `stage-k1-fields` mode remains a compatibility seam for older installed/session-loaded V3.1 instructions, but new V3.2 instructions use request-file mode.

### Request-file safety

The expected path is derived from keyed session/root-turn tags under the private Router installation `stage-requests` directory. Request handling:

- requires the exact expected absolute path;
- opens with no-follow semantics when supported;
- rejects symlinks and non-regular files;
- requires current-user ownership;
- rejects group/world-writable files;
- normalizes otherwise safe readable files to mode `0600` before reading;
- enforces the existing Hook input-size bound;
- requires exactly the seven schema keys above;
- validates string/list types and an absolute working directory;
- constructs canonical K1 inside Router;
- reuses the existing one-time session/root/task/generation capability validation;
- deletes the same-inode request only after successful staging;
- retains a failed request for bounded diagnostics;
- never persists model-authored raw K1.

A request-mode staging error returns the current mechanical `primary_fallback_state`. That is diagnostic state, not authority.

## 2. Bootstrap without denial-dependent continuation

The V3.2 live-path bootstrap is tied to the actual Codex Bash Hook schema.

For the first bound-executor `PreToolUse` of a staged generation:

- exact tool must be `Bash`;
- exact input must be `{"command":"pwd"}` with no extra fields;
- exact current/pending Luna identity and staged authority must already validate;
- Router atomically binds the child turn using the existing authority transition;
- Router returns `permissionDecision=allow` and canonical K1 in `additionalContext`;
- the read-only `pwd` probe may execute while K1 is injected;
- any other first Bash payload is denied **before** executor state is started.

Thus no substantive side effect can precede K1, while model continuation no longer depends on interpreting an expected permission denial.

Older/non-Bash synthetic compatibility paths retain the V3.1 deny-retry behavior so the mature safety core and older wire assumptions remain testable. The active V3.2 installed Luna instructions use the allowlisted Bash/pwd path.

Repository tests prove the output/state contract; whether a particular App build visibly delivers `allow + additionalContext` remains a live acceptance fact and is not inferred from tests.

## 3. Mechanical PRIMARY fallback

`classify_primary_fallback(snapshot)` is pure and returns one of:

- `SAFE_LOCAL_FALLBACK`
- `BLOCKED_ACTIVE_AUTHORITY`
- `BLOCKED_PENDING_SPAWN`
- `BLOCKED_TASK_STATE`

`SAFE_LOCAL_FALLBACK` requires all of:

- logical task `ACTIVE`;
- execution `IDLE`;
- no active packet;
- no active child turn;
- no staged authority wire;
- no pending spawn.

An already-bound but idle Luna may remain. Fallback does not retire, replace, resume, or send work to it.

### Degraded PRIMARY scope

When a Router capability is missing and the state is `SAFE_LOCAL_FALLBACK`, non-strict PRIMARY may continue only bounded workspace-local work:

- repository reads/inspection;
- edits inside the current workspace;
- tests/builds/linters;
- local Git inspection;
- bounded local debugging.

Automatic degradation does **not** authorize:

- deploy/publish/release;
- credential/token/cookie/private-key access;
- cloud/service mutation;
- package publication;
- external A1 side effects;
- privilege/authentication changes;
- new agent creation or delegation.

Those remain blocked or require a separately explicit direct/native flow.

## 4. Context compatibility

V3.2 does not inflate every initial Gen1 Hook context with fallback metadata.

For a normal fresh Gen1 route, the stable V3.1 route context shape is preserved apart from the complete request-file staging command. This reduces session/runtime compatibility churn.

The following fields are injected only when capability degradation is operationally relevant (a prior Router epoch exists) or strict mode is explicitly requested:

```text
capability_failure_policy=degrade_primary_safe_local
primary_fallback_state=<mechanical classifier>
strict_router=<true|false>
```

An initial staging error can still communicate `primary_fallback_state` through its structured CLI error result without changing Router authority.

## 5. Strict Router mode

Exact first non-empty line:

```text
[CODEX_ROUTER_STRICT]
```

forces `strict_router=true` and routes the turn. Capability failure then remains fail-closed; automatic PRIMARY degradation is prohibited.

Natural-language phrases such as “must use Router” are not parsed as a security marker. Existing direct/bypass first-line markers retain their one-turn behavior.

## 6. Follow-up unavailable

Gen1 readiness and persistent follow-up remain separate capabilities.

If `followup_task` is available, PRIMARY stages the next K1 and reuses the same Luna.

If follow-up is explicitly unavailable:

- do not stage Gen2;
- if non-strict and `primary_fallback_state=SAFE_LOCAL_FALLBACK`, continue bounded local PRIMARY work in the **same Codex task**;
- if strict or fallback state is not safe, stop fail-closed.

V3.2 does not emulate follow-up with `send_input`, `resume_agent`, `send_message`, replacement-spawn loops, polling, sleeps, or `wait_agent` synchronization.

`primary_gen2_readiness()` retains its V3.1 one-argument compatibility behavior. V3.2-aware callers may additionally classify an unavailable follow-up as `UNAVAILABLE_DEGRADE_ALLOWED`, `UNAVAILABLE_STRICT_BLOCK`, or `UNAVAILABLE_SAFETY_BLOCK` using explicit strict/fallback state. The capability helper itself does not grant authority.

## 7. PRIMARY model/readiness compatibility

A complete previously-supported V2 collaboration inventory remains sufficient for the legacy PRIMARY admission helper.

V3.2 additionally admits a proven V1 Gen1 path when structured sideband staging is positively evidenced, independently of persistent follow-up availability.

Global Gen1/readiness reporting continues to require the appropriate sideband/native evidence and does not infer follow-up from Gen1 capability.

## 8. New-task requirements

A new Codex task remains required after session-loaded configuration changes:

- global install/uninstall;
- Hook trust changes;
- refreshed AGENTS/agent-profile installation.

Ordinary runtime capability failures do **not** inherently require a new task:

- request staging validation failure with safe state;
- unavailable follow-up after completed Gen1;
- capacity failure before spawn;
- completed Luna turn;
- a bootstrap failure after the exact lifecycle boundary has returned Router authority to a safe idle state.

## 9. Offline self-test

The installed Hook subprocess is still exercised. V3.2 normalizes only the self-test's internal comparison view back to the stable V3.1 route-shape contract so new request mechanics do not cause false failures. Production Hook output is not rewritten for self-test convenience.

## 10. Non-goals

V3.2 does not:

- weaken actor/identity correlation;
- make native messages authoritative;
- authorize pending identity as a general lifecycle target;
- use `wait_agent` as synchronization;
- make `send_message` a work channel;
- restore `send_input` or `resume_agent`;
- add polling/sleep as a security primitive;
- add a daemon or second control plane;
- claim K1 scope is an OS sandbox;
- claim nested Codex is mechanically impossible from unrestricted shell;
- automatically perform A1/external side effects during degraded PRIMARY mode.

## 11. Verification contract

Automated coverage must include:

1. exact canonical staging through `stage-k1-fields --request-file`;
2. unknown schema keys, path escape, symlink, group-writable file, invalid list type, relative working directory, and stale capability replay without authority mutation;
3. safe request permissions normalized to private mode;
4. complete injected command with no model-appended packet flags;
5. exact Bash/pwd bootstrap gets `allow + K1`, while substantive/extra-payload first Bash is denied without execution-state mutation;
6. pure safe-fallback classifier and strict marker behavior;
7. completed Gen1 exposes safe fallback for continuation while fresh Gen1 keeps the stable route-context shape;
8. V1 Gen1 admission independent of persistent follow-up while legacy V2 admission remains compatible;
9. existing identity/generation/V1-V2 normalization/QueueOnly/no-descendant/lifecycle tests remain green;
10. full unit suite, compileall, diff check, fake-adapter smoke, wheel build, fresh wheel install/offline self-test, and exact-head GitHub CI/Secret Scan pass.

## 12. Live rollout

Repository landing and live activation remain separate.

After merge, refresh the live installation from landed `main`, review/trust the managed changes, and start a **new Codex task** before validating session-loaded V3.2 behavior. Existing tasks are not valid evidence for a newly installed policy/profile.
