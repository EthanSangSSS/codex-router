# Router V3.1 Current-App Runtime Acceptance Addendum

> **Historical / superseded:** The active lifecycle is V3.3 “Persistent Task, Disposable Luna.” Persistent-worker identity and required-follow-up steps below are non-authoritative history; see [the V3.3 design](../specs/2026-08-20-router-v3-3-persistent-task-disposable-luna-design.md).

Date: 2026-08-18
Status: RUNTIME ACCEPTANCE ADDENDUM; REPOSITORY GREEN OFFLINE; LIVE ACTIVATION BLOCKED
Repository: `EthanSangSSS/codex-router`
PR: #8
Parent plan: `docs/superpowers/plans/2026-08-17-router-v3-1-exact-runtime-validation.md`
Target design: `docs/superpowers/specs/2026-08-17-persistent-luna-minimal-control-plane-v3-1-design.md`
Normative pause addendum: `docs/superpowers/specs/2026-08-17-persistent-luna-hard-authority-pause-v3-1-addendum.md`

## 1. Authority and precedence

This addendum defines the normal V3.1 runtime-acceptance path after the repository correction pass.

Where this addendum conflicts with the parent exact-runtime validation plan, this addendum wins. In particular, the parent plan's disposable authenticated `CODEX_HOME`, disposable authentication gate, diagnostic Hook installation, and standalone authenticated root are no longer the normal path.

The following are locked:

```text
NEW_OAUTH_FOR_VALIDATION=FORBIDDEN
NEW_DEVICE_AUTH=FORBIDDEN
API_KEY_FALLBACK=FORBIDDEN
LIVE_AUTH_COPY_OR_REUSE=FORBIDDEN
STANDALONE_AUTHENTICATED_ROOT=NORMAL_PATH_DROPPED
CURRENT_APP_AUTHENTICATED_ROOT=NORMAL_PATH
```

This addendum does not authorize live Router installation, Hook trust changes, PR ready-for-review, or merge.

## 2. Repository baseline

The repository correction pass has been independently verified locally and in GitHub Actions.

Baseline before this addendum commit:

```text
REPOSITORY_HEAD=c01bb0412cc29eea054857bf3cff7991f4877a8a
UNIT_TESTS=169/169_PASS
CI_115=PASS
SECRET_SCAN_102=PASS
F1_RUNNING_GENERATION_BARRIER=FIXED_OFFLINE
F2_K1_AUTHORITY_BYPASS=FIXED_OFFLINE
F3_UNCONTROLLED_NEW_TASK_OVERWRITE=FIXED_OFFLINE
F4_TASK_EPOCH_LUNA_EPOCH_SEPARATION=FIXED_OFFLINE
F5_A1_MATRIX_CLOSURE_MODEL=HARDENED_OFFLINE
F6_SESSION_RECLAMATION=FIXED_OFFLINE
PROFILE_REASON_COUPLING=FIXED_OFFLINE
```

Runtime acceptance must not reopen these controls unless current-App evidence contradicts a concrete implementation assumption.

## 3. Existing current-App evidence

The first current-App smoke already established:

```text
P1_PRODUCT_RUNTIME_FEASIBILITY=PASS
G9_SHORT_CONTEXT_REUSE=PASS
INTERRUPT_ACK_AS_SETTLEMENT=REJECTED_BY_RUNTIME_EVIDENCE
```

Observed in the prior P4 interruption probe:

```text
interrupt_agent previous_status=running
foreground PID remained alive after interrupt acknowledgement
progress file continued from about 70 lines to 150 lines
completion timestamp occurred after interrupt acknowledgement
process then exited naturally
```

Therefore:

```text
interrupt ACK != process stop
interrupt ACK != settlement
```

Hard Authority Pause remains:

```text
immediate Router authority freeze
!= guaranteed immediate OS/process/tool kill
```

## 4. Exact-source findings for the reviewed bundled lineage

Reviewed bundled source lineage:

```text
9392c3fa5bcda342b5b96a1a04d67b2f781617c2
```

These source facts narrow the remaining runtime questions.

### 4.1 Hook actor fields exist in the exact source

At the reviewed source lineage, `PreToolUse`, `PermissionRequest`, and `PostToolUse` command inputs include optional:

```text
agent_id
agent_type
```

The hook runtime populates those fields for `SessionSource::SubAgent(SubAgentSource::ThreadSpawn { ... })` using the spawned thread id and agent role.

Therefore the old assumption that the exact runtime schema lacks child actor fields is superseded.

Current classification:

```text
G3_EXACT_SOURCE_SUPPORT=PASS
G3_CURRENT_APP_WIRE_OBSERVATION=STILL_REQUIRED_BEFORE_LIVE_HARD_CLAIM
```

