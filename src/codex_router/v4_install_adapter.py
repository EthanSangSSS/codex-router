"""V4 activation overlay for the managed global installer."""
from __future__ import annotations

from pathlib import Path
from typing import Any


_INSTALLED = False


def install(adapter_module: Any, core_module: Any, lease_control: Any) -> None:
    """Activate a safe V4 journal after every successful install/refresh."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_global_install = adapter_module.global_install

    def global_install(*args, **kwargs):
        codex_home = kwargs.get("codex_home", args[0] if args else None)
        status = original_global_install(*args, **kwargs)
        if codex_home is None:
            # The core installer owns argument validation; a successful return
            # without codex_home would violate its contract, so fail closed.
            raise ValueError("successful global install did not identify codex_home")
        managed = Path(codex_home).expanduser() / core_module.INSTALL_DIRECTORY_NAME
        lease_control.activate_installation(managed)
        return status

    adapter_module.global_install = global_install
    _INSTALLED = True
