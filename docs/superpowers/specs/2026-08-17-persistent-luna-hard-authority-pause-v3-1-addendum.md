# Codex Router V3.1 — Hard Authority Pause and Runtime-Gate Addendum

Date: 2026-08-17
Status: DESIGN ADDENDUM; USER-APPROVED PRODUCT SEMANTICS; NOT IMPLEMENTED
Repository: `EthanSangSSS/codex-router`
Branch: `hardening/native-luna-safety-v2`
PR: #8
Parent design: `docs/superpowers/specs/2026-08-17-persistent-luna-minimal-control-plane-v3-1-design.md`

## 1. Authority and scope

This addendum is normative for V3.1 where it conflicts with the parent design. All parent-design sections not changed here remain authoritative.

This addendum records two decisions established after current-App runtime smoke validation:

1. **Hard User Pause is defined as Hard Authority Pause, not guaranteed immediate process termination.**
2. **Authenticated standalone-root validation is no longer a prerequisite for implementation planning.** Runtime gates are staged according to whether the current App can meaningfully prove them before the V3.1 target profile exists.

This document does not authorize implementation, live installation, Hook trust changes, PR ready-for-review, or merge.

## 2. Current-App runtime evidence

The validation used the currently authenticated Codex App root with no new `CODEX_HOME`, no new OAuth, no live Router/config mutation, and a benign `/tmp/codex-router-luna-smoke` task.

Observed facts:

- exactly one Luna task path was created: `/root/luna_native_smoke`;
- the same Luna task path completed two related packets without a second spawn;
- the second packet retained useful task context from the first;
- the smoke project passed 2 tests after packet 1 and 3 tests after packet 2;
- `interrupt_agent` returned while the target's previous status was `running`;
- after interrupt acknowledgment, an already-started foreground process remained alive;
- its progress file continued from 70 lines to 150 lines;
- completion occurred after interrupt acknowledgment and the process then exited naturally;
- no native numeric `agent_id`, generation identifier, `SubagentStart` correlation identifier, or Hook actor field was exposed by the current orchestration surface;
- no descendant, nested Codex, target V3.1 authority profile, or A1 mutation probe was executed;
- live `~/.codex`, Hook trust, Router, repository implementation, and PR state were unchanged.

These observations are product-runtime evidence, not proof of fields or target-profile properties that were not exposed or installed.

## 3. P1 persistent-Luna disposition

The current-App smoke test establishes **runtime feasibility of the product-level P1 behavior**:

```text
spawn one Luna
  -> complete packet 1
  -> keep the same Luna task path
  -> follow up with packet 2
  -> preserve useful context
  -> no replacement spawn
```

Therefore V3.1 may plan around persistent reuse as the normal path.

The stronger implementation acceptance claim still requires the Router implementation to bind and reconcile the strongest native identity/profile information actually available to it. If the implementation layer exposes `agent_id`, parent relationship, role, generation, or equivalent identifiers that the App orchestration surface did not expose, acceptance tests must use them.

The absence of those fields in the current App surface is not itself a reason to abandon P1.

## 4. Hard Authority Pause

### 4.1 Normative meaning

V3.1 replaces the ambiguous phrase **Hard User Pause** with the following exact contract:

```text
Hard Authority Pause = immediate Router authority freeze
                     != guaranteed immediate OS/process/tool kill
```

When pause, cancel, stop, or a conflicting replacement packet is accepted by Sol, the current packet generation loses authority immediately even if a native action that started before the pause continues running.

### 4.2 Immediate authority-freeze effects

On transition from `ACTIVE(N)` to `QUIESCING(N)`:

- generation N becomes non-runnable for future scheduling;
- no new Luna packet may be dispatched under generation N;
- no generation N completion/result may advance current Router authority after supersession;
- no generation N result may authorize scope expansion, Luna replacement, or A1 execution;
- no new generation may begin while the old execution remains unsettled;
- native interrupt may be requested, but interrupt acknowledgment is not settlement.

The authority freeze is immediate even when underlying native execution is not.

### 4.3 Already-started native actions

A shell/process/tool action that began before the authority freeze may continue until it:

- is actually interrupted/terminated by the native runtime; or
- completes naturally; or
- reaches another runtime-observable terminal condition that proves it can no longer mutate the old execution context.

