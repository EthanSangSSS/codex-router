# Codex Router V3 — Persistent Luna Minimal Control Plane

Date: 2026-08-17
Status: DESIGN APPROVED FOR REVIEW; NOT IMPLEMENTED
Repository: `EthanSangSSS/codex-router`
Branch at design start: `hardening/native-luna-safety-v2`
PR: #8
Previous authoritative implementation design: `2026-08-16-router-authority-realignment-design.md`

## 1. Purpose

V3 realigns Router around the actual product objective:

- Sol remains the primary user-facing coordinator, planner, reviewer, and final responder.
- Luna becomes the default substantive executor with broad normal execution capabilities.
- Router minimizes Sol orchestration overhead and continuous Sol usage.
- Router enforces delegation authority and lifecycle invariants, not a second per-tool security runtime.
- One persistent Luna identity is reused across a Codex task/session whenever runtime semantics permit.
- User control remains supreme: pause, cancel, scope changes, and new directions can preempt Luna.

This document is a target design only. PR #8 remains a V2 implementation until a separate implementation plan is approved and executed.

## 2. Explicitly selected design decisions

The design decisions below were approved together and are normative.

- **A1 — Full Executor with explicit external-side-effect authorization**
- **P1 — One persistent Luna per Codex task/session**
- **S1 — Safety/Scope Preemption**
- **Hard User Pause**
- **Event-driven Sleeping Sol**
- **E2 — Evidence-driven Autonomous Escalation**
- **M1 — Minimal Control Plane**
- **R1 — Default-to-Luna routing**
- **K1 — Minimal Task Packet**
- **F1 — Controlled Replacement**
- **J1 — Minimal Per-Task State**
- **H1 — Four-Hook Minimal Control Plane**

## 3. Core role model

### 3.1 Sol — control plane

Sol is the only user-facing primary coordinator and owns control-plane authority.

Sol responsibilities:

- understand user intent;
- decide direct-vs-Luna routing under R1;
- plan and decompose substantive work;
- create the first Luna when needed;
- issue and replace K1 task packets;
- pause, resume, interrupt, cancel, retire, or replace Luna;
- grant or withhold explicit A1 external-side-effect authorization;
- review Luna evidence and results;
- correct Luna when needed;
- ask the user only when Sol itself cannot resolve a required product/intent decision;
- provide the final answer.

Sol must not continuously poll or supervise Luna through repeated reasoning turns.

### 3.2 Luna — execution plane

Luna is the default substantive executor.

Luna should normally be able to use, subject to native Codex sandbox/approval/runtime controls:

- read;
- write / apply_patch;
- shell / tests / builds;
- Unified Exec / Code Mode where natively available;
- web search;
- MCP / normal tools;
- plugins / tool discovery;
- ordinary local development and research operations.

Luna remains prohibited from:

- spawning or delegating to descendant agents;
- running nested Codex as a workaround;
- bypassing native Codex sandbox or approval controls;
- intentionally retrieving credentials, secrets, or unrelated private data;
- self-authorizing external persistent side effects that the current packet did not authorize;
- modifying its own packet scope or control state.

## 4. A1 external-side-effect boundary

Normal local development and research are autonomous Luna work.

The following categories require explicit authorization in the **current** packet before Luna may intentionally execute them:

- `git push`;
- creating or materially modifying a pull request;
- deploy/release/publish actions;
- sending email or other outbound user communications;
- cloud resource creation/modification/deletion;
- system-level installs or equivalent host-wide persistent modification;
- other comparable external or persistent side effects.

Authorization is packet-scoped and non-inheriting. A later packet or replacement Luna does not automatically inherit prior external-side-effect authorization.

Router does not attempt to parse and independently police every possible shell/tool representation of these side effects. The boundary is enforced primarily by task packet instructions plus native Codex sandbox/approval controls, with Sol retaining preemption authority.

## 5. Persistent Luna lifecycle (P1)

Within one Codex task/session:

1. Sol spawns exactly one `luna_worker` when substantive execution is first needed.
2. Native `agent_id` is bound to the task state.
3. Luna executes packet generation N.
4. When Luna becomes idle/completed, the identity remains reusable.
5. Later substantive turns reuse the same Luna through follow-up/resume semantics.
6. A new packet supersedes the prior packet but does not revoke Luna identity.
7. Luna identity ends only at task/session termination, explicit retirement, or unrecoverable runtime failure.

