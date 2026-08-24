# Router V4.0.1 Routing Ownership + Root Replay Implementation Amendment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this amendment together with the base V4.0.1 plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved PRIMARY ownership gates for explicit no-Luna directives and interactive browser/UI operations, and make transparent root auto-stage idempotent for duplicate delivery of the same native root turn.

**Architecture:** Keep the existing V4.0.1 generation-lease design unchanged after a route decision. Add narrow root-policy matchers in `policy.py` that run before protected-material/substantive classification, and add a replay check in the transparent root path before revoke/restage so the same root event cannot consume two generations. Child `UserPromptSubmit` remains a separate transport branch and is never inspected by these root matchers.

**Tech Stack:** Python >=3.12, stdlib only, existing `unittest`/`pytest` tests, V4 lease journal and Hook overlay.

**Specs:**
- `docs/superpowers/specs/2026-08-24-router-v4-0-1-transparent-auto-stage-design.md`
- `docs/superpowers/specs/2026-08-24-router-v4-0-1-routing-ownership-addendum.md`

**Base plan:** `docs/superpowers/plans/2026-08-24-router-v4-0-1-transparent-auto-stage.md`

## Binding execution order

This amendment is binding on the base plan. Execute in this order:

1. Amendment Task 0 below.
2. Base plan Task 1.
3. Base plan Task 2 plus Amendment Task 2A below.
4. Base plan Task 3.
5. Base plan Task 4 plus Amendment Task 4A below.
6. Base plan Task 5.
7. Base plan Task 6 plus Amendment Task 6A below.

If this amendment conflicts with the base plan only on root routing precedence, explicit no-Luna semantics, interactive browser ownership, root replay idempotence, or the added acceptance gates, this amendment wins. All other base-plan authority/security invariants remain unchanged.

## Global constraints added by this amendment

- Root routing precedence is: explicit no-Luna delegation veto -> legacy direct/bypass markers -> interactive browser/UI ownership -> protected-material routing -> substantive/default routing.
- `[CODEX_ROUTER_DIRECT]` keeps reason `explicit_one_turn_direct`; existing Router bypass markers keep `explicit_one_turn_bypass`.
- Natural-language no-Luna directives use reason `explicit_no_luna`.
- Interactive browser/UI operations use reason `primary_browser_operation`.
- Both new direct paths supersede prior Luna authority using ordinary new-root semantics, create no new Luna lease, expose no prepared spawn payload, and do not copy the turn objective into Luna context.
- The no-Luna matcher is directive-oriented and first-line-bounded; it must not search arbitrary quoted/body text for `Luna` or veto phrases.
- Browser ownership requires an interactive action at an imperative/action boundary plus a browser/webpage target. Merely mentioning browser/UI/code terms is insufficient.
- Playwright/Cypress/headless E2E/local browser-code engineering remains Luna-eligible.
- A mixed turn containing an explicit interactive browser step is PRIMARY-owned for all of V4.0.1; do not add a Luna -> PRIMARY -> Luna orchestration state machine.
- Child `UserPromptSubmit` branches to child transport validation before all root routing matchers.
- Transparent auto-stage creates at most one lease for one native `(session_id, turn_id)` root event.
- An exact same-root replay must never revoke/restage/increment generation.
- A same `(session_id, turn_id)` replay with changed prompt semantics or changed validated `cwd` fails closed without widening authority and without staging a replacement lease.

---

### Task 0: Add PRIMARY Ownership Routing Gates

**Files:**
- Modify: `src/codex_router/policy.py`
- Modify: `tests/test_policy.py`
- Later integration coverage: `tests/test_v4_root_wiring.py`

**Interfaces:**
- Keep public `classify_prompt(prompt: str) -> PolicyDecision` unchanged.
- Add private helpers in `policy.py`:
  - `_is_explicit_no_luna(first_line: str) -> bool`
  - `_is_primary_browser_operation(normalized: str) -> bool`
- Do not add a new policy module or dependency.

- [ ] **Step 1: Write RED tests for natural-language no-Luna directives**

Add to `tests/test_policy.py`:

```python
def test_natural_no_luna_directives_are_primary_owned(self):
    classify = self.policy()
    prompts = (
        "本轮明确禁止 Luna：修复这个问题",
        "不要交给 Luna：修复这些文件",
        "PRIMARY 直接执行：完成本地修改",
        "do not use Luna: fix this locally",
        "don't use Luna: fix this locally",
        "keep this in PRIMARY: fix this locally",
    )
    for prompt in prompts:
        with self.subTest(prompt=prompt):
            result = classify(prompt)
            self.assertEqual(result.decision, "direct")
            self.assertEqual(result.reason_code, "explicit_no_luna")
```

