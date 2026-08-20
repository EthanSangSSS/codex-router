"""Minimal Local Sol → Web Sol → Luna router."""

from .pipeline import Router, RouterRunError
from .state import RouterStateError, fail_stage, get_status, start_run, submit_stage
from .types import RunOutcome, StageResult, TransitionResult
from . import luna_control as luna_control
from .luna_control_recovery import install as _install_luna_control_recovery

_install_luna_control_recovery(luna_control)

from .usability_v32 import install as _install_router_usability_v32

_install_router_usability_v32()

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
