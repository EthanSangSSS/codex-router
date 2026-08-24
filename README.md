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

## Recommended mode: Native PRIMARY + Luna V1

Native V1 is the recommended user-facing mode. Sol/PRIMARY remains the persistent planner, coordinator, reviewer, and final responder. When useful, PRIMARY delegates substantial local engineering to a fresh native disposable `luna_worker`; if native spawn is unavailable, PRIMARY continues locally when normal tools allow it.

```bash
router native-install --codex-home "/absolute/path/to/active-codex-home"
router native-status --codex-home "/absolute/path/to/active-codex-home"
router native-self-test --codex-home "/absolute/path/to/active-codex-home"
```

Native mode manages only its bounded `AGENTS.md` block, `agents/luna-worker.toml`, and reversible private ownership state under `.codex-native-primary-luna-v1/`. Its normal path installs no Router routing Hooks and uses no K1, generation lease, request-file staging, or bootstrap capability ceremony. The historical `global-*` commands remain available as the experimental hard-authority Router path; they are not part of normal Native V1 operation.

To reverse only Native-owned changes:

```bash
router native-uninstall --codex-home "/absolute/path/to/active-codex-home"
```

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

## Global default routing policy (V3.3 — Persistent Task, Disposable Luna)

V3.3 keeps the Router task, K1 generation journal, repository state, and PRIMARY review continuous. A Luna identity is not continuous: every substantive generation uses one fresh, generation-scoped `luna_worker`, and the exact terminal transition forgets that worker. Task continuity therefore never depends on child memory, UUID persistence, or a native agent remaining in the live registry.

`UserPromptSubmit` classifies each prompt locally and deterministically. The global policy adds no daemon, polling loop, browser bridge, second App instance, or per-prompt legacy Router run.

Routing behavior:

1. `[CODEX_ROUTER_DIRECT]` or `本轮不用 Luna` on the first non-empty line applies direct execution to the current turn only; no Luna is created for that turn.
2. Exact first-line `本次不用 Router` or `仅本地执行` bypass markers also apply only to the current turn.
3. `[CODEX_ROUTER_STRICT]` on the exact first non-empty line keeps the turn routed and disables automatic capability degradation for that turn. Natural-language variants are not security markers.
4. Greetings, thanks, trivial arithmetic, brief concept explanations, current-task metadata, and one-step read-only inspection may run directly.
5. Changes, reviews, architecture or security work, research, verification, comparisons, plans, and multi-step work route by default when the Hook is active and trusted.

A routed context identifies the active design explicitly:

```text
workflow=persistent_task_disposable_luna
sol_role=plan_review_final_authority
luna_role=generation_scoped_execution
delegation_mode=fresh_worker_per_generation
luna_lifecycle=generation_scoped_disposable
luna_execution_mode=full_executor_v3_3_generation_scoped
parent_terminal_policy=hard_authority_pause
luna_descendant_policy=forbidden
luna_codex_runtime_policy=forbidden
web_mode=manual_operator
```

### Generation lifecycle and identity

For generation N, PRIMARY stages K1 and spawns exactly one worker. Router correlates the spawn reservation, native worker identity, child turn, actor, packet, and generation only while that generation is active. Two workers cannot consume one generation, and ambiguous correlation fails closed.

At the exact `SubagentStop`/verified terminal boundary, Router clears the active packet, child turn, pending spawn, current worker id/path, write scope, side-effect authorization, and recovery binding, then returns the execution state to `IDLE`. Generation N+1 stages normally and spawns a new worker B; B may and ordinarily will differ from worker A. Late `PreToolUse` or `SubagentStop` events from A are stale and cannot consume or mutate B's authority.

`followup_task` is not the normal V3.3 continuation protocol and is not a readiness requirement. A missing historical worker or an unavailable follow-up surface does not block the next generation. Low-level parser compatibility, where retained, carries no cross-generation or task-continuity authority. `send_message` remains QueueOnly; `send_input` and `resume_agent` are forbidden authority fallbacks. Wait, polling, and sleep are not work authority or synchronization primitives.

### K1 request-file staging

Router injects one complete `stage-k1-fields --request-file <exact-private-path>` command containing its root/session/task/generation capability. PRIMARY writes exactly these seven fields and runs the injected command verbatim:

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

PRIMARY does not append semantic argv fields or write generation, session identity, task/luna epoch, capability, native identity, or K1 wire into the request. Router checks the exact absolute path, directory and file ownership/mode, regular-file identity, symlinks, size, UTF-8, exact schema, field types, and replay state before constructing canonical K1. The legacy flag parser remains only as an external compatibility seam.

The native spawn message is a transport trigger, never authority. Exact V1 spawn uses `agent_type=luna_worker` with `fork_context=false` or omission; exact V2 uses `task_name=luna_worker`, `agent_type=luna_worker`, and `fork_turns=none`.

### Exact bootstrap

Luna becomes a Full Executor for the current K1 only after the exact first Codex tool/input:

```text
Bash {"command":"pwd"}
```

No extra input fields are allowed. Router validates current-generation identity and authority, then returns a `PreToolUse` `hookSpecificOutput` containing only `hookEventName=PreToolUse` and canonical K1 in `additionalContext`; Codex default-continue semantics allow the exact read-only probe to execute. Any other substantive first tool is denied before execution starts. Repository tests prove this output/state contract; a specific Codex App build still requires separate live observation before activation is claimed.

### Safe local fallback

Fresh-spawn failure is a capability failure, not automatically a security failure. Router may report `SAFE_LOCAL_FALLBACK` only when the task is active, execution is `IDLE`, and there is no active or staged packet, child turn, pending spawn, or current/stale worker binding. In non-strict mode PRIMARY may then continue bounded workspace-local read, edit, test, build, lint, local-Git inspection, and debugging.

