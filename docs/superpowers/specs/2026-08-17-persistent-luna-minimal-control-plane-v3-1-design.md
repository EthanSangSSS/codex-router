# Codex Router V3.1 — Persistent Luna Minimal Control Plane

Date: 2026-08-17
Status: DESIGN REVISED AFTER ADVERSARIAL REVIEW; SECOND-PASS REVIEW REQUIRED; NOT IMPLEMENTED
Repository: `EthanSangSSS/codex-router`
Branch: `hardening/native-luna-safety-v2`
PR: #8
Supersedes as target design: `2026-08-17-persistent-luna-minimal-control-plane-v3-design.md`
Current repository implementation: V2; unchanged by this document

## 1. Purpose

V3.1 preserves the product direction approved for V3 while adding only the narrow mechanical boundaries required by the adversarial review.

The target remains:

- Sol is the user-facing coordinator, planner, reviewer, controller, and final responder.
- Luna is the default substantive executor and should perform the full inspect/research/edit/test/debug/retry/verify loop with broad ordinary execution capabilities.
- Sol supervision is event-driven rather than continuous polling.
- One persistent Luna is reused across a coherent task whenever the native runtime safely permits it.
- Router owns delegation identity, lifecycle, packet authority, user preemption, and explicit external-side-effect authorization boundaries.
- Router does not become a second general-purpose per-tool security runtime.
- User pause/cancel/new-direction commands always outrank Luna execution.

This document is design authority only. It does not authorize implementation, live installation, Hook trust changes, merge, or ready-for-review transition.

## 2. Locked product decisions, refined by review

The following decisions remain normative:

- **A1 — Full Executor with explicit external-side-effect authorization**, refined so a hard authorization claim requires a proven mechanical pre-action gate.
- **P1 — One persistent Luna per task epoch**, not one disposable Luna per root turn and not one Luna forever across unrelated tasks.
- **S1 — Safety/Scope Preemption**, refined with an explicit quiescence/settlement barrier.
- **Hard User Pause**, refined so interrupt acknowledgment alone is not treated as settled pause.
- **Event-driven Sleeping Sol** — no periodic model polling or heartbeat review.
- **E2 — Evidence-driven Autonomous Escalation**, refined so Luna escalation is an untrusted proposal, never an authorization source.
- **M1 — Minimal Control Plane** — no broad ordinary-tool positive allowlist.
- **R1 — Default-to-Luna routing**.
- **K1 — Minimal Task Packet**, refined to distinguish semantic packet write intent from native sandbox authority.
- **F1 — Controlled Replacement**, refined to allow replacement for task-epoch reset or native authority-profile change as well as unrecoverable runtime failure.
- **J1 — Minimal Durable Control State**, refined with task/turn/generation correlation and structured spawn reservation.
- **H1' — Minimal Required Hook Surface** — four baseline Hooks, with a narrowly scoped A1-specific permission gate allowed only if runtime evidence proves it necessary.

## 3. Role model

### 3.1 Sol — control plane

Sol owns:

- user interaction and intent interpretation;
- direct-vs-Luna routing under R1;
- task decomposition and packet creation;
- creation and binding of the authoritative Luna;
- pause, quiesce, resume, interrupt, cancel, retire, and controlled replacement;
- A1 authorization decisions;
- independent review of Luna escalation requests;
- result/evidence review;
- correction packets when needed;
- final response.

Sol must not continuously poll Luna. Sol model reasoning should wake only for meaningful user, completion, blocker, authorization, safety/scope, or runtime-failure events.

### 3.2 Luna — execution plane

Subject to native Codex sandbox/approval/runtime controls and the active packet, Luna should normally be able to use:

- read;
- write / `apply_patch`;
- shell / tests / builds;
- Unified Exec / Code Mode where natively available;
- web search;
- MCP / ordinary tools;
- plugins / tool discovery;
- ordinary local development and research operations.

Luna remains prohibited from:

- spawning or delegating to descendant agents;
- intentionally using nested Codex as a delegation workaround;
- bypassing native sandbox or approval controls;
- intentionally retrieving credentials, secrets, or unrelated private data;
- self-authorizing A1 external/persistent side effects;
- expanding its own packet authority, native authority profile, task epoch, or control state.

## 4. Authority identifiers and epochs

V3.1 distinguishes four identities/scopes that must not be conflated:

1. **root/session identity** — the native parent context Router is serving;
2. **task_epoch** — one coherent user task/goal boundary;
3. **luna_epoch** — one authoritative Luna identity/profile within the task epoch;
4. **packet_generation** — the current executable instruction packet within the Luna epoch.

When native runtime evidence permits, each running Luna turn is additionally correlated by a native **child_turn_id** or equivalent turn/execution identifier.

Authority comparison for stale results therefore uses the strongest available tuple:

```text
(root/session identity,
 task_epoch,
 luna_epoch,
 packet_generation,
 child_turn_id if exposed)
```

A result or lifecycle event that does not match the current authoritative tuple cannot itself advance state, grant authority, or be accepted as the current packet's completion.

## 5. P1 persistent Luna lifecycle

### 5.1 Reuse boundary

The persistence unit is a **task epoch**.

Within one task epoch:

1. Sol creates exactly one authoritative `luna_worker` when substantive execution is first needed.
2. Router binds its native `agent_id` and validates its parent/role relationship.
3. Luna executes packet generation N.
4. Idle/completed Luna remains reusable.
5. Later related turns send follow-up/resume work to the same Luna when native runtime semantics support it.
6. A new packet supersedes prior packet authority without revoking Luna identity.

A root-turn boundary is not a Luna-lifecycle boundary.

### 5.2 Task epoch termination

`CANCELLED` terminates the current task epoch. A genuinely independent new task starts a new `task_epoch` even if the prior Luna is technically resumable.

The new task may use:

- a fresh Luna epoch; or
- a runtime-proven context-reset/reinitialization mechanism that establishes an equivalent fresh authority/context boundary.

Absent such a proven reset mechanism, a new independent task uses a new Luna epoch.

## 6. Native authority boundary vs packet write intent

The adversarial review established that a resident V2 child cannot be assumed to accept a new native permission/writable-root profile merely because a follow-up packet contains a narrower scope.

V3.1 therefore separates two concepts.

### 6.1 `native_workspace_boundary`

This is the native mechanical filesystem/sandbox authority associated with a Luna epoch.

Properties:

- established when the Luna epoch/profile is created or loaded;
- stable for that Luna epoch unless the exact runtime exposes and validates a safe in-place authority-profile update;
- normally scoped to the task workspace/worktree/repository rather than a tiny per-packet subdirectory;
- treated as a mechanical security boundary only to the extent proven by native Codex/runtime behavior.

### 6.2 `intended_write_scope`

K1 packets carry `intended_write_scope`, which is the semantic task boundary for writes in the current packet.

Properties:

- may narrow or change between packets inside the same `native_workspace_boundary`;
- does **not** claim to dynamically reconfigure a resident Luna's native sandbox;
- is an instruction/control contract reviewed by Sol, not hostile-agent filesystem containment;
- does not trigger Luna replacement merely because one packet writes `src/auth/**` and the next writes `src/api/**` inside the same native boundary.

If a task requires write authority outside the current `native_workspace_boundary`, Sol must either use a runtime-proven authority-profile update or perform controlled Luna replacement with a new native authority profile.

This preserves P1 persistence without making a false mechanical claim about per-packet sandbox mutation.

## 7. K1 minimal task packet

Each packet remains self-contained and small.

Required fields:

- `packet_id` / monotonic `generation`;
- `objective`;
- `working_directory`;
- `intended_write_scope`;
- `explicit_side_effect_authorizations`;
- `success_criteria`;
- `stop_conditions`.

Defaults that need not be repeated:

- task-relevant reads within the current native workspace are allowed;
- ordinary tools are available subject to native controls;
- web/MCP/shell/build/test/debug/retry are ordinary Luna capabilities;
- Luna should autonomously inspect, research, implement, test, diagnose, retry, and verify;
- Luna must respect `intended_write_scope` even when the native workspace boundary is broader;
- A1 persistent side effects require current-packet authorization and, where V3.1 claims hard enforcement, a proven mechanical pre-action gate;
- descendant agents and nested-Codex delegation are prohibited.

A new packet replaces prior packet authority; packet permissions are not additive.

## 8. Hard pause and quiescence settlement

Native `interrupt_agent` acknowledgment is not treated as a quiescence barrier.

### 8.1 Control states

Minimum active-path states are:

```text
ACTIVE
  -> QUIESCING
      -> PAUSED_SETTLED
      -> ACTIVE(new generation)   # only after legitimate resume/new direction
```

Additional terminal/administrative states may include `CANCELLED` and `RETIRED`.

### 8.2 Hard-pause sequence

For user pause/stop/cancel or a conflicting replacement packet:

1. mark the old packet non-runnable for future scheduling;
2. move control state to `QUIESCING`;
3. send native interrupt when Luna is executing;
4. do **not** treat interrupt acknowledgment as settlement;
5. observe the exact runtime event/status required to prove the old Luna turn has reached the design's validated `SETTLED` condition;
6. only then transition to `PAUSED_SETTLED`, cancellation, or a new packet generation as appropriate.

The exact native evidence that constitutes `SETTLED` is a mandatory runtime capability-validation gate before implementation planning.

### 8.3 Stale result rejection

Any delayed completion/result/event from a superseded `(task_epoch, luna_epoch, packet_generation, child_turn_id)` is stale.

Stale data may be logged as diagnostic evidence but must not:

- mark the current packet complete;
- authorize a transition;
- expand scope;
- satisfy an A1 decision;
- overwrite the current Luna binding.

An already-started irreversible external side effect cannot be undone by quiescence. That is why A1 remains a pre-execution authorization boundary.

## 9. S1 preemption

Sol may interrupt Luna without explicit user pause only for bounded reasons:

- current execution conflicts with new user input;
- Luna is continuing a superseded packet;
- Luna is clearly outside the semantic packet scope;
- an unauthorized A1 side effect is about to be attempted on a surface where Sol receives a pre-action gate;
- credible safety, destructive-data, or irreversible risk is present;
- Luna is repeating the same failure pattern without a new hypothesis.

Sol should not interrupt for stylistic preference or marginal implementation differences.

## 10. Event-driven Sleeping Sol

Normal Luna execution does not wake Sol for progress polling.

No design requirement calls for periodic:

- `list_agents`;
- `wait_agent` loops;
- heartbeat messages;
- intermediate Sol reasoning turns;
- routine test/debug relay.

Runtime state observation and Hook bookkeeping may occur without Sol model reasoning.

Sol wakes for:

1. user input;
2. Luna completion/result;
3. E2 blocker/decision escalation;
4. A1 authorization requirement;
5. credible safety/scope event;
6. settlement/control event when a user/packet action already requires Sol participation;
7. unrecoverable Luna/runtime failure.

## 11. E2 evidence-driven autonomous escalation

Luna must first investigate and attempt reasonable solutions while it has meaningful new hypotheses.

Ordinary test/lint/build errors, API uncertainty, documentation lookup, patch conflicts, dependency uncertainty, and routine tool failures are not escalation events.

Allowed escalation classes remain:

- `DECISION_REQUIRED`;
- `SCOPE_CHANGE_REQUIRED`;
- `SIDE_EFFECT_AUTH_REQUIRED`;
- human/product-intent ambiguity;
- `BLOCKED` after evidence shows further attempts would repeat the same failure mode without a credible new hypothesis.

### 11.1 Untrusted proposal rule

Every Luna escalation is an **untrusted proposal**, not authority.

Luna output can never itself authorize:

- broader intended write scope;
- a wider native workspace/authority profile;
- an A1 external side effect;
- a new task epoch;
- a replacement Luna;
- bypass of native approval/sandbox controls.