Also prove standalone first-line form with task body on later lines:

```python
def test_no_luna_standalone_first_line_applies_to_current_turn(self):
    result = self.policy()("本轮不要使用 Luna\n修复 Router 并运行测试")
    self.assertEqual((result.decision, result.reason_code), ("direct", "explicit_no_luna"))
```

- [ ] **Step 2: Write RED false-positive tests for quoted/discussed veto phrases**

```python
def test_discussed_no_luna_phrases_do_not_trigger_delegation_veto(self):
    classify = self.policy()
    prompts = (
        "请修复‘不要交给 Luna’这个 Router 识别问题",
        'Add a regression test for the phrase "do not use Luna"',
        "Explain why 本轮不用 Luna failed to match",
    )
    for prompt in prompts:
        with self.subTest(prompt=prompt):
            self.assertNotEqual(classify(prompt).reason_code, "explicit_no_luna")
```

- [ ] **Step 3: Write RED precedence test proving no-Luna beats protected material**

Use a synthetic protected string assembled at runtime so no real secret enters the repository:

```python
def test_no_luna_directive_beats_sensitive_detected(self):
    sensitive = "api_" + "key=synthetic-sensitive-value"
    result = self.policy()(f"本轮明确禁止 Luna：处理 {sensitive}")
    self.assertEqual((result.decision, result.reason_code), ("direct", "explicit_no_luna"))
```

- [ ] **Step 4: Run focused policy tests and confirm RED**

```bash
python3 -m pytest -q tests/test_policy.py
```

Expected: new `explicit_no_luna` assertions fail on the current narrow `_FORCE_DIRECT` grammar.

- [ ] **Step 5: Implement a first-line-bounded no-Luna matcher**

Keep the legacy `_FORCE_DIRECT` regex for `[CODEX_ROUTER_DIRECT]` and its existing reason. Add a separate directive matcher. The implementation must have the same semantics as this sketch:

```python
_NO_LUNA_DIRECTIVE = re.compile(
    r"(?ix)^(?:"
    r"本轮(?:明确)?(?:不用|禁止|不要使用)\s*luna"
    r"|这轮不要交给\s*luna"
    r"|不要(?:交给|调用)\s*luna"
    r"|primary\s+直接执行"
    r"|do\s+not\s+use\s+luna"
    r"|don't\s+use\s+luna"
    r"|keep\s+this\s+in\s+primary"
    r")"
    r"(?:\s*[。.!！]?\s*|\s*[:：,，;；\-—]\s*.*)$",
    re.IGNORECASE,
)


def _is_explicit_no_luna(first_line: str) -> bool:
    return _NO_LUNA_DIRECTIVE.fullmatch(first_line) is not None
```

Do not use `search()` over the whole prompt. Do not match a line that begins with another task verb such as `修复`, `解释`, `Add`, or `Explain` and only later quotes a veto phrase.

Update `classify_prompt` ordering to:

```python
if _is_explicit_no_luna(first_line):
    return PolicyDecision("direct", "explicit_no_luna")
if _FORCE_DIRECT.fullmatch(first_line):
    return PolicyDecision("direct", "explicit_one_turn_direct")
if _BYPASS.fullmatch(first_line):
    return PolicyDecision("bypass", "explicit_one_turn_bypass")
```

Only after those checks may protected-material routing run.

- [ ] **Step 6: Write RED browser-ownership tests**

Add positive cases:

```python
def test_interactive_browser_operations_are_primary_owned(self):
    classify = self.policy()
    prompts = (
        "打开浏览器登录测试站点并点击设置",
        "在 Chrome 里打开这个页面并检查结果",
        "open Chrome and verify the page manually",
        "visit this site in the browser and click Settings",
        "fill the form in the browser and submit it",
        "修复这个 UI bug，然后打开 Chrome 手工验证页面",
    )
    for prompt in prompts:
        with self.subTest(prompt=prompt):
            result = classify(prompt)
            self.assertEqual(result.decision, "direct")
            self.assertEqual(result.reason_code, "primary_browser_operation")
```

Add negative Luna-eligible cases:

