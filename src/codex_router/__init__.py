"""Minimal Local Sol → Web Sol → Luna router."""

from .pipeline import Router, RouterRunError
from .state import RouterStateError, fail_stage, get_status, start_run, submit_stage
from .types import RunOutcome, StageResult, TransitionResult
from . import luna_control as luna_control
from .luna_control_recovery import install as _install_luna_control_recovery

_install_luna_control_recovery(luna_control)

_authorize_parent_target = luna_control.authorize_parent_target


def _authorize_turn_dispatch_target(
    directory,
    secret,
    session_id,
    *,
    tool_name,
    target,
):
    # Exact current-App MultiAgentV2 maps send_message to QueueOnly. Admitting a
    # K1 generation on that surface would advance Router authority without
    # creating a Luna turn. Only a turn-triggering followup_task is a normal
    # continuation dispatch surface in current-App Turn-Boundary mode.
    if tool_name == "send_message":
        raise RouterStateError(
            "conflict",
            "Router K1 dispatch requires followup_task; send_message is queue-only",
        )
    return _authorize_parent_target(
        directory,
        secret,
        session_id,
        tool_name=tool_name,
        target=target,
    )


luna_control.authorize_parent_target = _authorize_turn_dispatch_target

__all__ = [
    "Router",
    "RouterRunError",
    "RouterStateError",
    "RunOutcome",
    "StageResult",
    "TransitionResult",
    "fail_stage",
    "get_status",
    "start_run",
    "submit_stage",
]
