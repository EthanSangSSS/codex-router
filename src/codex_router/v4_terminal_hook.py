"""V4 SubagentStop Hook overlay.

Only sessions that already have V4 lease state are handled here.  V3 sessions
continue through the previously installed Hook implementation unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import lease_control
from .state import RouterStateError


_INSTALLED = False


def install(hook_module: Any) -> None:
    """Install exact V4 SubagentStop reconciliation once."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_handle_hook_event = hook_module.handle_hook_event

    def handle_hook_event(
        event: Mapping[str, Any], installation_dir: Path
    ) -> dict[str, Any]:
        if (
            not isinstance(event, Mapping)
            or event.get("hook_event_name") != "SubagentStop"
            or event.get("agent_type") != "luna_worker"
        ):
            return original_handle_hook_event(event, installation_dir)

        session_id = event.get("session_id")
        agent_id = event.get("agent_id")
        child_turn_id = event.get("turn_id")
        if not isinstance(session_id, str) or not session_id:
            return original_handle_hook_event(event, installation_dir)

        journal = Path(installation_dir) / "lease-control-v4-0.json"
        if not journal.exists() and not journal.is_symlink():
            return original_handle_hook_event(event, installation_dir)

        try:
            secret, _config = hook_module._load_installation(Path(installation_dir))
            snapshot = lease_control.read_snapshot(
                Path(installation_dir), secret, session_id
            )
            if snapshot is None:
                # A global V4 journal may exist while this particular historical
                # session is still V3-only. Do not steal its lifecycle event.
                return original_handle_hook_event(event, installation_dir)
            if not isinstance(agent_id, str) or not agent_id:
                raise lease_control._error("SubagentStop agent_id is invalid")
            if not isinstance(child_turn_id, str) or not child_turn_id:
                raise lease_control._error("SubagentStop turn_id is invalid")

            lease_control.observe_subagent_stop(
                Path(installation_dir),
                secret,
                session_id,
                agent_id=agent_id,
                agent_type="luna_worker",
                child_turn_id=child_turn_id,
            )
            # CURRENT, STALE and NOOP are all successful observations from the
            # Hook protocol's perspective. Only exact CURRENT mutates authority.
            return {"hookSpecificOutput": {"hookEventName": "SubagentStop"}}
        except RouterStateError as error:
            return {"continue": False, "stopReason": str(error)[:500]}

    hook_module.handle_hook_event = handle_hook_event
    _INSTALLED = True