V3.1 does **not** promise to kill a PID/process group instantly and does not add a custom process supervisor solely to create that promise.

This is a deliberate Minimal Control Plane boundary, not a temporary omission.

### 4.4 Settlement condition

The old execution is `SETTLED` only when Router can observe a reliable terminal condition showing that the old executable work can no longer overlap a later generation.

The settlement condition may result from native interruption **or natural completion**. Therefore the design no longer requires proof that `interrupt_agent` itself causes settlement.

The required property is:

```text
authority freeze
  -> optional native interrupt
  -> observe reliable terminal/settled condition
  -> only then PAUSED_SETTLED / CANCELLED / ACTIVE(N+1)
```

A timeout, fixed sleep, interrupt acknowledgment, or merely marking generation N stale is not sufficient to declare `SETTLED`.

### 4.5 State machine

```text
ACTIVE(N)
  -> QUIESCING(N)          # authority frozen immediately
      -> PAUSED_SETTLED    # only after old execution is terminal/settled
          -> ACTIVE(N+1)   # only after legitimate resume/new direction
```

`CANCELLED` and `RETIRED` remain valid terminal/administrative states.

If the user cancels while native execution is still in flight, Router may mark the task logically cancelled but must retain enough quiescence state to reject stale output and prevent overlap until the old execution is observably settled.

## 5. G2 revised capability gate

The parent design's G2 requirement is replaced by:

### G2 — Authority freeze and settlement observation

Validate that:

1. Router can freeze old packet authority before sending or accepting replacement work;
2. `interrupt_agent` acknowledgment is never used as a settlement barrier;
3. Router can observe a reliable terminal/settled condition after the freeze, whether caused by interrupt or natural completion;
4. generation N+1 is not dispatched before that condition;
5. any late N output is rejected for current authority;
6. already-started irreversible A1 actions are outside the corrective power of pause and therefore remain governed by pre-action A1 authorization.

Current-App evidence already proves item 2 and demonstrates why item 3 is necessary: execution continued after interrupt acknowledgment.

Implementation planning must specify the fail-closed `QUIESCING` behavior and the runtime observation mechanism to be exercised by acceptance tests. If the implementation layer exposes no trustworthy terminal condition, the product must remain unable to resume/replace across that boundary rather than guessing settlement.

## 6. Runtime-gate staging

The previous validation workflow treated all G1-G9 as pre-implementation exact-runtime gates. That staging is no longer normative.

The gates now have three stages.

### 6.1 Product-runtime feasibility evidence available now

The current App smoke test provides sufficient product-level evidence to plan around:

- **G1 / P1:** persistent same-Luna follow-up is feasible in the real App workflow;
- **G2:** interrupt acknowledgment is not settlement; Hard Authority Pause must separate authority freeze from execution settlement;
- **G9:** same-Luna short-horizon context reuse is feasible.

These are not claims that every stronger identity/economics acceptance criterion is already satisfied.

### 6.2 Implementation/acceptance evidence

The following should be proven by the V3.1 implementation or its target profile because the current App orchestration surface does not expose enough information, or because the property does not exist until the target profile is rendered:

- **G1 strong identity/profile proof:** strongest available native Luna identity, role, parent relation, and authority-profile reconciliation;
- **G2 settlement observation:** exact terminal condition used to leave `QUIESCING`;
- **G3 actor attribution:** Hook/runtime actor fields actually available to Router at implementation level;
- **G4 no descendants:** effective tool inventory with the V3.1 disable triad installed in a controlled target profile;
- **G5 nested Codex:** whether Full Executor can resolve/launch nested Codex and what enforceable claim is supportable;
- **G6 native workspace/profile:** actual `native_workspace_boundary` and profile-update behavior of the V3.1 profile;
- **G7 A1 capability matrix:** exact pre-action gate for every enabled external/persistent mutation surface;
- **G8 durable correlation/recovery:** strongest correlation identifiers and ordering available to Router, including restart behavior;
- **G9 economics:** token/credit/latency/compaction behavior over a representative longer-lived task sequence.

Missing evidence at these gates must narrow or block the corresponding **live capability claim**. It must not be silently inferred from the smoke test.

### 6.3 Live-activation blockers

Before live activation or a merge-ready claim, V3.1 must still demonstrate:

