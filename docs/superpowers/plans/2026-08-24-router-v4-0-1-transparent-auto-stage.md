# Router V4.0.1 Transparent Auto-Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every new managed Codex conversation able to route substantive work to Luna through Router-owned auto-staging and prepared V1/V2 spawn payloads, while preserving first-child capability binding, stale-generation fencing, exact `validated_cwd` write scope, and explicit-intent A1 boundaries.

**Architecture:** Add a focused `v4_auto_stage.py` module that derives the canonical K1 from the validated root event, calls the existing `secure_web_payload` exactly once for objective sanitization, stages the next V4 generation internally, and returns Router-prepared V1/V2 spawn payloads. `v4_hook.py` will separate root `UserPromptSubmit` from child transport `UserPromptSubmit` before classification: only the exact current reserved generation's Router spawn message is admitted for a child, and authority remains unbound until the exact first child bootstrap `PreToolUse`. Existing V4 lease state, request-file CLI compatibility, V1/V2 parent spawn enforcement, native sandbox/approval, and terminal fencing remain in place.

**Tech Stack:** Python >=3.12, stdlib only, `unittest`/`pytest` test runner, existing Codex Router Hook/lease-control modules, setuptools wheel build.

**Spec:** `docs/superpowers/specs/2026-08-24-router-v4-0-1-transparent-auto-stage-design.md`

## Global Constraints

- Repository: `EthanSangSSS/codex-router`; implementation stays on PR #10 branch `hardening/router-v4-lease-core`.
- Resolve the current PR head from GitHub at execution time; do not assume the plan-document commit is still the implementation base.
- Keep PR #10 OPEN and Draft during implementation and live acceptance. Do not merge or enable auto-merge.
- Python requirement remains `>=3.12`; add no runtime dependency.
- Keep the existing V4 journal protocol `codex-router/lease-control/v4.0`; no destructive journal migration.
- Preserve monotonic generation fencing, root supersession, HMAC bootstrap, first-child `agent_id + child_turn_id` binding, stale-worker denial, and V1/V2 compatibility.
- Child `UserPromptSubmit` is transport-only. It must never classify as a root prompt, revoke/restage a lease, change generation/current-root authority, bind an agent, or inject K1.
- Child transport is admissible only for the exact current `STAGED` lease with a current spawn reservation and exact Router-generated current `spawn_message`; stale/foreign/unknown child input fails closed without journal mutation.
- V2 parent `PreToolUse` continues to treat spawn `message` as encrypted opaque data; plaintext equality is checked only at child `UserPromptSubmit`.
- `intended_write_scope` is either `[]` or exactly `[validated_cwd]`; never replace `validated_cwd` with Git root, repository root, a parent directory, or a model-inferred workspace.
- Objective sanitization uses exactly one call to existing `codex_router.security.secure_web_payload({"objective": candidate})`; no second secret scanner or model-authored sanitizer.
- The exact validated `cwd` prefix may be canonicalized to `<cwd>` before that one security call; unrelated absolute paths are not pre-whitelisted.
- A1 categories default to empty and may be derived only from explicit positive intent in the original root prompt; existing `validate_packet_authorizations` remains the final schema gate.
- Existing `stage-k1-fields --request-file` remains available for diagnostics/rollback compatibility but is not part of the normal new-conversation route.
- No daemon, MCP control plane, worker pool, Luna reuse, nested Codex, descendant agents, polling authority, concurrency-limit bypass, or transactional rollback.
- Historical-conversation resume is compatibility evidence, not a release blocker; new conversations are the release-critical surface.

## Execution Preflight — Mandatory Before Task 1

Use an isolated clean worktree at execution time. Do not implement in the user's currently dirty unrelated checkout.

- [ ] **Step 1: Fetch remote reality and inspect PR #10**

```bash
git fetch origin
gh pr view 10 --repo EthanSangSSS/codex-router \
  --json state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,mergeable,mergeStateStatus
```

Required before proceeding:

```text
state=OPEN
isDraft=true
headRefName=hardening/router-v4-lease-core
baseRefName=main
```

Record `headRefOid` as `PR_HEAD` and `baseRefOid` as `PR_BASE`. Stop if the PR is merged/closed, branch names differ, or GitHub cannot resolve the refs.

- [ ] **Step 2: Create/use an isolated worktree via `superpowers:using-git-worktrees`**

The execution workflow must invoke the worktree skill. The resulting worktree must point at `hardening/router-v4-lease-core` and contain no unrelated user changes.

- [ ] **Step 3: Synchronize the implementation worktree to GitHub PR head**

```bash
git status --short
git rev-parse HEAD
git rev-parse origin/hardening/router-v4-lease-core
```

If `git status --short` is non-empty, stop. If local HEAD differs from `PR_HEAD`, run:

```bash
git pull --ff-only origin hardening/router-v4-lease-core
```

Then verify:

```bash
test "$(git rev-parse HEAD)" = "$PR_HEAD"
git status --short
```

Stop on non-fast-forward, branch mismatch, or dirty state.

---

### Task 1: Build the Router-Owned Auto-Stage Derivation Module

**Files:**
- Create: `src/codex_router/v4_auto_stage.py`
- Create: `tests/test_v4_auto_stage.py`
- Read only for contracts: `src/codex_router/security.py`, `src/codex_router/a1.py`, `src/codex_router/protocol.py`, `src/codex_router/lease_control.py`, `src/codex_router/v4_cli.py`

**Interfaces:**
- Consumes: `security.secure_web_payload`, `a1.validate_packet_authorizations`, `protocol.build_luna_packet`, `lease_control.build_stage_capability`, `lease_control.stage_authorized_lease`, `lease_control.build_bootstrap_capability`, `v4_cli.spawn_message`.
- Produces:
  - `sanitize_objective(prompt: str, cwd: str) -> str`
  - `derive_write_scope(prompt: str, cwd: str) -> tuple[str, ...]`
  - `derive_a1_authorizations(prompt: str) -> tuple[str, ...]`
  - `stage_transparent_route(*, installation_dir: Path, secret: bytes, session_id: str, root_turn_id: str, prompt: str, cwd: str, snapshot: lease_control.LeaseSnapshot) -> dict[str, Any]`
- `stage_transparent_route` returns exactly these top-level keys for Hook consumption:
  - `packet_id`
  - `generation`
  - `task_name`
  - `bootstrap_capability`
  - `spawn_message`
  - `prepared_spawn`
- `prepared_spawn` contains `v1` and `v2` mappings. V1 is `{agent_type, fork_context, message}`; V2 is `{task_name, agent_type, fork_turns, message}`.

