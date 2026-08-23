"""Narrow V4 lease Hook overlay.

The V3.3 Hook remains the default. This overlay takes control only for native
Luna child events in a session that already has V4 lease state.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from . import lease_control
from .state import RouterStateError


_BOOTSTRAP_COMMAND_RE = re.compile(
    r"\Apwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4=(v4b1\.[0-9a-f]{64})\Z"
)
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


def install(hook_module: Any) -> None:
    """Install the V4 child overlay once, after the active V3.3 usability layer."""
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
        if name not in {"PreToolUse", "SubagentStart"}:
            return original_handle_hook_event(event, installation_dir)

        session_id = event.get("session_id")
        agent_type = event.get("agent_type")
        if (
            not isinstance(session_id, str)
            or not session_id
            or agent_type != "luna_worker"
        ):
            return original_handle_hook_event(event, installation_dir)

        try:
            secret, _config = hook_module._load_installation(Path(installation_dir))
            snapshot, v4_present = _v4_snapshot_if_present(
                Path(installation_dir), secret, session_id
            )
        except RouterStateError as error:
            if name == "PreToolUse":
                return _deny(hook_module, str(error))
            return {"continue": False, "stopReason": str(error)[:500]}
        except Exception:
            return original_handle_hook_event(event, installation_dir)

        if not v4_present or snapshot is None:
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
