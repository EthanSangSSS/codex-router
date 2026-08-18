# Router V3.1 Current-App Turn-Boundary Mode Addendum

Date: 2026-08-18
Status: APPROVED DESIGN ADDENDUM; IMPLEMENTATION PENDING
Repository: `EthanSangSSS/codex-router`
PR: #8
Parent design: `docs/superpowers/specs/2026-08-17-persistent-luna-minimal-control-plane-v3-1-design.md`
Hard Authority Pause addendum: `docs/superpowers/specs/2026-08-17-persistent-luna-hard-authority-pause-v3-1-addendum.md`
Quarantined recovery addendum: `docs/superpowers/specs/2026-08-18-quarantined-isolated-recovery-v3-1-addendum.md`

## 1. Purpose and precedence

This addendum narrows V3.1's current-App settlement claim to what the exact bundled Codex runtime can actually observe and enforce.

Where this addendum conflicts with earlier wording that requires Router to prove physical OS/process settlement before advancing scheduling authority, this addendum wins for the current ChatGPT App runtime.

The architecture remains a Minimal Control Plane. This addendum does not add a PID supervisor, process-group manager, shell parser, polling loop, workspace transaction layer, or background daemon.

## 2. Runtime fact driving the change

Current-App evidence established all of the following:

```text
interrupt acknowledgement != settlement
Interrupted AgentStatus != final settlement
background Unified Exec can outlive the initiating turn/interrupt path
current App does not expose the app-server control socket needed for native background-terminal inventory
```

Exact bundled Codex source also exposes `SubagentStop` for a thread-spawn child turn. `SubagentStop` is therefore a usable native Luna turn boundary, but it is not evidence that every OS descendant, detached process, or background terminal has terminated.

Accordingly:

```text
SubagentStop = native Luna turn boundary
SubagentStop != proof of physical OS/process death
```

## 3. Guarantee boundary

### 3.1 Hard guarantees retained

On the current App, Router may make hard claims only for:

```text
- immediate Router authority freeze on supersession/pause
- exactly one Router-authorized Luna turn at a time
- monotonic K1 packet generation
- stale generation/result rejection
- exact bound-Luna identity checks
- fail-closed lifecycle admission when actor identity is missing or ambiguous
- no Router-authorized Luna descendant lifecycle operation
- no authority revival from an old Luna turn after freeze/quarantine
```

### 3.2 Claims explicitly narrowed

Router must not claim mechanical proof of:

```text
- immediate OS process death after interrupt
- absence of detached/background descendants after Luna turn stop
- physical process settlement from interrupt acknowledgement
- physical process settlement from SubagentStop alone
```

The Luna profile must continue to prohibit intentional daemonization, detached long-lived background work, and nested Codex delegation. On the current App, those are policy/cooperative constraints except where a separate native control is proven.

### 3.3 A1 remains separately gated

This addendum does not broaden A1 authority.

```text
A1_HARD_CLAIM=WITHHELD_UNLESS_EXACT_PRE_ACTION_GATE_PROVEN
```

A turn boundary does not prove that an external persistent mutation completed safely. Explicit packet authorization and exact pre-action enforcement remain required for any hard A1 claim.

## 4. Managed Hook surface

The current-App baseline becomes exactly five managed Router Hook events:

```text
UserPromptSubmit
PreToolUse
PostToolUse
SubagentStart
SubagentStop
```

`PermissionRequest` remains conditional and A1-specific rather than baseline.

`Stop` remains a compatibility entry point but is not part of the baseline installer.

`SubagentStop` is added only to close the native Luna turn-authority lifecycle. It is not a process-kill or process-settlement Hook.

## 5. Runtime lifecycle wiring

### 5.1 Packet admission

A parent work packet remains valid only as canonical K1.

```text
parent communication tool
-> validate exact bound Luna target
-> parse/validate next K1 generation
-> begin_packet(...)
```

`begin_packet` reserves the generation and packet authority. It does not by itself assert that Luna execution has started.

### 5.2 Execution start

The first exact bound-Luna runtime event for the admitted packet that provides the native child turn identity starts the execution record.

Preferred source:

```text
bound-Luna PreToolUse
-> start_execution(..., child_turn_id=event.turn_id)
```

If the Luna turn completes without invoking any tool, `SubagentStop` may close the admitted packet directly only when the bound Luna identity and current generation are unambiguous.

Repeated tool events for the same already-bound child turn are idempotent. A different child turn for the same active generation fails closed.

### 5.3 Immediate authority freeze

A superseding substantive user instruction or explicit Router pause freezes the old generation's Router authority immediately when an execution is active:

```text
RUNNING -> QUIESCING
```

After freeze:

```text
- no new parent work may be sent to that Luna turn
- stale output cannot advance authority
- interrupt/close cleanup targeting may remain allowed
```

An interrupt acknowledgement never settles the turn.

### 5.4 Native turn boundary

For an exact bound Luna, matching `SubagentStop` closes the Router scheduling boundary for that Luna turn.

Normal completion path:

```text
RUNNING
-> SubagentStop(exact bound Luna / exact active child turn)
-> IDLE or equivalent packet-complete scheduling state
```

