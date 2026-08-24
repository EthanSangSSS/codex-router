# Router V4.0.1 Routing Ownership Addendum

## Status

Binding architecture amendment to:

`docs/superpowers/specs/2026-08-24-router-v4-0-1-transparent-auto-stage-design.md`

for PR #10 (`hardening/router-v4-lease-core`).

This addendum is not implementation approval. It must be reviewed and accepted before the implementation plan is revised and code execution begins.

If this addendum conflicts with the base V4.0.1 spec, this addendum wins only for root routing precedence, delegation veto semantics, and browser/UI ownership. All generation-lease, child-transport, bootstrap, actor-binding, stale-fencing, K1, A1, sanitizer, and exact-`validated_cwd` invariants from the base spec remain unchanged.

## Why this amendment exists

A live root prompt produced:

```text
DECISION=route
REASON=sensitive_detected
AUTHORITY_MODEL=generation_lease_v4
RESULT=STOPPED_NO_WRITES
```

while the user had explicitly forbidden Luna for that turn. The current policy already checks explicit direct/bypass before protected-material routing, but its natural-language direct matcher is too narrow: it recognizes only a small exact grammar such as `[CODEX_ROUTER_DIRECT]` or `本轮不用 Luna` on the first non-empty line. Natural directives such as `本轮明确禁止 Luna`, `不要交给 Luna`, or `PRIMARY 直接执行` can therefore fall through to `sensitive_detected` and route despite the user's delegation veto.

The same review identified a second missing ownership rule: interactive browser/UI operations should remain PRIMARY-owned rather than being delegated to Luna. The base V4.0.1 spec defines Luna as a high-freedom engineering executor inside current K1/native controls but does not currently assign interactive browser ownership.

These are routing-policy defects, not lease/bootstrap defects.

## Core routing principle

Router must distinguish **whether Luna should own the turn** from **how Luna is authorized once selected**.

The authority model remains strict after a route decision. But the root routing layer must first honor explicit user ownership choices and tool-surface ownership.

For root `UserPromptSubmit`, routing precedence is:

```text
1. explicit no-Luna delegation veto
2. legacy [CODEX_ROUTER_DIRECT] machine marker and explicit Router bypass (本次不用 Router / 仅本地执行)
3. interactive browser/UI ownership -> PRIMARY
4. protected-material classification
5. substantive local-engineering routing
6. existing trivial/read-only/direct cases
7. ambiguous default
```

Child `UserPromptSubmit` transport admission remains a separate protocol branch and must still execute before all root policy logic.

## 1. Explicit no-Luna delegation veto

### Requirement

A clear user instruction that the current turn must not use Luna is authoritative for delegation selection.

When such a directive is present:

```text
decision=direct
reason=explicit_no_luna
```

Router must:

- treat PRIMARY as the executor for that turn;
- revoke/supersede any prior current Luna generation using the normal new-root semantics;
- clear current root/Luna authority as required by the existing direct path;
- create no new Luna lease;
- create no prepared Luna spawn payload;
- perform no Luna spawn;
- copy no objective into Luna context;
- continue to rely on normal PRIMARY/native safety controls.

`protected_material` or other substantive content must not override this explicit delegation veto.

The existing machine marker `[CODEX_ROUTER_DIRECT]` may retain its current compatibility reason code `explicit_one_turn_direct`. The new natural-language delegation-veto grammar should use `explicit_no_luna` so telemetry can distinguish user ownership choice from the legacy marker.

### Directive grammar

The matcher must be directive-oriented, not keyword-oriented.

It should recognize clear first-line current-turn ownership directives, including equivalent forms such as:

```text
本轮不用 Luna
本轮禁止 Luna
本轮明确禁止 Luna
本轮不要使用 Luna
这轮不要交给 Luna
不要交给 Luna：<task>
不要调用 Luna：<task>
PRIMARY 直接执行：<task>
do not use Luna: <task>
don't use Luna: <task>
keep this in PRIMARY: <task>
```

A directive may be:

- a standalone first non-empty line followed by the task on later lines; or
- a first-line prefix followed by a clear delimiter such as `:`, `：`, `,`, `，`, `;`, `；`, `-`, or `—` and then the task body.

The matcher must not search arbitrary quoted/body text for the phrase `不要交给 Luna` or the token `Luna`.

### Required false-positive guard

