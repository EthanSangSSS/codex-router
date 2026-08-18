# Codex Router

Codex Router is a minimal, fail-closed workflow for:

```text
Local Sol → Web Sol → Luna → final result
```

- **Local Sol** performs read-only local analysis.
- **Web Sol** performs analysis, counter-analysis, and review in the in-app Web conversation.
- **Luna** runs locally and synthesizes the preceding results.

Codex App is the execution driver: it runs Local Sol, carries the Web packet to the continuous in-app Web Sol conversation, runs local Luna, and submits the resulting files. Router is the only workflow state authority: it creates `run_id`, verifies stages, revisions, packets and digests, persists canonical state, and selects `next_stage`.

All V1 access to the target workspace is read-only. Router writes only to its dedicated state root and Router-owned isolated Codex profiles. Each stage runs once and in order; a failed or timed-out stage blocks all downstream stages.

That staged workflow remains available as an explicit CLI compatibility path. The optional global policy is intentionally lighter: primary Sol plans and retains final authority, exactly one persistent task-epoch native `luna_worker` normally executes bounded work, and Sol reviews/corrects/finalizes. All Web Sol work remains manual operator copy/paste.

## Install

Python 3.12 or newer is required. The runtime has no third-party dependencies.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Run the offline demo

Fake mode makes no model, account, browser, or network calls:

```bash
router run \
  --task "Return exactly ROUTER_MVP_OK" \
  --adapter-mode fake \
  --state-dir "/absolute/path/to/router-state"
```

The command prints Luna's final result. Canonical state and rebuildable projections are stored under the state root:

```text
.profiles/
run-<id>/
  state.json
  request.json
  local-sol.json
  web-sol.json
  luna.json
  result.json
  events.jsonl
  packets/
```

`state.json` is the sole canonical workflow state. It is committed under a per-run lock with atomic replacement and directory durability. Packets, stage files, events, request, and result are derived views that `router status` can regenerate.

## Global default routing policy (V3.1)

The optional global policy routes substantive Codex turns to one persistent native Luna task epoch without adding a daemon, background service, browser bridge, second App instance, or per-prompt legacy Router run. `UserPromptSubmit` classifies each prompt locally and deterministically.

Routing behavior:

1. `[CODEX_ROUTER_DIRECT]` or `本轮不用 Luna` on the first non-empty line applies direct execution to the current turn only; no Luna is created for that turn.
2. Existing exact first-line `本次不用 Router` or `仅本地执行` bypass markers also apply only to the current turn.
3. Greetings, thanks, trivial arithmetic, brief concept explanations, current-task metadata, and one-step read-only inspection may run directly.
4. Changes, reviews, security or architecture work, research, verification, comparisons, decisions, plans, multi-step work, sensitive content, and ambiguity route through Router by default when the Hook is active and trusted.

A routed turn injects a policy context equivalent to:

```text
workflow=persistent_native_luna
sol_role=plan_review_final_authority
luna_role=default_execution
delegation_mode=sequential_work_packets
luna_lifecycle=persistent_task_epoch
parent_terminal_policy=hard_authority_pause
capacity_failure_policy=return_to_sol
luna_descendant_policy=forbidden
luna_codex_runtime_policy=forbidden
interactive_blocker_policy=return_to_sol_or_user
initial_context_mode=packet_only
pause_semantics=hard_authority_pause
sol_supervision=event_driven
luna_execution_mode=full_executor
web_mode=manual_operator
```

Sol remains the planner, reviewer, and final authority. A routed task has one `luna_worker` per persistent `task_epoch`; sequential packets and bounded corrections reuse that native Luna while the epoch remains valid. A packet replaces the previous packet authority and restates its working directory, allowed paths, forbidden operations, validation, stop conditions, and required output. Intended write-scope changes inside the same native authority profile do not replace Luna.

`spawn_agent` is admitted only for the Router Luna with `fork_turns=none`. Spawn results and `SubagentStart` are correlated to the exact task/luna epoch, root session, parent, role, task path, and available native agent identity. Ambiguous, stale, resumable-only, or mismatched identities fail closed; transcript JSON and child/root `turn_id` equality are not authorization sources.