- [ ] **Step 1: Write RED tests for one-call objective sanitization and exact cwd canonicalization**

Create `tests/test_v4_auto_stage.py` with focused tests. Use `unittest.mock.patch` against `codex_router.v4_auto_stage.security.secure_web_payload` so the call count is mechanical.

```python
from unittest.mock import patch

from codex_router.types import SecurityResult
from codex_router.v4_auto_stage import sanitize_objective


def test_sanitize_objective_canonicalizes_only_validated_cwd_and_calls_security_once(tmp_path):
    cwd = str(tmp_path / "repo")
    prompt = f"fix {cwd}/src/app.py and inspect /Users/other/private.txt"
    returned = SecurityResult(
        "redacted",
        {"objective": "fix <cwd>/src/app.py and inspect [REDACTED:private_path]"},
        ("private_path",),
        {"private_path": 1},
    )
    with patch(
        "codex_router.v4_auto_stage.security.secure_web_payload",
        return_value=returned,
    ) as secure:
        objective = sanitize_objective(prompt, cwd)

    assert objective == "fix <cwd>/src/app.py and inspect [REDACTED:private_path]"
    secure.assert_called_once_with(
        {"objective": "fix <cwd>/src/app.py and inspect /Users/other/private.txt"}
    )
```

Also add:

```python
def test_sanitize_objective_does_not_rewrite_cwd_prefix_lookalike(tmp_path):
    cwd = str(tmp_path / "repo")
    prompt = f"inspect {cwd}2/file.py"
    # The value supplied to secure_web_payload must still contain cwd + "2".
```

And block behavior:

```python
def test_sanitize_objective_block_result_raises_safe_router_error(tmp_path):
    result = SecurityResult("block", None, ("private_key",), {"private_key": 1})
    with patch(
        "codex_router.v4_auto_stage.security.secure_web_payload",
        return_value=result,
    ):
        with pytest.raises(RouterStateError) as raised:
            sanitize_objective("sensitive raw material", str(tmp_path))
    assert "sensitive raw material" not in str(raised.value)
```

- [ ] **Step 2: Run the focused test to prove RED**

```bash
python3 -m pytest -q tests/test_v4_auto_stage.py
```

Expected: FAIL because `codex_router.v4_auto_stage` does not exist.

- [ ] **Step 3: Implement cwd canonicalization and the single security API call**

Create `src/codex_router/v4_auto_stage.py` with this boundary:

```python
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from . import lease_control, security
from .a1 import validate_packet_authorizations
from .protocol import ProtocolError, build_luna_packet
from .state import RouterStateError
from .v4_cli import spawn_message


def _canonicalize_cwd_references(prompt: str, cwd: str) -> str:
    exact = cwd.rstrip("/") or "/"
    if exact == "/":
        return prompt
    pattern = re.compile(
        r"(?<![A-Za-z0-9_.-])"
        + re.escape(exact)
        + r"(?=$|[/\s'\"`),.;:!?])"
    )
    return pattern.sub("<cwd>", prompt)


def sanitize_objective(prompt: str, cwd: str) -> str:
    candidate = _canonicalize_cwd_references(prompt, cwd)
    secured = security.secure_web_payload({"objective": candidate})
    if secured.decision not in {"allow", "redacted"}:
        raise RouterStateError("invalid-input", "objective cannot be routed safely")
    value = secured.value
    objective = value.get("objective") if isinstance(value, dict) else None
    if not isinstance(objective, str) or not objective.strip():
        raise RouterStateError("invalid-input", "objective cannot be routed safely")
    return objective
```

Do not call `contains_protected_material`, `_redact_text`, or any new scanner from this function.

- [ ] **Step 4: Add RED tests for exact write scope**

Add table-driven cases:

```python
@pytest.mark.parametrize(
    ("prompt", "writes"),
    [
        ("fix the failing tests", True),
        ("please edit src/app.py", True),
        ("帮我修复测试失败", True),
        ("修改这个实现并验证", True),
        ("review this PR", False),
        ("research why this fails", False),
        ("plan how to fix this later", False),
        ("explain how to edit the file", False),
    ],
)
def test_write_scope_is_exact_validated_cwd_or_empty(prompt, writes, tmp_path):
    cwd = str(tmp_path / "repo" / "nested")
    assert derive_write_scope(prompt, cwd) == ((cwd,) if writes else ())
```

- [ ] **Step 5: Implement deterministic write-intent extraction**

Use conservative command-oriented patterns rather than the broad Router route classifier:

```python
_WRITE_INTENT = re.compile(
    r"(?is)(?:"
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+|help\s+me\s+to\s+)?"
    r"(?:edit|modify|create|delete|write|implement|fix|refactor|update)\b"
    r"|\b(?:and|then)\s+(?:edit|modify|create|delete|write|implement|fix|refactor|update)\b"
    r"|^\s*(?:请|请帮我|帮我)?(?:修改|编辑|创建|删除|写入|实现|修复|重构|更新)"
    r"|(?:并|并且|然后)\s*(?:修改|编辑|创建|删除|写入|实现|修复|重构|更新)"
    r")"
)
_READ_ONLY_PREFIX = re.compile(
    r"(?is)^\s*(?:review|research|inspect|compare|plan|explain|分析|研究|审查|评审|比较|规划|计划|解释)\b"
)


def derive_write_scope(prompt: str, cwd: str) -> tuple[str, ...]:
    if _READ_ONLY_PREFIX.search(prompt) and not re.search(
        r"(?is)\b(?:and|then)\s+(?:edit|modify|create|delete|write|implement|fix|refactor|update)\b|"
        r"(?:并|并且|然后)\s*(?:修改|编辑|创建|删除|写入|实现|修复|重构|更新)",
        prompt,
    ):
        return ()
    return (cwd,) if _WRITE_INTENT.search(prompt) else ()