Sol must independently evaluate evidence. A1 authority must be grounded in existing explicit user intent/authorization or a direct user decision obtained by Sol; Luna's request is never sufficient provenance.

## 12. A1 external-side-effect boundary

### 12.1 Policy goal

A1 remains a **hard policy goal**: listed external/persistent side effects must not be intentionally executed by Luna unless the current packet explicitly authorizes the exact category/action.

Categories include:

- `git push`;
- create/materially modify PR or equivalent remote collaboration state;
- deploy/release/publish;
- send email or other outbound user communication;
- cloud resource create/modify/delete;
- system-level install or equivalent host-wide persistent modification;
- comparable external/persistent mutations.

Authorization is packet-scoped and non-inheriting across packets, Luna epochs, or task epochs.

### 12.2 Mechanical-enforcement requirement

Packet text alone is not accepted as mechanical enforcement.

Before implementation planning, an **A1 capability matrix** must map each enabled A1 surface to the exact pre-action enforcement primitive available on the bundled runtime, such as:

- a structured tool-level authorization event;
- a native sandbox/network/write restriction;
- an approval gate whose actor and action are reliably attributable;
- another runtime primitive that blocks execution until authorization is resolved.

For any enabled surface where no reliable pre-action gate exists, V3.1 must choose one of these outcomes explicitly:

1. disable/withhold that mutating capability in the baseline Luna profile while retaining ordinary non-mutating/full-local-executor capabilities;
2. expose it only through a separately authorized native capability/profile elevation whose lifetime is bounded and auditable; or
3. classify the boundary as cooperative-only and therefore **not** satisfy the A1 hard guarantee for that surface.

Outcome 3 is not acceptable if the final product still claims hard A1 enforcement for that surface.

### 12.3 No broad command firewall

V3.1 does not restore a general shell-command parser, broad positive tool allowlist, or V2-style ordinary-tool firewall merely to implement A1.

If a `PermissionRequest` Hook or equivalent is required, it must be narrowly limited to the proven A1 interception use case and must not become general child execution policing.

## 13. No-descendant invariant

Full Executor does not mean Multi-Agent Executor.

The Luna role must mechanically disable child multi-agent capability at the configuration/feature level. The target profile must preserve the effective equivalent of:

```toml
[agents]
enabled = false

[features]
multi_agent = false
multi_agent_v2 = false
```

The lifecycle `PreToolUse` gate remains a second line of defense for lifecycle calls and authoritative targeting.

Acceptance requires runtime evidence of the **effective Luna tool inventory/configuration**, not merely rendered config text. Luna must not expose a usable descendant-spawn/delegation path.

Ordinary shell/process capability may return for Full Executor; that does not authorize nested Codex. Whether nested Codex can be resolved/launched under the exact Luna sandbox is a separate runtime gate.

## 14. M1 minimal control-plane enforcement

Router mechanically owns only narrow control/delegation invariants:

1. one authoritative Luna per task epoch;
2. correct native parent/role/agent identity binding;
3. no Luna descendants;
4. user/Sol pause, quiescence, resume, cancel, retire, and replacement authority;
5. hard pause cannot self-clear;
6. only the current packet generation can schedule new work;
7. stale prior-generation results cannot advance current state;
8. old and new packet execution must not overlap across a replacement boundary once the design declares the old execution settled;
9. controlled replacement rules;
10. A1 only on narrowly proven mechanical surfaces, without broad ordinary-tool policing.

Router does not impose a positive allowlist on normal read/write/shell/web/MCP/plugin/tool execution.

## 15. F1 controlled replacement

Replacement remains exceptional and must not become per-turn or per-packet churn.

A new Luna epoch is allowed only for one of these reasons:

1. **unrecoverable runtime identity** — current Luna cannot be resumed/reused;
2. **new task epoch** — prior task was cancelled/terminated and the new goal is genuinely independent, absent a proven safe context reset;
3. **native authority-profile change** — required work lies outside the current `native_workspace_boundary` or another native capability boundary cannot be safely updated in place;
4. **runtime-validated context reset policy** — a later soak test may establish a bounded context-growth/reset threshold, but this must not become arbitrary per-turn replacement.

