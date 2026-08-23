"""Minimal Local Sol → Web Sol → Luna router."""

from .pipeline import Router, RouterRunError
from .state import RouterStateError, fail_stage, get_status, start_run, submit_stage
from .types import RunOutcome, StageResult, TransitionResult
from . import luna_control as luna_control
from .luna_control_recovery import install as _install_luna_control_recovery

_install_luna_control_recovery(luna_control)

from .usability import install as _install_router_usability

_install_router_usability()

# V4 authority extensions install on the dedicated lease-control module. Native
# terminal notification is optional reconciliation evidence, never an admission
# prerequisite for the next generation. Installation activation only creates or
# validates an empty/valid V4 journal and never imports V3 authority.
from . import lease_control as lease_control
from .lease_control_activation import install as _install_v4_activation
from .lease_control_terminal import install as _install_v4_terminal_reconciliation

_install_v4_activation(lease_control)
_install_v4_terminal_reconciliation(lease_control)

# V4 lease fencing is an intentionally narrow Hook overlay installed after the
# mature V3.3 usability layer. Sessions without V4 state continue through V3.
from . import hook as _hook
from .v4_hook import install as _install_v4_hook
from .v4_terminal_hook import install as _install_v4_terminal_hook

_install_v4_hook(_hook)
_install_v4_terminal_hook(_hook)

# cli.py imports adapter callables eagerly; refresh wrappers whose callable
# identity changes when the active overlays are installed.
from . import cli as _cli
from . import global_install_adapter as _global_install_adapter
from .v4_cli import install as _install_v4_cli

_install_v4_cli(_cli)
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
