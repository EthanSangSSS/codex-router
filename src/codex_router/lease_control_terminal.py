"""Exact, optional terminal reconciliation for V4 generation leases.

This extension deliberately does not make native terminal notification a
prerequisite for authority revocation or for admitting generation N+1.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal


TerminalDisposition = Literal["CURRENT", "STALE", "NOOP"]


def install(base) -> None:
    """Add exact SubagentStop reconciliation to ``lease_control`` once."""
    if getattr(base, "_V4_TERMINAL_RECONCILIATION_INSTALLED", False):
        return

    def observe_subagent_stop(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        agent_id: str,
        agent_type: str,
        child_turn_id: str,
    ):
        """Close only the exact currently bound lease; stale stops are no-ops."""
        agent = base._text(agent_id, "SubagentStop agent_id")
        role = base._text(agent_type, "SubagentStop agent_type")
        child = base._text(child_turn_id, "SubagentStop child_turn_id")
        assert agent is not None and role is not None and child is not None
        if role != "luna_worker":
            raise base._error("SubagentStop agent_type must be luna_worker")

        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            lease = snapshot.active_lease
            if lease is None:
                return snapshot, "NOOP"

            # SubagentStop cannot establish identity. A staged/unbound lease has
            # no exact native actor to reconcile and therefore remains current.
            if lease.status == "STAGED":
                if lease.worker_agent_id is not None or lease.child_turn_id is not None:
                    raise base._error("staged V4 lease has inconsistent worker identity")
                return snapshot, "STALE"

            if lease.status != "ACTIVE":
                raise base._error("current V4 lease status is invalid")
            if lease.worker_agent_id is None or lease.child_turn_id is None:
                raise base._error("active V4 lease worker identity is incomplete")

            if lease.worker_agent_id != agent or lease.child_turn_id != child:
                return snapshot, "STALE"

            updated = replace(snapshot, active_lease=None)
            base._store_snapshot(state, updated)
            return updated, "CURRENT"

    base.observe_subagent_stop = observe_subagent_stop
    base._V4_TERMINAL_RECONCILIATION_INSTALLED = True