Ordinary changes to `intended_write_scope` inside the same native workspace do not justify replacement.

Replacement flow:

1. quiesce/settle the old executable turn if needed;
2. mark old Luna epoch `RETIRED` for Router authority;
3. advance `luna_epoch`;
4. create exactly one replacement Luna with the required native profile;
5. bind and validate its native identity/role/parent relation;
6. issue a new self-contained K1 packet;
7. do not inherit prior packet A1 authorization unless explicitly re-authorized in the new packet.

Idle/completed status alone does not justify replacement.

## 16. J1 minimal durable control state

Router persists only state necessary to make control-plane decisions deterministic; it does not persist execution history or transcript content.

Conceptual state:

```text
root_session_key
root_thread_id / native parent identity
task_epoch
luna_epoch
luna_agent_id
luna_role / validated native path relationship
native_authority_profile_id_or_hash
packet_generation
active_child_turn_id_or_equivalent   # when exposed/required
control_state
pending_spawn_reservation
```

### 16.1 Spawn reservation

`pending_spawn_reservation` is not a boolean. It includes at least:

```text
task_epoch
luna_epoch
expected_role
root/session identity
expected native parent identity
spawn correlation id, if the runtime exposes one
```

`SubagentStart` may establish a tentative binding; authoritative binding is committed only when the available spawn-result/lifecycle evidence corroborates the same reservation.

If no shared native correlation ID exists:

- spawn operations must be serialized;
- ambiguous or mismatched events fail closed for Router authority;
- native parent/role/agent graph reconciliation is required before accepting the binding.

### 16.2 Durable identity recovery

On restart/recovery, Router must not accept an `agent_id` merely because the native runtime says it exists or is resumable.

Recovery validates, to the extent the exact runtime exposes it:

- root/session identity;
- native parent/descendant relationship;
- expected Luna role/type;
- current task/luna epoch relationship;
- native authority profile compatibility.

Historical/resumable child identities that fail this validation do not become current Router authority.

### 16.3 Filesystem integrity

Retain:

- non-secret collision-resistant session/task locator hash;
- canonical key inside the record to catch accidental mismatch;
- `0600`;
- owner validation;
- no unsafe symlink substitution;
- locking;
- bounded schema validation;
- atomic replace;
- fsync consistent with existing durability expectations.

Do not retain V2 per-root HMAC authorization scopes unless a later threat model proves a concrete property they add under the stated same-UID host threat model.

## 17. H1' minimal required Hook surface

### 17.1 Baseline Hooks

Baseline managed Hooks remain:

```text
UserPromptSubmit
PreToolUse
PostToolUse
SubagentStart
```

Responsibilities remain narrow:

- `UserPromptSubmit`: control intent and minimal R1 routing/control-state transition;
- `PreToolUse`: agent lifecycle/control-plane operations only;
- `PostToolUse`: spawn-result reconciliation only;
- `SubagentStart`: tentative native identity binding/correlation only.

`Stop` must not revoke persistent Luna identity.

### 17.2 Conditional A1 Hook

`PermissionRequest` is **not** part of the baseline ordinary-tool firewall.

It may be retained or reintroduced only if the A1 capability matrix proves that a specific enabled external-mutation surface requires it as the narrow mechanical pre-action gate and actor attribution is runtime-validated.

If used, its policy surface must be limited to A1 authorization and must not restore broad child tool denial.

The design goal is minimal proven enforcement, not a fixed Hook count for its own sake.

## 18. Packet replacement sequencing

A packet replacement while Luna is executing follows:

```text
current generation N ACTIVE
  -> mark N superseded for future scheduling
  -> QUIESCING(N)
  -> native interrupt if required
  -> wait for runtime-proven SETTLED evidence (event-driven, no Sol polling loop)
  -> reject/ignore late N results for authority
  -> advance generation to N+1
  -> send K1 packet N+1 to the same Luna when P1 reuse remains valid
  -> ACTIVE(N+1)
```

