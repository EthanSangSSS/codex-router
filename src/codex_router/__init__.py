"""Minimal Local Sol → Web Sol → Luna router."""

from .pipeline import Router, RouterRunError
from .state import RouterStateError, fail_stage, get_status, start_run, submit_stage
from .types import RunOutcome, StageResult, TransitionResult
from . import luna_control as luna_control
from .luna_control_recovery import install as _install_luna_control_recovery

_install_luna_control_recovery(luna_control)

from .usability_v32 import install as _install_router_usability_v32

_install_router_usability_v32()

from .usability_v32_integration import install as _install_router_usability_v32_integration

_install_router_usability_v32_integration()

# cli.py imports adapter callables eagerly; refresh the one V3.2 wrapper whose
# callable identity changes after the compatibility integration is installed.
from . import cli as _cli
from . import global_install_adapter as _global_install_adapter

_cli.global_self_test = _global_install_adapter.global_self_test

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
