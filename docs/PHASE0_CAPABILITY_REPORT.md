# Phase 0 Capability Report

Status: BLOCKED

This report records the bounded Phase 0 probe only. It intentionally omits
account identifiers, browser URLs, prompts, transcripts, target-project source,
and credentials.

## Verified Baseline

- A dedicated private control repository was created and cloned into its
  dedicated local checkout.
- The verified remote base is main at
  39e5488621c30d9e7a6aa6f749ae6325864a7d88.
- The implementation branch is
  feat/local-sol-web-sol-luna-router-v1, created from that exact base.
- The control checkout was clean before this report was written.
- No target repository allowlist is configured, so no target project can be
  selected or written.
- Runtime probe artifacts are outside the repository and protected with
  owner-only permissions.

## Environment And Interface Telemetry

| Capability | Result | Evidence |
| --- | --- | --- |
| macOS and architecture | VERIFIED | macOS 15.7.7 on arm64 |
| Python 3.12 | VERIFIED | Python 3.12.10 is installed |
| GitHub CLI authentication | VERIFIED | gh auth status exited 0; account output was not retained |
| Codex CLI | VERIFIED | codex-cli 0.144.0 |
| Luna selection | VERIFIED | gpt-5.6-luna is present in the installed model catalog and accepts high reasoning effort |
| App Server schema | VERIFIED | The installed CLI generated the experimental JSON-RPC schema, including thread/start, thread/resume, thread/archive, thread/delete, and thread/unsubscribe |

## Mandatory Capability Gates

| Gate | Result | Bounded evidence |
| --- | --- | --- |
| Native Browser to Web Sol round-trip | FAILED | A new in-app Browser tab remained at about:blank after a bounded navigation attempt to the expected ChatGPT domain; no existing ChatGPT tab was available to claim. No message or conversation was created. |
| Web Sol GitHub Issue create/read/close test | UNVERIFIED | Not attempted because the Browser gate failed. No capability-test Issue was created. |
| Fresh Luna worker lifecycle | UNVERIFIED | The isolated probe produced the expected worktree-only file, but the client did not complete its supported event, unsubscribe, archive, and delete sequence as one verified lifecycle. |
| External worktree isolation | VERIFIED | A temporary local bare repository and external worktree were created below the runtime probe directory. The original temporary checkout remained clean; the only observed worker change was the probe file in the external worktree. |
| Supported thread cleanup operations | FAILED | Archive completed through the supported Codex thread control, but the supported CLI delete operation returned an error. Unsubscribe was not independently verified. |

## Fail-Closed Outcome

Product implementation has not started. No browser automation code, background
Web Sol controller, target-repository checkout, GitHub Issue, PR, push, or
target-project modification was created by this probe.

The temporary external worktree is intentionally retained under the protected
probe directory because it is dirty. It was not force-removed, reset, cleaned,
or deleted.

## Required Before Resuming

1. Restore normal in-app Browser navigation to the signed-in ChatGPT surface
   without using hidden APIs, browser data, CDP, AppleScript, or coordinate
   automation.
2. Rerun the Browser nonce round-trip and the safe GitHub Issue test.
3. Establish and verify a supported thread-delete path, then rerun the full
   Luna lifecycle probe from a clean temporary worktree.
4. Only after every mandatory gate is VERIFIED may the V1 implementation begin.
