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

That staged workflow remains available as an explicit CLI compatibility path. The optional global policy is intentionally lighter: primary Sol plans and retains final authority, exactly one native `luna_worker` normally executes bounded work for the current routed root turn, and Sol reviews/corrects/finalizes. All Web Sol work remains manual operator copy/paste.

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

## Global default routing policy

The optional global policy makes bounded native Luna delegation the default for substantive Codex turns without adding a daemon, background service, browser bridge, second App instance, or per-prompt legacy Router run. `UserPromptSubmit` classifies each prompt locally and deterministically.

Routing behavior:

1. `[CODEX_ROUTER_DIRECT]` or `本轮不用 Luna` on the first non-empty line forces **only the current turn** to primary-Sol direct execution. No Luna is created or used for that turn; the next normal substantive request routes again.
2. Existing exact first-line `本次不用 Router` or `仅本地执行` bypass markers also apply only to the current turn.
3. Greetings, thanks, trivial arithmetic, brief concept explanations, current-task metadata, and one-step read-only inspection may run directly.
4. Changes, reviews, security or architecture work, research, verification, comparisons, decisions, plans, multi-step work, sensitive content, and ambiguity route through Router by default when the Hook is active and trusted.

A routed turn injects a stateless policy context equivalent to:

```text
workflow=native_luna_worker
sol_role=plan_review_final_authority
luna_role=default_execution
delegation_mode=sequential_work_packets
luna_lifecycle=persistent_while_root_turn_active
parent_terminal_policy=revoke_then_cleanup
capacity_failure_policy=return_to_sol
luna_descendant_policy=forbidden
luna_codex_runtime_policy=forbidden
interactive_blocker_policy=return_to_sol_or_user
initial_context_mode=packet_only
web_mode=manual_operator
```

The primary Sol remains the highest ordinary execution authority. It must retain the native multi-agent capability needed to create, communicate with, observe, and perform one bounded cleanup operation on the current Router-managed Luna. The Router does **not** intentionally apply Luna's descendant-agent restriction to primary Sol.

Each routed root turn may bind at most one `luna_worker`. While that root turn remains authorized, Sol should reuse the same Luna across sequential work and correction packets, including after a Luna packet becomes completed or idle. Every packet restates its packet id, working directory, allowed paths, forbidden operations, validation, stop conditions, and required output. The previous packet's path authorization expires when a new packet is issued.

Luna is a bounded execution worker, not a second coordinator. Its custom agent profile disables descendant multi-agent capability and the known continuation/executor surfaces that would evade the supported Hook guard. Router additionally denies Luna attempts to launch/resume Codex, manipulate agent lifecycle, or obtain user-required permission escalation. Those Luna-specific restrictions must not be copied into the primary Sol's global effective configuration.

A stale or turn-mismatched Luna binding is irreversibly revoked before new work is admitted. Parent termination revokes authorization before any best-effort cleanup. On the deployed Multi-Agent V2 capability model, an observed `interrupt_agent` result is only cancellation evidence; it is not proof that an agent process was destroyed. Stop is a one-shot backstop: it may request at most one cleanup continuation after revocation and must never create an autonomous cleanup/wait/retry loop.

Capacity exhaustion and ordinary Luna blockers return control to Sol. Sol may retry with new evidence, narrow the packet, reuse the still-authorized Luna, take over ordinary execution, ask the user, or stop. Only stale-Luna resurrection, Luna process recursion, and interactive-security bypass are hard Router guards.

For permission requests, Router denies a Luna-originated `PermissionRequest`. For primary Sol or unrelated execution, Router does not return an automatic approval decision; native Codex/user approval remains authoritative.

The Luna nested-Codex gate is deliberately bounded. It classifies the supported one-shot shell command surface by effective executable intent and blocks direct/wrapped Codex launches. It must not reject a command merely because a filename or text argument contains the string `codex`. The guarantee is `LUNA_CODEX_GATE_VERIFIED_FOR_SUPPORTED_COMMAND_SURFACE`, not kernel-level process confinement.

If the `UserPromptSubmit` Hook is absent, disabled, skipped because trust changed, or otherwise not injected, the turn is **Router inactive**. Codex may then execute directly as a degraded fallback, but that is not a successful routed turn and should not be interpreted as `Router: active`.

The routing Hook does not create a legacy `run_id`, write the configured legacy state root, launch a model, or touch a browser. Native safety state is limited to the private turn-scoped Luna authorization journal used to prevent stale child reuse.

Install only from a durable Python environment where `codex_router` is installed for the same absolute interpreter recorded in the Hook command. The generated command uses `-E -P -m codex_router` so it cannot depend on the caller's `PYTHONPATH` or working directory. Before changing managed files, installation preflights the exact `UserPromptSubmit` command with a synthetic direct event and requires one valid Router hook-protocol JSON response. A failed probe leaves all managed user files unchanged:

```bash
router global-install \
  --codex-home "/absolute/path/to/active-codex-home" \
  --state-dir "/absolute/private/path/to/codex-router-runs" \
  --codex-bin "/Applications/ChatGPT.app/Contents/Resources/codex" \
  --local-model "gpt-5.6-sol" \
  --local-reasoning "max" \
  --web-model "sol" \
  --web-reasoning "xhigh" \
  --luna-model "gpt-5.6-luna" \
  --luna-reasoning "max"
```

