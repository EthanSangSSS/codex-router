# Native Luna Worker Router Design

Status: approved, amended after 2026-08-14 lifecycle incident and 2026-08-16 Codex V2 capability reconciliation
Date: 2026-08-05; hardening amendments 2026-08-14 and 2026-08-16
Target branch: `main`

## Objective

Keep the native Codex delegation model:

```text
Sol plans -> luna_worker executes sequential work packets -> Sol reviews
```

Sol remains the primary coordinator, highest decision authority, and final reviewer. Luna remains the default writable execution owner for bounded delegated work. The hardening amendment preserves that split while preventing a completed parent task from reactivating child work, preventing Luna from starting another Codex runtime through shell or PTY indirection, and failing closed when execution requires interactive user trust or approval.

Web Sol remains entirely operator-managed copy/paste and outside the automatic Router path. The existing canonical state machine and fake pipeline remain available only through explicit CLI commands.

## Authority model

Sol owns planning, decomposition, delegation, review, correction, bounded takeover, termination, and the final response. Ordinary execution policy is intentionally adaptive rather than a fixed decision tree: after a Luna blocker, Sol may narrow the packet, retry with new evidence, take over directly, ask the user, or stop.

Three safety invariants are not overridable by Sol or Luna:

1. A terminal parent task cannot be revived. Once the parent task enters a terminal state, its Luna and any child execution capability are permanently ineligible for reuse by that parent task.
2. Luna cannot launch, resume, probe, wrap, or indirectly execute another Codex runtime, including Codex CLI, `codex exec`, an embedded ChatGPT Codex binary, or a PTY/shell wrapper whose effective command launches Codex.
3. Luna cannot bypass or autonomously work around interactive user trust, approval, authentication, or security confirmation. Such a blocker returns control to Sol; Sol may handle it directly only when doing so does not violate the first two invariants or bypass a user-required confirmation.

Everything else remains under Sol's judgment. In particular, capacity, packet count, retry strategy, whether to continue using Luna, whether to take over ordinary execution, and when to stop are Sol decisions with explicit reasoning and observed evidence.

## 2026-08-16 Codex V2 compatibility amendment

The deployed `codex-cli 0.147.0-alpha.6.5` Multi-Agent V2 surface differs from
the earlier assumed lifecycle surface in two material ways: successful
`spawn_agent` output contains a canonical task path and optional nickname, not
the spawned thread UUID; and V2 exposes `interrupt_agent`, but not
model-visible `close_agent`.

The Router therefore uses a capability-verified adaptation. It does not infer
identity from model prose and never launches another Codex process to discover
lifecycle state.

### Binding protocol

PreToolUse records one private pending binding under the current `TURN_SCOPE`
with native `tool_use_id`, expected role `luna_worker`, and expected canonical
task path. PostToolUse accepts a spawn result only when the returned task path
exactly matches, but does not bind an ID V2 does not return.

The child-only SubagentStart Hook supplies `agent_id` and `agent_type`. It
reads only no-follow, owner-checked, bounded session metadata from the child
transcript and extracts only `parent_thread_id` and `agent_path`. Binding is
atomic only when parent thread, canonical task path, role, and current ACTIVE
scope all match the pending record. The pending record is single-use. A new
root turn, HMAC failure, malformed or ambiguous metadata, duplicate start, or
scope mismatch revokes it and fails closed. No child prompt or model output is
read for correlation.

### V2 cleanup protocol

`close_agent` is unavailable in V2. Parent termination atomically revokes
authorization before allowing exactly one `interrupt_agent` attempt for bound
Luna. PostToolUse records cleanup as `OBSERVED` only for a verified native
success response; all other outcomes are `UNVERIFIED`. `OBSERVED` means an
interrupt was observed, not that process termination was proven. No outcome
restores authorization or permits follow-up, messaging, resume, or a
replacement Luna in that parent scope.

### Luna execution surface

The generated role explicitly disables Unified Exec, Code Mode, Code Mode
Only, both multi-agent feature families, and request-permissions. The remaining
supported executor is the ordinary one-shot shell command. `write_stdin`, Code
Mode executors, descendant-agent tools, and unknown process/executor tools are
rejected for Luna at PreToolUse. Textual mentions of `codex` remain allowed;
only a supported command whose effective executable intent launches Codex is
blocked.

The profile is validated from the exact deployed Codex source/tag and synthetic
Hook fixtures. A fresh live Luna tool-list probe remains deferred to a
user-started live migration review because it would require a second Codex
process.

## Native Luna worker

The global installer manages exactly one custom agent file:

```text
~/.codex/agents/luna-worker.toml
```

Its identity and model contract are:

```toml
name = "luna_worker"
model = "gpt-5.6-luna"
model_reasoning_effort = "max"

[agents]
enabled = false
```

The file intentionally omits `sandbox_mode`, approval policy, MCP, and skill overrides so the child inherits the parent task's effective controls. It explicitly disables Unified Exec, Code Mode, descendant-agent features, and request-permissions. Its instructions require bounded scope, evidence-first work, no browser or Web Sol operation, no authentication access, and no GitHub/install/release mutations unless an exact delegated packet explicitly authorizes an otherwise permitted action.

The `[agents]` gate mechanically disables Luna's multi-Agent tools. Luna must never create, spawn, fork, relay, resume, or delegate a child or descendant; a packet that requires recursive delegation returns `BLOCKED_LUNA_RECURSIVE_DELEGATION`.

Luna also has a process-recursion prohibition. It must not use shell, PTY, environment wrappers, scripts, subprocess helpers, or absolute application paths to start or resume Codex itself. A packet that requires another Codex runtime returns `BLOCKED_LUNA_CODEX_RUNTIME` to Sol. The implementation must enforce this at the strongest verified local tool boundary available; policy text alone is not considered sufficient when a verified pre-tool gate exists.

## Parent-scoped persistence

Luna is persistent only while the parent Codex task is active.

The lifecycle distinction is:

```text
Luna packet completed/idle != parent task completed
```

While the parent task is active, Sol may reuse the same Luna across multiple sequential work packets and bounded correction packets, including when Luna's previous packet is completed or idle. This preserves cache continuity and avoids unnecessary cold-session context expansion.

When the parent task is about to enter a terminal state, Sol must use the one verified native cleanup operation. In V1 this is `close_agent`; in deployed V2 it is one `interrupt_agent` attempt. Authorization is revoked before that attempt, and a late result may be observed only for reporting. It must not cause new model work, a new packet, follow-up, resume, or inter-agent communication after the parent terminal boundary.

A parent-terminal Luna must never be selected by a later task. A new user task receives a new parent-scoped Luna identity if delegation is needed.

If the runtime cannot prove that a child was closed, the final report must disclose `LUNA_CLOSE_UNVERIFIED`; it must not claim cleanup succeeded merely because an agent message says completed or interrupted.

## Stateless global Hook

`UserPromptSubmit` continues to classify each prompt as `direct`, `bypass`, or `route`. A routed response contains bounded policy context such as:

```json
{
  "decision": "route",
  "workflow": "native_luna_worker",
  "sol_role": "plan_review_final_authority",
  "luna_role": "default_execution",
  "delegation_mode": "sequential_work_packets",
  "luna_agent": "luna_worker",
  "luna_model": "gpt-5.6-luna",
  "luna_reasoning": "max",
  "luna_lifecycle": "persistent_while_parent_active",
  "parent_terminal_policy": "close_and_forbid_resume",
  "capacity_failure_policy": "return_to_sol",
  "luna_descendant_policy": "forbidden",
  "luna_codex_runtime_policy": "forbidden",
  "interactive_blocker_policy": "return_to_sol_or_user",
  "initial_context_mode": "packet_only",
  "web_mode": "manual_operator"
}
```

The Hook remains stateless: it does not allocate a `run_id`, create state directories, launch a model, or touch the browser. Parent lifecycle enforcement belongs to verified agent/task and tool boundaries, not to invented Router run state. Legacy explicit Router CLI runs keep their existing state authority, transition, digest, and recovery semantics.

## Delegation policy

For routed work, Sol plans and decomposes the task, then normally delegates executable work packets to the persistent `luna_worker` sequentially. Sol may perform read-only inspection needed to plan or review. If Luna's result fails review, Sol may send a bounded correction packet to the same Luna while the parent task remains active.

Every delegation packet states objective, working directory, readable and writable paths, forbidden actions, validation, stop conditions, required output, and the current parent-task boundary. Previous packet write authorization expires when a new packet is issued.

Sol is not prohibited from taking over ordinary writable execution merely because Luna is unavailable. Luna capacity exhaustion or another ordinary execution blocker returns control to Sol. Sol may reuse Luna, close an unused non-Luna agent, narrow work, take over directly, ask the user, or stop. A takeover must disclose its reason and preserve single-writer ownership for the relevant file set.

Sol may also decide not to delegate when delegation would predictably violate a hard invariant, cause unnecessary cold-context duplication, or require an unresolved architecture decision. This preserves Sol's highest control authority without allowing lifecycle resurrection or recursive Codex execution.