- no usable Luna descendant path under the effective target profile;
- an accurate nested-Codex threat claim;
- a proven workspace/authority-profile model;
- the A1 matrix for every enabled hard-enforcement surface;
- reliable settlement observation before cross-generation execution;
- sufficient identity/correlation evidence to reject ambiguous stale lifecycle events;
- state-file integrity and restart behavior;
- no unsupported hard guarantee whose required native primitive is absent.

Thus the gate realignment changes **when** evidence is collected, not the standard required for live claims.

## 7. Validation topology decision

A standalone disposable authenticated root is no longer part of the normal V3.1 validation path.

Normative constraints:

- do not request or create new OAuth credentials solely for Router validation;
- do not copy/reuse live authentication to manufacture a standalone harness;
- do not require a synthetic root to prove product behavior that can be observed in the actual Codex App;
- prefer small, bounded, current-App smoke tasks for native lifecycle feasibility;
- use implementation-level instrumentation and a controlled target profile for properties that only exist after V3.1 is implemented;
- keep real external A1 mutations out of validation; use safe/local analogues where needed.

The earlier standalone-root/device-auth exploration remains historical evidence about configuration topology and authentication isolation, but it is not an ongoing project requirement.

## 8. A1 remains independent of pause

Hard Authority Pause does not weaken A1.

An irreversible side effect already sent to an external system may not be recoverable after pause. Therefore any surface for which V3.1 claims hard A1 enforcement still requires a pre-action mechanical gate.

The control model remains:

```text
Hard Authority Pause
+ stale-generation rejection
+ A1 pre-action authorization
```

These mechanisms solve different problems and must not be substituted for one another.

## 9. Minimal-Control-Plane consequences

This decision explicitly rejects adding any of the following solely to make pause mean immediate process death:

- Router-owned PID/process-group supervision for ordinary Luna work;
- periodic Sol polling to watch process liveness;
- global `no_process` mode;
- a broad shell parser;
- a broad ordinary-tool allowlist/firewall.

If a native tool offers deterministic cancellation, Router may use it as an optimization, but V3.1 correctness does not depend on immediate kill. Correctness depends on authority freeze, stale-result rejection, and observed settlement before replacement execution.

## 10. Implementation-planning gate

After this addendum is reviewed and accepted, V3.1 is eligible for implementation planning under these conditions:

- the implementation plan must preserve Hard Authority Pause semantics exactly;
- it must specify a fail-closed `QUIESCING` state when settlement is not yet observable;
- it must not claim G3-G8 target-profile properties before the implementation/acceptance evidence exists;
- it must explicitly stage G4-G7 acceptance after the target profile/control plane exists;
- it must keep PR #8 Draft and live activation blocked until the acceptance gates in section 6.3 are closed;
- no new OAuth/device-auth requirement may be introduced for normal V3.1 validation;
- no V2 broad execution firewall may be restored merely because a native runtime field is hidden.

Implementation planning is permission to design the code/test sequence, not evidence that live activation is safe.

## 11. Current disposition

```text
TARGET_DESIGN=V3.1_PLUS_THIS_ADDENDUM
P1_PRODUCT_RUNTIME_FEASIBILITY=PASS
HARD_AUTHORITY_PAUSE_SEMANTICS=RESOLVED
INTERRUPT_ACK_AS_SETTLEMENT=REJECTED_BY_RUNTIME_EVIDENCE
G2_SETTLEMENT_OBSERVATION=IMPLEMENTATION_ACCEPTANCE_GATE
G3_G8_HIDDEN_RUNTIME_FIELDS=DEFERRED_TO_IMPLEMENTATION_ACCEPTANCE
G4_G7_TARGET_PROFILE_GATES=DEFERRED_TO_TARGET_PROFILE_ACCEPTANCE
G9_SHORT_CONTEXT_REUSE=PASS
G9_ECONOMICS=DEFERRED_TO_SOAK_ACCEPTANCE
NEW_OAUTH_FOR_VALIDATION=FORBIDDEN
STANDALONE_AUTHENTICATED_ROOT=NORMAL_PATH_DROPPED
IMPLEMENTATION=NOT_STARTED
LIVE_ACTIVATION=BLOCKED
PR_READY_OR_MERGE=BLOCKED
```
