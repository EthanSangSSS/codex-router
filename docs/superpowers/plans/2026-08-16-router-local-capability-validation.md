# Router Local Capability Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine, without changing live Codex state, whether the exact installed Codex build provides the child identity, lifecycle schema, tool isolation, inherited-tool controls, and approval behavior required to activate Native Luna Safety V2.

**Architecture:** This is an evidence-collection pass, not a migration. Primary Sol performs read-only inspection of the exact local App/build, live Router configuration, existing logs, and repository state. No Luna is spawned merely to manufacture evidence, no diagnostic Hook is installed, no nested Codex executable is launched, and no write occurs under live `~/.codex`. Every runtime claim must be supported by passive exact-build evidence or remain an explicit blocker.

**Tech Stack:** macOS read-only filesystem inspection, Python 3.12 standard library, TOML/JSON parsing, Git, SHA-256 hashing, existing Codex/ChatGPT logs, Codex Router read-only `global-status`, GitHub source-of-truth comparison.

## Global Constraints

- Repository: `EthanSangSSS/codex-router`.
- Local checkout: `/path/to/codex-router`.
- Validation branch: `hardening/native-luna-safety-v2`.
- Baseline implementation reviewed before this plan: `ecf7b204735af6a6d2ec74fc6ee47e1659efff20`; validation must use the then-current remote PR head and report it explicitly.
- PR #8 remains Draft throughout this pass.
- Do not modify `~/.codex`, any ChatGPT/Codex App file, Hook trust state, user approval settings, credentials, or live agent configuration.
- Do not run `router global-install` against live `~/.codex`.
- Do not run `router global-uninstall` against live `~/.codex`.
- Do not run `router global-self-test` against live `~/.codex`.
- Do not install or inject a diagnostic Hook to obtain missing evidence.
- Do not launch `/Applications/ChatGPT.app/Contents/Resources/codex`, `codex`, `codex exec`, a PTY-wrapped Codex, or any second/nested Codex process for validation.
- Do not spawn Luna or another helper agent merely to generate Hook events. This pass is primary-Sol-only.
- Existing logs may be inspected read-only, but never print raw prompt text, tool arguments, credentials, cookies, tokens, private URLs, private environment values, or transcript contents. Extract field names, event types, IDs only when necessary, hashes, booleans, and capability labels.
- Do not use transcript JSON as a security identity source. Transcript format is not part of the V2 authorization contract.
- `SubagentStart.agent_id` is necessary but not sufficient. Actor identity on Luna-sensitive `PreToolUse` / `PermissionRequest`, or an independent config-level boundary that makes actor-specific Hook identity unnecessary, must be proven for the exact deployed build.
- Custom-agent settings omitted from the Luna profile must be treated as potentially inherited until exact effective behavior proves otherwise. In particular, parent `mcp_servers`, sandbox/approval settings, and other tool-enabling configuration must not be assumed absent.
- Do not assume an undocumented empty-table override, merge rule, feature flag, or approval policy has the desired semantics.
- Missing evidence is a blocker, not permission to weaken the boundary.
- No merge, live migration, Hook trust change, or auto-merge in this validation pass.

---

### Task 1: Freeze repository and exact-build version reality

**Files:**
- Read only: `/path/to/codex-router/.git/*`
- Read only: `/Applications/ChatGPT.app/Contents/Info.plist`
- Read only: `/Applications/ChatGPT.app/Contents/Resources/codex`
- Read only: `~/.codex/hooks.json`

**Interfaces:**
- Produces a `Version Reality` record containing local branch/head, remote PR head, worktree status, App version/build, bundled Codex binary path/size/SHA-256, and the Python interpreter configured by the live Router Hook.
- Does not change working-tree files or live Codex state.

- [ ] **Step 1: Verify local repository identity without resetting anything**

Run from the existing primary Sol session:

```bash
cd /path/to/codex-router
printf 'branch=' && git branch --show-current
printf 'head=' && git rev-parse HEAD
printf 'status_begin\n'
git status --short
printf 'status_end\n'
```

If the worktree is dirty, report `BLOCKED_DIRTY_WORKTREE` for any source-comparison action that could be confused by local edits. Do not reset, stash, checkout, clean, or rewrite files.

