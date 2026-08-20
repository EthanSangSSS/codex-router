# Router V3.2 Usability Hardening Implementation Plan

> **Execution status:** implemented on `hardening/router-usability-v3-2`; final verification/review remains before landing.

**Goal:** Make Router reliably usable for normal Codex work by separating security failures from recoverable runtime capability failures, while preserving K1 as the sole Luna work authority.

**Final architecture:** Keep V3.1 journal/locking/identity state as the safety core. Layer V3.2 usability behavior through `usability_v32.py` plus a narrow compatibility integration overlay. Active staging keeps the stable `stage-k1-fields` public name but uses a complete Router-injected `--request-file` command. Mechanical fallback state, exact strict mode, and a Bash/pwd allowlisted K1 bootstrap reduce operational failure without creating another authority path.

**Spec:** `docs/superpowers/specs/2026-08-20-router-v3-2-usability-hardening-design.md`

## Global constraints

- K1 remains the sole authoritative Luna work packet.
- Native spawn/follow-up messages remain non-authoritative transport triggers.
- `send_input` and `resume_agent` remain forbidden; `send_message` remains QueueOnly.
- No wait-as-sync, polling/sleep security primitive, second control plane, daemon, or broad shell firewall.
- Automatic PRIMARY degradation is allowed only from mechanically `SAFE_LOCAL_FALLBACK` and never grants A1/external side effects.
- Exact `[CODEX_ROUTER_STRICT]` disables capability degradation for that turn.
- Existing V1/V2 normalization, actor/identity correlation, generation monotonicity, and lifecycle fail-closed rules remain intact.

---

## Task 1 — Stable request-file K1 staging

**Implemented files:**
- `src/codex_router/usability_v32.py`
- `src/codex_router/usability_v32_integration.py`
- `src/codex_router/__init__.py`
- `tests/test_router_usability_v32.py`
- `tests/test_router_usability_v32_security.py`

- [x] Define a seven-field request schema.
- [x] Prove RED against V3.1 before implementation.
- [x] Derive exact private request path from session/root-turn keyed tags.
- [x] Validate exact path, regular/no-follow file, ownership, permissions, size and JSON schema.
- [x] Reject path escape, symlink, group/world-writable files, invalid list types and relative working directory.
- [x] Normalize otherwise safe readable files to `0600`.
- [x] Construct canonical K1 only inside Router and reuse existing one-time capability validation.
- [x] Delete only the same request inode after successful staging; retain failed requests for diagnostics.
- [x] Preserve the public `stage-k1-fields` command name and add mutually exclusive `--request-file` operation through the V3.2 compatibility layer.
- [x] Render one complete stage command; PRIMARY appends no packet flags.
- [x] Return mechanical `primary_fallback_state` on request-mode error without mutating authority.

**Compatibility decision:** the initial spike proposed an active `stage-k1-request` subcommand. The final design intentionally keeps `stage-k1-fields --request-file` as the active installed surface to reduce command-name/session drift. The internal alias remains an implementation seam, not the V3.2 operator contract.

---

## Task 2 — Mechanical PRIMARY fallback and strict mode

- [x] Add pure `classify_primary_fallback(snapshot)` with `SAFE_LOCAL_FALLBACK`, `BLOCKED_ACTIVE_AUTHORITY`, `BLOCKED_PENDING_SPAWN`, and `BLOCKED_TASK_STATE`.
- [x] Require ACTIVE + IDLE + no packet/child/wire/pending for safe fallback.
- [x] Add exact first-nonempty-line `[CODEX_ROUTER_STRICT]` marker without natural-language heuristics.
- [x] Preserve existing direct/bypass one-turn semantics.
- [x] Keep fresh normal Gen1 Hook context shape stable; inject fallback metadata only for strict mode or an existing Router epoch where continuation/degradation is relevant.
- [x] Limit automatic fallback instructions to workspace-local read/edit/test/build/local-Git/debug work.
- [x] Explicitly exclude deploy/publish/release, credentials, cloud/service mutation, package publication, A1 effects, privilege/auth changes, and agent creation/delegation.
- [x] Keep `native_surface_compatibility()` capability classification separate from state-based fallback authority.
- [x] Preserve legacy complete-V2 PRIMARY admission and additionally admit proven V1 Gen1 when structured sideband staging is evidenced.
- [x] Preserve the one-argument `primary_gen2_readiness()` compatibility API while allowing V3.2-aware `UNAVAILABLE_DEGRADE_ALLOWED`, `UNAVAILABLE_STRICT_BLOCK`, and `UNAVAILABLE_SAFETY_BLOCK` classification.

---

## Task 3 — Allowlisted first-tool bootstrap

- [x] Align tests with the real Codex Hook shape: `tool_name=Bash`, `tool_input={"command":"pwd"}`.
- [x] Prove RED against the V3.1 denial-dependent path.
- [x] Allow only the exact Bash/pwd probe when current Luna identity and staged authority validate.
- [x] Return `permissionDecision=allow` plus exact canonical K1 `additionalContext`.
- [x] Deny any other first Bash command before executor state starts.
- [x] Deny `pwd` when the tool payload contains extra fields.
- [x] Retain older/non-Bash V3.1 deny-retry compatibility behavior for existing tests/wire assumptions.
- [x] Keep live delivery of `allow + additionalContext` as a post-install runtime acceptance claim rather than inferring it from repository tests.

---

## Task 4 — Offline compatibility and regression safety

- [x] Preserve exact V1/V2 native schema, QueueOnly, no-descendant, lifecycle and generation safety tests.
- [x] Keep initial route context stable so V3.2 does not create unnecessary session/tool-surface churn.
- [x] Normalize only the offline self-test comparison view; production Hook output is not rewritten for self-test convenience.
- [x] Refresh the CLI's eagerly imported `global_self_test` callable after V3.2 integration install.
- [x] Run full CI once after implementation: unit tests, compile, diff check, fake adapter, wheel build, fresh wheel install/offline self-test all passed at head `be52cf1069e23cb8e32a9b91eb62780f24d6ad29` before the final security-test/doc commits.
- [x] Secret Scan passed at the same implementation head.
- [ ] Re-run exact-head CI and Secret Scan after final security tests/documentation.
- [ ] Complete security-focused diff review.
- [ ] Update README/PR body with final operational semantics.
- [ ] Mark PR ready only after exact-head verification.

---

## Task 5 — Documentation and live rollout

- [x] Update the V3.2 design spec to the final stable request-mode architecture.
- [x] Record the implementation/compatibility decisions in this plan.
- [ ] Document the user-facing operational states and new-task rules in repository usage docs/PR body.
- [ ] After repository landing, refresh the live installation from landed `main`.
- [ ] Review/trust session-loaded Hook/profile changes and start a new Codex task for live V3.2 acceptance.

## Required landing verification

The final PR head must have direct evidence for:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
```

and the CI workflow equivalents for:

- fake adapter smoke;
- wheel build;
- fresh disposable wheel install;
- offline self-test;
- exact-head Secret Scan.

No repository test may be presented as proof of unobserved App runtime behavior. In particular, live delivery of `allow + additionalContext`, exact target-profile inventory, and any hard A1 runtime gate remain live acceptance facts.