```

Do not call `git rev-parse`, search for a repository root, or resolve a parent directory.

- [ ] **Step 6: Add RED tests for explicit A1 intent, including required negatives**

For every category, include at least one positive test. Required negatives:

```python
assert derive_a1_authorizations("review PR #10") == ()
assert derive_a1_authorizations("explain deployment") == ()
assert derive_a1_authorizations("why did push fail?") == ()
```

Positive examples:

```python
assert "git_push" in derive_a1_authorizations("push this branch to origin")
assert "remote_collaboration_mutation" in derive_a1_authorizations("update PR #10")
assert "deploy_release_publish" in derive_a1_authorizations("deploy this service to production")
assert "outbound_user_communication" in derive_a1_authorizations("send the customer this message")
assert "cloud_resource_mutation" in derive_a1_authorizations("restart the AWS instance")
assert "system_level_install" in derive_a1_authorizations("brew install jq on this Mac")
assert "comparable_external_persistent_mutation" in derive_a1_authorizations("update the DNS record")
```

- [ ] **Step 7: Implement the explicit-intent table and validate through existing A1 code**

Use this minimal positive-intent table:

```python
_A1_INTENT_PATTERNS = (
    (
        "git_push",
        re.compile(
            r"(?is)(?:\bgit\s+push\b|\bpush\s+(?:this|the|my|our)?\s*(?:branch|commit|changes)\b|"
            r"推送(?:这个|该|当前)?(?:分支|提交|改动|代码))"
        ),
    ),
    (
        "remote_collaboration_mutation",
        re.compile(
            r"(?is)(?:\b(?:create|open|update|edit|close|merge|comment\s+on)\s+"
            r"(?:the\s+|this\s+|a\s+)?(?:pr|pull\s+request|issue)\b|"
            r"(?:创建|新建|更新|修改|关闭|合并|评论)(?:这个|该|当前)?(?:PR|pull request|issue|议题))"
        ),
    ),
    (
        "deploy_release_publish",
        re.compile(
            r"(?is)(?:\b(?:deploy|release|publish)\s+(?:this|the|my|our)?\s*"
            r"(?:app|service|package|release|build)\b|(?:部署|发布|上线)(?:这个|该|当前)?(?:应用|服务|包|版本|构建))"
        ),
    ),
    (
        "outbound_user_communication",
        re.compile(
            r"(?is)(?:\b(?:send|email|message|notify)\s+(?:the\s+)?(?:user|customer|client|team|them|him|her)\b|"
            r"(?:发送|邮件|消息|通知)(?:给)?(?:用户|客户|团队|对方))"
        ),
    ),
    (
        "cloud_resource_mutation",
        re.compile(
            r"(?is)(?:\b(?:create|delete|update|modify|restart)\s+(?:the\s+|this\s+)?"
            r"(?:aws|gcp|azure|cloud|bucket|instance|cluster|database)\b|"
            r"(?:创建|删除|更新|修改|重启)(?:这个|该)?(?:云资源|实例|集群|存储桶|数据库))"
        ),
    ),
    (
        "system_level_install",
        re.compile(
            r"(?is)(?:\b(?:sudo\s+)?(?:apt|apt-get|dnf|yum|brew)\s+install\b|"
            r"\bsystem[- ]wide\s+install\b|(?:系统级|全局)\s*安装)"
        ),
    ),
    (
        "comparable_external_persistent_mutation",
        re.compile(
            r"(?is)(?:\b(?:change|update|modify|delete)\s+(?:the\s+|this\s+)?(?:dns|external\s+database|remote\s+record)\b|"
            r"(?:修改|更新|删除)(?:这个|该)?(?:DNS|外部数据库|远程记录))"
        ),
    ),
)


def derive_a1_authorizations(prompt: str) -> tuple[str, ...]:
    categories = tuple(
        category for category, pattern in _A1_INTENT_PATTERNS if pattern.search(prompt)
    )
    return validate_packet_authorizations(categories)
```

If a test reveals ambiguity, make the matcher narrower, not broader.

- [ ] **Step 8: Add RED test for stateful transparent staging and prepared payloads**

Set up a V4 session, set the current root turn, and call `stage_transparent_route`. Assert:

```python
result["generation"] == 1
result["task_name"].startswith("luna_g1_")
result["prepared_spawn"]["v1"] == {
    "agent_type": "luna_worker",
    "fork_context": False,
    "message": result["spawn_message"],
}
result["prepared_spawn"]["v2"] == {
    "task_name": result["task_name"],
    "agent_type": "luna_worker",
    "fork_turns": "none",
    "message": result["spawn_message"],
}
```

Assert the lease is `STAGED`, has no spawn reservation yet, and no worker binding.

- [ ] **Step 9: Implement internal canonical packet construction and staging**

Use Router-owned defaults and existing lease APIs:

```python
_SUCCESS_CRITERIA = (
    "Satisfy the current user objective within the canonical packet scope.",
    "Verify material changes and results with available local evidence before reporting success.",
)
_STOP_CONDITIONS = (
    "Stop before an external or persistent side effect not explicitly authorized by the current packet.",
    "Stop before unrelated data access outside the exact validated working directory unless the root request explicitly requires it and native controls permit it.",
    "Stop if the current generation is revoked or bootstrap/actor validation fails.",
)


def _packet_id(snapshot: lease_control.LeaseSnapshot) -> str:
    root_tag = snapshot.current_root_turn_tag
    if not isinstance(root_tag, str) or not root_tag:
        raise RouterStateError("conflict", "current root authority is unavailable")
    return f"auto-g{snapshot.generation + 1}-{root_tag[:16]}"


def stage_transparent_route(
    *,
    installation_dir: Path,
    secret: bytes,
    session_id: str,
    root_turn_id: str,
    prompt: str,
    cwd: str,
    snapshot: lease_control.LeaseSnapshot,
) -> dict[str, Any]:
    objective = sanitize_objective(prompt, cwd)
    write_scope = derive_write_scope(prompt, cwd)
    authorizations = derive_a1_authorizations(prompt)
    packet_id = _packet_id(snapshot)
    capability = lease_control.build_stage_capability(
        secret, snapshot, root_turn_id=root_turn_id
    )
    try:
        packet_wire = build_luna_packet(
            packet_id=packet_id,
            generation=snapshot.generation + 1,
            objective=objective,
            working_directory=cwd,
            intended_write_scope=write_scope,
            explicit_side_effect_authorizations=authorizations,
            success_criteria=_SUCCESS_CRITERIA,
            stop_conditions=_STOP_CONDITIONS,
        )
    except ProtocolError as error:
        raise RouterStateError("invalid-input", "automatic K1 packet is invalid") from error
    staged = lease_control.stage_authorized_lease(
        installation_dir,
        secret,
        session_id,
        root_turn_id=root_turn_id,
        capability=capability,
        packet_wire=packet_wire,
    )
    lease = staged.active_lease
    if lease is None:
        raise RouterStateError("conflict", "automatic V4 staging produced no lease")
    bootstrap = lease_control.build_bootstrap_capability(secret, lease)
    message = spawn_message(bootstrap)
    return {
        "packet_id": packet_id,
        "generation": staged.generation,
        "task_name": lease.expected_task_name,
        "bootstrap_capability": bootstrap,
        "spawn_message": message,
        "prepared_spawn": {
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
        },
    }