- [ ] **Step 2: Read the remote PR branch head without changing the working tree**

Use an ordinary remote query:

```bash
git ls-remote origin refs/heads/hardening/native-luna-safety-v2
```

Record the returned SHA as `remote_pr_head`. If the command cannot reach the remote, keep the local SHA but report `REMOTE_HEAD_UNVERIFIED`; do not infer that the local head is current.

If local `HEAD != remote_pr_head`, do not pull or switch automatically. Report `BLOCKED_REPO_VERSION_MISMATCH` and continue only with build/config evidence that does not depend on source equality.

- [ ] **Step 3: Record ChatGPT App and bundled Codex binary identity without executing the binary**

Run:

```bash
APP=/Applications/ChatGPT.app
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Contents/Info.plist"
stat -f 'codex_size=%z codex_mtime=%Sm' "$APP/Contents/Resources/codex"
shasum -a 256 "$APP/Contents/Resources/codex"
```

Do **not** run the bundled `codex` binary even with `--version` or a schema/help subcommand.

- [ ] **Step 4: Extract only Router Hook command metadata from live hooks.json**

Use Python to print event names and Router command argv, never unrelated Hook bodies:

```bash
python3.12 - <<'PY'
import json, os, shlex
from pathlib import Path
p = Path.home() / '.codex' / 'hooks.json'
d = json.loads(p.read_text(encoding='utf-8'))
for event, groups in sorted(d.get('hooks', {}).items()):
    for group in groups if isinstance(groups, list) else []:
        for hook in group.get('hooks', []) if isinstance(group, dict) else []:
            if not isinstance(hook, dict):
                continue
            status = hook.get('statusMessage', '')
            command = hook.get('command', '')
            if 'codex-router-global-policy-v1' not in str(status) and 'codex_router' not in str(command):
                continue
            try:
                argv = shlex.split(str(command))
            except ValueError:
                argv = ['<unparseable>']
            print({'event': event, 'argv': argv, 'status_marker': str(status)[:120]})
PY
```

Record the exact Python interpreter and installation directory from the command. Do not read `installation-secret`.

- [ ] **Step 5: Stop conditions for version reality**

Return one or more of:

```text
BLOCKED_DIRTY_WORKTREE
BLOCKED_REPO_VERSION_MISMATCH
REMOTE_HEAD_UNVERIFIED
BLOCKED_LIVE_HOOK_COMMAND_UNREADABLE
```

Do not repair anything in this task.

---

### Task 2: Reconcile repository source with the live installed Router package

**Files:**
- Read only: `src/codex_router/*.py` in the local checkout.
- Read only: exact installed `codex_router` package resolved by the live Hook interpreter.
- Read only: `~/.codex/.codex-router-policy-v1/config.json` if present.

**Interfaces:**
- Produces `Source/Live Drift` with module paths and SHA-256 digests for the V2-relevant modules.
- Produces `SOURCE_MATCH`, `SOURCE_DRIFT_EXPLAINED`, or `BLOCKED_LIVE_SOURCE_DRIFT`.

- [ ] **Step 1: Resolve the live Hook interpreter from Task 1**

Let `HOOK_PYTHON` be the first argv element from the managed Router command. Verify only that it exists and is executable:

```bash
stat -f '%N %Sp %z' "$HOOK_PYTHON"
```

Do not replace it or install packages into it.

- [ ] **Step 2: Ask that interpreter where `codex_router` is loaded from**

Run Python only, not Codex:

```bash
"$HOOK_PYTHON" -E -P - <<'PY'
import importlib.util, json
mods = [
    'codex_router',
    'codex_router.hook',
    'codex_router.native_lifecycle',
    'codex_router.global_install',
    'codex_router.global_install_adapter',
    'codex_router.cli',
]
for name in mods:
    spec = importlib.util.find_spec(name)
    print(json.dumps({'module': name, 'origin': None if spec is None else spec.origin}, sort_keys=True))
PY
```

If a required V2 module cannot be resolved, report `BLOCKED_LIVE_SOURCE_DRIFT`.

