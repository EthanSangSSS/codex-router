"""Narrow V3.1 quarantine and isolated-recovery overlay.

This module extends the existing V3.1 Luna control journal without turning Router
into a process or workspace supervisor. It is installed onto ``luna_control`` at
package import time so the mature journal/locking implementation remains the
single persistence implementation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import re
import subprocess
from typing import Any, Literal, Mapping


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

    @dataclass(frozen=True)
    class ControlSnapshot(OriginalControlSnapshot):
        recovery_baseline: RecoveryBaseline | None = None

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
        expected_fields = set(ControlSnapshot.__dataclass_fields__)
        if set(data) != expected_fields:
            raise base._error("control snapshot schema is invalid")
        for field in packet_metadata_fields:
            if isinstance(data[field], list):
                data[field] = tuple(data[field])

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
        baseline = _clean_git_baseline(working_directory)
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
                packet = base.parse_luna_packet(wire)
            except base.ProtocolError as error:
                raise base._error(str(error)) from error
            updated = replace(
                snapshot,
                packet_generation=packet["generation"],
                active_packet_id=packet["packet_id"],
                active_child_turn_id=None,
                execution_status="IDLE",
                intended_write_scope=tuple(packet["intended_write_scope"]),
                explicit_side_effect_authorizations=tuple(
                    packet["explicit_side_effect_authorizations"]
                ),
                recovery_baseline=baseline,
            )
            base._store_snapshot(state, updated)
            return updated

    def current_luna(directory: Path, secret: bytes, session_id: str) -> ControlSnapshot:
        snapshot = base.read_snapshot(directory, secret, session_id)
        if (
            snapshot is None
            or snapshot.luna_agent_id is None
            or snapshot.luna_task_path is None
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
                active_packet_id=None,
                active_child_turn_id=None,
                execution_status="IDLE",
                intended_write_scope=(),
                explicit_side_effect_authorizations=(),
                recovery_baseline=None,
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
                updated = replace(snapshot, execution_status="PAUSED_SETTLED")
            elif snapshot.execution_status in {"IDLE", "RUNNING"}:
                updated = replace(
                    snapshot,
                    active_packet_id=None,
                    active_child_turn_id=None,
                    execution_status="IDLE",
                    intended_write_scope=(),
                    explicit_side_effect_authorizations=(),
                    recovery_baseline=None,
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
    base.begin_packet = begin_packet
    base.current_luna = current_luna
    base.authorize_parent_target = authorize_parent_target
    base.start_execution = start_execution
    base.accept_result = accept_result
    base.observe_turn_boundary = observe_turn_boundary
    base.quarantine_execution = quarantine_execution
    base.observe_settlement = observe_settlement
    base.replace_quarantined_luna_epoch = replace_quarantined_luna_epoch
    base._QUARANTINED_RECOVERY_INSTALLED = True