```

- [ ] **Step 10: Run focused tests GREEN**

```bash
python3 -m pytest -q tests/test_v4_auto_stage.py
```

Expected: PASS.

- [ ] **Step 11: Commit Task 1**

```bash
git add src/codex_router/v4_auto_stage.py tests/test_v4_auto_stage.py
git commit -m "feat: add V4 transparent auto-stage core"
```

---

### Task 2: Replace Normal Root Request-File Staging with Transparent Auto-Stage

**Files:**
- Modify: `src/codex_router/v4_hook.py`
- Modify: `tests/test_v4_root_wiring.py`
- Modify: `tests/test_v4_request_schema_contract.py`
- Modify: `tests/test_v4_request_staging.py`
- Modify: `tests/test_v4_process_boundary.py`
- Preserve compatibility implementation: `src/codex_router/v4_request_staging.py`

**Interfaces:**
- Consumes: `v4_auto_stage.stage_transparent_route` from Task 1.
- Produces normal root Hook context:
  - `decision="route"`
  - `workflow="generation_lease_v4_transparent"`
  - `generation`
  - `task_name`
  - `prepared_spawn`
  - optional machine-readable `V2_PARENT_MESSAGE_PRETOOL_VISIBILITY` and `V2_AUTHORITY_GATE`
- Normal route must not contain `K1_STAGE_COMMAND`, `K1_REQUEST_SCHEMA`, or `K1_STAGE_INTERFACE`.

- [ ] **Step 1: Rewrite root-wiring tests to RED on the current implementation**

Change the routed-root expectation from “issue a stage capability” to “stage immediately”:

```python
def test_new_routed_v4_root_auto_stages_current_generation(self):
    output = handle_hook_event(
        self.root_event(
            "Implement the next bounded repository change.",
            turn_id="new-root-turn",
        ),
        self.installation,
    )
    context = self.context(output)
    assert context["decision"] == "route"
    assert context["workflow"] == "generation_lease_v4_transparent"
    assert context["generation"] == 1
    assert set(context["prepared_spawn"]) == {"v1", "v2"}
    assert "K1_STAGE_COMMAND" not in context
    assert "K1_REQUEST_SCHEMA" not in context

    current = lease_control.read_snapshot(
        self.installation, self.secret, self.session_id
    )
    assert current.active_lease.status == "STAGED"
    assert current.active_lease.expected_task_name == context["task_name"]
```

Keep the direct/bypass supersession tests; they must still prove no active lease and no stage payload.

- [ ] **Step 2: Flip request-schema contract tests to assert the model no longer sees the schema**

Replace old assertions with:

```python
assert context["workflow"] == "generation_lease_v4_transparent"
assert "K1_REQUEST_SCHEMA" not in context
assert "K1_STAGE_COMMAND" not in context
agents = (self.codex_home / "AGENTS.md").read_text(encoding="utf-8")
assert "seven-field UTF-8 JSON request" not in agents
assert "K1_STAGE_COMMAND" not in agents
```

The packet schema remains covered by `tests/test_protocol.py` and the compatibility CLI test; do not delete protocol validation.

- [ ] **Step 3: Change request-file tests into explicit compatibility tests**

Normal root routing must assert request-file staging is absent. Preserve one diagnostic test by establishing a current root manually:

```python
snapshot = lease_control.set_current_root_turn(
    self.installation,
    self.secret,
    self.session_id,
    turn_id="legacy-diagnostic-root",
)
capability = lease_control.build_stage_capability(
    self.secret, snapshot, root_turn_id="legacy-diagnostic-root"
)
request_path = usability._stage_request_path(
    lease_control,
    self.installation,
    self.secret,
    self.session_id,
    snapshot,
)
```

Write the existing seven-field request to that exact private path, call `cli_module.main(["stage-k1-fields", ..., "--request-file", str(request_path)])`, and assert the compatibility path still stages/removes the request. Do not obtain the command from a normal root Hook response.

- [ ] **Step 4: Run the updated root/request/process tests to prove RED**

```bash
python3 -m pytest -q \
  tests/test_v4_root_wiring.py \
  tests/test_v4_request_schema_contract.py \
  tests/test_v4_request_staging.py \
  tests/test_v4_process_boundary.py
```

Expected: FAIL because current root path still emits request-file staging metadata.

- [ ] **Step 5: Integrate `stage_transparent_route` into the root-only path**

In `src/codex_router/v4_hook.py`:

```python
from . import v4_auto_stage
```

After validating a root event and applying root supersession:

```python
snapshot = lease_control.set_current_root_turn(
    installation_dir,
    secret,
    validated["session_id"],
    turn_id=validated["turn_id"],
)
try:
    staged = v4_auto_stage.stage_transparent_route(
        installation_dir=installation_dir,
        secret=secret,
        session_id=validated["session_id"],
        root_turn_id=validated["turn_id"],
        prompt=validated["prompt"],
        cwd=validated["cwd"],
        snapshot=snapshot,
    )
except RouterStateError as error:
    if error.code == "invalid-input":
        lease_control.set_current_root_turn(
            installation_dir,
            secret,
            validated["session_id"],
            turn_id=None,
        )
        return hook_module._hook_output(
            {
                "protocol": hook_module.HOOK_CONTEXT_PROTOCOL,
                "decision": "direct",
                "reason": "automatic_route_sanitization_blocked",
                "workflow": "primary_degraded_v4",
            }
        )
    raise