Luna is a Full Executor for ordinary inspect, research, edit, test, debug, retry, and verification work. Its profile disables only the descendant-agent triad. Ordinary shell/process, Unified Exec, Code Mode, apps, plugins, web, and other runtime capabilities remain available to the extent the target runtime exposes them. Router's narrow lifecycle gate denies descendant/delegation operations while leaving ordinary executor tools under native controls; it is not a broad shell parser or ordinary-tool firewall. Every Luna tool turn must first be admitted by a current K1 packet; an otherwise bound Luna cannot start unscheduled ordinary tool work.

Hard Authority Pause freezes Router authority immediately. On the current ChatGPT App, Router uses the exact bound-Luna native turn boundary (`SubagentStop`) to close **Router scheduling authority**. That boundary is deliberately narrower than physical process settlement: interrupt acknowledgements, `Interrupted`, timeouts, sleeps, polling, PID observations, and `SubagentStop` itself do not prove that detached or background OS processes are dead. Luna therefore must not intentionally daemonize, detach, or leave long-lived background work running beyond its bounded turn. Late or stale generations cannot regain Router authority.

No Luna descendants or nested Codex delegation are permitted by the packet contract and lifecycle gate. The effective target-profile capability and nested-Codex properties remain acceptance claims, not assumptions.

A1 hard claims are made only when an explicit packet authorization names a canonical category and the exact runtime surface provides a proven pre-action gate with proven actor attribution. Unknown categories fail at K1, authorizations never inherit across packet generations, and cooperative-only evidence is not presented as a hard claim. A native turn boundary does not prove an external persistent mutation completed safely. `PermissionRequest` is conditional and A1-specific; it is not part of the baseline Hook set.

The managed V3.1 Hook set is exactly:

- `UserPromptSubmit` — route/direct classification, task-epoch context, and immediate freeze of a still-running old generation on supersession;
- `PreToolUse` — K1 packet admission, exact bound-Luna execution-start binding, primary lifecycle control, and narrow Luna lifecycle denial;
- `PostToolUse` — spawn-result reconciliation only;
- `SubagentStart` — spawn reservation identity reconciliation;
- `SubagentStop` — exact Luna turn-boundary reconciliation for Router scheduling authority only.

`Stop` and `PermissionRequest` CLI entry points remain callable for safe upgrade compatibility, but neither is rendered by the baseline installer. `SubagentStop` is not a process-kill or physical-settlement Hook. The durable native control journal stores bounded task/luna epochs, packet authority, spawn correlation, execution pause/turn-boundary state, and current identity; it does not persist prompt text, transcripts, model output, or unbounded history.

Global readiness is intentionally honest. `global-status` and offline self-test report `live_activation=BLOCKED_ACCEPTANCE_GATES` even when disposable installer invariants pass. The current live blockers are:

```text
G1_STRONG_IDENTITY_PROFILE
G2_SETTLEMENT_OBSERVATION
G3_ACTOR_ATTRIBUTION
G4_NO_DESCENDANTS_EFFECTIVE_INVENTORY
G5_NESTED_CODEX
G6_NATIVE_AUTHORITY_PROFILE
G7_A1_CAPABILITY_MATRIX
G8_RECOVERY_CORRELATION
```

For the current-App turn-boundary mode, G2 is satisfied only as a Router scheduling-authority claim; it must not be interpreted as physical OS/process settlement. `G9_ECONOMICS` remains deferred acceptance evidence, not a live safety blocker. If the managed Hook is absent, disabled, untrusted, incompatible, or not injected, the turn is **Router inactive/degraded** and must not be reported as `Router: active`.

Install only from a durable Python environment where `codex_router` is installed for the same absolute interpreter recorded in the Hook command. The generated command uses `-E -P -m codex_router` so it cannot depend on the caller's `PYTHONPATH` or working directory. Before changing managed files, installation preflights the exact `UserPromptSubmit` command with a synthetic direct event and requires one valid Router Hook-protocol JSON response. A failed probe leaves managed user files unchanged:

```bash
router global-install \
  --codex-home "/absolute/path/to/active-codex-home" \
  --state-dir "/absolute/private/path/to/codex-router-runs" \
  --codex-bin "/Applications/ChatGPT.app/Contents/Resources/codex" \
  --local-model "inherit" \
  --local-reasoning "max" \
  --web-model "sol" \
  --web-reasoning "xhigh" \
  --luna-model "gpt-5.6-luna" \
  --luna-reasoning "max"
```

Installation manages the five V3.1 Router command Hooks listed above, one bounded block in `AGENTS.md`, and one custom Full Executor agent at `agents/luna-worker.toml`. It preserves unrelated Hook groups and user files. The installer does not edit the user's primary `config.toml`, `AGENTS.override.md`, or unrelated agent files.

Because Router does not own the primary Codex `config.toml`, `global-status` performs a read-only compatibility preflight. The global-install default `--local-model inherit` records that PRIMARY uses the current Codex App session model rather than selecting a Sol-named model. Readiness is capability-based: the required Multi-Agent V2 surface is `spawn_agent`, `followup_task`, and `send_message`; an exact runtime evidence record may prove it, while missing or explicitly disabled capability remains incompatible/unknown. It classifies statically observable primary capability as `COMPATIBLE`, `INCOMPATIBLE`, or `UNKNOWN_REQUIRES_CAPABILITY_CHECK` and reports `luna_execution_mode=full_executor_v3_1`, `router_design=v3.1`, and the blocked readiness gates above. Explicitly disabled primary agents, multi-agent capability, or Hooks are incompatible. Ambiguous layered/effective configuration remains unknown rather than being guessed.

Original managed files are backed up byte-for-byte under `.codex-router-policy-v1/` with private permissions. The prepared manifest records original and installed digests and modes before any managed write. If the process stops after a managed write, `global-status` reports partial state; the same compatible `global-install` can complete remaining writes, while `global-uninstall` restores exact originals. Recovery validates every target before its first write and refuses post-interruption user edits.

Inspect or reverse the installation with:

```bash
router global-status --codex-home "/absolute/path/to/active-codex-home"
router global-uninstall --codex-home "/absolute/path/to/active-codex-home"
```

Uninstall restores exact original bytes and modes when managed files still match installed hashes. It refuses concurrent or unrelated edits instead of overwriting them. Backups, installation evidence, and legacy Router run state remain. Install/uninstall changes require a new Codex task before session-loaded instructions can change.

The offline self-test deliberately refuses the live default Codex home. Run it only against a disposable installed home:

```bash
ROUTER_TEST_HOME="$(mktemp -d)"
ROUTER_TEST_STATE="$(mktemp -d)"
chmod 700 "$ROUTER_TEST_HOME" "$ROUTER_TEST_STATE"
router global-install \
  --codex-home "$ROUTER_TEST_HOME" \
  --state-dir "$ROUTER_TEST_STATE" \
  --codex-bin "/Applications/ChatGPT.app/Contents/Resources/codex"
router global-self-test --codex-home "$ROUTER_TEST_HOME"
router global-uninstall --codex-home "$ROUTER_TEST_HOME"
```

The self-test invokes the configured Hook command as a child process instead of calling the Hook function in-process. It verifies disposable installer and route invariants without allocating a legacy per-prompt Router run, performs no model/Web/browser/network action, does not activate Hook trust, leaves the configured legacy state root untouched, and does not close the V3.1 live-activation gates.

### Manual App acceptance checklist

Automated repository tests cannot prove App Hook trust, exact deployed child Hook wire fields/order, the post-install Luna tool inventory, or a real Luna model turn. Before treating a live installation as active:

1. Verify the recorded absolute Python interpreter is durable and imports `codex_router` with the configured `-E -P -m codex_router` command.
2. Verify primary Codex effective configuration has the multi-agent capability Sol needs to create/manage one Luna. Do not globally disable it to enforce child restrictions.
3. Verify the exact deployed build exposes the required `SubagentStart.agent_id`, `SubagentStop.agent_id`, and Luna-sensitive `PreToolUse` identity fields/order. If trustworthy child identity cannot be established, keep the corresponding V3.1 claim blocked rather than falling back to transcript internals.
4. Review and trust the exact five managed Router Hook definitions through the supported Codex trust flow. Do not bypass trust with unsafe launch flags.
5. Start a **new** Codex task after installation/trust changes.
6. Submit a normal substantive bounded task. Confirm routed context is present, Codex shows `Router: active`, Sol plans, one `luna_worker` executes as a Full Executor, and Sol reviews/finalizes.
7. Confirm Luna uses the configured model/reasoning, has no usable descendant path, and record the exact nested-Codex/tool-inventory evidence before making a hard claim.
8. Issue a bounded correction packet and verify the same task-epoch Luna is reused rather than a second Luna being created.
9. Begin a new turn with `[CODEX_ROUTER_DIRECT]` or `本轮不用 Luna`. Confirm Sol performs that turn directly with no new Luna packet; the next substantive turn reuses the current task epoch when still valid.
10. Exercise Hard Authority Pause. Confirm a pause freezes Router authority immediately, interrupt acknowledgement is not settlement, and the exact bound-Luna `SubagentStop` advances only Router scheduling authority. Do not report it as proof that detached/background OS work has terminated.
11. Confirm every enabled A1 hard claim has explicit packet authorization, a proven pre-action gate, and proven actor attribution; otherwise keep it withheld or cooperative-only.
12. Confirm no per-prompt legacy Router run is created and the configured legacy state root remains untouched by global routing.
13. Perform any Web Sol consultation manually by copy/paste. Router must not open, close, focus, or automate browser pages.
14. Run `global-uninstall`, start a new Codex task, and confirm managed Hooks, AGENTS block, and `luna_worker` are gone or restored while explicit legacy Router commands and retained installation evidence remain.

## App-driven workflow

Use one stable `driver_context_id` for runs initiated from the same Codex conversation. Those runs may reuse the App-managed continuous Web Sol context, so a new Web conversation is not created for every related question. A different Codex conversation must use a different `driver_context_id` and must not inherit the previous Web context.

Start a run with an absolute App Codex binary path and a dedicated Router state directory:

```bash
router start \
  --task "Review this task" \
  --driver-context-id "ctx-550e8400-e29b-41d4-a716-446655440000" \
  --state-dir "/absolute/path/to/router-state" \
  --codex-bin "/Applications/ChatGPT.app/Contents/Resources/codex" \
  --local-model "gpt-5.6-sol" \
  --local-reasoning "max" \
  --web-model "sol" \
  --web-reasoning "xhigh" \
  --luna-model "local-luna-model" \
  --luna-reasoning "max"
```

Replace the model values with the exact models selected for the run. The JSON response names the current packet and revision. After the App executes exactly that packet, submit the stage output and its execution evidence:

```bash
router submit-stage \
  --run-id "$RUN_ID" \
  --driver-context-id "$DRIVER_CONTEXT_ID" \
  --state-dir "/absolute/path/to/router-state" \
  --stage local_sol \
  --expected-revision 0 \
  --packet-digest "$PACKET_DIGEST" \
  --output-file "/absolute/path/to/local-output.txt" \
  --execution-file "/absolute/path/to/local-execution.json"
```

Use the returned packet and revision for Web Sol and then Luna. The Web response must preserve the packet's exact Router response marker as its unique first non-empty line.

If the current stage cannot complete, end the run explicitly:

```bash
router fail-stage \
  --run-id "$RUN_ID" \
  --driver-context-id "$DRIVER_CONTEXT_ID" \
  --state-dir "/absolute/path/to/router-state" \
  --stage web_sol \
  --expected-revision 1 \
  --packet-digest "$PACKET_DIGEST" \
  --error-file "/absolute/path/to/sanitized-error.json" \
  --execution-file "/absolute/path/to/web-execution.json"
```

