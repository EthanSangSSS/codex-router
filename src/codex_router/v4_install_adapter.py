"""V4 activation and model-contract overlay for the managed global installer."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import threading
from typing import Any, Iterator


_INSTALLED = False
_POLICY_LOCK = threading.RLock()

V4_LIVE_ACTIVATION_BLOCKERS = (
    "V40_LIVE_ROOT_REQUEST_STAGING",
    "V40_LIVE_PRETOOL_ACTOR_BINDING",
    "V40_LIVE_K1_BOOTSTRAP",
    "V40_LIVE_NORMAL_TERMINAL",
    "V40_LIVE_MISSING_STOP_SUPERSESSION",
    "V40_LIVE_STALE_WORKER_REJECTION",
    "V40_LIVE_CAPACITY_RECOVERY",
    "V40_OLD_CONVERSATION_RESUME",
)
V4_DEFERRED_ACCEPTANCE_EVIDENCE = (
    "V41_STABLE_DISPATCHER",
    "V42_NATIVE_PERMISSION_DELEGATION_WITH_K1_SCOPE",
)

V4_LUNA_DEVELOPER_INSTRUCTIONS = """You are one Router V4 generation-lease Luna Full Executor. PRIMARY is the persistent planner, coordinator, reviewer, and final authority.

Operating rules:
- Full Executor ordinary inspect/research/edit/test/debug/retry/verify work is allowed when the current canonical K1 authorizes that scope and the native runtime permits it.
- You have no descendants and must perform no nested Codex delegation. Never create, spawn, fork, relay to, resume, or coordinate another agent or Codex runtime.
- Native worker lifetime is not Router authority. Your authority exists only while your exact current generation lease remains active. A new PRIMARY root turn may logically revoke that lease without waiting for your native process or SubagentStop event to terminate.
- The current native spawn message carries only the capability-bound Router bootstrap command. Before canonical K1 is visible, your first tool MUST be the exact Codex Bash command from that current native spawn message, with shape `pwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4=v4b1.<mac>`. Do not replace it with plain `pwd`, edit the capability, or perform substantive work first.
- The bootstrap probe supplies no objective, scope, or permission. Router binds your native agent and child turn only when that exact capability is valid for the current lease, then injects canonical `[CODEX_ROUTER_PACKET_V3_1]` as additionalContext. If canonical K1 does not appear, stop fail-closed.
- After K1 is visible, work only inside the latest packet's working directory, paths, side-effect authorizations, success criteria, and stop conditions. Never inherit authority from an older generation or from child memory.
- If your lease is revoked or superseded, later substantive tool attempts are expected to be denied mechanically. Do not try to regain authority through followup, resume, send_input, polling, sleeps, or stale native identity.
- Native terminal/cleanup evidence is resource telemetry, not the source of Router authority. Never intentionally daemonize or detach long-lived background work beyond the bounded turn.
- A1/K1 intent scope remains authoritative in V4.0. Native permission or approval does not by itself broaden the current packet's task authority.
- Never access authentication, credentials, cookies, tokens, private keys, payment data, or unrelated user data. Never commit, push, modify a PR, install, deploy, publish, or start persistent services unless the latest explicit packet authorizes that exact action and normal platform controls permit it.
"""


def _v4_agents_block(core_module: Any) -> str:
    return f"""{core_module.AGENTS_BEGIN}
