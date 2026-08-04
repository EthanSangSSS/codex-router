# Global Auto Router Policy V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic default-on prompt routing, a fail-closed Web outbound security gate, and reversible global Codex installation without a daemon or browser bridge.

**Architecture:** A `UserPromptSubmit` command hook calls a pure local policy engine and idempotently creates Router runs. The existing state machine remains authoritative; a shared security scanner gates the Web packet after Local Sol, while a byte-preserving installer manages one global hook and one AGENTS block.

**Tech Stack:** Python 3.12 standard library, `unittest`, canonical JSON, HMAC-SHA-256, `fcntl`, atomic `os.replace`, Codex `hooks.json`.

## Global Constraints

- Phase 2 is stacked on `583ceb9aa8a95d8402c6663da05e9120d4a36776` and stays local.
- Do not push Phase 2 or create/alter a PR.
- Do not start the self-hosted runner.
- Do not install a daemon, LaunchAgent, login item, listener, browser bridge, or App restart mechanism.
- Do not modify live `~/.codex` in automated tests.
- Use TDD: each behavior test must fail for the intended missing behavior before production code.
- Local Sol and Luna default to `max`; Web Sol defaults to `xhigh`; all remain configuration values.
- Never persist or print raw hook session IDs, turn IDs, matched secret values, or duplicate full prompts outside local recovery state.
- No new dependency or lock-file change.

---

### Task 1: Policy types, HMAC identity, and deterministic classification

**Files:**
- Create: `src/codex_router/policy.py`
- Create: `tests/test_policy.py`
- Modify: `src/codex_router/state.py`

**Interfaces:**
- Produces: `PolicyDecision(decision, reason_code, sensitive_categories)`.
- Produces: `classify_prompt(prompt: str) -> PolicyDecision`.
- Produces: `derive_driver_context(secret: bytes, session_id: str) -> str`.
- Produces: `derive_event_identity(secret: bytes, session_id: str, turn_id: str) -> str`.
- Extends state validation to accept legacy `ctx-<uuid>` and hook `ctx-<64 lowercase hex>` identifiers.

- [ ] **Step 1: Add failing bypass and allowlist tests**

  Cover exact first-line bypass, punctuation/case normalization, quoted/example/code-fence non-bypass, greetings, thanks, arithmetic, short conceptual explanations, status metadata, and one-step inspection.

- [ ] **Step 2: Verify policy tests fail for missing module/API**

  Run: `PYTHONPATH=src python3.12 -m unittest tests.test_policy -v`

- [ ] **Step 3: Implement normalized bypass parsing and narrow allowlist**

  Route any write, code/review/security/architecture/research/decision/planning/multi-step/ambiguous prompt. Return bounded snake-case reason codes.

- [ ] **Step 4: Add failing HMAC identity tests**

  Assert same session is stable, different sessions differ, output is `ctx-` plus 64 lowercase hex characters, and no raw identity is returned.

- [ ] **Step 5: Implement full-length keyed identities**

  Use `hmac.new(secret, domain + b"\0" + value, hashlib.sha256).hexdigest()` with separate domains for session, turn, prompt, and event. Use `hmac.compare_digest` for secret-derived comparisons.

- [ ] **Step 6: Update state context validation and run focused tests**

  Run: `PYTHONPATH=src python3.12 -m unittest tests.test_policy tests.test_state -v`

- [ ] **Step 7: Commit**

  `git commit -m "feat(router): add deterministic prompt routing policy"`

### Task 2: Idempotent hook run creation and hook JSON contract

**Files:**
- Create: `src/codex_router/hook.py`
- Create: `tests/test_hook.py`
- Modify: `src/codex_router/state.py`
- Modify: `src/codex_router/cli.py`
- Modify: `src/codex_router/types.py`

**Interfaces:**
- Produces: `handle_user_prompt(event: Mapping[str, Any], installation_dir: Path) -> dict[str, Any]`.
- Produces: CLI `router hook-user-prompt --installation-dir <absolute path>` reading stdin once.
- Extends `start_run` with optional deterministic `run_id` and `idempotency_key`, without changing manual callers.

- [ ] **Step 1: Add failing hook schema and output tests**

  Validate `hook_event_name`, `session_id`, `turn_id`, `prompt`, and `cwd`; assert direct/bypass outputs contain one `hookSpecificOutput` and no prompt.

- [ ] **Step 2: Add failing duplicate-delivery tests**

  Deliver the same event serially and concurrently. Assert one deterministic run directory and identical run IDs; changed turn IDs create different runs.