```python
def test_headless_and_browser_code_engineering_remain_luna_eligible(self):
    classify = self.policy()
    prompts = (
        "fix this React component",
        "run Playwright tests and fix the failures",
        "run Cypress headlessly",
        "fix the browser click-handler implementation",
        "debug the browser API implementation in this codebase",
        "inspect HTML CSS and JS and fix the failing local E2E test",
    )
    for prompt in prompts:
        with self.subTest(prompt=prompt):
            result = classify(prompt)
            self.assertEqual(result.decision, "route")
```

Also add the ambiguity guard required by the design self-review:

```python
def test_bare_ui_action_without_browser_target_is_not_browser_owned(self):
    result = self.policy()("点击 Login 这个字符串的处理逻辑需要修复")
    self.assertNotEqual(result.reason_code, "primary_browser_operation")
```

- [ ] **Step 7: Implement narrow browser ownership detection**

Use two independent predicates: one for an action boundary and one for a browser/webpage target. Do not treat Playwright/Cypress/headless test terms as browser targets by themselves.

Semantics should match:

```python
_BROWSER_TARGET = re.compile(
    r"(?i)(?:浏览器|网页|网站|页面|chrome\b|safari\b|firefox\b|devtools\b|"
    r"\bbrowser\b|\bweb\s*page\b|\bwebsite\b|\bsite\b|"
    r"\bform\s+in\s+the\s+browser\b)"
)
_BROWSER_ACTION_BOUNDARY = re.compile(
    r"(?ix)(?:"
    r"^\s*(?:打开|访问|登录|填写|滚动|上传|下载|截图)"
    r"|(?:然后|并且|并)\s*(?:打开|访问|登录|填写|滚动|上传|下载|截图)"
    r"|^\s*(?:open|visit|log\s*in|fill|scroll|upload|download|screenshot)\b"
    r"|\b(?:and\s+then|then)\s+(?:open|visit|log\s*in|fill|scroll|upload|download|screenshot)\b"
    r")"
)


def _is_primary_browser_operation(normalized: str) -> bool:
    return bool(_BROWSER_TARGET.search(normalized) and _BROWSER_ACTION_BOUNDARY.search(normalized))
```

The concrete regex may be tightened if a RED test exposes a false positive, but must preserve the approved semantic boundary: actual interactive browser action + browser/web target. `click` alone is not sufficient because it commonly appears in source-code terms such as `click-handler`; a click may be recognized when it is syntactically coupled to an already-detected browser action/target phrase.

Insert browser ownership after legacy direct/bypass checks and before protected-material detection:

```python
if _is_primary_browser_operation(normalized):
    return PolicyDecision("direct", "primary_browser_operation")
```

- [ ] **Step 8: Add protected-material precedence coverage for browser ownership**

```python
def test_browser_ownership_beats_sensitive_detected(self):
    sensitive = "api_" + "key=synthetic-sensitive-value"
    result = self.policy()(f"打开 Chrome 访问测试页并填写 {sensitive}")
    self.assertEqual((result.decision, result.reason_code), ("direct", "primary_browser_operation"))
```

- [ ] **Step 9: Run policy suite GREEN**

```bash
python3 -m pytest -q tests/test_policy.py
```

Expected: PASS with legacy `[CODEX_ROUTER_DIRECT]`, `本次不用 Router`, and `仅本地执行` tests still unchanged.

- [ ] **Step 10: Commit Task 0**

```bash
git add src/codex_router/policy.py tests/test_policy.py
git commit -m "fix: add PRIMARY routing ownership gates"
```

---

### Task 2A: Make Transparent Root Auto-Stage Replay-Idempotent

Execute this as part of base-plan Task 2 before declaring root auto-stage GREEN.

**Files:**
- Modify: `src/codex_router/v4_auto_stage.py` created by base Task 1
- Modify: `src/codex_router/v4_hook.py`
- Modify: `tests/test_v4_root_wiring.py`
- Modify or create focused cases in: `tests/test_v4_auto_stage.py`
- Read contract: `src/codex_router/protocol.py::parse_luna_packet`

**Interfaces:**
- Add `derive_transparent_k1_fields(prompt: str, cwd: str) -> dict[str, Any]` in `v4_auto_stage.py`; it performs deterministic semantic derivation but does not mutate lease state.
- Add `reconstruct_transparent_route(*, secret: bytes, lease: lease_control.LeaseRecord) -> dict[str, Any]`; it derives the existing lease bootstrap capability/message and prepared V1/V2 payload without creating a lease.
- `stage_transparent_route(...)` consumes `derive_transparent_k1_fields` so first delivery and replay use one semantic derivation path.