A root-turn boundary is **not** a Luna-lifecycle boundary.

## 6. Preemption and hard pause

### 6.1 User hard pause

User control outranks all Router execution.

Examples such as `暂停`, `停止`, `不要继续`, `先别做`, `cancel`, or equivalent intent trigger hard pause.

Hard pause semantics:

- the current packet becomes non-runnable;
- Sol interrupts Luna through native lifecycle controls;
- Luna identity remains bound and reusable;
- Luna may not self-resume;
- external-side-effect authorization is frozen while paused;
- Sol may resume only after the user explicitly says to continue/resume or provides a new execution direction;
- Sol must not automatically decide that conditions are safe and resume on its own.

Pause is not equivalent to retiring or replacing Luna.

### 6.2 S1 safety/scope preemption

Even without an explicit user pause, Sol may interrupt Luna only for bounded reasons:

- Luna clearly exceeds current packet scope;
- Luna is about to execute an unauthorized A1 persistent side effect;
- continuing presents credible safety, data-loss, destructive, or irreversible risk;
- new user input conflicts with current Luna work;
- Luna is executing a superseded packet;
- Luna is clearly stuck in a repetitive failure loop without a new hypothesis.

Sol should not interrupt merely because it has a stylistic preference or a marginally different implementation idea.

## 7. Event-driven Sleeping Sol

Sol supervision is event-driven, not polling-driven.

While Luna is executing normally:

- Sol does not repeatedly call `list_agents` or `wait_agent` as a monitoring loop;
- Sol does not perform periodic reasoning turns;
- Luna does not send heartbeat progress merely to wake Sol;
- runtime-native state observation may exist without invoking Sol model reasoning.

Sol wakes only for meaningful events:

1. new user input;
2. Luna completion/result;
3. Luna blocker or decision escalation;
4. A1 side-effect authorization requirement;
5. credible safety/scope violation;
6. unrecoverable Luna/runtime failure.

This minimizes Sol usage while preserving control authority.

## 8. E2 evidence-driven autonomous escalation

Luna must first try to complete execution independently.

Ordinary failures are **not** escalation events. Examples:

- first test failure;
- lint failure;
- patch conflict;
- forgotten API usage;
- dependency-version uncertainty;
- need to read more code;
- need to search documentation;
- ordinary command/tool failure;
- routine merge conflict.

Luna should inspect evidence, diagnose root cause, research, try low-risk alternatives, validate, and iterate while it has meaningful new hypotheses.

Luna may wake Sol only when one of these conditions holds:

### 8.1 `DECISION_REQUIRED`

Multiple materially different viable solutions remain and the correct choice cannot be derived from the packet objective or available evidence. Luna should return concise options, trade-offs, evidence, and a recommendation.

### 8.2 `SCOPE_CHANGE_REQUIRED`

The required fix needs write access or task authority outside the current writable scope.

### 8.3 `SIDE_EFFECT_AUTH_REQUIRED`

A required A1 external/persistent side effect is not explicitly authorized by the current packet.

### 8.4 Human/product intent ambiguity

Continuing requires a product, compatibility, destructive-data, UX, or user-intent choice that cannot be reliably inferred.

### 8.5 `BLOCKED`

Luna has investigated sufficiently that further attempts would repeat the same failure mode without a credible new hypothesis.

Escalation should contain evidence, attempted approaches, remaining hypotheses, and the exact decision or authority required from Sol.

## 9. M1 minimal control-plane enforcement

Router mechanically enforces only delegation/lifecycle invariants:

1. at most one authoritative Luna per Codex task/session;
2. native `agent_id` binding for that Luna;
3. Luna cannot create descendant agents;
4. Sol can pause/resume/interrupt/cancel Luna;
5. hard pause cannot be self-cleared;
6. exactly one current packet generation is authoritative;
7. superseded packet execution is interrupted before replacement work starts;
8. controlled replacement requires retirement/unrecoverability of the old Luna.

