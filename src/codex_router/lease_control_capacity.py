"""Bounded V4 session-record reclamation without touching live authority."""
from __future__ import annotations

from pathlib import Path


def install(base) -> None:
    """Replace session initialization with safe idle-record reclamation."""
    if getattr(base, "_V4_SESSION_CAPACITY_INSTALLED", False):
        return

    def initialize_session(
        directory: Path,
        secret: bytes,
        session_id: str,
    ):
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            existing = state["sessions"].get(tag)
            if existing is not None:
                return base._snapshot_from_mapping(existing)

            if len(state["sessions"]) >= base._MAX_SESSIONS:
                idle_tags: list[str] = []
                for candidate_tag, record in state["sessions"].items():
                    snapshot = base._snapshot_from_mapping(record)
                    if (
                        snapshot.active_lease is None
                        and snapshot.current_root_turn_tag is None
                    ):
                        idle_tags.append(candidate_tag)
                if not idle_tags:
                    raise base._error("lease control session capacity is exhausted")

                # Session tags are HMACs, so lexical selection discloses no user
                # identifier. Any fully idle record is authority-free and safe
                # to forget; a resumed conversation receives a fresh task epoch.
                del state["sessions"][sorted(idle_tags)[0]]

            snapshot = base.LeaseSnapshot(
                task_epoch=base._new_task_epoch(),
                root_session_tag=tag,
                generation=0,
                active_lease=None,
                retired_worker_tags=(),
                current_root_turn_tag=None,
            )
            base._store_snapshot(state, snapshot)
            return snapshot

    base.initialize_session = initialize_session
    base._V4_SESSION_CAPACITY_INSTALLED = True
