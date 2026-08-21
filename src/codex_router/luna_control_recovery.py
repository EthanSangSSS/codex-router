"""Narrow V3.1 quarantine and isolated-recovery overlay.

This module extends the existing V3.1 Luna control journal without turning Router
into a process or workspace supervisor. It is installed onto ``luna_control`` at
package import time so the mature journal/locking implementation remains the
single persistence implementation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import hmac
from pathlib import Path
import re
import subprocess
from typing import Any, Literal, Mapping

from .protocol import ProtocolError, parse_luna_packet, verify_k1_stage_capability


_GIT_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40,64}\Z")
_GIT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class RecoveryBaseline:
    workspace_root: str
    head_commit: str
    git_common_dir: str


def _git_text(workspace: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _clean_git_baseline(working_directory: str) -> RecoveryBaseline | None:
    try:
        requested = Path(working_directory)
        if not requested.is_absolute():
            return None
        requested = requested.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not requested.is_dir():
        return None

    root_text = _git_text(requested, "rev-parse", "--show-toplevel")
    if not root_text:
        return None
    try:
        root = Path(root_text).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not root.is_dir():
        return None

    status = _git_text(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status is None or status:
        return None
    head = _git_text(root, "rev-parse", "HEAD")
    if head is None or _GIT_COMMIT_RE.fullmatch(head) is None:
        return None
    common_text = _git_text(root, "rev-parse", "--git-common-dir")
    if not common_text:
        return None
    common = Path(common_text)
    if not common.is_absolute():
        common = root / common
    try:
        common = common.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return RecoveryBaseline(
        workspace_root=str(root),
        head_commit=head.lower(),
        git_common_dir=str(common),
    )


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def install(base) -> None:
    """Install the quarantine extension onto ``codex_router.luna_control`` once."""
    if getattr(base, "_QUARANTINED_RECOVERY_INSTALLED", False):
        return

    OriginalControlSnapshot = base.ControlSnapshot
    original_validate_snapshot = base.validate_snapshot
    original_replacement_reservation = base._replacement_reservation
    original_authorize_parent_target = base.authorize_parent_target
    original_retire_luna = base.retire_luna

    @dataclass(frozen=True)
    class ControlSnapshot(OriginalControlSnapshot):
        recovery_baseline: RecoveryBaseline | None = None
        current_root_turn_tag: str | None = None

    def validate_recovery_baseline(value: RecoveryBaseline) -> None:
        if not isinstance(value, RecoveryBaseline):
            raise base._error("recovery baseline is invalid")
        workspace = base._text(value.workspace_root, "recovery workspace_root")
        common = base._text(value.git_common_dir, "recovery git_common_dir")
        head = base._text(value.head_commit, "recovery head_commit")
        assert workspace is not None and common is not None and head is not None
        if not Path(workspace).is_absolute() or not Path(common).is_absolute():
            raise base._error("recovery baseline paths must be absolute")
        if _GIT_COMMIT_RE.fullmatch(head) is None:
            raise base._error("recovery baseline commit is invalid")

    def validate_snapshot(snapshot: ControlSnapshot) -> None:
        original_validate_snapshot(snapshot)
        baseline = snapshot.recovery_baseline
        if baseline is not None:
            validate_recovery_baseline(baseline)
            if snapshot.active_packet_id is None:
                raise base._error("recovery baseline requires an active packet")
        root_turn_tag = snapshot.current_root_turn_tag
        if root_turn_tag is not None and base._TAG_RE.fullmatch(root_turn_tag) is None:
            raise base._error("current root turn tag is invalid")
        authority_packet_wire = snapshot.authority_packet_wire
        if authority_packet_wire is not None:
            try:
                parse_luna_packet(authority_packet_wire)
            except ProtocolError as error:
                raise base._error(str(error)) from error
        if snapshot.execution_status == "QUARANTINED" and snapshot.active_packet_id is None:
            raise base._error("quarantined execution requires an active packet")

    def snapshot_from_mapping(value: Any) -> ControlSnapshot:
        if not isinstance(value, Mapping):
            raise base._error("control snapshot schema is invalid")
        data = dict(value)
        packet_metadata_fields = {
            "intended_write_scope",
            "explicit_side_effect_authorizations",
        }
        for field in packet_metadata_fields:
            if field not in data:
                data[field] = ()
        if "recovery_baseline" not in data:
            data["recovery_baseline"] = None
        if "current_root_turn_tag" not in data:
            data["current_root_turn_tag"] = None
        if "authority_packet_wire" not in data:
            data["authority_packet_wire"] = None
        if "retired_luna_agent_tags" not in data:
            data["retired_luna_agent_tags"] = ()
        expected_fields = set(ControlSnapshot.__dataclass_fields__)
        if set(data) != expected_fields:
            raise base._error("control snapshot schema is invalid")
        for field in packet_metadata_fields:
            if isinstance(data[field], list):
                data[field] = tuple(data[field])
        if isinstance(data["retired_luna_agent_tags"], list):
            data["retired_luna_agent_tags"] = tuple(
                data["retired_luna_agent_tags"]
            )

        pending = data.get("pending_spawn")
        if pending is not None:
            if not isinstance(pending, Mapping):
                raise base._error("pending spawn schema is invalid")
            pending = dict(pending)
            expected_pending = set(base.SpawnReservation.__dataclass_fields__)
            legacy_pending = expected_pending - {"expected_agent_id"}
            if set(pending) == legacy_pending:
                pending["expected_agent_id"] = None
            elif set(pending) != expected_pending:
                raise base._error("pending spawn schema is invalid")
            try:
                data["pending_spawn"] = base.SpawnReservation(**pending)
            except TypeError as error:
                raise base._error("pending spawn schema is invalid") from error

        baseline = data.get("recovery_baseline")
        if baseline is not None:
            if not isinstance(baseline, Mapping) or set(baseline) != {
                "workspace_root",
                "head_commit",
                "git_common_dir",
            }:
                raise base._error("recovery baseline schema is invalid")
            try:
                data["recovery_baseline"] = RecoveryBaseline(**dict(baseline))
            except TypeError as error:
                raise base._error("recovery baseline schema is invalid") from error

        try:
            snapshot = ControlSnapshot(**data)
        except TypeError as error:
            raise base._error("control snapshot schema is invalid") from error
        validate_snapshot(snapshot)
        return snapshot

    def _root_turn_tag(secret: bytes, turn_id: str) -> str:
        key = base._secret(secret)
        turn = base._text(turn_id, "root turn_id")
        assert turn is not None
        return hmac.new(
            key,
            b"v3.1-root-turn\0" + turn.encode("utf-8", errors="strict"),
            hashlib.sha256,
        ).hexdigest()

    def set_current_root_turn(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        turn_id: str | None,
    ) -> ControlSnapshot:
        turn_tag = None if turn_id is None else _root_turn_tag(secret, turn_id)
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if turn_tag is not None and snapshot.logical_task_status != "ACTIVE":
                raise base._error("only an active task may bind root turn authority")
            unchanged = (
                turn_tag is not None
                and snapshot.current_root_turn_tag is not None
                and hmac.compare_digest(snapshot.current_root_turn_tag, turn_tag)
            )
            if not unchanged and snapshot.active_packet_id is not None and snapshot.active_child_turn_id is None:
                updated = replace(
                    snapshot,
                    current_root_turn_tag=turn_tag,
                    active_packet_id=None,
                    active_child_turn_id=None,
                    authority_packet_wire=None,
                    execution_status="IDLE",
                    intended_write_scope=(),
                    explicit_side_effect_authorizations=(),
                    recovery_baseline=None,
                )
            else:
                updated = replace(
                    snapshot,
                    current_root_turn_tag=turn_tag,
                    authority_packet_wire=(
                        snapshot.authority_packet_wire if unchanged else None
                    ),
                )
            base._store_snapshot(state, updated)
            return updated

    def stage_authority_packet(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        root_turn_id: str,
        capability: str,
        packet_wire: str,
    ) -> ControlSnapshot:
        tag = base.session_tag(secret, session_id)
        expected_root_tag = _root_turn_tag(secret, root_turn_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if snapshot.logical_task_status != "ACTIVE":
                raise base._error("current task cannot stage authority")
            if (
                snapshot.current_root_turn_tag is None
                or not hmac.compare_digest(
                    snapshot.current_root_turn_tag, expected_root_tag
                )
            ):
                raise base._error("staged authority root turn is not current")
            generation = snapshot.packet_generation + 1
            try:
                verify_k1_stage_capability(
                    capability,
                    secret,
                    session_tag=tag,
                    root_turn_tag=snapshot.current_root_turn_tag,
                    task_epoch=snapshot.task_epoch,
                    generation=generation,
                )
                packet = parse_luna_packet(packet_wire)
            except ProtocolError as error:
                raise base._error(str(error)) from error
            if packet["generation"] != generation:
                raise base._error("staged authority generation is not current")
            if snapshot.authority_packet_wire is None:
                updated = replace(snapshot, authority_packet_wire=packet_wire)
                base._store_snapshot(state, updated)
                return updated
            if hmac.compare_digest(snapshot.authority_packet_wire, packet_wire):
                return snapshot
            raise base._error("different staged authority already exists")

    def clear_staged_authority(
        directory: Path, secret: bytes, session_id: str
    ) -> ControlSnapshot:
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if snapshot.authority_packet_wire is None:
                return snapshot
            updated = replace(snapshot, authority_packet_wire=None)
            base._store_snapshot(state, updated)
            return updated

    def authorize_executor_tool(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        agent_id: str,
        child_turn_id: str,
    ) -> tuple[ControlSnapshot, str | None]:
        """Authorize one executor tool and conditionally consume the K1 wire.

        The state read, authority-state check, turn binding, and matching-wire
        clear are one locked journal transition.  The returned string is the
        exact K1 developer context for the first-tool handshake, or ``None``
        once that handshake has already been established.
        """
        child = base._text(child_turn_id, "child_turn_id")
        agent = base._text(agent_id, "agent_id")
        assert child is not None and agent is not None
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            pending = snapshot.pending_spawn
            bound_identity = snapshot.luna_agent_id == agent
            pending_identity = pending is not None and pending.agent_id == agent
            if (
                snapshot.logical_task_status != "ACTIVE"
                or not (bound_identity or pending_identity)
            ):
                raise base._error("executor identity is not currently bound")
            if snapshot.active_packet_id is None:
                raise base._error("Luna tool has no active K1 authority")
            if snapshot.execution_status in {
                "QUIESCING",
                "QUARANTINED",
                "PAUSED_SETTLED",
                "RETIRED",
            }:
                raise base._error("Luna authority is no longer running")
            if snapshot.active_child_turn_id is None:
                if snapshot.execution_status != "IDLE":
                    raise base._error("executor handshake state is invalid")
                if snapshot.authority_packet_wire is None:
                    raise base._error("Luna authority handshake state fails closed")
                updated = replace(
                    snapshot,
                    execution_status="RUNNING",
                    active_child_turn_id=child,
                )
                base._store_snapshot(state, updated)
                return updated, snapshot.authority_packet_wire
            if snapshot.active_child_turn_id != child:
                raise base._error("Luna executor turn does not match current K1 authority")
            if snapshot.execution_status != "RUNNING":
                raise base._error("Luna authority is no longer running")
            if snapshot.authority_packet_wire is None:
                return snapshot, None
            updated = replace(snapshot, authority_packet_wire=None)
            base._store_snapshot(state, updated)
            return updated, None

    def _packet_commit_fields(
        snapshot: ControlSnapshot, packet_wire: str
    ) -> dict[str, Any]:
        if snapshot.logical_task_status != "ACTIVE":
            raise base._error("current task cannot admit staged authority")
        if snapshot.execution_status not in {"IDLE", "PAUSED_SETTLED"}:
            raise base._error("current execution cannot admit staged authority")
        wire = base._authority_packet_wire(packet_wire)
        if wire is None:
            raise base._error("current dispatch has no staged authority")
        try:
            packet = parse_luna_packet(wire)
        except ProtocolError as error:
            raise base._error(str(error)) from error
        if packet["generation"] != snapshot.packet_generation + 1:
            raise base._error("staged authority generation is not current")
        return {
            "packet_generation": packet["generation"],
            "active_packet_id": packet["packet_id"],
            "active_child_turn_id": None,
            "execution_status": "IDLE",
            "intended_write_scope": tuple(packet["intended_write_scope"]),
            "explicit_side_effect_authorizations": tuple(
                packet["explicit_side_effect_authorizations"]
            ),
            "recovery_baseline": _clean_git_baseline(packet["working_directory"]),
        }

    def _commit_staged_packet(snapshot: ControlSnapshot) -> ControlSnapshot:
        wire = snapshot.authority_packet_wire
        if wire is None:
            raise base._error("current dispatch has no staged authority")
        return replace(snapshot, **_packet_commit_fields(snapshot, wire))

    def _require_current_root(snapshot: ControlSnapshot, secret: bytes, root_turn_id: str) -> None:
        expected = _root_turn_tag(secret, root_turn_id)
        if snapshot.current_root_turn_tag is None or not hmac.compare_digest(snapshot.current_root_turn_tag, expected):
            raise base._error("dispatch root turn is not current")

    def admit_staged_spawn(
        directory: Path, secret: bytes, session_id: str, *, root_turn_id: str,
        tool_use_id: str, task_name: str, agent_type: str, fork_turns: str,
    ) -> ControlSnapshot:
        if task_name != "luna_worker" or agent_type != "luna_worker" or fork_turns != "none":
            raise base._error("Luna spawn identity is invalid")
        tool_id = base._text(tool_use_id, "tool_use_id")
        assert tool_id is not None
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            _require_current_root(snapshot, secret, root_turn_id)
            if snapshot.pending_spawn is not None or snapshot.luna_agent_id is not None:
                raise base._error("a Luna spawn is already pending or bound")
            committed = _commit_staged_packet(snapshot)
            generation_luna_epoch = base._new_epoch("luna")
            reservation = base.SpawnReservation(
                task_epoch=committed.task_epoch, luna_epoch=generation_luna_epoch,
                expected_role="luna_worker", root_session_tag=committed.root_session_tag,
                expected_parent=committed.native_parent_identity, tool_use_id=tool_id,
                task_path=None, agent_id=None,
            )
            updated = replace(
                committed,
                luna_epoch=generation_luna_epoch,
                pending_spawn=reservation,
            )
            base._store_snapshot(state, updated)
            return updated

    def admit_staged_followup(
        directory: Path, secret: bytes, session_id: str, *, root_turn_id: str, target: str,
    ) -> ControlSnapshot:
        requested = base._text(target, "target")
        assert requested is not None
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            _require_current_root(snapshot, secret, root_turn_id)
            targets = {snapshot.luna_agent_id} if snapshot.luna_agent_id is not None else set()
            if snapshot.luna_task_path is not None:
                targets.add(snapshot.luna_task_path)
            if not targets or requested not in targets:
                raise base._error("parent lifecycle target is not the current Luna")
            updated = _commit_staged_packet(snapshot)
            base._store_snapshot(state, updated)
            return updated

    def freeze_authority(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        reason: str,
        logical_cancel: bool = False,
    ) -> ControlSnapshot:
        base._text(reason, "reason")
        if not isinstance(logical_cancel, bool):
            raise base._error("logical_cancel is invalid")
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if snapshot.logical_task_status != "ACTIVE":
                raise base._error("only an active task may freeze authority")
            if snapshot.active_packet_id is None:
                raise base._error("authority freeze requires an active packet")
            if snapshot.execution_status == "RETIRED":
                raise base._error("retired execution cannot freeze authority")
            if snapshot.execution_status == "PAUSED_SETTLED":
                raise base._error("settled execution cannot freeze authority")
            if snapshot.execution_status == "QUIESCING":
                if not logical_cancel:
                    return snapshot
                if snapshot.active_child_turn_id is None:
                    updated = replace(
                        snapshot,
                        logical_task_status="CANCELLED",
                        active_packet_id=None,
                        authority_packet_wire=None,
                        execution_status="IDLE",
                        intended_write_scope=(),
                        explicit_side_effect_authorizations=(),
                        recovery_baseline=None,
                    )
                else:
                    updated = replace(
                        snapshot,
                        logical_task_status="CANCELLED",
                        authority_packet_wire=None,
                    )
            else:
                if logical_cancel and snapshot.active_child_turn_id is None:
                    updated = replace(
                        snapshot,
                        logical_task_status="CANCELLED",
                        active_packet_id=None,
                        authority_packet_wire=None,
                        execution_status="IDLE",
                        intended_write_scope=(),
                        explicit_side_effect_authorizations=(),
                        recovery_baseline=None,
                    )
                else:
                    updated = replace(
                        snapshot,
                        logical_task_status=(
                            "CANCELLED"
                            if logical_cancel
                            else snapshot.logical_task_status
                        ),
                        execution_status="QUIESCING",
                        authority_packet_wire=(
                            None if logical_cancel else snapshot.authority_packet_wire
                        ),
                    )
            base._store_snapshot(state, updated)
            return updated

    def retire_luna(
        directory: Path,
        secret: bytes,
        session_id: str,
        reason: Literal[
            "unrecoverable_runtime_identity",
            "new_task_epoch",
            "native_authority_profile_change",
            "runtime_validated_context_reset",
        ],
        *,
        settlement_source: Literal["verified_native_terminal"] | None = None,
        terminal_status: Literal["completed", "failed", "interrupted", "cancelled"]
        | None = None,
        child_turn_id: str | None = None,
    ) -> ControlSnapshot:
        return original_retire_luna(
            directory,
            secret,
            session_id,
            reason,
            settlement_source=settlement_source,
            terminal_status=terminal_status,
            child_turn_id=child_turn_id,
        )

    def is_current_root_turn(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        turn_id: str,
    ) -> bool:
        snapshot = base.read_snapshot(directory, secret, session_id)
        if snapshot is None or snapshot.current_root_turn_tag is None:
            return False
        candidate = _root_turn_tag(secret, turn_id)
        return hmac.compare_digest(snapshot.current_root_turn_tag, candidate)

    def begin_packet(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        packet_id: str,
        objective: str,
        working_directory: str,
        intended_write_scope: list[str] | tuple[str, ...],
        explicit_side_effect_authorizations: list[str] | tuple[str, ...],
        success_criteria: list[str] | tuple[str, ...],
        stop_conditions: list[str] | tuple[str, ...],
    ) -> ControlSnapshot:
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if snapshot.logical_task_status != "ACTIVE":
                raise base._error("current task cannot begin a packet")
            if snapshot.execution_status not in {"IDLE", "PAUSED_SETTLED"}:
                raise base._error("current execution cannot begin a packet")
            generation = snapshot.packet_generation + 1
            try:
                wire = base.build_luna_packet(
                    packet_id=packet_id,
                    generation=generation,
                    objective=objective,
                    working_directory=working_directory,
                    intended_write_scope=base._packet_sequence(
                        intended_write_scope, "intended_write_scope"
                    ),
                    explicit_side_effect_authorizations=base._packet_sequence(
                        explicit_side_effect_authorizations,
                        "explicit_side_effect_authorizations",
                    ),
                    success_criteria=base._packet_sequence(
                        success_criteria, "success_criteria"
                    ),
                    stop_conditions=base._packet_sequence(
                        stop_conditions, "stop_conditions"
                    ),
                )
            except base.ProtocolError as error:
                raise base._error(str(error)) from error
            updated = replace(
                snapshot,
                **_packet_commit_fields(snapshot, wire),
                authority_packet_wire=wire,
            )
            base._store_snapshot(state, updated)
            return updated

    def current_luna(directory: Path, secret: bytes, session_id: str) -> ControlSnapshot:
        snapshot = base.read_snapshot(directory, secret, session_id)
        if (
            snapshot is None
            or snapshot.luna_agent_id is None
            or snapshot.logical_task_status != "ACTIVE"
            or snapshot.execution_status in {"RETIRED", "QUARANTINED"}
        ):
            raise base._error("no Luna is currently bound")
        return snapshot

    def authorize_parent_target(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        tool_name: str,
        target: str,
    ) -> None:
        snapshot = base.read_snapshot(directory, secret, session_id)
        if snapshot is None or snapshot.execution_status != "QUARANTINED":
            return original_authorize_parent_target(
                directory,
                secret,
                session_id,
                tool_name=tool_name,
                target=target,
            )
        tool = base._text(tool_name, "tool_name")
        requested = base._text(target, "target")
        assert tool is not None and requested is not None
        if tool not in base._PARENT_TARGET_TOOLS:
            raise base._error("unsupported Router parent lifecycle operation")
        if tool not in base._PARENT_CLEANUP_TOOLS:
            raise base._error("parent work dispatch is forbidden for quarantined Luna")
        if snapshot.luna_agent_id is None or snapshot.luna_task_path is None:
            raise base._error("quarantined Luna identity is unavailable")
        if requested not in {snapshot.luna_agent_id, snapshot.luna_task_path}:
            raise base._error("parent lifecycle target is not the quarantined Luna")

    def start_execution(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        child_turn_id: str | None,
    ) -> ControlSnapshot:
        child_turn = base._text(child_turn_id, "child_turn_id", optional=True)
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if snapshot.logical_task_status != "ACTIVE":
                raise base._error("current task cannot start execution")
            if snapshot.execution_status in {
                "QUIESCING",
                "QUARANTINED",
                "PAUSED_SETTLED",
                "RETIRED",
            }:
                raise base._error("current execution cannot start")
            if snapshot.active_packet_id is None:
                raise base._error("execution requires an active packet")
            if (
                snapshot.active_child_turn_id is not None
                and child_turn is not None
                and snapshot.active_child_turn_id != child_turn
            ):
                raise base._error("execution child turn conflicts with the current packet")
            baseline = snapshot.recovery_baseline
            if baseline is not None:
                current_baseline = _clean_git_baseline(baseline.workspace_root)
                if current_baseline != baseline:
                    baseline = None
            updated = replace(
                snapshot,
                execution_status="RUNNING",
                active_child_turn_id=(
                    snapshot.active_child_turn_id
                    if child_turn is None
                    else child_turn
                ),
                recovery_baseline=baseline,
            )
            base._store_snapshot(state, updated)
            return updated

    def accept_result(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        generation: int,
        child_turn_id: str | None,
    ) -> Literal["CURRENT", "STALE"]:
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
        ):
            raise base._error("generation is invalid")
        child_turn = base._text(child_turn_id, "child_turn_id", optional=True)
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if generation != snapshot.packet_generation:
                return "STALE"
            if snapshot.active_packet_id is None:
                return "STALE"
            if snapshot.execution_status in {
                "QUIESCING",
                "QUARANTINED",
                "PAUSED_SETTLED",
                "RETIRED",
            }:
                return "STALE"
            if snapshot.active_child_turn_id != child_turn:
                return "STALE"
            updated = replace(
                snapshot,
                luna_agent_id=None,
                luna_task_path=None,
                pending_spawn=None,
                active_packet_id=None,
                active_child_turn_id=None,
                authority_packet_wire=None,
                execution_status="IDLE",
                intended_write_scope=(),
                explicit_side_effect_authorizations=(),
                recovery_baseline=None,
                retired_luna_agent_tags=base._remember_retired_luna_agent(
                    snapshot, secret
                ),
            )
            base._store_snapshot(state, updated)
            return "CURRENT"

    def observe_turn_boundary(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        child_turn_id: str,
    ) -> Literal["CURRENT", "STALE"]:
        child_turn = base._text(child_turn_id, "child_turn_id")
        assert child_turn is not None
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if snapshot.active_packet_id is None:
                return "STALE"
            if snapshot.execution_status in {
                "QUARANTINED",
                "PAUSED_SETTLED",
                "RETIRED",
            }:
                return "STALE"
            if (
                snapshot.active_child_turn_id is not None
                and snapshot.active_child_turn_id != child_turn
            ):
                raise base._error(
                    "turn boundary child turn conflicts with the current packet"
                )
            if snapshot.execution_status == "QUIESCING":
                if snapshot.active_child_turn_id is None:
                    raise base._error(
                        "quiescing turn boundary requires the active child turn"
                    )
                updated = replace(
                    snapshot,
                    luna_agent_id=None,
                    luna_task_path=None,
                    pending_spawn=None,
                    execution_status="PAUSED_SETTLED",
                    retired_luna_agent_tags=base._remember_retired_luna_agent(
                        snapshot, secret
                    ),
                )
            elif snapshot.execution_status in {"IDLE", "RUNNING"}:
                updated = replace(
                    snapshot,
                    luna_agent_id=None,
                    luna_task_path=None,
                    pending_spawn=None,
                    active_packet_id=None,
                    active_child_turn_id=None,
                    authority_packet_wire=None,
                    execution_status="IDLE",
                    intended_write_scope=(),
                    explicit_side_effect_authorizations=(),
                    recovery_baseline=None,
                    retired_luna_agent_tags=base._remember_retired_luna_agent(
                        snapshot, secret
                    ),
                )
            else:
                return "STALE"
            base._store_snapshot(state, updated)
            return "CURRENT"

    def quarantine_execution(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        reason: str,
    ) -> ControlSnapshot:
        base._text(reason, "reason")
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if snapshot.execution_status == "QUARANTINED":
                return snapshot
            if snapshot.execution_status != "QUIESCING":
                raise base._error("quarantine requires quiescing execution")
            if snapshot.active_packet_id is None:
                raise base._error("quarantine requires an active packet")
            updated = replace(snapshot, execution_status="QUARANTINED")
            base._store_snapshot(state, updated)
            return updated

    def observe_settlement(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        source: Literal["verified_native_terminal"],
        terminal_status: str,
        child_turn_id: str | None,
    ) -> ControlSnapshot:
        if source != base._SETTLEMENT_SOURCE:
            raise base._error("settlement source is not verified")
        if terminal_status not in base._TERMINAL_STATUSES:
            raise base._error("terminal status is invalid")
        child_turn = base._text(child_turn_id, "child_turn_id", optional=True)
        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            snapshot = base._record_for_session(state, tag)
            if snapshot.execution_status not in {"QUIESCING", "QUARANTINED"}:
                raise base._error("settlement requires quiescing execution")
            if snapshot.active_packet_id is None:
                raise base._error("settlement requires an active packet")
            if snapshot.active_child_turn_id != child_turn:
                raise base._error("settlement child turn does not match the frozen packet")
            updated = replace(snapshot, execution_status="PAUSED_SETTLED")
            base._store_snapshot(state, updated)
            return updated

    def replace_quarantined_luna_epoch(
        directory: Path,
        secret: bytes,
        session_id: str,
        *,
        replacement_workspace: str,
        native_parent_identity: str,
        native_authority_profile: str,
        tool_use_id: str | None = None,
        expected_agent_id: str | None = None,
    ) -> ControlSnapshot:
        parent = base._text(native_parent_identity, "native_parent_identity")
        profile = base._text(native_authority_profile, "native_authority_profile")
        workspace_text = base._text(replacement_workspace, "replacement_workspace")
        tool_id = base._text(tool_use_id, "tool_use_id", optional=True)
        expected_id = base._text(expected_agent_id, "expected_agent_id", optional=True)
        assert parent is not None and profile is not None and workspace_text is not None
        candidate = _clean_git_baseline(workspace_text)
        if candidate is None:
            raise base._error("replacement workspace is not a clean Git baseline")
        try:
            requested_workspace = Path(workspace_text).resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise base._error("replacement workspace is unavailable") from error
        if requested_workspace != Path(candidate.workspace_root):
            raise base._error("replacement workspace must be the repository root")

        tag = base.session_tag(secret, session_id)
        with base._locked_state(Path(directory), mutate=True) as state:
            previous = base._record_for_session(state, tag)
            if (
                previous.logical_task_status != "ACTIVE"
                or previous.execution_status != "QUARANTINED"
            ):
                raise base._error("isolated recovery requires an active quarantined task")
            if previous.luna_agent_id is None or previous.luna_task_path is None:
                raise base._error("isolated recovery requires a bound quarantined Luna")
            if previous.pending_spawn is not None:
                raise base._error("isolated recovery cannot overlap a pending spawn")
            baseline = previous.recovery_baseline
            if baseline is None:
                raise base._error("isolated recovery requires a clean Git baseline")
            if previous.explicit_side_effect_authorizations:
                raise base._error("isolated recovery is blocked by unresolved A1 authority")
            if parent != previous.native_parent_identity:
                raise base._error("replacement parent identity does not match the task epoch")
            if profile == previous.native_authority_profile:
                raise base._error("isolated recovery requires a fresh authority profile")

            old_root = Path(baseline.workspace_root)
            new_root = Path(candidate.workspace_root)
            if _paths_overlap(old_root, new_root):
                raise base._error("replacement workspace overlaps the quarantined workspace")
            if candidate.git_common_dir == baseline.git_common_dir:
                raise base._error("linked worktree is not an isolated recovery repository")
            if candidate.head_commit != baseline.head_commit:
                raise base._error("replacement workspace does not match the recovery baseline")

            luna_epoch = base._new_epoch("luna")
            pending = original_replacement_reservation(
                task_epoch=previous.task_epoch,
                luna_epoch=luna_epoch,
                root_session_tag=tag,
                parent=parent,
                tool_id=tool_id,
                expected_id=expected_id,
            )
            replacement_snapshot = ControlSnapshot(
                task_epoch=previous.task_epoch,
                luna_epoch=luna_epoch,
                root_session_tag=tag,
                native_parent_identity=parent,
                native_authority_profile=profile,
                luna_agent_id=None,
                luna_task_path=None,
                packet_generation=previous.packet_generation,
                active_packet_id=None,
                active_child_turn_id=None,
                logical_task_status="ACTIVE",
                execution_status="IDLE",
                pending_spawn=pending,
                intended_write_scope=(),
                explicit_side_effect_authorizations=(),
                recovery_baseline=None,
                current_root_turn_tag=previous.current_root_turn_tag,
                authority_packet_wire=None,
                retired_luna_agent_tags=base._remember_retired_luna_agent(
                    previous, secret
                ),
            )
            base._store_snapshot(state, replacement_snapshot)
            return replacement_snapshot

    base.RecoveryBaseline = RecoveryBaseline
    base.ControlSnapshot = ControlSnapshot
    base.ExecutionStatus = Literal[
        "IDLE",
        "RUNNING",
        "QUIESCING",
        "QUARANTINED",
        "PAUSED_SETTLED",
        "RETIRED",
    ]
    base._EXECUTION_STATUSES = {
        "IDLE",
        "RUNNING",
        "QUIESCING",
        "QUARANTINED",
        "PAUSED_SETTLED",
        "RETIRED",
    }
    base._TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
    base._SNAPSHOT_FIELDS = frozenset(ControlSnapshot.__dataclass_fields__)
    base.validate_snapshot = validate_snapshot
    base._snapshot_from_mapping = snapshot_from_mapping
    base.set_current_root_turn = set_current_root_turn
    base.is_current_root_turn = is_current_root_turn
    base.stage_authority_packet = stage_authority_packet
    base.clear_staged_authority = clear_staged_authority
    base.authorize_executor_tool = authorize_executor_tool
    base._packet_commit_fields = _packet_commit_fields
    base.admit_staged_spawn = admit_staged_spawn
    base.admit_staged_followup = admit_staged_followup
    base.begin_packet = begin_packet
    base.current_luna = current_luna
    base.authorize_parent_target = authorize_parent_target
    base.start_execution = start_execution
    base.accept_result = accept_result
    base.observe_turn_boundary = observe_turn_boundary
    base.quarantine_execution = quarantine_execution
    base.observe_settlement = observe_settlement
    base.replace_quarantined_luna_epoch = replace_quarantined_luna_epoch
    base.freeze_authority = freeze_authority
    base.retire_luna = retire_luna
    base._QUARANTINED_RECOVERY_INSTALLED = True