- [ ] **Step 3: Implement deterministic exact-run allocation**

  Derive `run-hook-<64 hex>` from the event identity. Store only `idempotency_key` and keyed prompt digest in canonical request metadata. Existing matching state returns idempotently; incomplete or mismatched state returns `state-corrupt`/`conflict` and never allocates a second run.

- [ ] **Step 4: Implement hook handling and fail-closed initialization**

  Load bounded mode-`0600` secret/config, classify locally, create route runs before output, and return compact context. Valid route prompts with initialization failure return a bounded `decision=block` object mentioning the one-turn local directive.

- [ ] **Step 5: Implement CLI stdin boundary**

  Cap input bytes, require one JSON object, never echo stdin, preserve the standard JSON error contract for malformed input, and emit exactly one JSON object.

- [ ] **Step 6: Run focused tests**

  Run: `PYTHONPATH=src python3.12 -m unittest tests.test_hook tests.test_cli tests.test_state -v`

- [ ] **Step 7: Commit with Task 1 if interfaces changed together**

  Use the Task 1 commit message if both tasks are one coherent policy commit.

### Task 3: Typed Web outbound security gate

**Files:**
- Modify: `src/codex_router/security.py`
- Modify: `src/codex_router/state.py`
- Modify: `src/codex_router/types.py`
- Create: `tests/test_security.py`
- Modify: `tests/test_state.py`

**Interfaces:**
- Produces: `SecurityDecision` enum-like literals `allow`, `redacted`, `block`.
- Produces: `SecurityResult(decision, value, categories, counts)`.
- Produces: `secure_web_payload(payload: Mapping[str, Any]) -> SecurityResult`.

- [ ] **Step 1: Add failing scanner category tests**

  Construct protected fixtures at runtime for authorization, bearer, cookies,
  sessions, assignments, provider tokens, `.env`, private keys, private paths,
  Luhn-valid cards, email/account identifiers, dict-like secret fields, and
  high-entropy candidates. Test files must not contain usable credentials.

- [ ] **Step 2: Add failing deterministic redaction and re-scan tests**

  Assert replacement tokens are category-only and stable, counts contain no
  matched text, redacted output re-scans to allow, and residual/ambiguous
  material returns block.

- [ ] **Step 3: Implement recursive bounded scanning**

  Walk JSON-safe mappings/lists/strings with depth, field-count, character, and
  byte limits. Redact safely removable categories; block private/signing keys,
  cards, ambiguous structures, high entropy, invalid Unicode, and residuals.

- [ ] **Step 4: Add failing state-machine Web boundary tests**

  Submit Local Sol output containing redacted and blocked fixtures. Assert a
  redacted Web packet contains no original value. Assert block creates a
  terminal Web failure, no executable Web packet, no Luna transition, and no
  automatic fallback.

- [ ] **Step 5: Integrate the gate after Local Sol**

  Build the complete proposed Web payload in memory, scan it before packet
  persistence, store only categories/counts/decision as security evidence, and
  create a validated packet only for allow/redacted. A block commits Local Sol
  success plus a safe `router_security_gate` Web failure record.

- [ ] **Step 6: Verify existing manual and fake paths**

  Run: `PYTHONPATH=src python3.12 -m unittest tests.test_security tests.test_state tests.test_pipeline tests.test_cli -v`

- [ ] **Step 7: Commit**

  `git commit -m "feat(router): add Web outbound security gate"`

### Task 4: Reversible global installer, status, and uninstall

**Files:**
- Create: `src/codex_router/global_install.py`
- Create: `tests/test_global_install.py`
- Modify: `src/codex_router/cli.py`

**Interfaces:**
- Produces: `global_install(codex_home, state_root, codex_binary, defaults) -> GlobalStatus`.
- Produces: `global_status(codex_home) -> GlobalStatus`.
- Produces: `global_uninstall(codex_home) -> GlobalStatus`.
- Produces CLI commands `global-install`, `global-status`, and `global-uninstall`.

- [ ] **Step 1: Add failing preservation and mode tests**

  In a temporary Codex home, seed non-canonical formatted `hooks.json` and
  `AGENTS.md`. Assert semantic preservation during install, exact byte
  restoration after uninstall, mode `0700` install directory, and mode `0600`
  secret/config/backups.

- [ ] **Step 2: Add failing idempotency and conflict tests**

  Repeat install/uninstall; assert one handler/block. Test malformed JSON,
  symlinks, duplicate/conflicting markers, invalid config, and concurrent edits
  all fail closed without overwriting user content.

- [ ] **Step 3: Implement atomic installer storage**

  Use size-limited reads, `lstat`, owner checks for Router files, temp file
  `fsync`, `os.replace`, and directory `fsync`. Generate one 32-byte secret with
  `secrets.token_bytes`; never return it.