A new packet must not begin merely because `interrupt_agent` returned successfully.

## 19. Failure and race handling

Implementation planning must explicitly prove behavior for:

- user pause during an in-flight write/process/MCP/tool call;
- late result after packet supersession;
- new packet arriving before old-turn settlement;
- `PostToolUse` and `SubagentStart` in either order;
- spawn failure leaving a stale reservation;
- delayed `SubagentStart` from retired Luna epoch E racing with pending epoch E+1;
- cancelled task followed by a new independent task;
- restart with a historically resumable but non-authoritative Luna ID;
- capacity errors with idle versus active persistent Luna;
- authority-profile change requiring controlled replacement;
- A1 tool/shell/MCP surface that has no proven pre-action gate.

Fail closed for **delegation identity, packet authority, settlement, and hard A1 claims**. Do not fail closed by globally disabling ordinary Luna development capabilities.

## 20. Cost/usage objective

The target economics remain:

```text
Sol: understand + plan + K1 packet
  -> Luna: inspect/research/edit/test/debug/retry/verify
  -> Sol: review + decision/correction only when needed + final
```

No periodic Sol polling, heartbeat review, routine test relay, or ordinary debug relay is allowed by design.

Additional V3.1 bookkeeping must be deterministic runtime/Hook state handling, not repeated Sol model reasoning.

## 21. Security model and non-goals

### 21.1 Router-owned properties

Router intends to own and mechanically validate:

- authoritative task/Luna identity;
- one-Luna-per-task-epoch invariant;
- no Luna descendants;
- user/Sol control authority;
- quiescence/settlement before replacement execution;
- current generation authority and stale-result rejection;
- controlled replacement;
- state-file integrity;
- no automatic inheritance of A1 authorization;
- hard A1 enforcement only on surfaces with a proven pre-action mechanical gate.

### 21.2 Native/runtime-owned properties

Subject to explicit capability validation:

- ordinary tool sandboxing;
- filesystem/process/network restrictions;
- approval mechanics;
- MCP/tool/plugin capability inventory;
- host filesystem/system permissions beyond Router state.

### 21.3 Explicit non-goal

V3.1 is not hostile-agent containment and does not independently parse/block every arbitrary shell command or external protocol.

`intended_write_scope` is therefore a semantic task contract inside the proven `native_workspace_boundary`, not a claim of dynamic hostile-child sandbox reconfiguration.

## 22. Migration from V2

The target still removes or simplifies V2 machinery that does not serve a demonstrated runtime invariant.

### 22.1 Delete/simplify after replacement invariants are proven

- per-root HMAC authorization journal;
- per-root `ACTIVE -> REVOKED` Luna identity semantics;
- `Stop` identity revocation;
- broad ordinary-tool positive allowlist;
- hard global `no_process` restriction for normal build/test/debug work;
- per-tool generation ACL;
- complex bilingual routing keyword taxonomy;
- parent lifecycle ACLs unrelated to the narrowed control plane.

### 22.2 Retain narrowly

- Luna multi-agent feature disable;
- lifecycle `PreToolUse` control gate;
- native `agent_id`/role/parent binding;
- spawn-result reconciliation;
- state owner/0600/no-symlink/locking/atomic/fsync reliability;
- only the minimum A1 pre-action gate proven necessary by runtime capability mapping.

Installer backup/rollback/drift safety is orthogonal and should not be rewritten merely because execution authorization is simplified.

## 23. Mandatory runtime capability-validation gates

These gates must be resolved before implementation planning claims the architecture is implementable on the exact deployed runtime.

### G1 — Persistent reuse

Spawn Luna -> complete/idle -> follow-up -> prove same intended `agent_id`, role, parent relation, and expected native authority profile are reused successfully.

### G2 — Interrupt settlement

In a disposable environment, start a benign long-running process/write/tool action, interrupt it, and record:

- interrupt request acknowledgment;
- actual tool/process termination or completion;
- native interrupted/aborted/terminal status transition;
- any delayed completion/result;
- the exact event/state Router may treat as `SETTLED`.