This Codex task is the persistent PRIMARY coordinator and final reviewer. Router V4.0 uses `generation_lease_v4`: each routed job receives one generation-scoped authority lease; native Luna lifetime is separate from Router authority.
Honor `[CODEX_ROUTER_POLICY_V1]` Hook context exactly:
- `direct` and `bypass` keep their native local meaning. A new PRIMARY user turn performs logical lease revocation of any prior V4 authority immediately; this does not wait for `SubagentStop`, close_agent, worker STOPPED state, or native path cleanup.
- For a substantive `route`, use the complete injected `K1_STAGE_COMMAND` verbatim. Write exactly one seven-field UTF-8 JSON request to the exact absolute path following `--request-file` with these exact JSON field types: `packet_id`: `non-empty UTF-8 string`; `objective`: `non-empty UTF-8 string`; `working_directory`: `absolute path string`; `intended_write_scope`: `array[string]`; `explicit_side_effect_authorizations`: `array[string]`; `success_criteria`: `array[string]`; `stop_conditions`: `array[string]`. Do not serialize any array field as a scalar string or object. Do not append semantic K1 fields to the shell argv and do not add generation, session, lease, capability, or agent identity to the request. Router alone constructs canonical K1.
- Successful V4 staging returns the generation-scoped `task_name`, `bootstrap_capability`, and `spawn_message`. Use the actually exposed native spawn transport without inventing unsupported fields. V2: spawn exactly the task_name returned by staging using `agent_type=luna_worker`, `fork_turns=none`, and the spawn_message returned by staging unchanged. V1: use `multi_agent_v1__spawn_agent` with `agent_type=luna_worker`, `fork_context=false` (or omit `fork_context` only when the namespaced V1 surface permits omission), and the spawn_message returned by staging unchanged. V1 transport does not carry `task_name` or `fork_turns`; the generation-scoped task_name remains Router lease identity. Never substitute the static task name `luna_worker` for the returned generation-scoped task_name.
- V2 parent PreToolUse exposes the spawn `message` only as encrypted opaque data, so Router cannot mechanically compare its plaintext at that boundary. The parent V2 check validates the current generation/task envelope and a non-empty opaque message only; this does not grant worker authority. Router authority remains unbound until the exact first child capability bootstrap succeeds.
- `SubagentStart` is telemetry only and never grants V4 authority. The worker binds only on its first native PreToolUse when `agent_id`, child `turn_id`, and the exact capability-bound Bash bootstrap all match the current lease.
- Luna's first tool is the exact Bash command carried in the current spawn_message, with shape `pwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4=v4b1.<mac>`. Plain `pwd` is not the V4 bootstrap. Router injects canonical K1 only after exact current-lease validation.
- A later PRIMARY root turn may revoke the lease even if native terminal evidence is missing. After revocation, stale worker PreToolUse is denied; late SubagentStart/SubagentStop/PostToolUse from an older generation must not mutate the current lease.
- Native resource cleanup and native agent capacity are independent from Router authority. A native capacity failure must not restore an old lease. The next PRIMARY root turn may supersede the failed attempt; Router V4.0 does not implement a queue or bypass native concurrency limits.
- V4.0 does not use worker reuse, followup, resume, or a pool as its normal protocol. `send_input` and `resume_agent` are forbidden, `send_message` is QueueOnly, and wait/polling/sleeps are not work authority.
- Full Executor ordinary inspect/research/edit/test/debug/retry/verify work remains available after canonical K1 is visible. Luna has no descendants and no nested Codex delegation.
- K1/A1 task intent remains a separate authority layer from native sandbox/approval. Native permission does not broaden the current lease.
- Already-admitted tool work is not transactionally rolled back by lease revocation. V4.0 guarantees fencing of later PreToolUse, not reversal of effects that entered native execution before revocation.
- Live activation remains `PENDING_LIVE_ACCEPTANCE` until the explicit V4.0 runtime gates reported by `global-status` are mechanically demonstrated on the target Codex runtime.
- PRIMARY remains planner/reviewer/final authority; every generation must remain independently bounded and must not broaden scope or access unrelated private data.
{core_module.AGENTS_END}
"""


def _v4_status(status: Any) -> Any:
    return replace(
        status,
        router_design="v4.0_generation_lease",
        luna_execution_mode="generation_lease_v4",
        live_activation="PENDING_LIVE_ACCEPTANCE",
        live_activation_blockers=V4_LIVE_ACTIVATION_BLOCKERS,
        deferred_acceptance_evidence=V4_DEFERRED_ACCEPTANCE_EVIDENCE,
    )


def install(adapter_module: Any, core_module: Any, lease_control: Any) -> None:
    """Install V4 rendering/status while preserving the reversible installer core."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_install_hook_v3 = adapter_module.install_hook_v3
    original_global_install = adapter_module.global_install
    original_global_status = adapter_module.global_status
    original_global_uninstall = adapter_module.global_uninstall
    original_global_self_test = adapter_module.global_self_test

    def install_hook_v4(*args, **kwargs):
        rendered = original_install_hook_v3(*args, **kwargs)
        document = json.loads(rendered)
        hooks = document.get("hooks") if isinstance(document, dict) else None
        groups = hooks.get("SubagentStop") if isinstance(hooks, dict) else None
        if isinstance(groups, list):
            for group in groups:
                handlers = group.get("hooks") if isinstance(group, dict) else None
                if not isinstance(handlers, list):
                    continue
                for handler in handlers:
                    if isinstance(handler, dict):
                        handler.pop("additionalContextLimit", None)
        return (
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n"
        )

    # _rendering_adapter resolves install_hook_v3 by module-global name at call
    # time. Patch both the canonical V3 renderer name and its compatibility
    # alias so direct callers and managed installation produce the same V4
    # config. SubagentStop cannot emit additionalContext in current Codex.
    adapter_module.install_hook_v3 = install_hook_v4
    adapter_module.install_hook_v2 = install_hook_v4

    @contextmanager
    def v4_policy() -> Iterator[None]:
        # The V3 adapter intentionally resolves these renderer constants at call
        # time. Serialize the short replacement window so multiple in-process
        # installer/status operations cannot observe mixed contracts.
        with _POLICY_LOCK:
            old_agents = adapter_module.AGENTS_BLOCK_V3
            old_luna = adapter_module.LUNA_DEVELOPER_INSTRUCTIONS_V3
            adapter_module.AGENTS_BLOCK_V3 = _v4_agents_block(core_module)
            adapter_module.LUNA_DEVELOPER_INSTRUCTIONS_V3 = (
                V4_LUNA_DEVELOPER_INSTRUCTIONS
            )
            try:
                yield
            finally:
                adapter_module.AGENTS_BLOCK_V3 = old_agents
                adapter_module.LUNA_DEVELOPER_INSTRUCTIONS_V3 = old_luna

    def global_install(*args, **kwargs):
        codex_home = kwargs.get("codex_home", args[0] if args else None)
        with v4_policy():
            status = original_global_install(*args, **kwargs)
        if codex_home is None:
            # The core installer owns argument validation; a successful return
            # without codex_home would violate its contract, so fail closed.
            raise ValueError("successful global install did not identify codex_home")
        managed = Path(codex_home).expanduser() / core_module.INSTALL_DIRECTORY_NAME
        lease_control.activate_installation(managed)
        return _v4_status(status)

    def global_status(*args, **kwargs):
        with v4_policy():
            status = original_global_status(*args, **kwargs)
        return _v4_status(status)

    def global_uninstall(*args, **kwargs):
        with v4_policy():
            status = original_global_uninstall(*args, **kwargs)
        return _v4_status(status)

    def global_self_test(*args, **kwargs):
        with v4_policy():
            result = original_global_self_test(*args, **kwargs)
        return {
            **result,
            "router_design": "v4.0_generation_lease",
            "luna_execution_mode": "generation_lease_v4",
            "live_activation": "PENDING_LIVE_ACCEPTANCE",
            "live_activation_blockers": list(V4_LIVE_ACTIVATION_BLOCKERS),
            "deferred_acceptance_evidence": list(
                V4_DEFERRED_ACCEPTANCE_EVIDENCE
            ),
        }

    adapter_module.global_install = global_install
    adapter_module.global_status = global_status
    adapter_module.global_uninstall = global_uninstall
    adapter_module.global_self_test = global_self_test
    _INSTALLED = True
