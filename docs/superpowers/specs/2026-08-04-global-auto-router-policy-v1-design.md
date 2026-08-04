# Global Auto Router Policy V1 Design

## Status and dependency

This design implements the user-approved global default routing policy on the
stacked branch `feat/global-auto-router-policy-v1`. It depends on PR #3 at
`583ceb9aa8a95d8402c6663da05e9120d4a36776` and must not be merged ahead of
that base. PR #3 remains the App-driven Router state machine; this branch adds
the deterministic prompt trigger, Web boundary enforcement, and reversible
global installation.

Codex App is the sole execution driver. Router remains the sole workflow state
authority. The hook decides whether to create a run and supplies structured
context; it never marks a stage complete. Local Sol, Web Sol, and Luna execute
their stages but do not choose the next state.

## Verified Codex hook surface

The current official Codex Hooks guide documents `UserPromptSubmit` as a
turn-scoped command hook. Its JSON input includes common fields
`session_id`, `cwd`, and `hook_event_name`, plus `turn_id` and `prompt`. JSON
output may add developer context through
`hookSpecificOutput.additionalContext`. A hook may block with
`{"decision":"block","reason":"..."}`. User hooks require explicit review and
trust through `/hooks`; changed hook definitions require renewed review.

User hooks load from the active Codex home, normally `~/.codex/hooks.json`.
Global `AGENTS.md` guidance is loaded once at the start of a Codex session, so
new managed instructions apply only to new sessions. The installer must state
both limitations and may never use `--dangerously-bypass-hook-trust`.

## Runtime architecture

```text
UserPromptSubmit
        |
        v
deterministic local policy engine
        |
        +-- direct/bypass --> structured additionalContext only
        |
        +-- route --> idempotent Router run creation
                          |
                          v
                 structured additionalContext
                          |
                          v
Codex App drives Local Sol(max) -> Web Sol(xhigh) -> Luna(max)
```

No daemon, LaunchAgent, login item, listener, browser bridge, App restart, or
second Codex App instance is permitted. The policy command runs only when
Codex invokes the lifecycle hook.

## Evidence model

The implementation records evidence without overstating verification:

- `configured`: a local Router configuration value.
- `hook_reported`: input delivered by the Codex hook runtime.
- `app_server_reported`: Local Sol or Luna evidence reported by App Server.
- `operator_attested`: Web conversation, model, reasoning, and context reuse.
- `locally_verified`: filesystem modes, digests, schema, and test behavior
  directly checked by Router.
- `unknown`: hook trust and browser lifecycle unless directly supported by a
  Codex interface.

The code does not claim that Web model selection, xhigh reasoning, browser tab
reuse, or absence of a newly opened page is technically verified. Those remain
operator-attested and belong in the manual App checklist.

## Session identity and privacy

`session_id` from the hook JSON is the primary identity. Installation creates
a random 32-byte secret and stores it in the Router-owned installation
directory with mode `0600`. The stable driver context is the full lowercase
hex HMAC, without truncation:

```text
ctx-<HMAC-SHA-256(installation_secret, "session\0" + session_id)>
```

Using all 256 bits avoids a truncation collision policy. Existing UUID-shaped
`driver_context_id` values remain accepted for manual PR #3 commands; hook
contexts use the HMAC form. Secret-derived identity comparisons use
`hmac.compare_digest`.

The original session ID is never persisted or printed. `turn_id` is likewise
converted to an HMAC digest. The deduplication identity is a digest over the
session-context digest and turn digest. Prompt digests are keyed HMAC values,
not raw SHA values.

`CODEX_THREAD_ID` is allowed only in an explicit non-hook helper path and is
recorded as `fallback_lower_confidence`. Hook execution never consults that
environment variable.

## Deterministic policy precedence

Classification follows this exact order:

1. explicit one-turn bypass;
2. sensitive-information policy;
3. narrow direct-execution allowlist;
4. Router by default.

The classifier is pure deterministic Python and returns a typed decision plus
a bounded reason code. It never calls a model.

### One-turn bypass

The first non-empty prompt line may be exactly `本次不用 Router` or
`仅本地执行`, with safe case normalization for `Router` and optional terminal
punctuation. It must be a standalone directive. Quoted text, code fences,
examples, documentation prose, or an embedded phrase do not bypass. The
decision is not stored as a session preference.

### Direct allowlist

Only greetings/casual acknowledgements, thanks, trivial arithmetic, a brief
conceptual explanation with no repository or external research action,
current-task/status metadata lookup, and one-step read-only inspection may run
directly. File or code changes, reviews, security/architecture work, research,
fact verification, comparisons, decisions, planning, design, multi-step work,
write effects, and ambiguity always route.

Sensitive content never becomes a direct-policy escape hatch. It routes with a
`sensitive_detected` reason so local work may continue, while the later Web
boundary must redact or block it.

## Hook input, output, and deduplication

`router hook-user-prompt` reads one bounded JSON object from stdin. It requires
`hook_event_name == "UserPromptSubmit"` and non-empty string values for
`session_id`, `turn_id`, `prompt`, and `cwd`. It never prints the prompt.

Direct and bypass decisions return one compact hook output object. Route
decisions acquire a stable event lock and use a deterministic run ID derived
from the deduplication identity. Router creates or returns that exact run. A
duplicate delivery cannot allocate a second run. An incomplete deterministic
run is corruption and blocks rather than allocating a replacement.

Route context contains only protocol, decision, run ID, driver context ID,
revision, next stage, packet path, reason, and `web_policy=redact_or_fail`.
It contains no raw prompt, raw session/turn identity, secret, credential, or
matched security value.