The following must **not** trigger the delegation veto merely because the text mentions a veto phrase:

```text
请修复“不要交给 Luna”这个 Router 识别问题
Add a regression test for the phrase "do not use Luna"
Explain why “本轮不用 Luna” failed to match
```

The rule is a current-turn directive grammar, not sentiment/keyword detection.

## 2. Interactive browser/UI ownership

### Requirement

Interactive browser or user-session UI operations are PRIMARY-owned in V4.0.1.

When the root user request requires operating a browser/UI surface interactively, Router returns:

```text
decision=direct
reason=primary_browser_operation
```

and applies the same root supersession semantics as any other direct turn:

- prior Luna authority is revoked/superseded;
- no new Luna lease is staged;
- no Luna spawn is prepared or attempted;
- PRIMARY owns the whole turn.

This rule is intentionally an ownership rule, not a security scanner and not a new control plane.

### Interactive browser/UI examples

The following should be PRIMARY-owned when expressed as actual requested actions:

```text
打开浏览器访问这个网站
在 Chrome 里打开这个页面
在网页里点击 Login
登录这个网站
填写网页表单
滚动页面并检查结果
在网页里上传文件
从网页 UI 下载文件
在浏览器中截图
打开 DevTools 检查页面
visit this site in the browser and click Settings
log in to the site and fill the form
open Chrome and verify the UI manually
```

The deterministic matcher must require evidence of an **interactive action** plus a **browser/UI target**. A standalone action word such as `click`, `登录`, or `截图` is insufficient without browser/UI context. Merely mentioning HTML, CSS, a browser, a button, a URL, or a web framework is also insufficient.

### What remains Luna-eligible

This ownership rule must not reduce Luna to a backend-only executor.

Luna remains eligible for ordinary engineering work such as:

```text
fix this React component
change the CSS and run tests
run the Playwright test suite and fix failures
run Cypress headlessly
debug a browser API implementation in the codebase
fix the code that handles a click event
run local E2E tests
inspect HTML/CSS/JS source
```

Likewise, non-interactive HTTP/API/search/fetch work is not automatically a browser operation merely because it concerns the web. It may remain Luna-eligible when the current K1/native controls permit it and it does not require an interactive authenticated/user browser session.

The router must therefore distinguish:

```text
interactive browser / user-session UI operation -> PRIMARY
local code / CLI / headless browser automation -> Luna eligible
```

### Mixed browser + engineering tasks

For V4.0.1, a single root turn that combines local engineering work with an explicit interactive browser step is owned entirely by PRIMARY.

Example:

```text
fix this UI bug, then open Chrome and verify the page manually
```

returns:

```text
decision=direct
reason=primary_browser_operation
```

V4.0.1 does not split such a turn into `Luna code -> PRIMARY browser -> Luna retry` orchestration. That would introduce partial-objective ownership, multi-stage scheduling, and a second coordination state machine outside the scope of this release.

## 3. Sensitive material precedence

Protected-material detection remains important, but it is no longer allowed to override explicit ownership rules.

For a root prompt:

```text
本轮明确禁止 Luna：处理 <protected material>
```

expected routing is:

```text
decision=direct
reason=explicit_no_luna
```

not:

```text
decision=route
reason=sensitive_detected
```

Similarly, an interactive browser operation that contains sensitive-looking material remains PRIMARY-owned rather than being routed to Luna because of `sensitive_detected`.

This does not weaken the existing V4.0.1 objective sanitizer for Luna-routed turns. It prevents protected material from becoming a reason to delegate against the user's ownership choice or browser ownership rule.

## 4. Root-state semantics

No-Luna and browser-direct turns are still real new root turns.

Therefore they must preserve the V4 root supersession invariant:

```text
new root turn
-> revoke/supersede previous current Luna authority
-> do not wait for SubagentStop
-> return PRIMARY direct decision
-> do not stage a replacement Luna lease
```

This avoids a dangerous interpretation where “do not use Luna this turn” leaves an old Luna generation active in parallel.

A later normal substantive root turn can route Luna again under ordinary V4.0.1 auto-stage semantics. The delegation veto is one-turn only unless the user repeats it.

## 5. Child transport remains isolated

This addendum does not alter child transport admission.

A Luna child `UserPromptSubmit` must still branch to the base-spec child transport validator before any root policy classifier runs. Browser/no-Luna root matchers must never inspect or reclassify the Router-generated child bootstrap transport message.