- [ ] **Step 3: Hash repository and installed V2-relevant modules**

For each resolved file corresponding to:

```text
hook.py
native_lifecycle.py
global_install.py
global_install_adapter.py
cli.py
policy.py
types.py
```

compute SHA-256 using `shasum -a 256`. Compare against the same repository file under `src/codex_router/` when both exist.

Do not print file contents. Report path + digest + equality only.

- [ ] **Step 4: Read only non-secret live Router config fields**

If `~/.codex/.codex-router-policy-v1/config.json` exists, parse and report only:

```text
protocol
codex_binary path
top-level role names
requested model/reasoning labels
state_root path
```

Never read or print `installation-secret`.

- [ ] **Step 5: Classify source/live drift**

Use:

```text
SOURCE_MATCH
SOURCE_DRIFT_EXPLAINED
BLOCKED_LIVE_SOURCE_DRIFT
```

`SOURCE_DRIFT_EXPLAINED` is allowed only when the exact difference is already expected and does not affect the V2 capability being validated. Unknown code drift is blocking.

---

### Task 3: Obtain passive exact-build Hook wire evidence

**Files:**
- Read only: existing Codex/ChatGPT log files already present on the machine.
- Do not edit: `~/.codex/hooks.json`.

**Interfaces:**
- Produces an `Official-vs-Local Matrix` for `SubagentStart`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, and `Stop`.
- For each observed event, records only field-name sets and whether stable actor identity fields are present.
- Produces actor-identity verdicts without printing raw event values.

- [ ] **Step 1: Locate candidate existing logs by path only**

Start with filenames, not contents:

```bash
find "$HOME/Library/Logs" -maxdepth 5 -type f \
  \( -iname '*codex*' -o -iname '*chatgpt*' -o -iname '*openai*' \) \
  -mtime -7 -print 2>/dev/null
```

If needed, inspect only narrowly related ChatGPT/Codex application-support log directories already known from prior forensics. Do not recursively dump the entire home directory.

- [ ] **Step 2: Identify files containing Hook event markers without printing matching lines**

For candidate files, use filename-only matching:

```bash
rg -l --no-messages 'SubagentStart|PreToolUse|PermissionRequest|PostToolUse|"hook_event_name"|hook_event_name' <candidate-files>
```

Do not run `rg -n` or otherwise print raw matching lines at this stage.

- [ ] **Step 3: Extract Hook payload key sets only**

For each matching file, parse structured JSON/JSONL records where possible. Recursively locate dictionary objects whose `hook_event_name` is one of:

```text
SubagentStart
PreToolUse
PermissionRequest
PostToolUse
Stop
```

Print only:

```text
source filename
event name
sorted top-level key names
presence booleans for: session_id, turn_id, agent_id, agent_type, tool_name, tool_use_id, tool_input, tool_response, permission_mode
```

Never print the values of `prompt`, `tool_input`, `tool_response`, `description`, transcript content, environment fields, or arbitrary log text.

If a log format is not safely parseable without exposing raw text, skip it and report `UNPARSED_LOG_FORMAT`; do not dump the line to debug the parser.

- [ ] **Step 4: Correlate one existing child lifecycle sequence if passive evidence exists**

Using only IDs/hashes and event timestamps, determine whether an already-existing historical sequence can show:

```text
SubagentStart(agent_id=A)
  -> later child PreToolUse carries A or another mechanically stable actor identity
  -> later child PermissionRequest, if one already exists, carries A or another mechanically stable actor identity
```

Do not use transcript contents or role prose as identity.

If there is no existing child `PermissionRequest`, record that as missing evidence rather than triggering one.

- [ ] **Step 5: Compare the exact local payload shape with the release documentation assumption**

Required answers:

```text
SUBAGENTSTART_AGENT_ID = PROVEN | NOT_OBSERVED
PRETOOL_CHILD_AGENT_ID = PROVEN | ABSENT | NOT_OBSERVED
PRETOOL_OTHER_STABLE_ACTOR_ID = <field-name-or-NONE>
PERMISSION_CHILD_AGENT_ID = PROVEN | ABSENT | NOT_OBSERVED
PERMISSION_OTHER_STABLE_ACTOR_ID = <field-name-or-NONE>
```

