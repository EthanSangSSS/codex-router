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

The optional global policy makes Router the default for substantive Codex turns without adding a daemon, background service, browser bridge, or second App instance. Codex invokes one `UserPromptSubmit` command hook for each turn. The hook classifies the prompt locally and deterministically:

1. An exact first non-empty line of `本次不用 Router` or `仅本地执行` bypasses Router for that turn only.
2. Greetings, thanks, trivial arithmetic, brief concept explanations, current-task metadata, and one-step read-only inspection may run directly.
3. Changes, reviews, security or architecture work, research, verification, comparisons, decisions, plans, multi-step work, sensitive content, and ambiguity route through Router.

The hook uses a full HMAC-SHA-256 identity for the Codex conversation and a deterministic event identity for the turn. Re-delivery of the same event returns the same run; it cannot create a duplicate replacement run. Raw hook session and turn IDs are not printed or persisted. The normalized task remains in private per-run state as the explicit local-recovery copy.

Install only from an environment where `router` is available to the same absolute Python interpreter recorded in the hook command:

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

Installation adds exactly one handler to `hooks.json` and one bounded block to `AGENTS.md`. It does not edit `config.toml` or `AGENTS.override.md`. Original user files are backed up byte-for-byte under `.codex-router-policy-v1/` with private permissions. The model names and reasoning levels above are configuration values; `max`, `xhigh`, and `max` are defaults, not state-machine constants.

Inspect or reverse the installation with:

```bash
router global-status --codex-home "/absolute/path/to/active-codex-home"
router global-uninstall --codex-home "/absolute/path/to/active-codex-home"
```

Uninstall restores exact original bytes and modes when the managed files still match the installed hashes. It refuses concurrent or unrelated edits instead of overwriting them. Backups, installation evidence, and Router run state remain. Both install and uninstall require a new Codex task before session-loaded instructions can change.

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

The self-test creates only ephemeral Router runs, performs no model, Web, browser, or network action, does not activate hook trust, and leaves the configured state root untouched.

### Manual App acceptance checklist

Automated tests cannot verify Codex UI hook trust, Web model selection, reasoning level, or browser conversation reuse. Before treating a live installation as active:

1. Open `/hooks`, review the exact `UserPromptSubmit` command, and explicitly trust it. Never bypass hook trust with an unsafe launch flag.
2. Start a new Codex task. Confirm `global-status` still reports `hook_trust=requires-user-check`; this conservative value is expected because Router has no supported trust receipt.
3. Submit one substantive synthetic task. Confirm Codex shows `Router: active` and exactly one deterministic run reaches `awaiting_local_sol`.
4. Continue with a related question in the same Codex task. Reuse the current in-app Web Sol conversation and current browser page; do not create a new Web conversation for every related turn. Treat this reuse, Web Sol selection, and `xhigh` reasoning as operator-attested.
5. Start a different Codex task and confirm it receives a different driver context and does not inherit the previous Web conversation.
6. Confirm Local Sol and Luna use the configured local models with `max` reasoning evidence, while Web remains operator-attested.
7. Submit a Web response with a wrong run, packet, revision, digest, or response marker and confirm Router rejects it.
8. Begin one prompt with `仅本地执行` and confirm only that turn bypasses Router; the next substantive turn must route again.
9. Use a synthetic protected-value fixture and confirm the Web-bound packet is deterministically redacted or the run ends with `router-security-gate`, with no Web packet, Luna transition, retry, or fallback.
10. Run `global-uninstall`, start a new Codex task, and confirm the global Router behavior is gone while manual Router commands and retained evidence remain.

Same-task Web continuity is an App/operator responsibility. Router binds the run, driver context, revision, packet, digest, and response marker, but it never opens, closes, focuses, or duplicates browser pages.

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
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
```

## Known limitations

- App-driven stages still require Codex App or the operator to execute the returned packet and supply bounded evidence files.
- Real `--adapter-mode real` provider wiring is not configured or validated.
- Web model, reasoning, and context claims are operator-attested rather than browser-verified.
- Hook trust and new-task activation must be confirmed manually through Codex; `global-status` never claims them as verified.
- The Web security gate blocks or redacts detected protected categories but cannot prove that every unknown sensitive value was detected.
- Fake mode proves Router orchestration and persistence, not model quality.
- The MVP does not manage Codex archive/delete lifecycle.
- There is no Web UI, daemon, scheduler, distributed queue, retry system, database, browser automation, or plugin marketplace.
- Run state can contain task and stage output. Keep the Router-owned state directory private and do not put credentials in tasks.