- [ ] **Step 4: Implement hook and AGENTS managed mutations**

  Add one `UserPromptSubmit` handler with absolute Python/module command and
  stable Router status marker. Append one unique AGENTS block. Record original
  and installed SHA-256 values. Never edit `config.toml` or
  `AGENTS.override.md`.

- [ ] **Step 5: Implement uninstall and status**

  Restore exact backups when installed hashes match. Remove only a
  Router-created hooks file when the absence backup proves ownership. Refuse
  concurrent hook edits. Leave install evidence/backups and all run state.
  Report hook trust conservatively as `unknown`/`requires-user-check`.

- [ ] **Step 6: Add CLI tests and run focused suite**

  Run: `PYTHONPATH=src python3.12 -m unittest tests.test_global_install tests.test_cli -v`

- [ ] **Step 7: Commit**

  `git commit -m "feat(router): add reversible global Codex installation"`

### Task 5: Safe self-test, documentation, and compatibility

**Files:**
- Modify: `src/codex_router/hook.py`
- Modify: `src/codex_router/global_install.py`
- Modify: `src/codex_router/cli.py`
- Modify: `README.md`
- Create: `tests/test_global_self_test.py`

**Interfaces:**
- Produces CLI `router global-self-test --codex-home <temporary home>`.
- Documents exact manual App acceptance checklist and evidence limits.

- [ ] **Step 1: Add failing self-test privacy tests**

  Use runtime-constructed synthetic sessions/prompts. Assert stable/different
  mappings, bypass/direct/route, duplicate event idempotency, no Web/browser
  action, and no raw values anywhere in output or installation/run files.

- [ ] **Step 2: Implement offline self-test**

  Exercise production policy/hook functions against temporary roots only. Do
  not set a trusted/active claim and do not touch the live Codex home.

- [ ] **Step 3: Document installation and manual acceptance**

  Include `/hooks` review, new-session requirement, Router banner, one run per
  prompt, same/new session behavior, operator-attested Web reuse/no-new-page,
  marker rejection, one-turn bypass, synthetic protected payload block, and
  uninstall/new-session rollback.

- [ ] **Step 4: Run all compatibility tests**

  Run: `PYTHONPATH=src python3.12 -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

  `git commit -m "test(router): cover global routing and security boundaries"`

### Task 6: Final verification and local-only handoff

**Files:**
- Verify all files changed since `583ceb9aa8a95d8402c6663da05e9120d4a36776`.

- [ ] **Step 1: Run required validation**

  ```bash
  PYTHONPATH=src python3.12 -m unittest discover -s tests -v
  python3.12 -m compileall -q src tests
  git diff --check 583ceb9aa8a95d8402c6663da05e9120d4a36776..HEAD
  ```

- [ ] **Step 2: Run fake and real fail-closed smoke tests**

  Use fresh mode-`0700` temporary state roots. Require fake stdout exactly
  `ROUTER_MVP_OK`; require real non-zero, empty stdout, and
  `provider-not-configured` on stderr.

- [ ] **Step 3: Run temporary-home install/uninstall integration**

  Install, status, self-test, uninstall, and status against one explicit
  temporary Codex home. Compare seeded user files byte-for-byte after uninstall.

- [ ] **Step 4: Run leakage scans**

  Run the repository-approved staged scan and `gitleaks git .
  --log-opts='583ceb9aa8a95d8402c6663da05e9120d4a36776..HEAD' --redact`.
  Search tracked branch content for constructed test sentinels and forbidden
  private data while avoiding disclosure of matched text.

- [ ] **Step 5: Audit every requirement and Git boundary**

  Confirm no daemon/browser automation, live Codex mutation, dependency change,
  Phase 2 push, second PR, PR #3 metadata change, runner start, or merge.

- [ ] **Step 6: Prepare a redacted Web review packet**

  Include repository, stacked base/head, changed files, behavior, exact tests,
  evidence limits, risks, and review questions. Exclude local-only paths,
  prompts, session IDs, secrets, and account data.

- [ ] **Step 7: Submit to the existing in-app Web conversation**

  Reuse the current page, wait for the Web reviewer response, and iterate with
  TDD and full re-verification until the reviewer and local evidence agree.

## Plan self-review

- Spec coverage: every trigger, identity, hook, security, persistence,
  installation, status, rollback, compatibility, test, and Git-boundary
  requirement maps to Tasks 1-6.
- Placeholder scan: every implementation step contains a concrete action and verification.
- Type consistency: policy, hook, security, installer, state, and CLI interfaces
  are named once and consumed by later tasks under the same names.
- Execution mode: inline in the current Codex task using
  `superpowers:executing-plans`; no parallel writable agent is permitted.
