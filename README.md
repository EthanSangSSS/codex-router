# Codex Router

Codex Router is a minimal, fail-closed pipeline that runs one task through:

```text
Local Sol → Web Sol → Luna → final result
```

- **Local Sol** performs local work and is the only stage allowed to modify a target workspace.
- **Web Sol** performs read-only analysis, counter-analysis, and review.
- **Luna** synthesizes the preceding results into the final response.

The MVP executes each stage once, in order. A failed or timed-out stage prevents every downstream stage from running.

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
router run --task "Return exactly ROUTER_MVP_OK" --adapter-mode fake
```

The command prints Luna's final result. Run evidence is written beneath `.router/runs/<run_id>/`:

```text
request.json
local-sol.json
web-sol.json
luna.json
result.json
events.jsonl
```

Stage files and the final result are atomically replaced. Completed stages remain available if a later stage fails.

Use a different state root when needed:

```bash
router run --task "Review this task" --adapter-mode fake --state-dir /path/to/router-runs
```

## Configuration

Fake mode needs no configuration. `--timeout` sets the per-stage timeout in seconds and defaults to 60.

The real-provider adapter boundary is intentionally small:

```text
run(task, context) -> StageResult
```

Provider wiring belongs in `src/codex_router/adapters.py`. This repository does not yet contain an approved real Web Sol or Luna provider configuration. Consequently, `--adapter-mode real` fails closed with `provider-not-configured`; it never pretends that a real provider ran.

## Router handoff protocol

Every stage produces an envelope containing its run and stage identity:

```json
{
  "router_protocol": "codex-router/v1",
  "run_id": "<run_id>",
  "stage": "local_sol",
  "content": "<stage output>"
}
```

For Codex App Server `thread/inject_items`, the envelope is serialized as assistant `output_text` beginning with:

```text
[CODEX_ROUTER_V1]
```

Codex-generated developer, user-shaped, environment, instruction, and installation context is normal internal context. Router parsing ignores that context and recognizes only its own prefix, current `run_id`, and expected stage. A missing or duplicate Router marker is rejected.

## Development

Run all offline tests:

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
```

## Known limitations

- Real Local Sol, Web Sol, and Luna provider wiring is not configured or validated.
- Fake mode proves Router orchestration and persistence, not model quality.
- The MVP does not manage Codex archive/delete lifecycle.
- There is no Web UI, daemon, scheduler, distributed queue, retry system, database, browser automation, or plugin marketplace.
- Run state can contain task and stage output. Keep the router-owned state directory private and do not place credentials in tasks.
