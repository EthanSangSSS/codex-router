# Native PRIMARY + Luna V1 Design

## Status

Approved simplification direction for a new implementation branch:

`simplify/native-primary-luna-v1`

This design intentionally stops extending PR #10's V4 lease/K1 architecture. PR #10 remains a Draft experimental hard-authority prototype and is not the base for this implementation.

The implementation base is `main@8fa458948ea0dc021096dc13b5eeec6c45628a40`.

## Product goal

Provide the native user experience the project originally wanted:

```text
User
  -> Sol / PRIMARY
       -> handles simple work, planning, review, browser/UI, and final response
       -> when useful, spawns one native Luna execution subagent
            -> Luna performs the delegated local engineering task
            -> Luna returns evidence/result
       -> Sol reviews and responds
```

The user should be able to open a fresh ordinary Codex conversation and ask for normal work such as:

```text
fix the failing tests in this project and verify the result
```

without seeing or authoring Router protocol, K1, generation, lease, capability, request-file, bootstrap, or staging ceremony.

## Core principle

Use Codex's native parent/subagent model as the authority and lifecycle substrate instead of reconstructing a second agent runtime in Hook code.

The Router package may provide installation/configuration convenience and a thin native-surface compatibility layer. It does not mechanically decide or authorize ordinary delegation in V1.

PRIMARY owns orchestration. Luna owns delegated execution. Native Codex sandbox, approvals, workspace access, and tool exposure remain the hard execution boundaries.

## Architecture

### 1. PRIMARY is permanent coordinator

Managed PRIMARY instructions are short and behavioral:

- PRIMARY is the persistent planner, coordinator, reviewer, and final responder.
- Delegate substantial local engineering execution to Luna when doing so is useful.
- Keep simple answers, planning, review, and final synthesis in PRIMARY.
- If the user explicitly asks not to use Luna for the current turn, do not spawn Luna.
- Interactive browser/user-session UI operations stay in PRIMARY.
- Local/headless browser engineering such as Playwright/Cypress/E2E remains delegable to Luna.
- If Luna/native spawn is unavailable or fails, PRIMARY continues locally rather than stopping the user's task merely because delegation failed.
- After Luna returns, PRIMARY reviews the result/evidence and owns the final answer.

These are model-level orchestration preferences, not cryptographic policy claims.

### 2. Luna is one disposable native executor

Managed `agents/luna-worker.toml` defines Luna as an execution subagent.

Luna may, within the native workspace/sandbox/approval boundary and the delegated objective:

- inspect/search/read files;
- edit relevant files;
- create/delete task-related files;
- run ordinary shell commands;
- run tests/build/lint/typecheck;
- run project-local tooling;
- run Playwright/Cypress/headless E2E;
- debug, instrument, retry, refactor, and verify;
- inspect local Git status/diff/log.

Luna must not:

- spawn descendants or another Codex runtime;
- perform unrelated destructive actions;
- intentionally daemonize persistent background work;
- perform commits, pushes, PR mutation, deploy/publish, outbound communication, cloud mutation, or system-level installation unless the delegated user objective explicitly requires that action and normal native platform controls permit/approve it;
- claim external effects without direct evidence.

There is no K1 packet, generation lease, HMAC bootstrap, Router A1 packet, or Router journal in the normal Native V1 delegation path.

### 3. Native spawn only

PRIMARY uses the native spawn surface actually exposed by the runtime.

Supported compatibility behavior:

#### V1 native surface

Use the exposed `multi_agent_v1__spawn_agent`-family surface with:

```text
agent_type = luna_worker
fork_context = false
message = ordinary delegated task
```

Omit `fork_context` only when the exposed schema itself does not accept it.

#### V2 native surface

Use the exposed V2 `spawn_agent`-family surface with the schema actually exposed by that runtime. Where the known schema accepts the current fields, use:

```text
task_name = luna_worker
agent_type = luna_worker
fork_turns = none
message = ordinary delegated task
```

Do not invent unsupported fields. The compatibility layer may normalize the native schema, but it must not add an authority protocol.

The spawn message is ordinary delegation text, not a capability or transport token.

### 4. No automatic Router classification in the normal path

Native V1 does not install a `UserPromptSubmit` routing Hook and does not mechanically classify prompts into route/direct/bypass.

Therefore it does not need:

- `sensitive_detected -> route`;
- no-Luna regex parsing;
- browser-operation regex parsing;
- ambient browser-context provenance parsing;
- same-root replay generation logic;
- root lease supersession;
- K1 objective sanitization/staging;
- child bootstrap transport admission.

This removes the runtime prompt-composition dependency that repeatedly broke V4 routing.

### 5. Browser ownership is a PRIMARY orchestration preference

Interactive browser/user-session tasks remain in PRIMARY because PRIMARY owns the user-facing session and orchestration.

Examples that PRIMARY should keep:

```text
open Chrome and verify the page manually
log in to the site and fill the form
click Settings in the browser
use DevTools to inspect the page
```

Examples that remain Luna-eligible:

```text
fix this React component
run Playwright tests and fix failures
run Cypress headlessly
fix the click-handler implementation
run local browser E2E tests
```

No Hook/parser enforces this distinction. It is part of the managed PRIMARY behavioral contract and live acceptance.

### 6. Delegation failure degrades to PRIMARY, not task failure

Native delegation is an optimization/capability, not a prerequisite for the user's task.

If:

- the native spawn surface is absent;
- the spawn call fails;
- Luna returns an execution blocker;
- the runtime refuses the agent type;

PRIMARY should continue the task locally when native tools/sandbox allow it.

The user should not receive `STOPPED_NO_WRITES` merely because Luna could not be created.

PRIMARY may report the delegation limitation if it materially affected completeness.

### 7. Installation model

Add a separate Native V1 installation mode rather than mutating the existing Router global-install semantics in place.

Recommended CLI surface:

```text
native-install
native-status
native-uninstall
native-self-test
```

Native installation manages only the minimum required user configuration:

- the Native PRIMARY block in `~/.codex/AGENTS.md`;
- `~/.codex/agents/luna-worker.toml`.

It must not install Router Hook handlers for normal Native V1 operation.

If migrating from an existing Router-managed installation, the supported migration must remove only Router-owned managed Hook/configuration artifacts and preserve unrelated user hooks, unrelated `AGENTS.md` content, and unrelated agent files.

Existing `global-install/global-status/global-uninstall/global-self-test` remain available for the experimental Router architecture and are not silently redefined.

### 8. Reversible ownership markers

Native V1 uses its own distinct managed markers and install-state identity so it does not masquerade as the Router global policy.

Example marker names:

```text
# BEGIN CODEX NATIVE PRIMARY LUNA V1
# END CODEX NATIVE PRIMARY LUNA V1
```

The Luna agent file is managed with explicit content hash/backup evidence.

Native install/uninstall must be idempotent and reversible.

### 9. Migration from an existing Router-managed install

The target Mac may already have the existing Router global policy installed.

Migration requirements:

1. detect whether the existing Router installation is present and managed by this package;
2. refuse to overwrite ambiguous/unowned Router-looking content;
3. use the existing reversible ownership evidence to restore/remove Router-owned Hook and managed policy content safely;
4. preserve unrelated user configuration;
5. install the Native PRIMARY block and Luna config;
6. verify that no Router-owned routing Hook remains active after successful migration;
7. require a fresh Codex conversation after migration.

Do not manually delete arbitrary user hooks.

### 10. Self-test

`native-self-test` is offline and non-destructive.

It verifies:

- Native PRIMARY managed block is present exactly once;
- Luna agent file parses and matches expected config;
- no Router-owned routing Hook remains in the managed normal path;
- unrelated hooks/config are not treated as failures merely for existing;
- installer ownership state is internally consistent;
- installed policy text contains no K1/lease/generation/request-file/bootstrap ceremony;
- installed Luna contract contains no descendant/nested-Codex permission.

It does not launch a real Luna worker or browser.

### 11. Live acceptance

Repository/static tests are not sufficient. Target-Mac acceptance uses genuinely fresh Codex conversations after Native V1 installation.

#### Case A: ordinary engineering delegation

Prompt:

```text
fix the failing tests in this project and verify the result
```

Required:

```text
PRIMARY_ACTIVE=YES
LUNA_NATIVE_SPAWN_ATTEMPTED=YES
LUNA_NATIVE_SPAWN_SUCCEEDED=YES
LUNA_EXECUTION_OBSERVED=YES
LUNA_LOCAL_ENGINEERING=YES
LUNA_RESULT_RETURNED=YES
PRIMARY_REVIEWED=YES
PRIMARY_FINAL_RESPONSE=YES
NO_K1_OR_LEASE_CEREMONY=YES
```

#### Case B: explicit no-Luna

Prompt contains a clear current-turn instruction not to use Luna.

Required:

```text
PRIMARY_ACTIVE=YES
LUNA_NATIVE_SPAWN_ATTEMPTED=NO
PRIMARY_CONTINUED_LOCALLY=YES
```

This is a behavioral acceptance criterion, not a Hook-level cryptographic guarantee.

#### Case C: interactive browser/UI

Prompt requires real interactive browser/user-session UI work.

Required:

```text
PRIMARY_OWNS_BROWSER_STEP=YES
LUNA_NATIVE_SPAWN_FOR_BROWSER_STEP=NO
```

#### Case D: headless browser engineering

Prompt:

```text
run Playwright tests and fix the failures
```

Required:

```text
LUNA_DELEGATION_ELIGIBLE=YES
```

#### Case E: delegation unavailable

Safely reproduce or simulate native spawn unavailability.

Required:

```text
PRIMARY_LOCAL_FALLBACK=YES
USER_TASK_NOT_ABORTED_ONLY_BECAUSE_LUNA_UNAVAILABLE=YES
```

### 12. Non-goals

Native PRIMARY + Luna V1 does not implement:

- generation leases;
- K1 packets;
- HMAC bootstrap capabilities;
- Router A1 packet authorization;
- prompt-provenance parsing;
- root replay idempotence logic;
- stale-generation fencing beyond native subagent lifecycle;
- persistent Luna reuse;
- worker pools;
- Router daemon/MCP control plane;
- automatic browser/task splitting;
- cryptographic enforcement of no-Luna or browser ownership;
- automatic remote mutation/deploy/publish authorization beyond native platform controls and model instructions.

If future evidence shows a specific hard safety boundary is missing from the native platform, add the smallest independently justified mechanism for that boundary instead of recreating the V4 control plane wholesale.

## Success criterion

A fresh Codex conversation should feel native:

```text
User -> Sol -> Luna works -> Sol reviews -> Sol replies
```

The user should not need to know that Router generations, K1, staging, bootstrap, or prompt provenance ever existed.