Accepted child transport remains transport-only and grants no authority before the exact first-child capability bootstrap.

## 6. Model-visible contract

The managed PRIMARY contract should remain short. Add only the ownership semantics necessary for the model to act correctly:

```text
Router may return route, direct, or bypass.
- route: use the Router-prepared Luna spawn payload for the native surface actually exposed.
- direct/bypass: continue in PRIMARY; do not create or invoke Luna manually.
- explicit user no-Luna instructions and interactive browser/UI operations are PRIMARY-owned.
```

Do not expose the natural-language matcher grammar, regexes, sensitive-routing implementation, K1 schema, request-file format, or child-transport internals to PRIMARY.

## 7. Required TDD regressions

Implementation must add RED tests before modifying routing behavior.

### Explicit delegation-veto tests

Must cover:

```text
"本轮明确禁止 Luna：修复这个问题" -> direct / explicit_no_luna
"不要交给 Luna：修复这些文件" -> direct / explicit_no_luna
"PRIMARY 直接执行：完成本地修改" -> direct / explicit_no_luna
"do not use Luna: fix this locally" -> direct / explicit_no_luna
```

With protected material present, the result must remain `direct / explicit_no_luna` and no Luna lease may be staged.

False positives must include:

```text
"请修复‘不要交给 Luna’这个识别问题" -> not explicit_no_luna
"Explain why do not use Luna failed" -> not explicit_no_luna
```

Existing `[CODEX_ROUTER_DIRECT]` and `本次不用 Router` / `仅本地执行` compatibility tests must remain green.

### Browser ownership tests

Positive direct cases:

```text
"打开浏览器登录测试站点并点击设置" -> direct / primary_browser_operation
"open Chrome and verify the page manually" -> direct / primary_browser_operation
"fill the form in the browser and submit it" -> direct / primary_browser_operation
```

Negative Luna-eligible cases:

```text
"fix this React component" -> route
"run Playwright tests and fix the failures" -> route
"run Cypress headlessly" -> route
"fix the browser click-handler implementation" -> route
```

Mixed case:

```text
"fix this UI bug and then open Chrome to verify it" -> direct / primary_browser_operation
```

### State tests

For both `explicit_no_luna` and `primary_browser_operation`:

- seed an old current Luna lease;
- submit the new direct root turn;
- prove old authority is revoked/superseded;
- prove no replacement lease exists;
- prove no prepared spawn payload exists;
- prove no Luna actor remains current.

### Ordering tests

Mechanically prove root precedence:

```text
explicit_no_luna > sensitive_detected
primary_browser_operation > sensitive_detected
```

and prove child transport bypasses root routing classification entirely.

## 8. Live acceptance additions

In addition to the base V4.0.1 happy-path acceptance, target-Mac live testing must include:

```text
EXPLICIT_NO_LUNA_DIRECT=YES
EXPLICIT_NO_LUNA_NO_STAGE=YES
EXPLICIT_NO_LUNA_SUPERSEDES_OLD_LUNA=YES
BROWSER_OPERATION_PRIMARY_OWNED=YES
BROWSER_OPERATION_NO_LUNA_STAGE=YES
HEADLESS_BROWSER_ENGINEERING_LUNA_ELIGIBLE=YES
```

A sensitive no-Luna live probe should no longer produce `route/sensitive_detected`.

A browser/UI live probe should not create a Luna lease even if the request is substantive.

The normal Luna happy path must still pass afterward in a fresh ordinary engineering turn, proving these rules are narrow ownership exceptions rather than a global degradation of Luna availability.

## 9. Completion criteria added by this amendment

V4.0.1 is not complete until all of the following are true:

1. natural-language explicit no-Luna directives reliably produce PRIMARY direct execution;
2. explicit no-Luna wins over protected-material routing;
3. quoted/discussed no-Luna phrases do not falsely suppress Luna;
4. interactive browser/UI operations are PRIMARY-owned;
5. local/headless browser engineering remains Luna-eligible;
6. mixed engineering + interactive-browser turns are PRIMARY-owned without introducing a new orchestration state machine;
7. both direct ownership paths supersede old Luna authority but create no new Luna lease;
8. child transport and first-child bootstrap authority semantics remain unchanged;
9. ordinary non-browser engineering tasks still transparently auto-stage and route to Luna under the base V4.0.1 design.