- [ ] **Step 1: Write RED test for exact same-root replay**

Create an integration test that submits the same root event twice with exactly the same `session_id`, `turn_id`, `prompt`, and validated `cwd`.

Assertions after the second call:

```python
assert second_context["decision"] == "route"
assert second_context["workflow"] == "generation_lease_v4_transparent"
assert second_context["generation"] == first_context["generation"]
assert second_context["task_name"] == first_context["task_name"]
assert second_context["prepared_spawn"] == first_context["prepared_spawn"]
assert snapshot_after_second == snapshot_after_first
```

The journal comparison must prove no generation increment, no revoke/restage, no lease-id replacement, and no authority-field mutation.

- [ ] **Step 2: Write RED mismatch tests for same native turn identity**

For an already auto-staged current root, replay the same `session_id + turn_id` with:

1. changed prompt text that would change objective/write/A1 semantics;
2. changed `cwd`.

Both must fail closed. Assertions:

```python
assert snapshot_after == snapshot_before
assert snapshot_after.generation == snapshot_before.generation
assert snapshot_after.active_lease == snapshot_before.active_lease
```

The returned failure must not include the expected bootstrap capability, spawn message, raw authority packet, or protected prompt text.

Do not convert a changed same-turn event into a new direct task while leaving the old lease active. Treat it as a native replay identity conflict.

- [ ] **Step 3: Run focused root tests and prove RED**

```bash
python3 -m pytest -q tests/test_v4_root_wiring.py tests/test_v4_auto_stage.py
```

Expected: duplicate delivery currently revokes/restages or otherwise does not preserve exact lease identity.

- [ ] **Step 4: Separate semantic K1 derivation from state mutation**

In `v4_auto_stage.py`, factor deterministic fields into one helper:

```python
def derive_transparent_k1_fields(prompt: str, cwd: str) -> dict[str, Any]:
    return {
        "objective": sanitize_objective(prompt, cwd),
        "working_directory": cwd,
        "intended_write_scope": list(derive_write_scope(prompt, cwd)),
        "explicit_side_effect_authorizations": list(derive_a1_authorizations(prompt)),
        "success_criteria": [
            "Satisfy the user's stated objective within the current packet scope.",
            "Verify material changes or results using available local evidence before reporting success.",
        ],
        "stop_conditions": [
            "Stop before an external or persistent side effect that is not explicitly authorized by the original root request.",
            "Stop before accessing unrelated data outside the exact validated working directory unless the original request explicitly requires it and native controls permit it.",
            "Stop when the current generation lease is revoked or superseded, or bootstrap/actor validation fails.",
        ],
    }
```

Use the exact same constants/text for first stage and replay comparison; do not let replay use a second semantic policy implementation.

`sanitize_objective` still calls `secure_web_payload` exactly once per root Hook delivery; do not add another scanner.

- [ ] **Step 5: Detect current-root replay before revoke/restage**

In the root path, after event validation and root policy classification but before `revoke_current_lease`, check whether the snapshot already has an active lease for the exact current root turn.

Use the existing V4 root HMAC proof (`_require_current_v4_root` / `build_stage_capability`) rather than comparing raw turn IDs stored in the journal.

If current-root proof succeeds and an active lease exists:

1. parse `lease.authority_packet_wire` through `protocol.parse_luna_packet`;
2. derive current semantic fields from the incoming prompt/cwd;
3. compare `objective`, `working_directory`, `intended_write_scope`, `explicit_side_effect_authorizations`, `success_criteria`, and `stop_conditions` exactly;
4. require packet `generation == lease.generation` and `packet_id == lease.packet_id`;
5. if all match, reconstruct and return the existing route context without calling revoke, set-current-root, stage, or any lease mutation;
6. if any semantic field differs, return a bounded machine-readable replay-conflict failure without journal mutation.

Never infer replay merely from generation number or task name.

- [ ] **Step 6: Reconstruct the prepared payload from existing lease authority**

Use only Router-owned current lease fields:

```python
capability = lease_control.build_bootstrap_capability(secret, lease)
message = spawn_message(capability)
prepared = {
    "v1": {
        "agent_type": "luna_worker",
        "fork_context": False,
        "message": message,
    },
    "v2": {
        "task_name": lease.expected_task_name,
        "agent_type": "luna_worker",
        "fork_turns": "none",
        "message": message,
    },
}
```