`agent_type=luna_worker` alone is not equivalent to the bound native `agent_id` unless the final security design explicitly accepts that weaker identity and proves collision/impersonation behavior. This validation pass must not silently make that design change.

- [ ] **Step 6: Apply the actor-identity stop gate**

If child `PreToolUse` has no trustworthy actor identity and the config-level tool boundary has not yet independently eliminated every unsafe child tool path, report:

```text
BLOCKED_PRETOOL_AGENT_ID_UNVERIFIED
```

If child `PermissionRequest` identity is absent/unproven and child config does not independently make user-required escalation fail closed, report:

```text
BLOCKED_PERMISSION_AGENT_ID_UNVERIFIED
```

If no safe passive payload evidence exists at all, report:

```text
BLOCKED_NO_PASSIVE_WIRE_EVIDENCE
```

Do not add a logging Hook to obtain it.

---

### Task 4: Validate primary capability and exact lifecycle schema evidence

**Files:**
- Read only: `~/.codex/config.toml`.
- Read only: existing logs/resources that reveal already-used lifecycle tool inputs.
- Read only: PR source `src/codex_router/native_lifecycle.py`.

**Interfaces:**
- Produces `Primary Capability` and `Lifecycle Schema` records.
- Produces `COMPATIBLE`, `INCOMPATIBLE`, or `UNKNOWN_REQUIRES_CAPABILITY_CHECK` without mutating primary config.

- [ ] **Step 1: Run repository `global-status` against live home in read-only mode**

Only when local repository HEAD matches the current remote validation head, run from the repository source without installing it:

```bash
cd /path/to/codex-router
PYTHONPATH=src python3.12 -m codex_router global-status --codex-home "$HOME/.codex"
```

This command is permitted only as a read-only status query. Do not run global-install/uninstall/self-test on live home.

Record:

```text
state
hook_configured
agents_managed
luna_agent_configured
config_valid
identity_material_valid
hook_trust
compatibility
compatibility_reason
luna_execution_mode
```

- [ ] **Step 2: Parse only relevant primary config capability keys**

Using `tomllib`, report values or `<absent>` for:

```text
agents.enabled
features.multi_agent
features.hooks
features.shell_tool
features.unified_exec
features.code_mode.enabled
approval_policy
sandbox_mode
```

For `mcp_servers`, report only server IDs and non-secret structural flags such as `enabled`, `enabled_tools` names, `disabled_tools` names, and approval-mode labels. Do not print command arguments, URLs, tokens, headers, bearer values, or environment values.

- [ ] **Step 3: Verify already-observed lifecycle input field names**

From passive logs only, look for historical primary-Sol lifecycle calls and record top-level `tool_input` key names for:

```text
spawn_agent
send_input
send_message
followup_task
interrupt_agent
close_agent
resume_agent
```

Expected repository adapter fields are:

```text
spawn_agent     -> task_name + fork_turns
send_input      -> target
send_message    -> target
followup_task   -> target
interrupt_agent -> target
close_agent     -> target
resume_agent    -> id
```

Do not print message bodies or task text.

- [ ] **Step 4: Verify packet-only semantics passively**

Look for existing historical evidence that `spawn_agent(..., fork_turns=none)` was used and that the resulting Luna did not receive inherited parent-turn content as initial context. Accept only structural evidence already present; do not read or quote parent transcript content to prove this.

If `fork_turns=none` field usage is observed but actual packet-only behavior cannot be established safely, report:

```text
BLOCKED_FORK_TURNS_UNVERIFIED
```

- [ ] **Step 5: Do not infer runtime compatibility from config alone**

`COMPATIBLE` static config is not equivalent to proving Hook actor fields or child tool isolation. Keep those gates separate in the final matrix.

---

### Task 5: Audit Luna effective hard-mode and inherited tool surface

**Files:**
- Read only: live `~/.codex/agents/luna-worker.toml` if present.
- Read only: repository V2 renderer in `src/codex_router/global_install_adapter.py`.
- Read only: relevant parent `~/.codex/config.toml` structure.

