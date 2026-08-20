# Router V3.1 Current-App Turn-Boundary Mode Addendum

> **Historical / superseded:** The active lifecycle is V3.3 “Persistent Task, Disposable Luna.” Persistent-worker identity and required-follow-up statements below are non-authoritative history; see [the V3.3 design](2026-08-20-router-v3-3-persistent-task-disposable-luna-design.md).

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

Current-App evidence established:

```text
interrupt acknowledgement != settlement
Interrupted AgentStatus != final settlement
background Unified Exec can outlive the initiating turn/interrupt path
current App does not expose the app-server control socket needed for native background-terminal inventory
```

Exact bundled Codex source exposes `SubagentStop` for a thread-spawn child turn. It is a usable native Luna turn boundary, but it is not evidence that every OS descendant, detached process, or background terminal has terminated.

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

The Luna profile continues to prohibit intentional daemonization, detached long-lived background work, and nested Codex delegation. On the current App those are policy/cooperative constraints except where a separate native control is proven.

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

The packaged CLI must expose the corresponding `hook-subagent-stop` entry point so the installed Hook command is executable from a fresh wheel.

## 5. Runtime lifecycle wiring

### 5.1 Packet admission

A parent work packet remains valid only as canonical K1.

```text
parent communication tool
-> validate exact bound Luna target
-> parse/validate next K1 generation
-> begin_packet(...)
```

`begin_packet` reserves the generation and packet authority. It does not assert that Luna execution has started.

### 5.2 Execution start

Every ordinary bound-Luna `PreToolUse` event must be reconciled against the current active packet before the tool executes.

```text
bound-Luna PreToolUse
-> start_execution(..., child_turn_id=event.turn_id)
```

The first event changes `IDLE + active_packet` to `RUNNING` and binds `active_child_turn_id`.

Repeated tool events with the same child turn are idempotent. A different child turn for the same active generation fails closed. A bound Luna ordinary tool call when no active K1 packet exists fails closed rather than running as unscheduled work.

### 5.3 Immediate authority freeze

Router freezes the old generation before later authority can be issued when either condition occurs:

```text
A. a new UserPromptSubmit arrives while the current execution is RUNNING
B. primary Sol issues interrupt_agent against the exact current Luna while RUNNING
```

The transition is:

```text
RUNNING -> QUIESCING
```

After freeze:

```text
- no new parent work may be sent to that Luna turn
- stale output cannot advance authority
- interrupt/close cleanup targeting remains allowed
```

A repeated freeze is idempotent. An interrupt acknowledgement never settles the turn.

A new user prompt received while the Luna is already `IDLE` does not replace the Luna or advance `task_epoch`; the persistent task-epoch model remains unchanged.

### 5.4 Exact turn-boundary transition

The control plane adds one explicit native-turn transition:

```python
observe_turn_boundary(
    directory,
    secret,
    session_id,
    *,
    child_turn_id,
) -> Literal["CURRENT", "STALE"]
```

The Hook validates exact `session_id`, bound Luna `agent_id`, and `agent_type=luna_worker` before calling it.

Its state contract is:

```text
IDLE + active_packet + active_child_turn_id=None
  + exact bound-Luna SubagentStop
  -> clear active packet metadata
  -> remain IDLE
  -> CURRENT
  # valid no-tool Luna turn

RUNNING + matching active_child_turn_id
  + exact bound-Luna SubagentStop
  -> clear active packet + child-turn metadata
  -> IDLE
  -> CURRENT

QUIESCING + matching active_child_turn_id
  + exact bound-Luna SubagentStop
  -> retain retired packet identity required by PAUSED_SETTLED
  -> PAUSED_SETTLED
  -> CURRENT

no active packet, PAUSED_SETTLED, RETIRED, or historical event
  -> no authority mutation
  -> STALE
```

A mismatched non-null `active_child_turn_id` is a conflict and fails closed; it is not silently treated as stale.

For the `IDLE + active_packet` no-tool case, there is no previously accepted turn waiting for a late `SubagentStop`: normal packet completion is driven by this same Hook. The Router still serializes one packet/turn per bound Luna.

The resulting boundary means:

```text
ROUTER_TURN_AUTHORITY_SETTLED=YES
PHYSICAL_OS_PROCESS_SETTLEMENT=NOT_CLAIMED
```

### 5.5 SubagentStop Hook behavior

`SubagentStop` must require:

```text
session_id
turn_id
agent_id
agent_type
```

For the exact current `luna_worker`, it invokes `observe_turn_boundary(..., child_turn_id=turn_id)`.

A historical/unbound Luna, ambiguous child actor, or conflicting current turn fails closed and cannot mutate the active generation. A `SubagentStop` with no active packet is a stale lifecycle observation and performs no authority mutation.

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

Implementation is limited to existing lifecycle/control seams:

```text
src/codex_router/cli.py
src/codex_router/global_install_adapter.py
src/codex_router/hook.py
src/codex_router/luna_control.py and/or the existing recovery overlay only if required
focused tests
README/manual acceptance wording
```

No new subsystem is authorized.

Required behaviors:

```text
1. baseline installer renders SubagentStop as the fifth managed Hook
2. fresh-wheel CLI exposes hook-subagent-stop
3. exact bound-Luna PreToolUse starts/binds execution idempotently
4. unscheduled bound-Luna ordinary tools fail closed
5. new UserPromptSubmit freezes a RUNNING generation before processing new authority
6. interrupt_agent freezes RUNNING authority before native interrupt executes
7. exact SubagentStop invokes observe_turn_boundary
8. normal RUNNING SubagentStop clears the packet and returns to IDLE
9. QUIESCING SubagentStop reaches PAUSED_SETTLED for Router scheduling authority
10. no-tool exact SubagentStop safely clears an admitted packet
11. Interrupted remains non-settling
12. stale/mismatched SubagentStop cannot mutate current authority
13. quarantined cleanup-only targeting remains unchanged
14. README/status wording stops claiming physical process settlement on current App
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

Repository implementation is acceptable only when all existing tests still pass and focused tests prove:

```text
- exactly five baseline Hooks including SubagentStop
- packaged `hook-subagent-stop` CLI path exists
- first bound-Luna tool event starts execution once
- repeated same-turn events are idempotent
- unscheduled bound-Luna ordinary tool call is denied
- different active child turn fails closed
- no-tool Luna turn closes through exact SubagentStop identity
- RUNNING + exact SubagentStop returns to IDLE with packet authority cleared
- QUIESCING + exact SubagentStop reaches PAUSED_SETTLED
- new UserPromptSubmit freezes an active RUNNING generation
- interrupt_agent freezes before cleanup dispatch
- Interrupted still cannot settle
- old/unbound/mismatched SubagentStop cannot mutate replacement/current authority
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

BOUND_LUNA_TOOL_WITHOUT_ACTIVE_PACKET=DENY
NEW_USER_PROMPT_WHILE_RUNNING=FREEZE_OLD_AUTHORITY
INTERRUPT_AGENT_WHILE_RUNNING=FREEZE_BEFORE_NATIVE_INTERRUPT
INTERRUPT_ACK=NOT_SETTLED
AMBIGUOUS_IDENTITY=FAIL_CLOSED
QUARANTINE=EXCEPTION_PATH
A1_HARD_CLAIMS=SEPARATELY_GATED

NO_PID_SUPERVISOR=YES
NO_POLLING_LOOP=YES
NO_SHELL_PARSER=YES
NO_WORKSPACE_ORCHESTRATOR=YES
```