Return the same `generation`, `task_name`, `spawn_message`, and `prepared_spawn` values as the first auto-stage result. A replay may include a diagnostic boolean such as `replay=True` only if existing Hook context conventions allow additive non-authority metadata; PRIMARY must not be required to understand it.

- [ ] **Step 7: Guard already-progressed leases without creating duplicate authority**

If live/native testing shows duplicate `UserPromptSubmit` can arrive after a spawn reservation or after the lease becomes `ACTIVE`, do not restage and do not create a second worker. Add a regression matching the observed event ordering. Prefer a deterministic non-spawning replay response or fail-closed replay-conflict response over duplicate spawn. Do not weaken current authority to accommodate replay.

This is the only observation-driven step in this amendment: the exact post-spawn replay response must follow captured native evidence, but the invariant is fixed — no second lease and no second authority grant for one root turn.

- [ ] **Step 8: Run root/auto-stage tests GREEN**

```bash
python3 -m pytest -q tests/test_v4_auto_stage.py tests/test_v4_root_wiring.py tests/test_v4_request_staging.py tests/test_v4_process_boundary.py
```

- [ ] **Step 9: Commit Task 2A with base Task 2 changes**

Use one coherent commit after the whole root auto-stage boundary is GREEN:

```bash
git add src/codex_router/v4_auto_stage.py src/codex_router/v4_hook.py tests/test_v4_auto_stage.py tests/test_v4_root_wiring.py tests/test_v4_request_staging.py tests/test_v4_process_boundary.py
git commit -m "feat: auto-stage V4 roots idempotently"
```

---

### Task 4A: Install the Ownership Contract and Add Release Gates

Execute this with base-plan Task 4.

**Files:**
- Modify: `src/codex_router/v4_install_adapter.py`
- Modify: `src/codex_router/global_install.py`
- Modify: `tests/test_v4_installed_policy.py`
- Modify: `tests/test_global_self_test.py`
- Modify as needed: `tests/test_v4_install_preflight.py`

- [ ] **Step 1: Add RED installed-policy assertions**

The managed PRIMARY contract must contain concise semantics equivalent to:

```text
- route: use the Router-prepared Luna spawn payload for the native surface actually exposed.
- direct/bypass: continue in PRIMARY and do not create/invoke Luna manually.
- explicit user no-Luna instructions and interactive browser/UI operations are PRIMARY-owned.
```

It must not publish the matcher regex grammar.

- [ ] **Step 2: Add RED self-test routing cases**

The disposable global self-test must assert:

```text
本轮明确禁止 Luna：修复这个问题
-> direct / explicit_no_luna

打开 Chrome 访问测试页面并手工验证
-> direct / primary_browser_operation

run Playwright tests and fix failures
-> route / generation_lease_v4_transparent
```

The self-test remains no-network/no-browser/no-persistent-install-mutation. The browser prompt is only a Hook classification probe; do not actually launch a browser.

- [ ] **Step 3: Update managed PRIMARY policy and self-test expectations**

Keep the contract short. Do not reintroduce request-file/K1 schema mechanics. Add no browser-control implementation to Router; this task only establishes ownership/routing semantics.

- [ ] **Step 4: Add live-gate names**

In the V4.0.1 live acceptance/status set, include:

```text
V401_EXPLICIT_NO_LUNA_DIRECT
V401_EXPLICIT_NO_LUNA_NO_STAGE
V401_EXPLICIT_NO_LUNA_SUPERSEDES_OLD_LUNA
V401_BROWSER_OPERATION_PRIMARY_OWNED
V401_BROWSER_OPERATION_NO_LUNA_STAGE
V401_HEADLESS_BROWSER_ENGINEERING_LUNA_ELIGIBLE
V401_ROOT_REPLAY_IDEMPOTENT
```

Retain the base-plan V4.0.1 gates for auto-stage, spawn-message delivery, bootstrap attempt, actor binding, K1 delivery, terminal behavior, stale-worker rejection, and capacity recovery.

- [ ] **Step 5: Run installer/self-test tests GREEN**

```bash
python3 -m pytest -q tests/test_v4_installed_policy.py tests/test_global_self_test.py tests/test_v4_install_preflight.py
```

- [ ] **Step 6: Commit Task 4A with base Task 4**

