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
from .lease_control_capacity import install as _install_v4_session_capacity

_install_v4_activation(lease_control)
_install_v4_terminal_reconciliation(lease_control)
_install_v4_session_capacity(lease_control)

# V4 lease fencing is an intentionally narrow Hook overlay installed after the
# mature V3.3 usability layer. Sessions without V4 state continue through V3.
from . import hook as _hook
from .v4_hook import install as _install_v4_hook
from .v4_terminal_hook import install as _install_v4_terminal_hook

_install_v4_hook(_hook)
_install_v4_terminal_hook(_hook)

# Patch the installer adapter. The V3.3 usability installer imports cli.py
# eagerly, so cli may already have copied pre-V4 function objects into module
# globals before this point. Refresh those bindings after all V4 Hook overlays
# are installed; otherwise fresh ``python -m codex_router`` Hook subprocesses
# can dispatch an earlier handler while in-process hook calls use the final one.
from . import global_install as _global_install_core
from .v4_hook_code_identity_preflight import (
    install as _install_v4_hook_code_identity_preflight,
)
from . import global_install_adapter as _global_install_adapter
from .v4_install_adapter import install as _install_v4_global_install

_install_v4_hook_code_identity_preflight(_global_install_core, lease_control)
_install_v4_global_install(
    _global_install_adapter,
    _global_install_core,
    lease_control,
)

from . import cli as _cli
from .v4_cli import install as _install_v4_cli
from .v4_request_staging import install as _install_v4_request_staging

_cli.global_install = _global_install_adapter.global_install
_cli.global_status = _global_install_adapter.global_status
_cli.global_uninstall = _global_install_adapter.global_uninstall
_cli.global_self_test = _global_install_adapter.global_self_test
_install_v4_cli(_cli)
_install_v4_request_staging(_hook, _cli)
_cli.handle_hook_event = _hook.handle_hook_event

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