```

Return a compact context:

```python
return hook_module._hook_output(
    {
        "protocol": hook_module.HOOK_CONTEXT_PROTOCOL,
        "decision": "route",
        "reason": policy.reason_code,
        "workflow": "generation_lease_v4_transparent",
        "sol_role": "plan_review_final_authority",
        "luna_role": "generation_lease_executor",
        "generation": staged["generation"],
        "task_name": staged["task_name"],
        "prepared_spawn": staged["prepared_spawn"],
        "V2_PARENT_MESSAGE_PRETOOL_VISIBILITY": "encrypted_opaque_not_plaintext_verifiable",
        "V2_AUTHORITY_GATE": "first_child_capability_bootstrap",
    }
)
```

Do not emit `bootstrap_capability` separately in root model context; it already exists inside the Router-generated `spawn_message`. Do not emit `K1_STAGE_COMMAND` or `K1_REQUEST_SCHEMA`.

- [ ] **Step 6: Ensure the legacy request wrapper naturally bypasses transparent normal routes**

`v4_request_staging.install(...).handle_hook_event` currently only rewrites a route when:

```python
context.get("workflow") == "generation_lease_v4"
```

Keep that compatibility discriminator. Add a regression assertion that `generation_lease_v4_transparent` receives no request-file rewrite.

- [ ] **Step 7: Update fresh-process test expectation**

`tests/test_v4_process_boundary.py` should assert:

```python
assert '"workflow":"generation_lease_v4_transparent"' in additional
assert '"prepared_spawn"' in additional
assert "K1_STAGE_INTERFACE" not in additional
assert " --request-file " not in additional
```

Also read the disposable V4 journal and assert an active `STAGED` lease exists after the root Hook subprocess.

- [ ] **Step 8: Run focused tests GREEN**

```bash
python3 -m pytest -q \
  tests/test_v4_auto_stage.py \
  tests/test_v4_root_wiring.py \
  tests/test_v4_request_schema_contract.py \
  tests/test_v4_request_staging.py \
  tests/test_v4_process_boundary.py
```

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git add \
  src/codex_router/v4_hook.py \
  tests/test_v4_root_wiring.py \
  tests/test_v4_request_schema_contract.py \
  tests/test_v4_request_staging.py \
  tests/test_v4_process_boundary.py
git commit -m "feat: auto-stage V4 root routes"
```

---

### Task 3: Admit Only the Current Reserved Child Transport and Preserve Bootstrap-Only Authority Binding

**Files:**
- Modify: `src/codex_router/v4_hook.py`
- Modify: `tests/test_v4_spawn_wiring.py`
- Modify: `tests/test_v4_v2_encrypted_spawn_boundary.py`
- Modify: `tests/test_hook_v4_lease.py` only if an existing child-block assertion must be narrowed to stale/foreign children.

**Interfaces:**
- Produces private Hook helper:
  - `_handle_v4_child_prompt(hook_module, validated, installation_dir, secret, snapshot) -> dict[str, Any]`
- Successful current transport admission returns `{}` and performs no journal write.
- Any stale/foreign/invalid child transport returns the existing generic child block shape without capability/message disclosure.
- `lease_control.authorize_executor_tool(...)` remains unchanged as the only worker identity binding primitive.

- [ ] **Step 1: Add RED V1 round-trip test with explicit no-state-mutation proof**

Adapt the V1 fixture to use the root `prepared_spawn["v1"]`. After parent `PreToolUse` reserves the spawn:

```python
before_child = lease_control.read_snapshot(
    self.installation, self.secret, self.session_id
)
assert before_child.active_lease.status == "STAGED"
assert before_child.active_lease.spawn_tool_use_id == "spawn-v1-child"

child_output = handle_hook_event(
    {
        "hook_event_name": "UserPromptSubmit",
        "session_id": self.session_id,
        "turn_id": "child-turn-v1",
        "prompt": context["prepared_spawn"]["v1"]["message"],
        "cwd": str(self.root),
        "agent_id": "agent-v1-child",
        "agent_type": "luna_worker",
    },
    self.installation,
)
assert child_output == {}
after_child = lease_control.read_snapshot(
    self.installation, self.secret, self.session_id
)
assert after_child == before_child
assert after_child.active_lease.worker_agent_id is None
assert after_child.active_lease.child_turn_id is None
```

Current code must fail this test because it blocks every child prompt.

- [ ] **Step 2: Add stale/foreign/unknown child RED tests**

For each case, snapshot before and after must compare equal:

```text
wrong agent_type
wrong prompt
old generation's spawn message
no active lease
STAGED lease with no spawn reservation
ACTIVE/already-bound lease
wrong session
superseded root/generation
```

Assert the serialized rejection does not contain `v4b1.` or the exact expected spawn message.

- [ ] **Step 3: Implement transport-only child admission before root classification**

Add a helper in `v4_hook.py`:

```python
def _handle_v4_child_prompt(
    hook_module: Any,
    validated: Mapping[str, str],
    installation_dir: Path,
    secret: bytes,
    snapshot: Any,
) -> dict[str, Any]:
    if validated.get("agent_type") != "luna_worker" or snapshot is None:
        return hook_module._child_block()
    lease = snapshot.active_lease
    if (
        lease is None
        or lease.status != "STAGED"
        or not lease.spawn_tool_use_id
        or lease.worker_agent_id is not None
        or lease.child_turn_id is not None
        or snapshot.current_root_turn_tag is None
        or lease.root_turn_tag != snapshot.current_root_turn_tag
    ):
        return hook_module._child_block()
    expected_capability = lease_control.build_bootstrap_capability(secret, lease)
    expected_message = spawn_message(expected_capability)
    if validated.get("prompt") != expected_message:
        return hook_module._child_block()
    return {}
```

Then discriminate immediately after `_validate_event` and before `classify_prompt`:

```python
validated = hook_module._validate_event(event)
if "agent_id" in validated:
    return _handle_v4_child_prompt(
        hook_module,
        validated,
        installation_dir,
        secret,
        snapshot,
    )
```

Do not call `set_current_root_turn`, `revoke_current_lease`, `stage_transparent_route`, or any sanitization function in the child branch.

- [ ] **Step 4: Run V1 child tests GREEN before adding V2 coverage**

```bash
python3 -m pytest -q tests/test_v4_spawn_wiring.py
```

Expected: PASS for the new current/stale child tests and existing V1 bootstrap/telemetry tests.

- [ ] **Step 5: Add V2 opaque-parent → plaintext-child round-trip test**

Extend `tests/test_v4_v2_encrypted_spawn_boundary.py`:

1. obtain the Router-prepared V2 plaintext `message` from the root route;
2. send an opaque synthetic ciphertext to parent `PreToolUse` and assert reservation succeeds without authority;
3. send the Router-prepared plaintext message as child `UserPromptSubmit` and assert `{}` plus exact state equality;
4. send the first child Bash bootstrap using the capability embedded in that prepared message;
5. assert the bootstrap binds `agent_id + child_turn_id`, changes status to `ACTIVE`, and K1 additionalContext appears.

The test must prove parent plaintext equality is not reintroduced.

- [ ] **Step 6: Add first-tool enforcement test**

After child transport admission, attempt a non-bootstrap child tool first:

```python
output = handle_hook_event(
    {
        "hook_event_name": "PreToolUse",
        "session_id": self.session_id,
        "turn_id": "child-turn",
        "tool_name": "Bash",
        "tool_use_id": "wrong-first-tool",
        "tool_input": {"command": "pytest -q"},
        "agent_id": "agent-child",
        "agent_type": "luna_worker",
    },
    self.installation,
)
assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
```

Then issue the exact bootstrap and assert ACTIVE binding/K1 delivery.

- [ ] **Step 7: Run all transport-focused tests GREEN**

```bash
python3 -m pytest -q \
  tests/test_v4_spawn_wiring.py \
  tests/test_v4_v2_encrypted_spawn_boundary.py \
  tests/test_hook_v4_lease.py \
  tests/test_lease_control_v4_bootstrap.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add \
  src/codex_router/v4_hook.py \
  tests/test_v4_spawn_wiring.py \
  tests/test_v4_v2_encrypted_spawn_boundary.py \
  tests/test_hook_v4_lease.py
git commit -m "fix: admit current V4 child transport safely"
```

If `tests/test_hook_v4_lease.py` did not need modification, omit it from `git add`.

---

### Task 4: Shorten Managed PRIMARY Policy and Replace Obsolete Live Gates

**Files:**
- Modify: `src/codex_router/v4_install_adapter.py`
- Modify: `tests/test_v4_installed_policy.py`
- Modify: `tests/test_v4_v2_message_visibility_contract.py`
- Modify: `src/codex_router/global_install.py` only for the offline self-test route validator
- Modify: `tests/test_global_self_test.py`
- Preserve: `tests/test_v4_install_preflight.py`

**Interfaces:**
- Managed PRIMARY contract refers only to decision handling and prepared payload selection; it contains no request-file/K1 schema authoring instructions.
- Luna instructions retain exact first bootstrap, no descendants/nested Codex, stale-generation stop, K1/A1 scope.
- `global-status` remains `PENDING_LIVE_ACCEPTANCE` and adds release-critical transparent-route gates.

- [ ] **Step 1: Rewrite installed-policy tests to RED**

Require compact PRIMARY semantics:

```python
assert "prepared" in agents.lower()
assert "decision=route" in agents or "`route`" in agents
assert "PRIMARY" in agents
assert "K1_STAGE_COMMAND" not in agents
assert "seven-field UTF-8 JSON request" not in agents
assert "K1_REQUEST_SCHEMA" not in agents
assert "request-file" not in agents
```

Still require Luna policy:

```python
assert "CODEX_ROUTER_LEASE_BOOTSTRAP_V4" in luna
assert "no descendants" in luna.lower()
assert "nested Codex" in luna
```

- [ ] **Step 2: Change V2 visibility tests from prose contract to machine boundary**

Root context assertions:

```python
assert context["workflow"] == "generation_lease_v4_transparent"
assert context["V2_PARENT_MESSAGE_PRETOOL_VISIBILITY"] == "encrypted_opaque_not_plaintext_verifiable"
assert context["V2_AUTHORITY_GATE"] == "first_child_capability_bootstrap"
assert set(context["prepared_spawn"]["v2"]) == {
    "task_name", "agent_type", "fork_turns", "message"
}
```

Installed AGENTS only needs to say “use the Router-prepared payload unchanged” and “authority starts at first child bootstrap”; it does not need to teach PRIMARY the encrypted transport mechanism.

- [ ] **Step 3: Update V4 live-blocker expectations to RED**

The release blockers must include:

```text
V401_LIVE_AUTO_STAGE
V401_LIVE_SPAWN_MESSAGE_DELIVERED
V401_LIVE_BOOTSTRAP_ATTEMPT_OBSERVED
V40_LIVE_PRETOOL_ACTOR_BINDING
V40_LIVE_K1_BOOTSTRAP
V40_LIVE_NORMAL_TERMINAL
V40_LIVE_MISSING_STOP_SUPERSESSION
V40_LIVE_STALE_WORKER_REJECTION
V40_LIVE_CAPACITY_RECOVERY
```

Remove `V40_LIVE_ROOT_REQUEST_STAGING` from release blockers. Move `V40_OLD_CONVERSATION_RESUME` into deferred acceptance evidence because historical conversation resume is not a V4.0.1 release gate.

- [ ] **Step 4: Replace the long `_v4_agents_block` text with the minimal contract**

The managed block should be semantically equivalent to:

```text
Router is globally available for this PRIMARY Codex conversation.
- For `direct` or `bypass`, continue locally.
- For `route`, select the Router-prepared spawn payload matching the native spawn surface actually exposed and pass that payload unchanged.
- Do not construct Router leases, capabilities, K1 packets, request files, generations, or spawn fields manually.
- Child transport and first-child bootstrap are Router protocol boundaries; do not work around a blocked child with followup/resume/send_input.
- Router owns lease/fencing. PRIMARY owns planning, review, and the final user response. Luna executes only the current bounded K1 under native Codex controls.
- A new root turn may supersede an older generation without waiting for SubagentStop. Stale workers must not be reused.
```

Keep the existing begin/end markers unchanged.

- [ ] **Step 5: Keep Luna instructions concise but preserve hard invariants**

Do not remove these meanings from `V4_LUNA_DEVELOPER_INSTRUCTIONS`:

```text
first tool = exact capability bootstrap
no substantive work before K1
no descendants
no nested Codex
current generation only
no send_input/resume/polling authority recovery
A1/K1 scope remains authoritative
native approval does not broaden task authority
```

Do not add PRIMARY-side K1 construction instructions to the Luna file.

- [ ] **Step 6: Update offline global self-test to validate transparent routing rather than sideband staging**

In `src/codex_router/global_install.py::global_self_test`, replace the old `valid_sideband_route_context` rule with a transparent route validator. Because a normal route now mutates only the disposable V4 journal, compare stable semantics rather than requiring duplicate route byte equality.

Use a helper with this shape:

```python
def valid_transparent_route_context(context: Mapping[str, Any]) -> bool:
    if context.get("protocol") != HOOK_CONTEXT_PROTOCOL:
        return False
    if context.get("decision") != "route":
        return False
    if context.get("workflow") != "generation_lease_v4_transparent":
        return False
    if "K1_STAGE_COMMAND" in context or "K1_REQUEST_SCHEMA" in context:
        return False
    generation = context.get("generation")
    task_name = context.get("task_name")
    prepared = context.get("prepared_spawn")
    if not isinstance(generation, int) or generation < 1:
        return False
    if not isinstance(task_name, str) or not task_name.startswith(f"luna_g{generation}_"):
        return False
    if not isinstance(prepared, Mapping) or set(prepared) != {"v1", "v2"}:
        return False
    v1 = prepared["v1"]
    v2 = prepared["v2"]
    if not isinstance(v1, Mapping) or not isinstance(v2, Mapping):
        return False
    return (
        v1.get("agent_type") == "luna_worker"
        and v1.get("fork_context") is False
        and isinstance(v1.get("message"), str)
        and v2.get("task_name") == task_name
        and v2.get("agent_type") == "luna_worker"
        and v2.get("fork_turns") == "none"
        and v2.get("message") == v1.get("message")
    )
```