```bash
git add src/codex_router/v4_install_adapter.py src/codex_router/global_install.py tests/test_v4_installed_policy.py tests/test_global_self_test.py tests/test_v4_install_preflight.py
git commit -m "feat: install V4.0.1 routing ownership contract"
```

---

### Task 6A: Target-Mac Ownership + Replay Live Acceptance

Execute after base-plan Task 5 exact-head repository validation succeeds and the exact tested wheel is installed through the supported managed refresh path.

**Live probes:**

- [ ] **Step 1: Explicit no-Luna probe**

In a fresh Codex conversation, issue a normal current-turn directive that clearly forbids Luna and requests local work. Required evidence:

```text
DECISION=direct
REASON=explicit_no_luna
LUNA_LEASE_CREATED=NO
LUNA_SPAWN_ATTEMPTED=NO
PRIMARY_CONTINUED=YES
```

- [ ] **Step 2: Sensitive + no-Luna precedence probe**

Use only synthetic protected-looking material. Required:

```text
EXPLICIT_NO_LUNA_DIRECT=YES
SENSITIVE_DETECTED_DID_NOT_FORCE_LUNA=YES
LUNA_LEASE_CREATED=NO
```

Do not use a real token/credential.

- [ ] **Step 3: Browser ownership probe**

Issue a fresh request that actually requires interactive browser operation. Required:

```text
DECISION=direct
REASON=primary_browser_operation
BROWSER_OPERATION_PRIMARY_OWNED=YES
LUNA_LEASE_CREATED=NO
LUNA_SPAWN_ATTEMPTED=NO
```

PRIMARY may perform the browser operation only if the actual Codex runtime exposes/permits the relevant browser surface. Browser capability availability is separate from routing ownership correctness.

- [ ] **Step 4: Headless/browser-engineering Luna probe**

Issue a local engineering task such as `run Playwright tests and fix the failures`. Required:

```text
DECISION=route
HEADLESS_BROWSER_ENGINEERING_LUNA_ELIGIBLE=YES
AUTO_STAGE=YES
```

Then continue through the base happy-path Luna gates.

- [ ] **Step 5: Old-Luna supersession probe**

With an existing current Luna generation, submit a new explicit no-Luna or interactive-browser root turn. Prove:

```text
OLD_LUNA_AUTHORITY_SUPERSEDED=YES
REPLACEMENT_LUNA_LEASE_CREATED=NO
STALE_OLD_LUNA_TOOL_REJECTED=YES
```

Do not wait for `SubagentStop` before checking new-root authority.

- [ ] **Step 6: Same-root replay probe when safely reproducible**

If the native Hook/runtime exposes a safe way to replay the exact same root `UserPromptSubmit`, capture before/after snapshots and prove:

```text
ROOT_REPLAY_IDEMPOTENT=YES
GENERATION_UNCHANGED=YES
LEASE_ID_UNCHANGED=YES
NO_SECOND_LUNA_AUTHORITY=YES
```

If native replay cannot be safely induced, repository regression evidence may satisfy this gate as `LIVE_REPLAY=INCONCLUSIVE`; do not fake a live PASS.

- [ ] **Step 7: Re-run an ordinary Luna happy path after all direct probes**

A new normal non-browser engineering turn must still auto-stage and reach Luna. This proves the ownership gates are narrow exceptions rather than global degradation.

---

## Amendment self-review checklist

Before execution, verify all of the following in the combined base plan + amendment:

- [ ] Every routing-ownership requirement from the approved addendum maps to Task 0, Task 4A, or Task 6A.
- [ ] Child transport remains before root policy classification and receives no browser/no-Luna matching.
- [ ] `sensitive_detected` cannot override `explicit_no_luna` or `primary_browser_operation`.
- [ ] Browser matcher requires action + browser/web target and preserves Playwright/Cypress/headless/local web-engineering routing.
- [ ] Mixed engineering + interactive browser is whole-turn PRIMARY in V4.0.1; no second orchestration state machine is introduced.
- [ ] Same-root exact replay cannot increment generation or replace the lease.
- [ ] Changed same-turn prompt/cwd cannot broaden authority and cannot silently become a second task.
- [ ] Replay reconstruction uses existing lease authority and the same Router bootstrap/spawn derivation, not model-authored fields.
- [ ] No new secret scanner, daemon, worker pool, Luna reuse, nested Codex, or dependency was introduced.
- [ ] Base-plan V1/V2 child transport, first-child bootstrap, actor binding, stale fencing, exact `validated_cwd`, A1, packaging, and live acceptance remain mandatory.