## Interactive and retry policy

Interactive trust or security blockers are not autonomous retry problems. Examples include Hook trust review, user approval prompts, authentication, or another confirmation that explicitly requires the user.

Luna must return `BLOCKED_USER_INTERACTION_REQUIRED` with the observed blocker and no workaround attempt that launches another Codex runtime or changes terminal emulation merely to force an interactive path. Sol may choose a safe direct action if supported, otherwise it returns the required action to the user.

For non-interactive blockers, retry policy remains adaptive. Repeating the same failed operation without new evidence is discouraged and must return control to Sol rather than creating an unbounded wait/interrupt/retry loop. There is no fixed global turn-count restart rule because forced session replacement can destroy prompt-cache continuity and recreate the cold-context amplification observed in the incident.

## Economic guardrails

Economic controls are advisory to Sol, not fixed quota cutoffs. The Router must not hard-code a weekly token or credit ceiling because plan accounting and model mix can change.

The implementation should expose or preserve bounded telemetry that lets Sol recognize suspicious amplification when available: repeated identical blocker cycles, unexpected new Codex process/session creation, unusually large uncached context, or repeated cold-session initialization. When such a signal appears, Luna stops expanding the execution path and returns evidence to Sol. Sol then decides whether to narrow, take over, ask the user, or stop.

The design explicitly prefers cache continuity inside an active parent task. It must not implement a blanket rule such as "restart Luna every 50 turns". A new Luna is created only for a new parent task or when the active parent deliberately replaces a failed worker without violating lifecycle or single-writer constraints.

## Process-recursion gate

The source-of-truth repository must contain any runtime gate used to block Luna from launching Codex. A live `site-packages` implementation that is absent from the repository is not an acceptable final state.

Before implementation, reconcile the current repository with the installed Router package and `~/.codex/hooks.json` read-only. If the installed package already contains a verified pre-tool handler absent from `main`, port only the minimal relevant mechanism into source with tests. Do not invent hook names, event schemas, or tool payload fields. If no mechanically enforceable pre-tool boundary is available, stop with `BLOCKED_CODEX_RUNTIME_GATE_UNAVAILABLE` rather than claiming the policy is enforced.

The gate must use effective command intent, not only a literal first token. It must reject direct and wrapped attempts including absolute Codex binaries, `env ... codex`, shell `-c` wrappers, PTY/script wrappers, and equivalent command forms that resolve to a Codex runtime. It must not block unrelated commands merely because a filename or text argument contains the word `codex`.

## Installer ownership and recovery

The installer continues to own only its Hook entries, bounded AGENTS block, installation metadata, and `agents/luna-worker.toml`. Existing unrelated hooks, AGENTS text, and agent files are preserved.

If lifecycle or pre-tool hooks are added, they become explicit managed targets inside the same reversible `hooks.json` ownership model; install/uninstall and conflict detection must remain byte/mode safe for unrelated user content.

No direct edits to live `site-packages`, `~/.codex/AGENTS.md`, or `~/.codex/hooks.json` are considered source implementation. Live installation happens only through the project's validated installer after repository tests pass.

## Validation invariants

Offline tests must prove at minimum:

- routed Hook context preserves Sol plan/review/final authority and Luna default execution;
- Luna is reusable across sequential packets while the parent is active;
- a parent terminal boundary forbids later Luna resume, `send_input`, new packet, or inter-agent reactivation;
- V2 binding correlates only verified native pending-spawn and SubagentStart metadata;
- cleanup status is reported truthfully and unverified interrupt cleanup is not called successful;
- Luna descendant-agent creation remains mechanically disabled;
- Luna cannot launch a Codex runtime through direct, absolute-path, environment, shell, or PTY wrappers at the strongest verified tool boundary;
- interactive user-required blockers return control instead of autonomous PTY/TERM retry loops;
- Sol may take over ordinary execution after a disclosed non-hard-invariant blocker;
- no blanket fixed-turn Luna restart is introduced;
- packet-only initial context and cache-friendly same-parent reuse remain intact;
- Hook routing remains stateless and legacy CLI/fake behavior remains compatible;
- installer ownership, recovery, and unrelated user configuration preservation remain exact.

Runtime acceptance must additionally verify from a new Codex task that Sol can plan, delegate to one Luna, review, issue a correction packet, and finish; after the parent task finishes, no old Luna or child session can be reactivated by later inter-agent communication. Runtime acceptance must not intentionally launch a nested Codex process to prove the negative guard; use the verified pre-tool gate's dry/in-process test path instead.