Router explicitly does **not** implement a positive allowlist for ordinary execution tools.

Normal read/write/shell/web/MCP/plugin/tool execution is governed by native Codex capabilities, sandbox, approvals, and the packet contract.

## 10. R1 default-to-Luna routing

Routing should be intentionally simple.

Direct Sol handling:

- explicit one-turn direct/bypass marker;
- pause/resume/cancel/control messages;
- obvious trivial conversation/meta interaction;
- very small answers that do not require substantive execution.

Default Luna delegation:

- code modification;
- debugging;
- testing/building;
- repository investigation;
- substantive file analysis;
- web research;
- GitHub/tool operations;
- artifact-producing or otherwise executable work.

Router should avoid a large bilingual keyword/regex taxonomy. Sol performs semantic planning; Router only needs a small direct/control classification surface.

## 11. K1 minimal task packet

Each packet is self-contained and minimal.

Required fields:

- `packet_id` / monotonic `generation`;
- `objective`;
- `working_directory`;
- `writable_scope`;
- `explicit_side_effect_authorizations`;
- `success_criteria`;
- `stop_conditions`.

Defaults that do not need to be repeated in each packet:

- task-relevant read access inside the current workspace/repository is allowed;
- ordinary tools are allowed through native Codex controls;
- web/MCP/shell/build/test/debug/retry are ordinary Luna execution capabilities;
- Luna should autonomously inspect, research, implement, test, debug, retry, and verify;
- writes remain limited to `writable_scope`;
- A1 persistent side effects require explicit current-packet authorization;
- no descendant agents or nested Codex.

A new packet replaces the prior packet's execution authority. Old packet permissions do not remain additive.

## 12. F1 controlled replacement

Replacement is exceptional.

A new Luna may be created only when the current Luna is demonstrably unrecoverable, for example:

- runtime explicitly reports it cannot be resumed/reused;
- its identity no longer exists;
- native follow-up/resume rejects it as terminal/unrecoverable;
- the agent/runtime has failed in a way that prevents continuation.

Replacement flow:

1. confirm old Luna is unrecoverable;
2. mark old Luna `RETIRED`;
3. increment `luna_epoch`;
4. create exactly one replacement Luna;
5. bind the new native `agent_id`;
6. issue a new self-contained K1 recovery packet;
7. do not inherit old packet A1 authorization unless Sol explicitly includes it again.

Idle, completed, or temporarily capacity-blocked does not by itself justify replacement.

## 13. J1 minimal durable per-task state

Router stores only control-plane state, not execution history.

Conceptual state:

```text
session/task
├─ luna_agent_id
├─ luna_epoch
├─ packet_generation
├─ control_state
└─ pending_spawn
```

`pending_spawn` exists only during initial creation or controlled replacement.

Minimum control states:

- `ACTIVE`
- `PAUSED`
- `CANCELLED`
- `RETIRED` as an old-Luna terminal marker during replacement/cleanup semantics

The design should not retain V2's per-root HMAC authorization scopes or monotonic `ACTIVE -> REVOKED` identity lifecycle.

Recommended filesystem reliability properties:

- per-session/task state file using a non-secret stable hash for filename selection;
- `0600` permissions;
- owner validation;
- reject unsafe symlink substitution;
- file locking;
- bounded validated schema;
- atomic replacement;
- fsync as appropriate for the existing installer/runtime durability expectations.

HMAC/session-secret machinery is not part of the V3 target unless a later threat-model review demonstrates a concrete security property that ordinary owner-protected state does not provide.

## 14. H1 four-hook surface

The target managed Hook surface is exactly four events:

### 14.1 `UserPromptSubmit`

Responsibilities:

- detect control intent such as pause/cancel/resume/direct;
- perform minimal R1 direct-vs-route classification;
- update control state for a new direction or hard pause;
- ensure a prior packet is superseded before replacement work begins.

It does not create per-turn Luna authorization scopes and does not revoke Luna identity on each root turn.

### 14.2 `PreToolUse`

Responsibilities are limited to native **agent lifecycle/control-plane tools**.

It may enforce rules around:

