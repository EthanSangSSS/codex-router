# Router V3.3 Persistent Task, Disposable Luna Implementation Plan

> **Execution mode:** PRIMARY-only in the existing clean PR #9 worktree. Do not invoke Router/Luna or use subagents. Do not modify the live Router installation or Hook trust.

**Goal:** Replace cross-generation Luna identity continuity with one fresh, generation-scoped worker per K1 generation while preserving V3.2 staging, bootstrap, fallback, and fail-closed security.

**Architecture:** Keep the durable V3.1-compatible journal, but treat its Luna identity fields as transient generation correlation. Rotate the Luna epoch at spawn admission, retain only a bounded HMAC-tagged prior-worker rejection history, clear usable worker identity at the exact terminal transition, and base readiness on structured K1 plus fresh-spawn capability. Consolidate V3.2 usability and compatibility integration into one active module instead of adding a V3.3 overlay.

**Tech Stack:** Python 3.12 standard library, `unittest`, setuptools wheel packaging, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-20-router-v3-3-persistent-task-disposable-luna-design.md`

## Global Constraints

- K1 remains the sole Luna work authority.
- Exact root/session/current-generation, actor, monotonicity, concurrency, descendant, QueueOnly, and A1 gates remain fail-closed.
- Fresh worker spawn is the only model-visible normal generation transport.
- Follow-up compatibility is non-authorizing and not required for readiness.
- Automatic fallback is limited to non-strict mechanically `SAFE_LOCAL_FALLBACK` workspace-local work.
- No dependency, lockfile, live installation, Hook trust, merge, force-push, or unrelated refactor changes.

---

### Task 1: Reproduce the persistent-worker deadlock and actor ambiguity

**Files:**
- Modify then rename: `tests/test_router_usability_v32.py` -> `tests/test_router_usability.py`
- Modify then rename: `tests/test_router_usability_v32_operator.py` -> `tests/test_router_usability_operator.py`
- Preserve/rename: `tests/test_router_usability_v32_security.py` -> `tests/test_router_usability_security.py`

**Interfaces:**
- Consumes: `stage_authority_packet`, `admit_staged_spawn`, spawn correlation, exact Bash/pwd bootstrap, `SubagentStop`.
- Produces: behavioral coverage for fresh worker B, stale A rejection, single-worker consumption, ambiguous-actor denial, and spawn-failure fallback.

- [ ] Add a lifecycle test that completes Gen1 with worker A, asserts the terminal binding is cleared, stages Gen2, and admits/binds worker B without follow-up.
- [ ] Add late worker-A `SubagentStart`, `PreToolUse`, and `SubagentStop` tests after Gen2 begins; assert denial/no mutation.
- [ ] Add concurrent/ambiguous worker tests; assert one reservation/actor only and no authority mutation.
- [ ] Add readiness tests proving missing follow-up is `READY`, while missing spawn degrades only for non-strict safe state and otherwise blocks.
- [ ] Run the new focused tests against V3.2 and record expected RED failures caused by the bound worker, follow-up blocker, and ambiguous Luna actor.

### Task 2: Make worker identity generation-scoped

**Files:**
- Modify: `src/codex_router/luna_control_recovery.py`
- Modify: `src/codex_router/hook.py`

**Interfaces:**
- Consumes: current journal lock, `ControlSnapshot`, `SpawnReservation`, `_commit_staged_packet`, `_snapshot_matches_luna`.
- Produces: atomic generation-local epoch rotation, terminal identity clearing, stale-event rejection, and fail-closed ambiguous Luna actor handling.

- [ ] Rotate `luna_epoch` atomically when a staged fresh spawn commits the next generation.
- [ ] Clear `luna_agent_id`, `luna_task_path`, packet/turn/wire/scope/recovery fields on exact normal terminal/result transitions.
- [ ] Preserve quiescing/settlement semantics without granting new authority.
- [ ] Deny a tool event when any actor source claims Luna but actor identity sources are ambiguous.
- [ ] Run lifecycle and security tests to GREEN, then run the touched legacy lifecycle suites.

### Task 3: Remove follow-up from readiness and rendered authority

**Files:**
- Modify: `src/codex_router/global_install_adapter.py`
- Modify: `src/codex_router/types.py`
- Modify: `tests/test_primary_capability_v3.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_global_install.py`

**Interfaces:**
- Consumes: `native_surface_compatibility`, `primary_gen2_readiness`, global status/self-test rendering.
- Produces: V3.3 fresh-spawn readiness, compatibility-only follow-up telemetry, V3.3 live-gate names, and model-visible disposable-worker instructions.

- [ ] Make structured K1 + supported fresh spawn sufficient for `READY`, independent of follow-up evidence.
- [ ] Preserve `primary_gen2_readiness` as a compatibility alias whose decision is based on next-generation spawn, never historical worker presence.
- [ ] Classify spawn failure as safe degradation, strict block, or safety block using explicit strict/fallback state.
- [ ] Remove `BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` from normal result/reason paths.
- [ ] Render one-generation/one-fresh-worker instructions and update design/version/readiness reporting to V3.3.
- [ ] Replace persistent-reuse/recovery gates with current-generation correlation and stale-generation rejection.

### Task 4: Consolidate the usability implementation

**Files:**
- Rename and modify: `src/codex_router/usability_v32.py` -> `src/codex_router/usability.py`
- Delete after folding: `src/codex_router/usability_v32_integration.py`
- Modify: `src/codex_router/__init__.py`

**Interfaces:**
- Consumes: V3.2 request-file, strict marker, fallback classifier, Bash/pwd bootstrap, CLI compatibility, offline self-test normalization.
- Produces: one install function for the active usability path with no stacked V3.3 monkey patch.

- [ ] Fold stable command/help/error/self-test compatibility into `usability.py`.
- [ ] Remove adapter text/readiness monkey patches now implemented coherently in `global_install_adapter.py`.
- [ ] Keep request path/symlink/mode/ownership/size/schema/replay behavior unchanged.
- [ ] Keep exact Bash/pwd bootstrap behavior unchanged.
- [ ] Update package initialization to install one usability module and refresh the self-test callable once.

### Task 5: Replace current documentation with the V3.3 contract

**Files:**
- Modify: `README.md`
- Keep: `docs/superpowers/specs/2026-08-20-router-v3-3-persistent-task-disposable-luna-design.md`
- Keep/update: `docs/superpowers/plans/2026-08-20-router-v3-3-persistent-task-disposable-luna-implementation.md`
- Remove: the superseded V3.2 spec and implementation plan.

- [ ] Document `Persistent Task, Disposable Luna` and generation-local identity.
- [ ] Document fresh spawn for every generation and no normal follow-up requirement.
- [ ] Document exact terminal clearing, stale-event behavior, fallback limits, and updated live gates.
- [ ] Preserve the repository-vs-live-activation boundary.
- [ ] Search active README/rendered policy/Luna profile for obsolete persistent-worker instructions.

### Task 6: Verify, commit, and update PR #9

**Files:** all task-authorized source, tests, and current docs above.

- [ ] Run focused V3.3, lifecycle, compatibility, request-file, and bootstrap tests.
- [ ] Run `python -m unittest discover -s tests -v`, `python -m compileall -q src tests`, and `git diff --check`.
- [ ] Mirror CI: editable install, fake adapter smoke, fresh wheel build/install, outside-repository fake invocation, disposable global install/self-test/uninstall.
- [ ] Run the configured local incremental secret scan and a final security-focused diff review.
- [ ] Verify the diff whitelist and create normal commits on `hardening/router-usability-v3-2`.
- [ ] Push without force, retitle/rewrite PR #9, verify the exact remote/PR head, and wait for exact-head CI plus Secret Scan success.
- [ ] Leave PR #9 Ready for Review and unmerged; do not touch live installation or Hook trust.
