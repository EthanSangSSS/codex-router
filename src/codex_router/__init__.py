"""Minimal Local Sol → Web Sol → Luna router."""

from .pipeline import Router, RouterRunError
from .state import RouterStateError, fail_stage, get_status, start_run, submit_stage
from .types import RunOutcome, StageResult, TransitionResult
from . import luna_control as luna_control
from .luna_control_recovery import install as _install_luna_control_recovery

_install_luna_control_recovery(luna_control)

from .usability import install as _install_router_usability

_install_router_usability()

# cli.py imports adapter callables eagerly; refresh the self-test wrapper whose
# callable identity changes when the active usability layer is installed.
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