Paused path:

```text
QUIESCING
-> SubagentStop(exact bound Luna / exact active child turn)
-> PAUSED_SETTLED for Router scheduling authority
```

The resulting state means:

```text
ROUTER_TURN_AUTHORITY_SETTLED=YES
PHYSICAL_OS_PROCESS_SETTLEMENT=NOT_CLAIMED
```

This boundary permits the next Router-authorized generation while preserving the explicit policy prohibition on detached/background work.

### 5.5 Identity mismatch and incomplete evidence

Any of the following fails closed:

```text
- SubagentStop for an unbound or historical Luna
- wrong session/task/luna epoch
- wrong active child turn when one is recorded
- ambiguous child actor identity
- conflicting native turn identity for the same generation
```

When runtime identity cannot be reconciled safely, Router uses the existing quarantine path rather than guessing settlement.

## 6. Quarantine interaction

The existing narrow quarantined recovery addendum remains valid.

Quarantine is reserved for identity/runtime ambiguity or situations where Router cannot establish a valid current turn boundary. It is not the normal completion path.

A quarantined Luna:

```text
- receives no new work
- cannot regain authority from late results
- remains eligible only for bounded cleanup targeting
```

The existing clean-baseline independent-repository recovery escape hatch remains unchanged.

## 7. Minimal implementation delta

Implementation should be limited to the existing lifecycle/control seams:

```text
src/codex_router/global_install_adapter.py
src/codex_router/hook.py
src/codex_router/luna_control.py and/or the existing recovery overlay only if required
existing focused tests
README/manual acceptance wording
```

No new subsystem is authorized.

Required implementation behaviors:

```text
1. baseline installer renders SubagentStop as the fifth managed Hook
2. exact bound-Luna PreToolUse binds/starts the active child turn idempotently
3. matching SubagentStop closes the current Router turn boundary
4. QUIESCING + matching SubagentStop reaches Router scheduling settlement
5. Interrupted remains non-settling
6. stale/mismatched SubagentStop fails closed and cannot mutate current authority
7. quarantined cleanup-only targeting remains unchanged
8. README/status wording stops claiming physical process settlement on current App
```

## 8. Non-goals

Explicitly out of scope:

```text
- process/PID supervision
- process-group killing
- background-terminal polling
- shell command parsing
- universal detached-process detection
- workspace_epoch/checkpoint/promotion systems
- broad tool firewalling
- restoring V2 no-process mode
- automatic PR mutation, merge, deployment, or publication
```

## 9. Offline acceptance

Repository implementation is acceptable only when all existing tests still pass and new focused tests prove at least:

```text
- five baseline Hooks exactly, including SubagentStop
- SubagentStop handler is installed and callable from the packaged wheel
- first bound-Luna tool event starts execution once
- repeated same-turn events are idempotent
- mismatched turn id fails closed
- no-tool Luna turn can close safely through exact SubagentStop identity
- RUNNING + exact SubagentStop closes the scheduling boundary
- QUIESCING + exact SubagentStop closes Router scheduling authority
- Interrupted still cannot settle
- old/stale SubagentStop cannot mutate a replacement Luna/generation
- quarantine recovery regressions remain green
```

Full verification remains:

```text
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
fake adapter smoke
wheel build
fresh wheel install/smoke
disposable global-install -> global-self-test -> global-uninstall
Secret Scan
```

## 10. Live activation acceptance after implementation

Passing repository tests does not itself authorize live installation.

After the exact implementation head is synced locally, a separate explicit live-install authorization is still required.

The first live acceptance must verify in a new Codex task:

```text
- exact five managed Hooks are trusted/loaded
- normal substantive prompt routes through Router
- one persistent Luna is spawned and reused
- Luna Full Executor ordinary tools work
- descendant lifecycle attempt is unavailable/denied
- correction packet reuses the same Luna
- SubagentStop advances Router turn scheduling state
- pause/supersession freezes authority immediately
- interrupt acknowledgement is not reported as physical settlement
- no Router claim says detached/background OS work is mechanically settled
```

If target-profile actor identity cannot be established, lifecycle admission remains fail-closed and live activation stays blocked.

## 11. Final normative summary

```text
CURRENT_APP_MODE=TURN_BOUNDARY

HARD_SETTLEMENT_DOMAIN=ROUTER_SCHEDULING_AUTHORITY
PHYSICAL_OS_PROCESS_SETTLEMENT=NOT_CLAIMED

SUBAGENT_STOP=TURN_BOUNDARY
SUBAGENT_STOP!=PROCESS_DEATH_PROOF

BASELINE_HOOK_COUNT=5
BASELINE_HOOKS=UserPromptSubmit,PreToolUse,PostToolUse,SubagentStart,SubagentStop

INTERRUPT_ACK=NOT_SETTLED
AMBIGUOUS_IDENTITY=FAIL_CLOSED
QUARANTINE=EXCEPTION_PATH
A1_HARD_CLAIMS=SEPARATELY_GATED

NO_PID_SUPERVISOR=YES
NO_POLLING_LOOP=YES
NO_SHELL_PARSER=YES
NO_WORKSPACE_ORCHESTRATOR=YES
```