**Interfaces:**
- Produces `Luna Effective Profile` and `Inherited Tool Surface` records.
- Determines whether the repository claim `hard_mode_no_process` is mechanically supported by the exact effective child configuration or remains blocked.

- [ ] **Step 1: Parse the live Luna profile structurally**

Report only these keys/values where present:

```text
name
model
model_reasoning_effort
agents.enabled
features.multi_agent
features.shell_tool
features.unified_exec
features.code_mode.enabled
approval_policy
sandbox_mode
mcp_servers server IDs and non-secret enable/approval/tool-name metadata
```

Do not print full `developer_instructions` unless comparing its SHA-256 to repository-rendered expected bytes. Never print secrets or inherited parent values that are not required for the capability matrix.

- [ ] **Step 2: Compare live Luna profile with repository-generated V2 profile**

Use file hashes or parsed non-secret configuration equality. Record:

```text
LUNA_PROFILE_SOURCE_MATCH = YES | NO | UNVERIFIED
```

If the live profile differs from repository V2 in a way that changes tool, approval, model, or lifecycle behavior, report `BLOCKED_LIVE_SOURCE_DRIFT`.

- [ ] **Step 3: Determine inherited MCP/app/tool risk without guessing merge semantics**

If parent config contains enabled MCP servers or other tool-enabling settings and the Luna profile omits an explicit override, record:

```text
INHERITED_MCP_SURFACE_PRESENT
```

List only server/tool identifiers and approval-mode labels, never secret connection data.

Do not claim that `mcp_servers = {}` would clear inherited servers unless the exact build or official release contract proves that merge behavior.

- [ ] **Step 4: Search passive evidence for actual Luna tool inventory**

If existing logs record the tool inventory for a historical Luna, extract tool names only. Required negative evidence for repository hard mode includes absence of:

```text
spawn_agent / descendant lifecycle tools
shell/Bash arbitrary process tool
Unified Exec / equivalent arbitrary executor
Code Mode executor
unexpected inherited MCP/process executor
```

If the inventory is not passively available, report `LUNA_TOOL_INVENTORY_UNVERIFIED`; do not spawn Luna solely to inspect it.

- [ ] **Step 5: Apply inherited-surface gate**

If an inherited MCP/app/process-capable surface is present and its child isolation/approval behavior is not mechanically proven, report:

```text
BLOCKED_INHERITED_MCP_SURFACE
```

This is a capability blocker, not proof of exploitation.

---

### Task 6: Validate child approval boundary without triggering an approval

**Files:**
- Read only: parent config, live Luna profile, existing passive Hook/approval logs.

**Interfaces:**
- Produces `Approval Boundary` with exact evidence for whether user-required trust/approval/auth/security confirmation can be triggered or bypassed by Luna.
- Never manufactures an approval request.

- [ ] **Step 1: Record current child approval settings**

Determine whether the Luna profile explicitly sets `approval_policy`. If omitted, record:

```text
LUNA_APPROVAL_POLICY_EXPLICIT = NO
PARENT_APPROVAL_POLICY = <non-secret label or ABSENT>
```

Treat omitted child approval settings as potentially inherited.

- [ ] **Step 2: Identify approval-capable child surfaces structurally**

From the effective/inherited tool matrix, identify whether Luna could access any surface that can request:

```text
sandbox escalation
managed network approval
MCP/tool approval or elicitation
request_permissions
skill approval
external authentication/confirmation
```

Do not invoke any such surface.

- [ ] **Step 3: Use existing passive PermissionRequest evidence only**

If historical child `PermissionRequest` events exist, record their key sets and actor-identity fields as in Task 3. Do not print descriptions or tool arguments.

- [ ] **Step 4: Apply fail-closed decision**

A pass requires one of these to be proven for the exact build:

```text
A. child PermissionRequest carries trustworthy bound-child identity and Router denial is guaranteed on that path;
OR
B. child configuration independently prevents/auto-rejects all user-required escalation paths accessible to Luna, so actor-specific PermissionRequest Hook identity is not needed for the hard invariant.
```

If neither is proven, report:

```text
BLOCKED_CHILD_APPROVAL_BOUNDARY_UNVERIFIED
```

