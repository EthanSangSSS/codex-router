"""Narrow V4 lease Hook overlay.

The V3.3 Hook remains the default. This overlay takes control only when an
installation has opted into the V4 lease journal.
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path
from typing import Any, Mapping

from . import lease_control
from .state import RouterStateError
from .v4_cli import spawn_message


_BOOTSTRAP_COMMAND_RE = re.compile(
    r"\Apwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4=(v4b1\.[0-9a-f]{64})\Z"
)
_K1_REQUEST_SCHEMA = {
    "packet_id": "non-empty UTF-8 string",
    "objective": "non-empty UTF-8 string",
    "working_directory": "absolute path string",
    "intended_write_scope": "array[string]",
    "explicit_side_effect_authorizations": "array[string]",
    "success_criteria": "array[string]",
    "stop_conditions": "array[string]",
}
_INSTALLED = False


def _deny(hook_module: Any, reason: str) -> dict[str, Any]:
    return hook_module._pretool_output("deny", reason[:500])


def _v4_snapshot_if_present(
    installation_dir: Path,
    secret: bytes,
    session_id: str,
):
    journal = installation_dir / "lease-control-v4-0.json"
    if not journal.exists() and not journal.is_symlink():
        return None, False
    return lease_control.read_snapshot(installation_dir, secret, session_id), True


def _bootstrap_capability(event: Mapping[str, Any]) -> str | None:
    if event.get("tool_name") != "Bash":
        return None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, Mapping) or set(tool_input) != {"command"}:
        return None
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    match = _BOOTSTRAP_COMMAND_RE.fullmatch(command)
    if match is None:
        return None
    return match.group(1)


def _v4_stage_command(
    installation_dir: Path,
    *,
    session_id: str,
    root_turn_id: str,
    capability: str,
) -> str:
    return shlex.join(
        (
            sys.executable,
            "-E",
            "-P",
            "-m",
            "codex_router",
            "stage-k1-fields",
            "--installation-dir",
            str(installation_dir),
            "--session-id",
            session_id,
            "--root-turn-id",
            root_turn_id,
            "--capability",
            capability,
        )
    )


def _handle_v4_root_prompt(
    hook_module: Any,
    event: Mapping[str, Any],
    installation_dir: Path,
    secret: bytes,
    config: Mapping[str, Any],
    snapshot: Any,
) -> dict[str, Any]:
    validated = hook_module._validate_event(event)
    if "agent_id" in validated:
        return hook_module._child_block()

    policy = hook_module.classify_prompt(validated["prompt"])
    if snapshot is None:
        snapshot = lease_control.initialize_session(
            installation_dir, secret, validated["session_id"]
        )

    # Every new root user turn supersedes the prior Router authority
    # immediately. Native worker cleanup is deliberately not a prerequisite.
    snapshot = lease_control.revoke_current_lease(
        installation_dir, secret, validated["session_id"]
    )

    if policy.decision in ("direct", "bypass"):
        lease_control.set_current_root_turn(
            installation_dir,
            secret,
            validated["session_id"],
            turn_id=None,
        )
        return hook_module._hook_output(
            {
                "protocol": hook_module.HOOK_CONTEXT_PROTOCOL,
                "decision": policy.decision,
                "reason": policy.reason_code,
                "workflow": "primary_direct_v4",
            }
        )

    snapshot = lease_control.set_current_root_turn(
        installation_dir,
        secret,
        validated["session_id"],
        turn_id=validated["turn_id"],
    )
    stage_capability = lease_control.build_stage_capability(
        secret, snapshot, root_turn_id=validated["turn_id"]
    )
    stage_command = _v4_stage_command(
        installation_dir,
        session_id=validated["session_id"],
        root_turn_id=validated["turn_id"],
        capability=stage_capability,
    )
    luna = config["role_config"]["luna"]
    return hook_module._hook_output(
        {
            "protocol": hook_module.HOOK_CONTEXT_PROTOCOL,
            "decision": "route",
            "reason": policy.reason_code,
            "workflow": "generation_lease_v4",
            "sol_role": "plan_review_final_authority",
            "luna_role": "generation_lease_executor",
            "delegation_mode": "fresh_worker_per_generation",
            "luna_agent": "luna_worker",
            "luna_model": luna["requested_model"],
            "luna_reasoning": luna["requested_reasoning"],
            "authority_model": "generation_lease_v4",
            "terminal_reconciliation": "optional_not_admission_prerequisite",
            "native_cleanup_policy": "independent_from_router_authority",
            "K1_STAGE_CAPABILITY": stage_capability,
            "K1_STAGE_COMMAND": stage_command,
            "K1_REQUEST_SCHEMA": dict(_K1_REQUEST_SCHEMA),
            "spawn_contract": (
                "Run K1_STAGE_COMMAND with the bounded K1 fields first and use the actually "
                "exposed native spawn surface. V2: spawn the returned task_name with "
                "agent_type=luna_worker, fork_turns=none, and the returned spawn_message "
                "unchanged. V1: use multi_agent_v1__spawn_agent with agent_type=luna_worker, "
                "fork_context=false (or omit fork_context only when the namespaced V1 surface "
                "permits omission), and the returned spawn_message unchanged. V1 transport "
                "does not carry task_name or fork_turns; the generation-scoped task_name remains "
                "Router lease identity. Never invent fields unsupported by the exposed surface."
            ),
        }
    )


def _v4_root_spawn_base(hook_module: Any, event: Mapping[str, Any], name: str):
    base = hook_module._event_base(
        event, name, ("session_id", "turn_id", "tool_name", "tool_use_id")
    )
    hook_module._normalize_event_tool_name(base)
    if base["tool_name"] != "spawn_agent":
        return None
    if hook_module._identity_kind(event, lifecycle=False) != "root":
        return None
    return base


def _require_current_v4_root(
    secret: bytes,
    snapshot: Any,
    *,
    root_turn_id: str,
) -> None:
    # build_stage_capability performs an exact HMAC comparison with the current
    # root-turn tag. The returned next-generation capability is intentionally
    # discarded here; this helper only proves the event belongs to current root.
    lease_control.build_stage_capability(
        secret, snapshot, root_turn_id=root_turn_id
    )


def _handle_v4_root_spawn_pre(
    hook_module: Any,
    event: Mapping[str, Any],
    installation_dir: Path,
    secret: bytes,
    snapshot: Any,
) -> dict[str, Any] | None:
    base = _v4_root_spawn_base(hook_module, event, "PreToolUse")
    if base is None:
        return None
    lease = snapshot.active_lease
    if lease is None:
        return _deny(hook_module, "Router V4 spawn has no current lease")
    try:
        _require_current_v4_root(
            secret, snapshot, root_turn_id=base["turn_id"]
        )
        tool_input = event.get("tool_input")
        if not isinstance(tool_input, Mapping):
            raise lease_control._error("V4 spawn tool_input must be an object")
        hook_module._discriminate_spawn_profile(base, tool_input)
        match = base.get("native_tool_match")
        is_v1 = (
            isinstance(match, hook_module.NativeToolMatch)
            and match.surface_profile in {"multi_agent_v1", "collapsed_v1_spawn"}
        )
        if is_v1:
            allowed_v1_keys = (
                {"agent_type", "message"},
                {"agent_type", "fork_context", "message"},
            )
            if set(tool_input) not in allowed_v1_keys:
                raise lease_control._error("V4 V1 spawn input schema is invalid")
            hook_module._v1_spawn_projection(tool_input, match.surface_profile)
            expected_capability = lease_control.build_bootstrap_capability(secret, lease)
            expected_message = spawn_message(expected_capability)
            if tool_input.get("message") != expected_message:
                raise lease_control._error("V4 spawn message does not match current lease")
        else:
            expected_keys = {"task_name", "agent_type", "fork_turns", "message"}
            if set(tool_input) != expected_keys:
                raise lease_control._error("V4 spawn input schema is invalid")
            if tool_input.get("task_name") != lease.expected_task_name:
                raise lease_control._error("V4 spawn task_name does not match current lease")
            if tool_input.get("agent_type") != "luna_worker":
                raise lease_control._error("V4 spawn agent_type must be luna_worker")
            if tool_input.get("fork_turns") != "none":
                raise lease_control._error("V4 spawn must use fork_turns=none")
            message = tool_input.get("message")
            if not isinstance(message, str) or not message:
                raise lease_control._error("V4 V2 spawn message is invalid")
            # Codex V2 encrypts spawn_agent.message before the blocking
            # PreToolUse hook. This boundary can validate only the visible
            # generation/task envelope; it must not treat opaque ciphertext as
            # Router authority. Worker authority remains unbound until the
            # exact current capability is proven by the first child PreToolUse.
        lease_control.reserve_spawn(
            installation_dir,
            secret,
            base["session_id"],
            tool_use_id=base["tool_use_id"],
            task_name=lease.expected_task_name,
            agent_type="luna_worker",
            fork_turns="none",
        )
        return {}
    except RouterStateError as error:
        return _deny(hook_module, str(error))


def _handle_v4_root_spawn_post(
    hook_module: Any,
    event: Mapping[str, Any],
    installation_dir: Path,
    secret: bytes,
    snapshot: Any,
) -> dict[str, Any] | None:
    base = _v4_root_spawn_base(hook_module, event, "PostToolUse")
    if base is None:
        return None
    try:
        match = base.get("native_tool_match")
        is_v1 = (
            isinstance(match, hook_module.NativeToolMatch)
            and match.surface_profile == "multi_agent_v1"
        )
        lease = snapshot.active_lease
        # A late result for a superseded spawn is safe to classify by its stale
        # tool_use_id without requiring the old root turn to still be current.
        if lease is not None and lease.spawn_tool_use_id == base["tool_use_id"]:
            _require_current_v4_root(
                secret, snapshot, root_turn_id=base["turn_id"]
            )
        if is_v1:
            # Namespaced V1 returns a native agent_id rather than the
            # generation-scoped V2 task path. Validate it as correlated native
            # telemetry only. Worker authority remains unbound until the
            # capability-bound first child PreToolUse proves exact identity.
            hook_module._spawn_agent_id(event.get("tool_response"))
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}
        lease_control.observe_spawn_result(
            installation_dir,
            secret,
            base["session_id"],
            tool_use_id=base["tool_use_id"],
            task_path=hook_module._spawn_task_path(event.get("tool_response")),
        )
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}
    except RouterStateError as error:
        return {"continue": False, "stopReason": str(error)[:500]}


def install(hook_module: Any) -> None:
    """Install the V4 overlay once, after the active V3.3 usability layer."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_handle_hook_event = hook_module.handle_hook_event

    def handle_hook_event(
        event: Mapping[str, Any], installation_dir: Path
    ) -> dict[str, Any]:
        if not isinstance(event, Mapping):
            return original_handle_hook_event(event, installation_dir)
        name = event.get("hook_event_name")
        if name not in {
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "SubagentStart",
        }:
            return original_handle_hook_event(event, installation_dir)

        session_id = event.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return original_handle_hook_event(event, installation_dir)

        try:
            secret, config = hook_module._load_installation(Path(installation_dir))
            snapshot, v4_present = _v4_snapshot_if_present(
                Path(installation_dir), secret, session_id
            )
        except RouterStateError as error:
            if name == "PreToolUse":
                return _deny(hook_module, str(error))
            return {"continue": False, "stopReason": str(error)[:500]}
        except Exception:
            return original_handle_hook_event(event, installation_dir)

        if not v4_present:
            return original_handle_hook_event(event, installation_dir)

        if name == "UserPromptSubmit":
            try:
                return _handle_v4_root_prompt(
                    hook_module,
                    event,
                    Path(installation_dir),
                    secret,
                    config,
                    snapshot,
                )
            except RouterStateError as error:
                return {"decision": "block", "reason": str(error)[:500]}
            except Exception:
                return {"decision": "block", "reason": hook_module._BLOCK_REASON}

        if snapshot is None:
            return original_handle_hook_event(event, installation_dir)

        if name == "PreToolUse":
            parent_spawn = _handle_v4_root_spawn_pre(
                hook_module,
                event,
                Path(installation_dir),
                secret,
                snapshot,
            )
            if parent_spawn is not None:
                return parent_spawn
        elif name == "PostToolUse":
            parent_spawn = _handle_v4_root_spawn_post(
                hook_module,
                event,
                Path(installation_dir),
                secret,
                snapshot,
            )
            if parent_spawn is not None:
                return parent_spawn
            return original_handle_hook_event(event, installation_dir)

        if event.get("agent_type") != "luna_worker":
            return original_handle_hook_event(event, installation_dir)

        if name == "SubagentStart":
            try:
                agent_id = event.get("agent_id")
                turn_id = event.get("turn_id")
                if not isinstance(agent_id, str) or not agent_id:
                    raise lease_control._error("SubagentStart agent_id is invalid")
                if not isinstance(turn_id, str) or not turn_id:
                    raise lease_control._error("SubagentStart turn_id is invalid")
                lease_control.observe_subagent_start(
                    Path(installation_dir),
                    secret,
                    session_id,
                    agent_id=agent_id,
                    agent_type="luna_worker",
                    turn_id=turn_id,
                )
                return {
                    "hookSpecificOutput": {"hookEventName": "SubagentStart"}
                }
            except RouterStateError as error:
                return {"continue": False, "stopReason": str(error)[:500]}

        agent_id = event.get("agent_id")
        turn_id = event.get("turn_id")
        if not isinstance(agent_id, str) or not agent_id:
            return _deny(hook_module, "Router V4 Luna agent identity is unavailable")
        if not isinstance(turn_id, str) or not turn_id:
            return _deny(hook_module, "Router V4 Luna child turn is unavailable")

        lease = snapshot.active_lease
        if lease is None:
            return _deny(hook_module, "Luna tool has no active V4 lease")

        try:
            if lease.status == "STAGED":
                capability = _bootstrap_capability(event)
                if capability is None:
                    return _deny(
                        hook_module,
                        "Router V4 lease bootstrap requires exact capability-bound Bash pwd probe",
                    )
                _updated, packet_wire = lease_control.authorize_executor_tool(
                    Path(installation_dir),
                    secret,
                    session_id,
                    agent_id=agent_id,
                    agent_type="luna_worker",
                    child_turn_id=turn_id,
                    bootstrap_capability=capability,
                )
                if packet_wire is None:
                    return _deny(
                        hook_module, "Router V4 lease bootstrap authority is unavailable"
                    )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": packet_wire,
                    }
                }

            lease_control.authorize_executor_tool(
                Path(installation_dir),
                secret,
                session_id,
                agent_id=agent_id,
                agent_type="luna_worker",
                child_turn_id=turn_id,
                bootstrap_capability=None,
            )
            tool_name = event.get("tool_name")
            if isinstance(tool_name, str) and hook_module._looks_like_agent_lifecycle_tool(
                tool_name
            ):
                return _deny(
                    hook_module,
                    "Luna tool surface forbids agent lifecycle continuation",
                )
            return {}
        except RouterStateError as error:
            return _deny(hook_module, str(error))

    hook_module.handle_hook_event = handle_hook_event
    _INSTALLED = True