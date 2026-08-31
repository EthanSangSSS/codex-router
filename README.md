# Codex Router

Native-first orchestration for Codex: PRIMARY plans and reviews, while fresh disposable Luna workers execute substantial local engineering under Codex's native sandbox and approval model.

> **Unofficial community project.** Codex Router is not affiliated with, endorsed by, or maintained by OpenAI.

## What it does

The recommended Native mode keeps the normal Codex conversation as the control plane:

```text
User
  |
  v
PRIMARY / Sol
  |-- simple answers, planning, review, interactive UI work --> PRIMARY
  |
  `-- substantial local engineering -------------------------> fresh luna_worker
                                                               |
                                                               v
                                                         execution evidence
                                                               |
                                                               v
                                                        PRIMARY review/final
```

PRIMARY remains the persistent planner, coordinator, reviewer, and final responder. Luna is a disposable execution subagent for bounded local engineering such as implementation, test suites, builds, package validation, systematic debugging, and headless E2E work.

Native mode intentionally does **not** install Router routing Hooks and does not use the historical K1 / generation-lease / request-staging control plane.

## Current stable line: Native V1.1

Native V1.1 makes delegation explicit and observable.

Before substantive work, PRIMARY emits one decision:

```text
LUNA_DECISION=SPAWN|PRIMARY_ONLY|FALLBACK
LUNA_REASON=<short reason>
```

PRIMARY must attempt one fresh `luna_worker` for substantial local engineering including:

- full test, coverage, or broad regression suites;
- build, compile, package, release-build, simulator, emulator, or Xcode validation;
- isolated-worktree, clean-copy, or exact-head validation;
- multi-file implementation or refactoring;
- iterative systematic debugging;
- multiple independent validation layers such as tests + build + artifact/config inspection;
- local engineering work reasonably expected to take more than five minutes.

PRIMARY stays local for lightweight questions, planning/review-only work, interactive browser/user-session UI work, or when spawning Luna would create a conflicting writable executor.

Optional user overrides:

```text
[USE_LUNA]   # require a Luna attempt when safe and available
[NO_LUNA]    # keep the current turn in PRIMARY
```

Normal use does not require either token.

If native spawning is unavailable or fails, PRIMARY reports a visible `FALLBACK` decision and may continue locally when normal Codex tools permit.

## Safety model

Codex Router is orchestration policy, **not a separate sandbox**. Effective permissions come from Codex's native sandbox, approval policy, exposed tools, and workspace scope.

The generated Luna profile:

- can read, edit, test, build, lint, typecheck, debug, and inspect local Git when the delegated objective requires it;
- cannot spawn descendants or another Codex runtime;
- must not intentionally daemonize persistent background work;
- must not perform unrelated destructive actions;
- must not commit, push, mutate PRs, deploy, publish, communicate externally, mutate cloud resources, or perform system-level installation unless the delegated objective explicitly requires that action and native platform controls permit/approve it;
- must return implementation evidence, tests, blockers, and remaining risks to PRIMARY.

Native installation manages only:

```text
<codex-home>/AGENTS.md                     # one bounded managed block
<codex-home>/agents/luna-worker.toml       # Luna profile
<codex-home>/.codex-native-primary-luna-v1/ # reversible ownership state
```

It preserves unrelated `AGENTS.md` content and unrelated agent/config files. Managed uninstall is fail-closed if owned content was unexpectedly modified.

## Requirements

- Python 3.12+
- a Codex runtime that exposes native subagent spawning for `luna_worker`
- a writable Codex home for installation

The Python runtime has no third-party runtime dependencies.

## Install from source

```bash
git clone https://github.com/EthanSangSSS/codex-router.git
cd codex-router
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Enable Native mode

Use the Codex home that the target Codex installation actually reads:

```bash
router native-install \
  --codex-home "/absolute/path/to/active-codex-home"
```

Defaults:

```text
luna model     = gpt-5.6-luna
reasoning      = max
```

You can override them explicitly:

```bash
router native-install \
  --codex-home "/absolute/path/to/active-codex-home" \
  --luna-model "gpt-5.6-luna" \
  --luna-reasoning "max"
```

Installation or managed-policy changes require a **new Codex conversation/task** before the new PRIMARY instructions and agent surface can be relied on. Once a conversation starts with the new Native configuration, that conversation can continue to spawn fresh Luna workers across later tasks.

## Status and self-test

Inspect the managed installation:

```bash
router native-status \
  --codex-home "/absolute/path/to/active-codex-home"
```

Expected healthy state includes:

```text
state=installed
agents_managed=true
luna_agent_configured=true
router_hooks_present=false
```

Run the offline, non-model self-test:

```bash
router native-self-test \
  --codex-home "/absolute/path/to/active-codex-home"
```

Healthy output reports all checks as `true`:

```text
INSTALL_STATE_CONSISTENT
LUNA_AGENT_CONFIG
NATIVE_PRIMARY_BLOCK
NO_K1_LEASE_CEREMONY
NO_LUNA_DESCENDANTS
ROUTER_ROUTING_HOOK_ABSENT
```

This proves static installation integrity. It does not replace a real fresh-conversation runtime smoke proving that Codex can actually spawn `luna_worker`.

## Uninstall

```bash
router native-uninstall \
  --codex-home "/absolute/path/to/active-codex-home"
```

The command reverses only Native-owned changes and preserves unrelated user configuration. Start a new Codex conversation after uninstalling or changing the managed policy.

## Development

Create an editable environment first so the `src/` layout is importable:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Run the complete test suite and compile check:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
```

Build a wheel:

```bash
python -m pip wheel . --no-deps --wheel-dir dist
```

CI also exercises a fresh-wheel Native install/status/self-test/uninstall lifecycle.

## Historical compatibility paths

This repository contains earlier Router experiments and compatibility code, including the staged Local Sol -> Web Sol -> Luna pipeline and the Hook/K1-based `global-*` control plane.

They remain in the repository for regression coverage and historical reference, but they are **not the recommended user-facing architecture**.

Normal Native users should prefer:

```text
native-install
native-status
native-self-test
native-uninstall
```

The following surfaces are historical/experimental rather than the default setup:

```text
run / start / submit-stage / fail-stage
global-install / global-status / global-self-test / global-uninstall
hook-* / stage-k1*
```

## Security

Please read [SECURITY.md](SECURITY.md) before reporting a vulnerability. Do not include credentials, private repository contents, or sensitive local paths in public issues.

The repository includes automated secret scanning, but users are still responsible for keeping their Codex home, task content, credentials, and local workspace permissions appropriately protected.

## License

MIT. See [LICENSE](LICENSE).