- `spawn_agent`;
- follow-up/send/resume operations;
- interrupt/close operations;
- targeting only the current authoritative Luna;
- preventing a second Luna while a valid authoritative Luna exists;
- preventing Luna from spawning descendants;
- preventing resume while hard-paused unless control state has been legitimately changed by Sol/user flow;
- allowing replacement spawn only after the prior Luna is retired/unrecoverable.

It must not impose a positive allowlist on ordinary Luna execution tools.

### 14.3 `PostToolUse`

Responsibilities are limited to spawn bookkeeping:

- corroborate successful pending spawn;
- clear or reconcile pending spawn after a failed spawn result.

It is not a general security monitor.

### 14.4 `SubagentStart`

Responsibilities are limited to native identity binding:

- bind the unique expected pending Luna spawn to the emitted native `agent_id`;
- reject/ignore unrecognized starts from acquiring Router Luna authority.

### 14.5 Hooks removed from the V3 target

- `PermissionRequest` — Router no longer implements child-specific ordinary tool/permission firewalling.
- `Stop` — a root/turn stop must not revoke persistent Luna identity.

## 15. Packet replacement sequencing

Because M1 removes per-tool generation enforcement, packet replacement must be a control-plane sequence rather than a tool-time ACL check.

Required ordering:

1. new user direction or Sol correction arrives;
2. old packet becomes superseded/non-runnable;
3. Sol interrupts the currently executing Luna if necessary;
4. interruption is accepted/settled sufficiently for safe continuation;
5. `packet_generation` advances;
6. Sol sends the new K1 packet to the same Luna identity;
7. Luna resumes execution under the new packet only.

The design must avoid allowing an old and new packet to execute concurrently.

## 16. Failure and race handling

Implementation planning must explicitly address these race classes:

- user pause arriving while Luna is issuing or waiting on a tool call;
- new packet arriving while the prior Luna execution has not fully quiesced;
- spawn success and `SubagentStart` arriving in either observable order;
- spawn failure leaving `pending_spawn` stale;
- replacement attempt racing with delayed lifecycle events from the retired Luna;
- a late completion/result from a superseded packet;
- user cancel followed immediately by a new independent task;
- task/session restart with durable state pointing to a no-longer-existing Luna;
- runtime capacity errors when the persistent Luna is idle versus actively executing.

For every case, fail closed with respect to **delegation identity and packet authority**, but do not fail closed by globally disabling ordinary Luna tools.

## 17. Cost/usage objective

The architecture intentionally minimizes expensive Sol intermediate turns.

Target execution economics:

```text
Sol: understand + plan + packet
  -> Luna: inspect/research/edit/test/debug/retry/verify
  -> Sol: review + correction only if needed + final
```

No periodic Sol polling, heartbeat review, or ordinary test/debug relay is part of the design.

Sol usage should correlate with actual planning/review/decision events, not with the number of Luna execution steps.

## 18. Security model and non-goals

### 18.1 Security properties Router intends to own

- correct authoritative Luna identity;
- one-Luna invariant;
- no Luna descendants;
- user/Sol preemption authority;
- hard-pause persistence;
- current packet generation authority;
- controlled replacement;
- safe state-file handling;
- no accidental privilege inheritance of A1 side-effect authorization across packets/replacements.

### 18.2 Security properties delegated to native Codex/runtime

- ordinary tool sandboxing;
- approval prompts/policies;
- MCP/tool/plugin capability availability;
- process execution restrictions imposed by the native environment;
- host filesystem/system permissions beyond Router's own state.

### 18.3 Explicit non-goal

V3 is not intended to be a hostile-agent containment system that independently interprets and blocks every possible command or external side effect. Attempting to build that layer is considered out of scope unless a separate threat model later justifies it.

## 19. Migration from current PR #8 V2

Current PR #8 remains a Draft V2 implementation and currently assumes:

- per-root Luna authority;
- `ACTIVE -> REVOKED` no-revival lifecycle;
- six managed Hooks;
- hard `no_process` Luna execution restrictions;
- child-specific tool/permission enforcement;
- HMAC-derived authorization journal scopes.

V3 intentionally supersedes those architectural choices **as a design target**, but this document does not itself change code or live installation state.

Implementation planning should preferentially delete obsolete machinery rather than adapt every V2 abstraction forward.