If validated input is Router-eligible but configuration, identity, state-root,
or idempotent run initialization fails, the hook returns a bounded block
decision explaining that the user may explicitly begin the prompt with
`仅本地执行`. It does not silently proceed without Router.

## Configurable execution defaults

The Router-owned `config.json` contains:

- state root;
- absolute App-bundled Codex binary;
- Local Sol requested model and reasoning;
- Web Sol claimed model and reasoning;
- Luna requested model and reasoning.

Defaults are Local Sol `max`, Web Sol `xhigh`, and Luna `max`. These are
configuration values, not state-transition constants. Every run copies the
exact configured values into its role configuration with the existing
verification levels.

## Web outbound security gate

`security.py` owns one reusable scanner and a typed result with decisions
`allow`, `redacted`, and `block`. The scanner operates on the complete proposed
Web payload after Local Sol succeeds and before a Web packet is executable. It
includes the task, Local Sol output, included excerpts, and Web-bound metadata.

Detected credentials, authorization headers, bearer tokens, cookies, sessions,
passwords, API keys, `.env` assignments, provider tokens, email/account
identifiers, and private paths use deterministic category replacement tokens
when the value can be safely removed. Private/signing key material,
Luhn-valid card candidates, unbounded high-entropy candidates, ambiguous
structured secrets, or any value that remains after re-scan block the payload.

Only category names, counts, and the decision are added to Router evidence.
Matched substrings never enter security events, errors, hook output, or
telemetry. The scanner re-scans redacted output. A residual detection changes
the result to `block`.

On block, the canonical run records Local Sol success and a terminal Web
security failure. No executable Web packet is created, no Web request occurs,
and Luna cannot continue. There is no retry, provider switch, Web skip, or
automatic local fallback.

This gate prevents detected protected material from crossing the Web boundary;
it does not prove the absence of every unknown secret.

## Prompt persistence boundary

The complete prompt is not copied into the global policy ledger, installation
state, hook output, CLI output, telemetry, or context mapping. The local Router
state retains the canonical normalized task, task digest, local packet, and
stage outputs because local recovery requires them. Local packet and state
files remain mode `0600` under a marker-owned `0700` root.

This local recovery copy is an explicit exception. Web packets contain only
the security-gated task and Local Sol output, never the raw local versions.

## Continuous Web context

Router binds run, packet, revision, marker, digest, and driver context. Web
execution remains `operator_attested`. The Codex App/operator maintains the
mapping from driver context to the current Web conversation. Same-session runs
reuse that conversation; a new session receives a new context. Router neither
opens, closes, focuses, nor duplicates browser pages.

Wrong response marker, run, packet, revision, or driver context is rejected by
the existing state machine. Browser reuse is verified only by the manual App
acceptance checklist.

## Global installation layout

The installer accepts an explicit Codex home and otherwise resolves the active
Codex home. It creates `.codex-router-policy-v1/` under that home with mode
`0700`. Files inside use atomic mode-`0600` writes:

```text
.codex-router-policy-v1/
  config.json
  installation-secret
  install-state.json
  backups/
    hooks.json.original
    agents.md.original
```

The configured Router state root is outside the live Codex profile and uses the
Phase 1 ownership marker contract.

`hooks.json` receives exactly one `UserPromptSubmit` command handler with a
stable Router status message and command marker. `AGENTS.md` receives one
concise block bounded by unique begin/end markers. The block tells Codex to
show the Router banner, obey structured hook context, drive the existing state
machine, wait for terminal state before answering routed substantive work,
honor direct/bypass, recover from canonical state, and never fabricate a stage.

Existing JSON is parsed with size and type limits before mutation. Exact
original bytes are backed up without timestamps or personal metadata. Install
is idempotent. Conflicting markers, malformed files, symlinks, duplicate Router
handlers, or an unsafe previous installation fail closed.

Uninstall removes only the Router handler and managed AGENTS block. If managed
files are unchanged since installation, their exact original bytes are
restored. If hooks changed concurrently and byte-preserving removal cannot be
proven, uninstall refuses rather than rewriting unrelated content. Backups and
run evidence remain. Repeated uninstall is safe.

The installer never overwrites full `AGENTS.md`, `AGENTS.override.md`,
`hooks.json`, or `config.toml`, and never alters `config.toml` in V1.

## Status, self-test, and activation limits

`global-status` reports installation presence, hook configuration, managed
AGENTS block, secret presence/mode, configuration validity, hook trust as
`unknown` or `requires-user-check`, and `new-session-required`. It never claims
trust without a supported Codex trust receipt.

The safe self-test uses synthetic in-memory hook events, makes no Web/model call,
and creates no browser activity. It proves stable/different session mapping,
bypass/direct/route decisions, duplicate event idempotency, and absence of raw
synthetic identity/prompt data from output and persisted files. It does not
activate the live installation.

## Rollback and manual acceptance

Installation is not active until the operator reviews `/hooks`, starts a new
Codex session, and completes the documented manual checklist. Uninstall restores
manual Router behavior only for new sessions because AGENTS guidance is loaded
at session start.

Manual acceptance must check same-session context reuse, new-session isolation,
one run per turn, no new Web page, marker rejection, one-turn bypass, protected
payload block, and uninstall behavior. Automated tests must not claim these UI
facts.

## Non-goals

- No daemon, LaunchAgent, login item, listener, scheduler, or App restart.
- No browser bridge or browser lifecycle automation.
- No provider integration or automatic model turn in tests.
- No database, retry engine, fallback provider, or background queue.
- No PR #3 merge, runner start, second PR, or Phase 2 push in this task.