Installation manages Router command handlers for `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PermissionRequest`, `Stop`, `SubagentStart`, and `SubagentStop`; one bounded block in `AGENTS.md`; and one custom agent at `agents/luna-worker.toml`. It preserves unrelated Hook groups and user files. The Luna file defines `name=luna_worker`, uses the configured Luna model/reasoning, disables descendant multi-agent capability for that child, and deliberately omits sandbox/approval overrides so ordinary platform controls remain inherited. The installer does not edit `config.toml`, `AGENTS.override.md`, or unrelated agent files.

Because the installer does not own the primary Codex `config.toml`, live activation must independently verify that the **primary Sol** still has the multi-agent capability required to create/reuse Luna. An effective global setting that disables primary multi-agent operation is incompatible with the default `Sol → Luna → Sol` workflow even if the Router Hook itself is installed correctly.

Original managed files are backed up byte-for-byte under `.codex-router-policy-v1/` with private permissions. The `prepared` manifest records original and installed digests and modes before any managed write. If the process stops after any managed write, `global-status` reports `partial`; the same compatible `global-install` completes remaining writes, while `global-uninstall` restores exact originals. Recovery validates every target before its first write and refuses post-interruption user edits.

Inspect or reverse the installation with:

```bash
router global-status --codex-home "/absolute/path/to/active-codex-home"
router global-uninstall --codex-home "/absolute/path/to/active-codex-home"
```

Uninstall restores exact original bytes and modes when the managed files still match installed hashes. It refuses concurrent or unrelated edits instead of overwriting them. Backups, installation evidence, and legacy Router run state remain. Install/uninstall changes require a new Codex task before session-loaded instructions can change.

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

The self-test invokes the configured Hook command as a child process instead of calling the Hook function in-process. Direct, bypass, repeated route, changed-session, and changed-turn probes use the exact installed command. It verifies route output matches the installed Luna configuration and that no legacy per-prompt Router run is allocated. It performs no model, Web, browser, or network action, does not activate Hook trust, and leaves the configured legacy state root untouched.

### Manual App acceptance checklist

Automated repository tests cannot prove App Hook trust, exact deployed child Hook identity semantics, the post-install Luna tool inventory, or a real Luna model turn. Before treating a live installation as active:

1. Verify the recorded absolute Python interpreter is durable and imports `codex_router` with the configured `-E -P -m codex_router` command.
2. Verify the primary Codex effective configuration has native multi-agent capability enabled. Do not globally disable the feature Sol needs to create/reuse the one Luna.
3. Review and trust the exact managed Router Hook definitions through the supported Codex trust UI/flow after any Hook definition changes. Do not bypass trust with unsafe launch flags.
4. Start a **new** Codex task after installation/trust changes.
5. Submit a normal substantive bounded task. Confirm the routed context is present, Codex shows `Router: active`, Sol plans, one `luna_worker` executes bounded work, and Sol reviews/finalizes.
6. Confirm the Luna task uses the configured Luna model/reasoning and that its actual tool inventory lacks descendant-agent and unsupported continuation/executor capabilities expected to be disabled by its custom profile.
7. Issue a bounded correction packet and verify the same current-turn Luna is reused rather than a second Luna being created.
8. Begin a new turn with `[CODEX_ROUTER_DIRECT]` or `本轮不用 Luna`. Confirm Sol performs that turn directly with no Luna use, while any stale prior-turn binding is revoked. Confirm the following normal substantive turn routes again.
9. Exercise a synthetic lifecycle fixture before real work: verify turn mismatch denies historical Luna communication, first Stop revokes before at most one cleanup continuation, and no post-revoke follow-up/resume path is admitted.
10. Confirm Luna permission escalation is denied while primary Sol permission requests still follow the native Codex/user approval path rather than being Router-auto-approved.
11. Confirm no per-prompt legacy Router run is created and the configured legacy state root is untouched by global routing.
12. Perform any Web Sol consultation manually by copy/paste. Router must not open, close, focus, or automate browser pages.
13. Run `global-uninstall`, start a new Codex task, and confirm managed Hooks, AGENTS block, and `luna_worker` are gone or restored while explicit legacy Router commands and retained installation evidence remain.

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

- Global Router activation depends on Codex actually loading and trusting the current managed Hook definitions; `Router: active` is a routed policy marker, not independent runtime telemetry.
- The current V2 Luna binding adapts to the verified deployed capability surface; live activation must reverify child Hook identity/turn semantics and the generated Luna tool inventory before trust/install is considered complete.
- `interrupt_agent` is cleanup/cancellation evidence, not proof that a child process was permanently terminated. Router safety therefore depends on durable authorization revocation rather than cleanup status.
- The Luna nested-Codex classifier is verified only for its explicit supported command surface; dynamic/unknown executor forms are not advertised as kernel-level confinement.
- The installer does not own primary `config.toml`; a global configuration that disables primary Sol multi-agent capability can prevent Luna creation and must be corrected through the supported Codex configuration flow before runtime acceptance.
- App-driven legacy stages still require Codex App or the operator to execute the returned packet and supply bounded evidence files.
- Real `--adapter-mode real` provider wiring is not configured or validated.
- Web model, reasoning, and context claims are operator-attested rather than browser-verified.
- Hook trust and new-task activation must be confirmed manually through Codex; `global-status` never claims them as verified.
- The Web security gate blocks or redacts detected protected categories but cannot prove every unknown sensitive value was detected.
- Fake mode proves Router orchestration and persistence, not model quality.
- The MVP does not manage Codex archive/delete lifecycle.
- There is no Web UI, daemon, scheduler, distributed queue, retry system, database, browser automation, or plugin marketplace.
- Run state can contain task and stage output. Keep Router-owned state directories private and do not put credentials in tasks.