### G3 — Actor attribution

Prove the exact deployed Hook payloads can distinguish primary Sol lifecycle calls from Luna lifecycle attempts wherever V3.1 depends on actor-specific `PreToolUse` or conditional A1 interception.

### G4 — No descendants

Verify effective Luna configuration/tool inventory with the multi-agent disable triad and prove no usable descendant-spawn/delegation path remains.

### G5 — Nested Codex

From disposable Luna execution, determine whether shell can resolve/launch a nested Codex process and what sandbox/approval/Hook behavior applies. If the intended no-nested-Codex property is not mechanically enforceable under Full Executor, the final threat-model claim must be narrowed or a native restriction identified.

### G6 — Native workspace/authority profile

Prove the native `native_workspace_boundary` applied to a Luna epoch and whether any supported in-place profile update exists. If none exists, authority-profile expansion/change uses controlled replacement.

### G7 — A1 capability matrix

For every enabled A1 category, document:

- executable surface(s): shell, structured tool, MCP, plugin, etc.;
- whether the action can occur without a pre-action event;
- exact mechanical gate;
- actor attribution quality;
- fail-open/fail-closed behavior;
- baseline-disabled/elevated-profile fallback when no hard gate exists.

No hard A1 claim is accepted without this matrix.

### G8 — Durable recovery and spawn correlation

Validate native parent/role/agent graph recovery, ordering of spawn result vs `SubagentStart`, and the strongest available correlation identifier. Prove ambiguous delayed lifecycle events do not acquire current authority.

### G9 — Context longevity

Reuse one Luna across a representative task sequence and record context growth, compaction, latency, quality, and token/credit behavior. Introduce a context-reset/replacement threshold only if evidence justifies it.

## 24. Second-pass adversarial review scope

A fresh session should review **this V3.1 document only as the target design** and check current PR/runtime reality before trusting it.

The second pass should be deliberately narrow. It should try to falsify these questions:

1. Does the `QUIESCING -> SETTLED` contract still assume a runtime event that may not exist or may arrive too late to be useful?
2. Can stale old-generation output still alter current state through a path not covered by the correlation tuple?
3. Does the `native_workspace_boundary` / `intended_write_scope` split accurately describe resident Luna behavior without falsely claiming mechanical per-packet write confinement?
4. Can P1 remain economically useful when authority-profile changes, task-epoch resets, and context-growth resets are all accounted for?
5. Does the multi-agent disable triad plus lifecycle gate actually remove descendant capability on the exact runtime?
6. Does any enabled A1 surface still permit an external mutation without a proven pre-action gate?
7. Can conditional `PermissionRequest` remain narrow, or would using it inevitably recreate broad V2 permission policing?
8. Can delayed spawn/lifecycle events bind the wrong `luna_epoch` despite the reservation protocol?
9. Can a historical resumable Luna be confused with the current task epoch after restart?
10. Does any proposed correction require continuous Sol monitoring or materially reintroduce orchestration tax?

Classify each as `PASS`, `FINDING`, `INCONCLUSIVE_RUNTIME_EVIDENCE`, or `OUT_OF_SCOPE`, with concrete evidence.

## 25. Acceptance criteria before implementation planning

Implementation planning remains blocked until:

- this V3.1 spec receives fresh-session second-pass review;
- material design findings are resolved in the spec;
- unresolved dynamic claims are explicit runtime gates, not assumed facts;
- the four high-priority adversarial issues are either closed or deliberately reframed with accurate guarantees: quiescence/generation, scope semantics, multi-agent disable, A1 enforcement;
- no live `~/.codex` installation or Hook trust is changed;
- PR #8 remains Draft unless separately authorized.

## 26. Current disposition

**Target design:** V3.1, revised after adversarial review.

**Repository implementation:** still V2.

**Implementation planning:** blocked pending second-pass V3.1 review and required runtime-gate disposition.

**Live activation:** not authorized.

**Merge / ready-for-review transition:** not authorized.
