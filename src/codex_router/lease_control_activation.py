"""Safe installation-level activation for the V4 lease journal.

Activation creates only an empty V4 authority journal. It never imports,
translates, deletes, or rewrites V3 authority state.
"""
from __future__ import annotations

import os
from pathlib import Path


_INSTALLED = False


def install(base) -> None:
    """Attach ``activate_installation`` to ``lease_control`` once."""
    global _INSTALLED
    if _INSTALLED:
        return

    def activate_installation(directory: Path) -> Path:
        """Create or validate the empty V4 journal without overwriting state.

        Existing valid V4 state is accepted unchanged. Existing symlink,
        malformed, unsafe, or corrupt state fails closed through the normal
        lease journal validation path.
        """
        directory = Path(directory)
        journal = directory / base._STATE

        # Preserve strong path semantics even before the journal exists.
        base._validate_directory(directory)
        existed_before = os.path.lexists(journal)

        # _locked_state validates the lock plus any existing journal. If an
        # unsafe/corrupt journal exists this raises before entering the body,
        # so activation can never replace it with a fresh empty journal.
        with base._locked_state(directory, mutate=True) as state:
            if existed_before:
                # Successful entry proves the existing journal is valid.
                return journal

            # The empty state is byte-equal to the context manager's initial
            # state, so an explicit write is required for first activation.
            # Use the journal's existing atomic write/fsync implementation.
            base._write_state_unlocked(directory, state)

        return journal

    base.activate_installation = activate_installation
    base._V4_INSTALLATION_ACTIVATION_INSTALLED = True
    _INSTALLED = True