Do not retain `K1_STAGE_CAPABILITY`/`K1_STAGE_COMMAND` as self-test requirements.

The existing self-test repeatedly invokes the same synthetic session/turn. Transparent auto-stage is not required to make duplicate root delivery byte-identical; instead assert each returned route is structurally valid and that changed sessions/turns cannot reuse the same current lease identity. Keep the disposable-copy/no-network/no-browser/no-persistent-installation-mutation checks.

- [ ] **Step 7: Run installer/self-test tests GREEN**

```bash
python3 -m pytest -q \
  tests/test_v4_installed_policy.py \
  tests/test_v4_v2_message_visibility_contract.py \
  tests/test_v4_install_preflight.py \
  tests/test_global_self_test.py \
  tests/test_v4_process_boundary.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add \
  src/codex_router/v4_install_adapter.py \
  src/codex_router/global_install.py \
  tests/test_v4_installed_policy.py \
  tests/test_v4_v2_message_visibility_contract.py \
  tests/test_global_self_test.py
git commit -m "feat: install transparent V4 routing contract"
```

---

### Task 5: Full Regression, Packaging, and Exact-Head Remote Verification

**Files:**
- Modify only files required to fix regressions caused by Tasks 1–4.
- Do not perform unrelated refactors.

**Interfaces:**
- All existing V4 authority and installer safety contracts remain green.
- Wheel/install path must use the final source tree, not editable-install residue.

- [ ] **Step 1: Run the complete test suite**

```bash
python3 -m pytest -q
```

Expected: all tests PASS. If an old test asserts request-file staging for the normal route, update it to the approved transparent contract; do not reintroduce model-side staging to satisfy stale tests.

- [ ] **Step 2: Run compile and whitespace checks**

```bash
python3 -m compileall -q src tests
git diff --check origin/main...HEAD
```

Expected: exit code 0 for both.

- [ ] **Step 3: Review the implementation diff for scope**

```bash
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- \
  src/codex_router/v4_auto_stage.py \
  src/codex_router/v4_hook.py \
  src/codex_router/v4_request_staging.py \
  src/codex_router/v4_install_adapter.py \
  src/codex_router/global_install.py \
  tests
```

Reject any daemon/pool/reuse changes, journal schema migration, new dependency, hidden broad write scope, or authorization derived from Luna/tool output.

- [ ] **Step 4: Build a wheel from the exact implementation tree**

```bash
rm -rf dist build
python3 -m pip wheel . -w dist --no-deps
ls -l dist/codex_router-0.1.0-py3-none-any.whl
shasum -a 256 dist/codex_router-0.1.0-py3-none-any.whl
```

Record the SHA-256.

- [ ] **Step 5: Verify the wheel in a fresh disposable virtual environment**

```bash
rm -rf /tmp/codex-router-v401-verify /tmp/codex-router-v401-home /tmp/codex-router-v401-runs
python3 -m venv /tmp/codex-router-v401-verify
/tmp/codex-router-v401-verify/bin/python -m pip install --force-reinstall \
  dist/codex_router-0.1.0-py3-none-any.whl
mkdir -m 700 /tmp/codex-router-v401-home
printf '#!/bin/sh\nexit 0\n' > /tmp/codex-router-v401-codex
chmod 700 /tmp/codex-router-v401-codex
/tmp/codex-router-v401-verify/bin/python -m codex_router global-install \
  --codex-home /tmp/codex-router-v401-home \
  --state-dir /tmp/codex-router-v401-runs \
  --codex-bin /tmp/codex-router-v401-codex
/tmp/codex-router-v401-verify/bin/python -m codex_router global-self-test \
  --codex-home /tmp/codex-router-v401-home
```

Expected: install reports V4 Router installed and self-test status `pass` without touching the live `~/.codex`.

- [ ] **Step 6: Commit any regression-only fixes**

If Steps 1–5 required source/test changes:

```bash
git add <only-the-regression-files>
git commit -m "test: close V4.0.1 regressions"
```

If no changes were required, do not create a no-op commit.

- [ ] **Step 7: Push the implementation branch**

```bash
git push origin hardening/router-v4-lease-core
```

- [ ] **Step 8: Perform a GitHub Reality Audit on the pushed exact head**

```bash
gh pr view 10 --repo EthanSangSSS/codex-router \
  --json state,isDraft,mergedAt,headRefName,headRefOid,baseRefName,baseRefOid,mergeable,mergeStateStatus
PR_HEAD="$(gh pr view 10 --repo EthanSangSSS/codex-router --json headRefOid --jq .headRefOid)"
git rev-parse HEAD
gh run list --repo EthanSangSSS/codex-router --branch hardening/router-v4-lease-core --limit 20
```

Do not report repository PASS until CI and secret/Gitleaks workflows associated with the exact `PR_HEAD` are complete and successful. PR must still be OPEN, Draft, unmerged.

---

### Task 6: Target-Mac Live Acceptance for New Conversations

**Files:**
- No repository code changes unless live evidence exposes a new reproducible defect.
- Managed installation under the target Mac `~/.codex` may be refreshed only after Task 5 exact-head repository verification.

**Interfaces:**
- Consumes exact pushed `PR_HEAD` wheel/package.
- Produces operator/live evidence for the V4.0.1 release gates. Live evidence is not replaced by unit tests.

- [ ] **Step 1: Re-run the version-sync gate on the target Mac before installation**

```bash
git fetch origin
gh pr view 10 --repo EthanSangSSS/codex-router \
  --json state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid

git status --short
git rev-parse HEAD
```

Require clean worktree and local HEAD equal current PR `headRefOid`. If not, use `git pull --ff-only`; stop on failure or dirty state.

- [ ] **Step 2: Build/install the exact tested head into the managed Router Hook environment**

Use the repository's existing supported global-install/refresh procedure. Do not hand-edit `~/.codex/hooks.json`, `AGENTS.md`, or `agents/luna-worker.toml`. Record:

```text
PR_HEAD=<sha>
WHEEL_SHA256=<sha256>
MANAGED_HOOK_PYTHON=<absolute interpreter>
ROUTER_GLOBAL_STATUS=<captured safe output>
```

Confirm the installed policy requires a new Codex conversation.

- [ ] **Step 3: Open a fresh Codex conversation and run a normal bounded edit/test task with no Router vocabulary**

Use a disposable/safe repository or scratch worktree. Example user request:

```text
fix the failing tests in this project and verify the result
```

Do not mention Luna, Router, K1, generation, V1/V2, request file, bootstrap, or prepared payload in the user prompt.

- [ ] **Step 4: Capture the first happy-path acceptance matrix**

Do not infer these from spawn success alone. Report each independently:

```text
ROUTE=YES|NO
AUTO_STAGE=YES|NO
REQUEST_FILE_REQUIRED=NO|YES
LEASE_CREATED=YES|NO
PREPARED_SPAWN_SELECTED=YES|NO
LUNA_SPAWNED=YES|NO
SPAWN_MESSAGE_DELIVERED=YES|NO
BOOTSTRAP_ATTEMPT_OBSERVED=YES|NO
ACTOR_BOUND_BY_CAPABILITY=YES|NO
K1_DELIVERED=YES|NO
WRITE_SCOPE_EQUALS_VALIDATED_CWD=YES|NO
LUNA_COMPLETED=YES|NO
NORMAL_TERMINAL=YES|NO
```

Definitions:

- `SPAWN_MESSAGE_DELIVERED=YES` only when native child evidence shows the Router-prepared message actually reached Luna.
- `BOOTSTRAP_ATTEMPT_OBSERVED=YES` only when child tool telemetry shows its first tool attempt is the current capability-bound `pwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4=...` command.
- A lease that remains `STAGED` with only `spawn_tool_use_id` is a FAIL for both downstream gates.
- `ACTOR_BOUND_BY_CAPABILITY=YES` requires the lease to become `ACTIVE` with the observed `worker_agent_id + child_turn_id` only after the bootstrap.

- [ ] **Step 5: Run the second fresh-conversation proof**

Close/start another fresh Codex conversation and use a different bounded task. Require the same route → delivery → bootstrap → bind → K1 path. This proves global new-conversation availability rather than one-session luck.

- [ ] **Step 6: Run adversarial acceptance probes**

Where safely reproducible, prove:

```text
STALE_FOREIGN_CHILD_TRANSPORT_REJECTED=YES
MISSING_STOP_NEXT_GENERATION_ADMITTED=YES
STALE_WORKER_REJECTED=YES
STALE_TERMINAL_CANNOT_CLEAR_NEW_LEASE=YES
CAPACITY_FAILURE_RECOVERABLE=YES|INCONCLUSIVE
V2_PARENT_MESSAGE_REMAINS_NON_AUTHORITATIVE=YES|NOT_EXPOSED
```

If target runtime exposes only V1, mark the V2 live surface `NOT_EXPOSED`; repository V2 regression tests remain mandatory.

- [ ] **Step 7: Stop on any live mismatch and return to TDD**

If child spawn succeeds but no child prompt/bootstrap appears, do not relax first-child authority. Capture the exact event/order/state and add a minimal failing repository test before changing code.

If a new code fix is required, return to Task 1–5 discipline: RED test → minimal fix → full regression → exact-head GitHub Reality Audit → reinstall exact head → repeat live acceptance.

- [ ] **Step 8: Final release-readiness report**

Only after repository exact-head workflows and target-Mac live gates pass, report:

```text
REPOSITORY=<repo>
PR_NUMBER=10
PR_STATE=OPEN
PR_DRAFT=YES
PR_MERGED=NO
PR_HEAD=<exact sha>
CI=PASS
GITLEAKS_OR_SECRET_SCAN=PASS
UNIT_TESTS=PASS
COMPILEALL=PASS
DIFF_CHECK=PASS
WHEEL_SHA256=<sha256>
FRESH_WHEEL_SELF_TEST=PASS
NEW_CONVERSATION_1=PASS
NEW_CONVERSATION_2=PASS
SPAWN_MESSAGE_DELIVERED=PASS
BOOTSTRAP_ATTEMPT_OBSERVED=PASS
ACTOR_BINDING=PASS
K1_DELIVERY=PASS
STALE_FENCING=PASS
LIVE_ACCEPTANCE=PASS|INCONCLUSIVE|FAIL
```

Keep PR Draft and do not merge unless the user separately authorizes the transition.

## Plan Self-Review

### Spec coverage

- Transparent root auto-stage: Tasks 1–2.
- No model-authored K1/request file on normal path: Tasks 2 and 4.
- Exact `[validated_cwd]` write scope: Task 1 tests and implementation.
- One `secure_web_payload` objective sanitizer: Task 1, mechanically asserted with call count.
- Explicit-intent A1 categories and required negatives: Task 1.
- Prepared V1/V2 payloads: Tasks 1–2.
- V2 opaque parent boundary: Tasks 3–4.
- P1 child transport-only admission: Task 3.
- No child state mutation / no early authority: Task 3.
- First-child exact capability binding and K1 delivery: Task 3.
- Legacy request-file compatibility: Task 2.
- Minimal managed PRIMARY contract: Task 4.
- Installer corruption/symlink safety: Task 4 regression.
- Fresh-process behavior: Tasks 2 and 4.
- Packaging/exact-head CI verification: Task 5.
- `SPAWN_MESSAGE_DELIVERED` and `BOOTSTRAP_ATTEMPT_OBSERVED`: Task 6.
- Two fresh conversations and stale/missing-stop fencing: Task 6.
- Historical conversation resume deferred: Task 4 live-gate update.

### Placeholder scan

No implementation step depends on `TBD`, `TODO`, unspecified error handling, or “write tests for the above” without named cases. Any implementation refinement must preserve the exact interfaces and assertions defined by this plan and the approved spec.

### Type/interface consistency

- `sanitize_objective` returns `str`.
- `derive_write_scope` and `derive_a1_authorizations` return tuples accepted by existing `build_luna_packet`.
- `stage_transparent_route` consumes a `LeaseSnapshot` with current root authority and returns one dict consumed by `v4_hook`.
- `prepared_spawn.v1.message` and `.v2.message` are the same exact Router string.
- Child `UserPromptSubmit` uses that string only as transport correlation; `authorize_executor_tool` remains the sole worker-binding API.
- Normal workflow is consistently named `generation_lease_v4_transparent`; legacy `generation_lease_v4` remains only as the compatibility discriminator for request-file staging.