Likely deletion/simplification targets include:

- per-root revocation semantics;
- `Stop` revocation behavior;
- `PermissionRequest` Router enforcement;
- ordinary-tool positive allowlists;
- HMAC per-turn scope authorization where no longer threat-model-justified;
- complex routing keyword taxonomies;
- parent lifecycle ACLs unrelated to the one-Luna/control-plane invariants.

Installer transaction safety, backup, rollback, and drift reconciliation should not be casually rewritten merely because the runtime authorization model is simplified.

## 20. Runtime facts already motivating V3

The exact bundled Codex source lineage previously audited for PR #8 includes the upstream Multi-Agent V2 change that counts active execution rather than merely durable/resident child threads for concurrency accounting. This makes persistent/idle Luna reuse a viable architecture candidate and removes much of the original motivation for per-root disposable Luna identities.

This source-level fact does **not** by itself prove all required persistent-resume behavior on the exact deployed runtime.

## 21. Required adversarial review before implementation planning

A fresh session should review this design rather than assume it is safe because it is simpler.

The reviewer should specifically try to falsify these assumptions:

1. Can hard pause be reliably enforced when Luna is mid-tool-call, and what exact guarantee does native `interrupt_agent` provide?
2. Can follow-up/resume reliably reuse an idle/completed Luna identity on the exact bundled runtime?
3. Can a delayed result from a superseded packet cause Sol or state to accept stale authority?
4. Does four-Hook ordering expose a race between `PostToolUse` and `SubagentStart` during spawn binding?
5. Can Luna invoke lifecycle tools through an alias/tool surface that bypasses the intended `PreToolUse` lifecycle gate?
6. Does `[agents] enabled=false` or equivalent custom-agent configuration reliably prevent Luna descendants without reintroducing per-tool restrictions?
7. Can Luna indirectly launch nested Codex/process delegation through ordinary shell capability, and is instruction/native sandbox policy sufficient for the intended threat model?
8. Is A1 packet-level authorization sufficient for external side effects, or does the actual threat model require a narrow mechanical gate for specific structured operations?
9. Can writable-scope instructions be violated through ordinary shell commands, symlinks, generated files, or tool aliases, and is native sandboxing sufficient?
10. Can user control messages be delayed behind an executing Luna such that hard pause is not meaningfully preemptive?
11. Can task/session identity be spoofed or confused across concurrent sessions when state filenames are derived from a non-secret hash?
12. Can stale durable state incorrectly bind a newly created task to a historical Luna identity?
13. Are cancellation and later new-task semantics sufficiently distinct from pause/resume?
14. Does removing `PermissionRequest` eliminate any capability needed for Sol to block unauthorized A1 actions before they occur?
15. Does Router have a trustworthy way to distinguish primary Sol lifecycle calls from Luna lifecycle calls on the exact runtime surfaces it plans to gate?
16. Are there capacity/deadlock cases where an idle persistent Luna still prevents follow-up or replacement despite active-execution accounting?
17. Does persistent Luna context growth create quality/token problems large enough to require deliberate context-reset/replacement policy?
18. Can malicious or accidental Luna output manipulate Sol into granting broader follow-up scope without sufficient evidence?
19. Which V2 protections were compensating for real runtime behavior rather than overengineering, and would deleting them reopen a demonstrated bug?
20. Can the design be implemented with fewer than four Hooks without weakening an actual invariant, or are any of the four still redundant?

The fresh reviewer should classify each item as `PASS`, `FINDING`, `INCONCLUSIVE_RUNTIME_EVIDENCE`, or `OUT_OF_SCOPE`, with concrete source/runtime evidence.

## 22. Acceptance criteria for the design phase

Before implementation planning begins:

- this spec is reviewed in a fresh session;
- material findings are resolved in the spec;
- ambiguous runtime claims are converted into explicit capability-validation gates rather than assumptions;
- no live `~/.codex` installation is changed;
- PR #8 remains Draft unless separately authorized;
- implementation work does not begin merely because the design document exists.

## 23. Current disposition

**Design target:** approved by the user for independent review.

**Implementation:** not started.

**Live activation:** not authorized.

**Merge / ready-for-review transition:** not authorized.