Recover after an App or conversation interruption from canonical state, not chat memory:

```bash
router status \
  --run-id "$RUN_ID" \
  --state-dir "/absolute/path/to/router-state"
```

`completed` and `failed` are terminal. V1 has no resume or retry transition; start a new run instead. An identical resubmission is idempotent, while different content for an accepted stage is a conflict.

Local Sol and Luna store requested model/reasoning separately from values reported by App Server. Web model, `xhigh` reasoning, continuous context, and conversation isolation are recorded only as `operator_attested`; Router does not claim that browser UI selections were independently verified.

## Router handoff protocol

Every stage packet binds its driver context, run, target stage, source revision, packet ID, packet digest, and cumulative payload. Web output must begin with the exact response marker derived from that packet.

The original MVP handoff envelope remains available for the synchronous adapter interface:

```json
{
  "router_protocol": "codex-router/v1",
  "run_id": "<run_id>",
  "stage": "local_sol",
  "content": "<stage output>"
}
```

For Codex App Server `thread/inject_items`, that envelope begins with `[CODEX_ROUTER_V1]`. Router parsing ignores unrelated automatic context and accepts only its own marker, current `run_id`, and expected stage.

## Configuration and provider boundary

Fake mode needs no configuration. `--timeout` sets its per-stage timeout in seconds and defaults to 60.

The adapter boundary remains:

```text
run(task, context) -> StageResult
```

Provider wiring belongs in `src/codex_router/adapters.py`. `--adapter-mode real` is intentionally unconfigured and fails closed with `provider-not-configured`; it never pretends a real provider ran. The App-driven commands accept externally executed stage evidence and do not independently call a browser or model.

Router execution, local state transitions, recovery, and fake validation do not require GitHub or GitHub Actions quota. GitHub is optional source-control and CI infrastructure. Real model stages still depend on approved OpenAI/ChatGPT access and available service capacity.

## Development

Run all offline tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src tests
```

The editable installation is required for global-install tests because the production Hook command deliberately ignores `PYTHONPATH`.

## Known limitations

- Global Router activation depends on Codex actually loading and trusting the current five managed Hook definitions; `Router: active` is a routed policy marker, not independent runtime telemetry.
- Live activation must reverify native child identity fields/order and the generated Full Executor Luna effective tool inventory against the exact deployed Codex build. Repository fixtures are not a substitute for that capability check.
- Current-App turn-boundary mode gives a hard Router scheduling-authority boundary, not a physical OS-process settlement guarantee. `SubagentStop` cannot prove that detached/background processes are gone.
- Luna intentionally retains ordinary process-capable Full Executor tools, so the current-App profile relies on the explicit policy prohibition against intentional daemonization/detached long-lived background work where no stronger native process boundary is exposed.
- A1 hard claims remain separately withheld unless the exact enabled runtime surface proves a deterministic pre-action gate and actor attribution.
- The installer does not own primary `config.toml`; compatibility preflight is read-only and ambiguous layered/effective configuration remains `UNKNOWN_REQUIRES_CAPABILITY_CHECK`.
- App-driven legacy stages still require Codex App or the operator to execute the returned packet and supply bounded evidence files.
- Real `--adapter-mode real` provider wiring is not configured or validated.
- Web model, reasoning, and context claims are operator-attested rather than browser-verified.
- Hook trust and new-task activation must be confirmed manually through Codex; `global-status` never claims trust is verified when it cannot observe it.
- The Web security gate blocks or redacts detected protected categories but cannot prove every unknown sensitive value was detected.
- Fake mode proves Router orchestration and persistence, not model quality.
- The MVP does not manage Codex archive/delete lifecycle.
- There is no Web UI, daemon, scheduler, distributed queue, retry system, database, browser automation, or plugin marketplace.
- Run state can contain task and stage output. Keep Router-owned state directories private and do not put credentials in tasks.