Do not change the live child approval policy during this pass.

---

### Task 7: Produce the evidence matrix and stop before live migration

**Files:**
- No live writes.
- Optional local report may be printed to the conversation; do not persist it under `~/.codex`.

**Interfaces:**
- Produces one structured final report suitable for ChatGPT/GitHub Reality Audit.
- Does not claim live readiness unless every hard gate is evidenced.

- [ ] **Step 1: Build the final capability matrix**

Report exactly these rows:

```text
Repository remote head
Local repository head / dirty status
ChatGPT App version/build
Bundled Codex SHA-256
Live Hook interpreter + installed package origins/digests
Live/source drift
Primary multi-agent capability
Hooks capability
SubagentStart.agent_id
Child PreToolUse actor identity
Child PermissionRequest actor identity
Lifecycle tool field mapping
fork_turns=none observed
packet-only semantics
Luna profile source match
Luna shell/process disabled
Luna Unified Exec disabled
Luna Code Mode disabled
Luna descendant agents disabled
Parent MCP/app surface
Luna inherited MCP/app surface
Actual Luna tool inventory
Child approval policy/boundary
Stop revoke-only source behavior
Hook trust observable/not observable
```

Every row must be one of:

```text
PROVEN
NOT_PROVEN
INCOMPATIBLE
NOT_APPLICABLE
```

and include a terse evidence reference such as file path + hash, log filename + event timestamp/key-set, or command output label. Do not cite raw sensitive content.

- [ ] **Step 2: Compute one final status**

Use `PASSIVE_CAPABILITY_EVIDENCE_SUFFICIENT` only if all required hard gates are `PROVEN` and there is no unexplained source/live drift or inherited unsafe surface.

Otherwise choose the most specific blocker(s):

```text
BLOCKED_DIRTY_WORKTREE
BLOCKED_REPO_VERSION_MISMATCH
REMOTE_HEAD_UNVERIFIED
BLOCKED_LIVE_SOURCE_DRIFT
BLOCKED_PRETOOL_AGENT_ID_UNVERIFIED
BLOCKED_PERMISSION_AGENT_ID_UNVERIFIED
BLOCKED_FORK_TURNS_UNVERIFIED
BLOCKED_NO_PASSIVE_WIRE_EVIDENCE
BLOCKED_INHERITED_MCP_SURFACE
BLOCKED_CHILD_APPROVAL_BOUNDARY_UNVERIFIED
INCONCLUSIVE
```

Multiple blockers may be reported together.

- [ ] **Step 3: Final report format**

Return exactly these sections:

```text
Status
Version Reality
Official-vs-Local Matrix
Hook Wire Evidence
Primary Capability
Lifecycle Tool Schema
fork_turns / Packet-Only Evidence
Luna Effective Profile
Inherited Tool Surface
Approval Boundary
Source/Live Drift
Safety Verdict
Next Minimal Action
```

`Next Minimal Action` must propose the smallest additional evidence or repository change needed. It must not install, trust, merge, or launch nested Codex automatically.

- [ ] **Step 4: Mandatory terminal statement**

End the local validation report with:

```text
LIVE_INSTALLATION_CHANGED=NO
HOOK_TRUST_CHANGED=NO
NESTED_CODEX_LAUNCHED=NO
LUNA_SPAWNED_FOR_VALIDATION=NO
MERGED=NO
```

---

## Self-Review

- Spec coverage: version reality, source/live drift, Hook wire identity, lifecycle schemas, `fork_turns`, primary capability, hard-mode tool isolation, inherited MCP/tool surface, approval behavior, and strict no-live-mutation gate are each covered by a dedicated task.
- Privacy boundary: raw prompts, tool arguments, transcript contents, secret environment values, tokens, cookies, URLs, and credentials are never required as report output.
- Safety boundary: no nested Codex, no diagnostic Hook, no validation Luna, no live installer operation, no Hook trust mutation, and no merge are permitted.
- Failure semantics: missing passive evidence produces an explicit blocker instead of a weakened assumption.
- Runtime/source separation: repository CI remains evidence for repository behavior only; exact-build runtime claims require local passive evidence.