A current-App model surface that does not display Hook stdin does not falsify source support; it only limits direct observation.

### 4.2 `interrupt_agent` is request/acknowledgement, not settlement

The exact source captures agent status before sending `Op::Interrupt` and returns only:

```text
previous_status
```

This confirms the prior runtime finding.

### 4.3 Native status subscription provides a settlement candidate

The exact source exposes an agent-status watch/subscription. Status transitions include:

```text
TurnStarted  -> Running
TurnComplete -> Completed(...)
TurnAborted(Interrupted) -> Interrupted
Error -> Errored(...)
ShutdownComplete -> Shutdown
```

`Interrupted` is explicitly not final.

The native `wait_agent` implementation subscribes to status and returns only when `is_final(status)` is true; it does not treat `Interrupted` as final.

This creates a concrete G2 candidate:

```text
candidate SETTLED observation = native wait/status reaches a final AgentStatus
```

This is only a candidate until current-App runtime evidence proves that no late mutation or child-turn output occurs after that final status for the tested execution class.

### 4.4 Spawn/lifecycle correlation is split across surfaces

Exact source provides:

`SubagentStart`:

```text
session_id
turn_id
agent_id
agent_type
```

Tool Hook events provide:

```text
session_id
turn_id
agent_id/agent_type for thread-spawn children
tool_use_id for PreToolUse/PostToolUse
```

`SubagentStart` does not expose a shared spawn `tool_use_id` in its command input schema.

Therefore G8 must not depend on a nonexistent universal correlation id. The intended fallback remains:

```text
serialize one pending spawn
+ root/session identity
+ expected role
+ expected parent relation
+ observed agent_id/task path
+ spawn PostToolUse correlation when available
+ fail closed on ambiguity
```

Current classification:

```text
G8_EXACT_SOURCE_SUPPORT=PARTIAL_COMPATIBLE_WITH_SERIALIZED_RESERVATION
G8_CURRENT_APP_RECONCILIATION=ACCEPTANCE_PROBE
```

## 5. Normal current-App acceptance workspace

Use the already authenticated current Codex App root. Do not set `CODEX_HOME`.

Use only a benign temporary workspace:

```text
/tmp/codex-router-v3-1-acceptance
```

Allowed mutations are confined to that temporary workspace.

Do not:

- read or modify live `~/.codex`;
- install/uninstall Router against live Codex;
- change Hook trust or Hook configuration;
- create diagnostic Hooks merely to manufacture evidence;
- change account/auth state;
- create OAuth/device auth/API keys;
- push to GitHub or mutate PR state as a runtime probe;
- deploy, publish, send email, mutate cloud resources, or install system packages;
- start nested Codex merely to create evidence.

## 6. Acceptance pass A — freeze exact runtime identity

Before interpreting any previous evidence, re-record read-only App identity:

```text
app_version
app_build
bundled_codex_path
bundled_codex_size
bundled_codex_sha256
repo_head
remote_pr_head
bundled_source_lineage
```

If the App binary/hash changed from the reviewed lineage, classify prior source-backed conclusions as requiring source reconciliation before using them for a hard claim.

## 7. Acceptance pass B — targeted G2 final-status settlement probe

This is the highest-priority active probe.

Create one Luna in the current App root and one benign long-running foreground action under the temporary workspace. The action should append monotonically numbered/timestamped records to a file and record a completion marker.

Required sequence:

```text
P1: establish one Luna identity/task path and perform a small local action
P2: follow up on the same Luna to reconfirm persistence
P3: start long-running foreground mutation loop
while P3 is running: issue interrupt_agent exactly once
immediately after interrupt acknowledgement: invoke the native wait/status path for the same Luna
observe until wait/status returns a final status or times out
```

Record:

```text
T0 action start
T1 interrupt request
T2 interrupt acknowledgement + previous_status
T3 first Interrupted status if visible
T4 wait/status final return
T5 final AgentStatus value
T6 completion marker timestamp if produced
T7 last mutation timestamp/sequence
T8 process disappearance/exit observation if available
```

Mandatory checks:

1. mutations after T2 are expected to be possible and do not fail the A semantics;
2. determine whether any mutation occurs after T4;
3. determine whether any child completion/result arrives after T4;
4. determine whether `wait_agent` times out while status is merely `Interrupted` and only returns after a later final state;
5. do not classify `Interrupted` itself as settled;
6. do not use a fixed sleep as the settlement decision.

G2 passes only if current-App evidence establishes a concrete rule equivalent to:

```text
final native AgentStatus observed through wait/status
=> no later execution mutation/result from the old child turn
```

If mutations/results can occur after final status, or the current App cannot expose/consume the final status reliably, classify:

```text
G2=BLOCKED_NO_RELIABLE_SETTLED_EVENT
```

Do not change V3.1 into a PID supervisor as an automatic response.

## 8. Acceptance pass C — G3 source/runtime reconciliation

Do not install diagnostic Hooks.

First record the exact-source result from §4.1.

Then inspect only already-available current-App/runtime evidence for whether child tool Hook payloads are surfaced anywhere in existing logs/events without changing configuration.

If direct wire evidence is already available, verify:

```text
child PreToolUse agent_id == spawned Luna agent_id
child agent_type == expected Luna role
root PreToolUse has no child agent identity or is otherwise distinguishable
```

If direct wire evidence is not available from the current App surface, classify:

```text
G3_SOURCE_SUPPORT=PASS
G3_RUNTIME_WIRE_OBSERVATION=DEFERRED_TO_TARGET_PROFILE_ACCEPTANCE
```

Do not downgrade exact-source support merely because the UI hides the payload.

## 9. Acceptance pass D — G8 serialized-spawn reconciliation

Use exactly one spawned Luna; do not create competing children merely to force an ambiguous race.

Record the strongest available current-App evidence:

```text
root task path/session
spawn tool call/result
returned task path
SubagentStart-visible identity if surfaced
Luna task path
follow-up reuse path
interrupt/wait target path
no second spawn
```

Combine this with exact-source facts from §4.4.

G8 may be classified implementation-compatible if all of these hold:

```text
only one pending spawn is permitted by Router design
current App produces one unambiguous child for the serialized spawn
returned path/agent identity remains stable across follow-up
old/stale child cannot be confused with a newer active Luna in the observed scenario
missing shared spawn correlation is explicitly handled by fail-closed serialized reservation
```

Do not claim a stronger shared correlation field than the source actually exposes.

## 10. G4/G5/G6/G7 staging

The current authenticated App does not yet run the installed V3.1 target profile, so current-profile behavior cannot prove target-profile hard guarantees.

Therefore:

```text
G4_NO_DESCENDANTS=TARGET_PROFILE_ACCEPTANCE
G5_NESTED_CODEX=TARGET_PROFILE_ACCEPTANCE_OR_CLAIM_NARROWING
G6_NATIVE_AUTHORITY_PROFILE=TARGET_PROFILE_ACCEPTANCE
G7_A1_CAPABILITY_MATRIX=TARGET_PROFILE_ACCEPTANCE
```

Source inspection may reduce uncertainty, but current-profile active probes must not be reported as final V3.1 profile PASS.

Do not restore V2 `hard_mode_no_process` merely because G5 remains unresolved.

## 11. G9 staging

No new economics/soak experiment is required in this pass.

```text
G9_SHORT_CONTEXT_REUSE=PASS
G9_LONGEVITY_ECONOMICS=DEFERRED_SOAK_EVIDENCE
```

G9 economics does not block live safety activation unless it reveals a correctness failure.

## 12. Runtime acceptance report contract

Return exactly these classifications, with concise evidence:

```text
CURRENT_APP_RUNTIME_IDENTITY=
SOURCE_LINEAGE_RECONCILED=

P1_PERSISTENT_REUSE=
G2_SETTLEMENT_OBSERVATION=
G2_FINAL_STATUS=
G2_MUTATION_AFTER_INTERRUPT_ACK=
G2_MUTATION_AFTER_FINAL_STATUS=
G2_LATE_RESULT_AFTER_FINAL_STATUS=

G3_EXACT_SOURCE_SUPPORT=
G3_CURRENT_APP_WIRE_OBSERVATION=

G8_SOURCE_CORRELATION=
G8_CURRENT_APP_RECONCILIATION=

G4_NO_DESCENDANTS=
G5_NESTED_CODEX=
G6_NATIVE_AUTHORITY_PROFILE=
G7_A1_CAPABILITY_MATRIX=
G9_SHORT_CONTEXT_REUSE=
G9_LONGEVITY_ECONOMICS=

LIVE_STATE_INTEGRITY=
LIVE_CODEX_HOME_CHANGED=
HOOK_TRUST_CHANGED=
NEW_OAUTH_CREATED=
PR_CHANGED=

LIVE_ACTIVATION=
PR_READY_OR_MERGE=
FINAL_DISPOSITION=
```

Allowed final disposition after this pass is still one of:

```text
RUNTIME_ACCEPTANCE_PARTIAL_PASS
BLOCKED_RUNTIME_ASSUMPTION
INCONCLUSIVE_RUNTIME_EVIDENCE
```

Do not return `LIVE_ACTIVATION=PASS` unless all remaining live safety gates required by the implementation status are actually closed against the target profile.
