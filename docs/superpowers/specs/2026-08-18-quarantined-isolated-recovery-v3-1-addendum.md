# Codex Router V3.1 — Quarantined Isolated Recovery Addendum

Date: 2026-08-18
Status: USER-APPROVED DESIGN ADDENDUM; IMPLEMENTATION AUTHORIZED
Repository: `EthanSangSSS/codex-router`
Branch: `hardening/native-luna-safety-v2`
PR: #8
Parent design: `docs/superpowers/specs/2026-08-17-persistent-luna-minimal-control-plane-v3-1-design.md`
Parent pause addendum: `docs/superpowers/specs/2026-08-17-persistent-luna-hard-authority-pause-v3-1-addendum.md`

## 1. Purpose

Current-App validation established that the deployed ChatGPT App does not expose a trustworthy settlement observer to Router: `interrupt_agent` acknowledgment is not settlement, `Interrupted` is non-final, V2 `collaboration.wait_agent` did not deliver a bounded completion event in the tested path, and the running App did not expose the app-server control socket that could otherwise provide native thread/background-terminal state.

This addendum keeps the V3.1 Minimal Control Plane and adds one narrow liveness escape hatch. It does not introduce a process supervisor, polling loop, workspace transaction system, checkpoint service, broad shell parser, or new OAuth/auth topology.

## 2. Normative rule

```text
Unknown settlement blocks conflicting execution,
not unrelated control-plane progress.
```

When old execution cannot be proven settled after authority freeze, Router may transition that Luna execution from `QUIESCING` to `QUARANTINED`.

`QUARANTINED` means:

- old packet authority remains frozen;
- old Luna receives no new K1 work and is never resumed as the current Luna;
- late old-generation results are stale and non-authoritative;
- old physical execution may still exist;
- Sol may continue user interaction, planning, review, and other non-conflicting control-plane work;
- conflicting execution in the old authoritative mutation domain remains forbidden.

`QUARANTINED` is not settlement and must never be treated as `PAUSED_SETTLED`.

## 3. Normal path remains unchanged

The normal persistent-Luna path remains:

```text
ACTIVE(N)
  -> authority freeze if needed
  -> reliable settlement observed
  -> PAUSED_SETTLED
  -> next generation on the same Luna when otherwise valid
```

Quarantine is an exceptional recovery state, not a new normal packet lifecycle.

## 4. Narrow automatic isolated recovery

A quarantined active task may continue with a fresh Luna epoch only when Router can mechanically prove a simple isolated Git recovery baseline.

The recovery prerequisites are deliberately narrow:

1. Before the old packet executes, Router captured a clean Git baseline for that packet's working directory:
   - exact canonical workspace root;
   - exact `HEAD` commit;
   - exact Git common-directory identity;
   - working tree/index were clean at capture time.
2. The quarantined packet carried no explicit A1 side-effect authorization. If any A1 authorization was active, automatic isolated recovery is denied.
3. The replacement workspace is a clean independent Git repository at the exact captured baseline commit.
4. The replacement workspace path is disjoint from the old workspace path.
5. The replacement repository's Git common directory is different from the old repository's Git common directory; a linked `git worktree` is therefore insufficient.
6. The replacement Luna receives a fresh `luna_epoch` and a fresh native authority-profile identity while preserving the same `task_epoch`.
7. `packet_generation` remains monotonic across the task epoch. The replacement starts with no active packet; the next K1 packet increments generation normally.

If any prerequisite is missing or ambiguous, automatic recovery is denied and execution remains fail-closed. Normal execution is still allowed when no clean recovery baseline exists; only the automatic recovery escape hatch is unavailable.

## 5. No snapshot or promotion subsystem

V3.1 does not add:

- `workspace_epoch`;
- per-generation snapshot archives;
- a checkpoint lineage service;
- automatic salvage/reconciliation of quarantined output;
- automatic copy-back/promotion into the old workspace.

The clean Git commit captured before execution is the only automatic recovery seed.

Late quarantined output may be inspected manually after it is safely readable, but it never becomes authority automatically.

## 6. Settlement correction

Exact-runtime evidence established that native `Interrupted` is not a final agent status. Therefore `Interrupted` is not a valid settlement terminal condition for V3.1.

Router must continue to require a caller-provided `verified_native_terminal` source, and must reject `terminal_status="interrupted"` as settlement evidence.

This addendum does not broaden which other native terminal statuses are proven in the current App. Live acceptance must still validate the exact terminal mapping used by the installed target profile.

## 7. Minimal state changes

The durable control state adds only:

- execution status `QUARANTINED`;
- optional clean-Git recovery baseline metadata associated with the currently active packet.

No historical quarantine list is required. Once isolated replacement succeeds, the current snapshot advances to the fresh Luna epoch; stale-generation and current-Luna identity checks prevent the old Luna from reacquiring authority.

## 8. Replacement semantics

Quarantined isolated recovery preserves:

```text
task_epoch = unchanged
packet_generation = unchanged until the next packet begins
luna_epoch = fresh
native_authority_profile = fresh
active_packet = none
execution_status = IDLE
```

The old Luna is not first marked `RETIRED`, because retirement still means a settled administrative transition. Quarantine and retirement remain distinct concepts.

A later trustworthy settlement observation may settle a still-quarantined execution if no replacement has occurred yet. After replacement, old results remain stale by epoch/generation/current-identity rules and do not reactivate the old Luna.

## 9. Failure policy

```text
SETTLEMENT_UNKNOWN
  -> QUARANTINED

if isolated recovery proof passes:
  -> fresh Luna epoch
  -> next K1 generation may continue

otherwise:
  -> execution recovery blocked
  -> Sol/control-plane interaction remains available
```

Timeout, sleep, interrupt acknowledgment, `Interrupted`, PID disappearance alone, or unverified caller assertions are not accepted as settlement.

## 10. Scope boundaries

This addendum does not change:

- P1 persistent Luna as the normal path;
- A1 pre-action authorization requirements;
- no-descendant policy;
- no nested-Codex authorization;
- four-Hook baseline;
- stale-generation rejection;
- Draft PR / no-merge policy;
- prohibition on live install, Hook-trust mutation, new OAuth/device auth, or real external A1 probes during validation.

## 11. Acceptance

Repository acceptance requires tests proving:

- `QUARANTINED` cannot begin/start new work on the old Luna;
- old results are stale while quarantined;
- `Interrupted` cannot settle execution;
- clean baseline capture is optional and does not block normal dirty/non-Git work;
- linked worktrees fail isolated-recovery proof;
- dirty, wrong-commit, same-path, same-common-dir, missing-baseline, and A1-authorized recovery all fail closed;
- an independent clean repository at the exact baseline permits fresh-Luna replacement with the same `task_epoch` and monotonic generation;
- existing V3.1 offline tests remain green.

Live activation remains blocked until the remaining exact-runtime/target-profile acceptance gates are closed.