Automatic fallback never authorizes deploy, publish, release, credentials/tokens/cookies/private keys, cloud/service mutation, package publication, external A1 effects, privilege or authentication changes, or agent creation/delegation. Active, pending, stale, ambiguous, or otherwise unsafe authority blocks. Strict mode blocks the same capability failure instead of degrading.

Hard Authority Pause freezes Router scheduling authority immediately. A native terminal event is not proof that detached or background OS processes are dead; Luna must not intentionally daemonize or detach long-lived work. K1 is an authority packet, not an OS sandbox.

No Luna descendants or nested Codex orchestration are permitted. A1 hard claims still require an explicit current-generation authorization, a proven pre-action gate, and proven actor attribution. Authorizations never inherit across generations.

### Hooks and readiness

The managed baseline remains exactly five events:

- `UserPromptSubmit` — routing/strict classification, task state, request command, and mechanical fallback state;
- `PreToolUse` — current-generation spawn admission, exact K1 bootstrap, actor checks, and lifecycle denials;
- `PostToolUse` — current-generation spawn-result reconciliation;
- `SubagentStart` — current-generation worker identity correlation with durable prior-generation replay rejection;
- `SubagentStop` — exact terminal reconciliation, worker-binding clearance, and one-way retired-worker tagging.

`global-status` and offline self-test keep live activation blocked until target-runtime evidence proves:

```text
G1_CURRENT_GENERATION_SPAWN_CORRELATION
G2_SETTLEMENT_OBSERVATION
G3_ACTOR_ATTRIBUTION
G4_NO_DESCENDANTS_EFFECTIVE_INVENTORY
G5_NESTED_CODEX
G6_NATIVE_AUTHORITY_PROFILE
G7_A1_CAPABILITY_MATRIX
G8_STALE_GENERATION_REJECTION
```

`G9_ECONOMICS` remains deferred evidence. No gate requires a worker to survive across generations or requires native follow-up. If Hook loading, trust, identity, or capability evidence is absent or ambiguous, Router does not claim active status.

### Installation and offline self-test

Install only from a durable Python environment where `codex_router` is installed for the exact absolute interpreter recorded in the Hook command. The command uses `-E -P -m codex_router` and does not depend on caller `PYTHONPATH` or working directory:

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

Installation manages the five Hook commands, one bounded `AGENTS.md` block, and `agents/luna-worker.toml`. It preserves unrelated Hook groups and files and does not edit primary `config.toml` or `AGENTS.override.md`. Original bytes and modes are backed up under `.codex-router-policy-v1/`; refresh and uninstall refuse conflicting user edits.

Inspect or reverse the installation with:

```bash
router global-status --codex-home "/absolute/path/to/active-codex-home"
router global-uninstall --codex-home "/absolute/path/to/active-codex-home"
```

Install/uninstall, Hook trust, and session-loaded policy/profile changes require a new Codex task. A failed request validation or unavailable worker spawn does not inherently require a new task.

The offline self-test deliberately refuses the live default Codex home. Use a disposable home and state directory:

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

The self-test invokes the configured Hook command as a subprocess, performs no model/Web/browser/network action, does not activate Hook trust, leaves the configured legacy state root untouched, and does not close live acceptance gates.

### Manual App acceptance checklist

Automated repository tests do not prove App Hook trust, deployed child identity fields/order, effective target-profile tools, or a real Luna turn. Before treating a later refreshed V3.3 installation as active:

1. Verify the recorded interpreter and exact five trusted Hook definitions, then start a new Codex task.
2. Stage a bounded Gen1 request through the complete injected request-file command.
3. Spawn worker A and observe exact `Bash {"command":"pwd"}` delivery with canonical K1 `additionalContext`.
4. Observe A's exact terminal boundary and verify Router clears its worker binding.
5. Stage Gen2 and spawn worker B, with B allowed to differ from A and no follow-up requirement.
6. Verify late A events cannot affect Gen2 and simultaneous workers cannot consume one generation.
7. Verify a safe non-strict spawn capability failure degrades locally, while strict or unsafe state blocks.
8. Verify effective no-descendants, nested-Codex, actor-attribution, and A1 gates before making hard claims.
9. Keep Web Sol manual and verify no per-prompt legacy Router run is created.
10. Verify uninstall restores managed files, then start a new task.

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

- Global Router activation depends on Codex actually loading and trusting the current five managed Hook definitions; a routed policy marker is not independent runtime telemetry.
- V3.3 repository tests prove the request-file, generation-scoped lifecycle, and Bash/pwd context-only `K1 additionalContext` output/state contracts, but the exact deployed App must still be observed before that behavior is claimed live.
- Live activation must reverify native child identity fields/order and the generated Full Executor Luna effective tool inventory against the exact deployed Codex build. Repository fixtures are not a substitute for that capability check.
- Current-App turn-boundary mode gives a hard Router scheduling-authority boundary, not a physical OS-process settlement guarantee. `SubagentStop` cannot prove that detached/background processes are gone.
- Luna intentionally retains ordinary process-capable Full Executor tools, so the current-App profile relies on the explicit policy prohibition against intentional daemonization/detached long-lived background work where no stronger native process boundary is exposed.
- A1 hard claims remain separately withheld unless the exact enabled runtime surface proves a deterministic pre-action gate and actor attribution.
- Automatic V3.3 degraded PRIMARY mode is intentionally limited to workspace-local development work; it is not an A1 or external-side-effect fallback.
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
