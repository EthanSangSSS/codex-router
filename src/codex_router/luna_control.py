"""Durable V3.1 persistent-Luna control state."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Iterator, Literal, Mapping
import uuid

from .protocol import ProtocolError, build_luna_packet, parse_luna_packet
from .state import RouterStateError


PROTOCOL = "codex-router/luna-control/v3.1"
_STATE = "luna-control-v3-1.json"
_LOCK = "luna-control-v3-1.lock"
_MAX_SESSIONS = 64
_MAX_STATE_BYTES = 256 * 1024
_EPOCH_RE = re.compile(r"(?:task|luna)-[0-9a-f]{32}\Z")
_TAG_RE = re.compile(r"[0-9a-f]{64}\Z")

TaskStatus = Literal["ACTIVE", "COMPLETED", "CANCELLED"]
ExecutionStatus = Literal["IDLE", "RUNNING", "QUIESCING", "PAUSED_SETTLED", "RETIRED"]
_TASK_STATUSES = {"ACTIVE", "COMPLETED", "CANCELLED"}
_EXECUTION_STATUSES = {"IDLE", "RUNNING", "QUIESCING", "PAUSED_SETTLED", "RETIRED"}
_TERMINAL_STATUSES = {"completed", "failed", "interrupted", "cancelled"}
_SETTLEMENT_SOURCE = "verified_native_terminal"
_RETIRE_REASONS = {
    "unrecoverable_runtime_identity",
    "new_task_epoch",
    "native_authority_profile_change",
    "runtime_validated_context_reset",
}
_LUNA_REPLACEMENT_REASONS = _RETIRE_REASONS - {"new_task_epoch"}


@dataclass(frozen=True)
class SpawnReservation:
    task_epoch: str
    luna_epoch: str
    expected_role: str
    root_session_tag: str
    expected_parent: str
    tool_use_id: str
    task_path: str | None
    agent_id: str | None
    expected_agent_id: str | None = None


@dataclass(frozen=True)
class ControlSnapshot:
    task_epoch: str
    luna_epoch: str
    root_session_tag: str
    native_parent_identity: str
    native_authority_profile: str
    luna_agent_id: str | None
    luna_task_path: str | None
    packet_generation: int
    active_packet_id: str | None
    active_child_turn_id: str | None
    logical_task_status: TaskStatus
    execution_status: ExecutionStatus
    authority_packet_wire: str | None = None
    pending_spawn: SpawnReservation | None = None
    intended_write_scope: tuple[str, ...] = ()
    explicit_side_effect_authorizations: tuple[str, ...] = ()

    @property
    def active_intended_write_scope(self) -> tuple[str, ...]:
        return self.intended_write_scope

    @property
    def active_explicit_side_effect_authorizations(self) -> tuple[str, ...]:
        return self.explicit_side_effect_authorizations


_SNAPSHOT_FIELDS = frozenset(ControlSnapshot.__dataclass_fields__)


def _error(message: str) -> RouterStateError:
    return RouterStateError("conflict", message)


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
        raise _error(f"{field} is invalid")
    return value


def _text_sequence(value: Any, field: str, *, unique: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _error(f"{field} is invalid")
    result = tuple(_text(item, f"{field} entry") for item in value)
    if unique and len(result) != len(set(result)):
        raise _error(f"{field} entries must be unique")
    return result


def _secret(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise _error("installation secret is invalid")
    return value


def session_tag(secret: bytes, session_id: str) -> str:
    key = _secret(secret)
    session = _text(session_id, "session_id")
    assert session is not None
    return hmac.new(
        key,
        b"v3.1-session\0" + session.encode("utf-8", errors="strict"),
        hashlib.sha256,
    ).hexdigest()


def _new_epoch(kind: Literal["task", "luna"]) -> str:
    return f"{kind}-{uuid.uuid4().hex}"


def validate_snapshot(snapshot: ControlSnapshot) -> None:
    if not isinstance(snapshot, ControlSnapshot):
        raise _error("control snapshot type is invalid")
    if (
        _EPOCH_RE.fullmatch(snapshot.task_epoch) is None
        or not snapshot.task_epoch.startswith("task-")
    ):
        raise _error("task_epoch is invalid")
    if (
        _EPOCH_RE.fullmatch(snapshot.luna_epoch) is None
        or not snapshot.luna_epoch.startswith("luna-")
    ):
        raise _error("luna_epoch is invalid")
    if _TAG_RE.fullmatch(snapshot.root_session_tag) is None:
        raise _error("root_session_tag is invalid")
    _text(snapshot.native_parent_identity, "native_parent_identity")
    _text(snapshot.native_authority_profile, "native_authority_profile")
    luna_agent_id = _text(snapshot.luna_agent_id, "luna_agent_id", optional=True)
    luna_task_path = _text(snapshot.luna_task_path, "luna_task_path", optional=True)
    packet_id = _text(snapshot.active_packet_id, "active_packet_id", optional=True)
    child_turn = _text(
        snapshot.active_child_turn_id, "active_child_turn_id", optional=True
    )
    authority_packet_wire = _text(
        snapshot.authority_packet_wire, "authority_packet_wire", optional=True
    )
    if (luna_agent_id is None) != (luna_task_path is None):
        raise _error("Luna identity and task path must be bound together")
    if (
        not isinstance(snapshot.packet_generation, int)
        or isinstance(snapshot.packet_generation, bool)
        or snapshot.packet_generation < 0
    ):
        raise _error("packet_generation is invalid")
    if snapshot.logical_task_status not in _TASK_STATUSES:
        raise _error("logical_task_status is invalid")
    if snapshot.execution_status not in _EXECUTION_STATUSES:
        raise _error("execution_status is invalid")
    intended_write_scope = _text_sequence(
        snapshot.intended_write_scope,
        "intended_write_scope",
        unique=True,
    )
    explicit_side_effect_authorizations = _text_sequence(
        snapshot.explicit_side_effect_authorizations,
        "explicit_side_effect_authorizations",
    )
    if packet_id is None and (
        intended_write_scope or explicit_side_effect_authorizations
    ):
        raise _error("packet metadata requires an active packet")
    if (
        snapshot.logical_task_status == "ACTIVE"
        and snapshot.execution_status == "RETIRED"
        and luna_agent_id is None
    ):
        raise _error("active task may retire only a bound Luna epoch")
    if snapshot.execution_status in {"RUNNING", "QUIESCING"} and packet_id is None:
        raise _error("running or quiescing execution requires an active packet")
    if snapshot.execution_status == "IDLE" and child_turn is not None:
        raise _error("idle execution cannot retain active execution identity")
    if snapshot.execution_status == "PAUSED_SETTLED" and packet_id is None:
        raise _error("settled execution requires the retired packet identity")
    if snapshot.execution_status == "RETIRED" and (
        packet_id is not None
        or child_turn is not None
        or intended_write_scope
        or explicit_side_effect_authorizations
    ):
        raise _error("retired execution cannot retain active execution identity")
    if child_turn is not None and packet_id is None:
        raise _error("active child turn requires an active packet")
    if (
        packet_id is not None
        and child_turn is None
        and authority_packet_wire is None
    ):
        raise _error(
            "active packet without child turn requires staged authority wire"
        )
    if authority_packet_wire is not None:
        try:
            parse_luna_packet(authority_packet_wire)
        except ProtocolError as error:
            raise _error(str(error)) from error
    if snapshot.packet_generation == 0 and (
        packet_id is not None
        or intended_write_scope
        or explicit_side_effect_authorizations
    ):
        raise _error("generation zero cannot have an active packet")
    pending = snapshot.pending_spawn
    if pending is not None:
        if not isinstance(pending, SpawnReservation):
            raise _error("pending spawn is invalid")
        if (
            pending.task_epoch != snapshot.task_epoch
            or pending.luna_epoch != snapshot.luna_epoch
            or pending.root_session_tag != snapshot.root_session_tag
            or pending.expected_parent != snapshot.native_parent_identity
            or pending.expected_role != "luna_worker"
        ):
            raise _error("pending spawn identity is inconsistent")
        _text(pending.tool_use_id, "tool_use_id")
        pending_path = _text(pending.task_path, "task_path", optional=True)
        _text(pending.agent_id, "agent_id", optional=True)
        _text(pending.expected_agent_id, "expected_agent_id", optional=True)
        if pending_path is not None and pending_path != "/root/luna_worker":
            raise _error("pending spawn task path is invalid")
        if pending.task_path is not None and pending.agent_id is not None:
            raise _error("fully observed spawn must be bound, not pending")
        if snapshot.luna_agent_id is not None:
            raise _error("bound Luna cannot retain a pending spawn")


def _snapshot_from_mapping(value: Any) -> ControlSnapshot:
    if not isinstance(value, Mapping):
        raise _error("control snapshot schema is invalid")
    data = dict(value)
    if "authority_packet_wire" not in data:
        data["authority_packet_wire"] = None
    packet_metadata_fields = {
        "intended_write_scope",
        "explicit_side_effect_authorizations",
    }
    if set(data) == _SNAPSHOT_FIELDS - packet_metadata_fields:
        data.update({field: () for field in packet_metadata_fields})
    elif set(data) != _SNAPSHOT_FIELDS:
        raise _error("control snapshot schema is invalid")
    for field in packet_metadata_fields:
        if isinstance(data[field], list):
            data[field] = tuple(data[field])
    pending = data.get("pending_spawn")
    if pending is not None:
        if not isinstance(pending, Mapping):
            raise _error("pending spawn schema is invalid")
        pending = dict(pending)
        expected_fields = set(SpawnReservation.__dataclass_fields__)
        legacy_fields = expected_fields - {"expected_agent_id"}
        if set(pending) == legacy_fields:
            pending["expected_agent_id"] = None
        elif set(pending) != expected_fields:
            raise _error("pending spawn schema is invalid")
        try:
            data["pending_spawn"] = SpawnReservation(**pending)
        except TypeError as exc:
            raise _error("pending spawn schema is invalid") from exc
    try:
        snapshot = ControlSnapshot(**data)
    except TypeError as exc:
        raise _error("control snapshot schema is invalid") from exc
    validate_snapshot(snapshot)
    return snapshot


def _empty_state() -> dict[str, Any]:
    return {"protocol": PROTOCOL, "sessions": {}}


def _validate_state(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"protocol", "sessions"}
        or value.get("protocol") != PROTOCOL
        or not isinstance(value.get("sessions"), dict)
        or len(value["sessions"]) > _MAX_SESSIONS
    ):
        raise _error("Luna control journal schema is invalid")
    for key, record in value["sessions"].items():
        if not isinstance(key, str) or _TAG_RE.fullmatch(key) is None:
            raise _error("Luna control session key is invalid")
        snapshot = _snapshot_from_mapping(record)
        if snapshot.root_session_tag != key:
            raise _error("Luna control session tag is inconsistent")
    return value


def _validate_directory(directory: Path) -> None:
    try:
        metadata = directory.lstat()
    except OSError as exc:
        raise _error("Luna control directory is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise _error("Luna control directory is unsafe")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_state_unlocked(directory: Path) -> dict[str, Any]:
    path = directory / _STATE
    if not os.path.lexists(path):
        return _empty_state()
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise _error("Luna control journal is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > _MAX_STATE_BYTES
    ):
        raise _error("Luna control journal is unsafe")
    try:
        raw = path.read_bytes()
        if len(raw) > _MAX_STATE_BYTES:
            raise _error("Luna control journal exceeds the size limit")
        value = json.loads(raw)
    except RouterStateError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("Luna control journal is unreadable") from exc
    return _validate_state(value)


def _canonical_state_bytes(state: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(state),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
        + b"\n"
    )


def _write_state_unlocked(directory: Path, state: Mapping[str, Any]) -> None:
    validated = _validate_state(dict(state))
    content = _canonical_state_bytes(validated)
    if len(content) > _MAX_STATE_BYTES:
        raise _error("Luna control journal exceeds the size limit")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".luna-control-v3-1.", dir=directory
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / _STATE)
        os.chmod(directory / _STATE, 0o600)
        _fsync_directory(directory)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _locked_state(directory: Path, *, mutate: bool) -> Iterator[dict[str, Any]]:
    _validate_directory(directory)
    lock_path = directory / _LOCK
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise _error("Luna control lock is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise _error("Luna control lock is unsafe")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX if mutate else fcntl.LOCK_SH)
        state = _read_state_unlocked(directory)
        before = _canonical_state_bytes(state)
        yield state
        if mutate and _canonical_state_bytes(state) != before:
            _write_state_unlocked(directory, state)
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _reclaim_terminal_session(sessions: dict[str, Any]) -> bool:
    candidates: list[str] = []
    for key, record in sessions.items():
        snapshot = _snapshot_from_mapping(record)
        if (
            snapshot.logical_task_status in {"CANCELLED", "COMPLETED"}
            and snapshot.execution_status == "RETIRED"
            and snapshot.pending_spawn is None
        ):
            candidates.append(key)
    if not candidates:
        return False
    del sessions[min(candidates)]
    return True


def new_task(
    directory: Path,
    secret: bytes,
    session_id: str,
    native_parent_identity: str,
    native_authority_profile: str,
) -> ControlSnapshot:
    directory = Path(directory)
    tag = session_tag(secret, session_id)
    parent = _text(native_parent_identity, "native_parent_identity")
    profile = _text(native_authority_profile, "native_authority_profile")
    assert parent is not None and profile is not None
    snapshot = ControlSnapshot(
        task_epoch=_new_epoch("task"),
        luna_epoch=_new_epoch("luna"),
        root_session_tag=tag,
        native_parent_identity=parent,
        native_authority_profile=profile,
        luna_agent_id=None,
        luna_task_path=None,
        packet_generation=0,
        active_packet_id=None,
        active_child_turn_id=None,
        logical_task_status="ACTIVE",
        execution_status="IDLE",
        pending_spawn=None,
    )
    validate_snapshot(snapshot)
    with _locked_state(directory, mutate=True) as state:
        sessions = state["sessions"]
        if tag in sessions:
            raise _error("a task epoch already exists for this session")
        if len(sessions) >= _MAX_SESSIONS and not _reclaim_terminal_session(sessions):
            raise _error("Luna control session capacity is exhausted")
        sessions[tag] = asdict(snapshot)
    return snapshot


def read_snapshot(
    directory: Path, secret: bytes, session_id: str
) -> ControlSnapshot | None:
    directory = Path(directory)
    tag = session_tag(secret, session_id)
    with _locked_state(directory, mutate=False) as state:
        record = state["sessions"].get(tag)
        if record is None:
            return None
        return _snapshot_from_mapping(record)


_PARENT_WORK_TOOLS = {
    "send_input",
    "send_message",
    "followup_task",
    "resume_agent",
}
_PARENT_CLEANUP_TOOLS = {"interrupt_agent", "close_agent"}
_PARENT_TARGET_TOOLS = _PARENT_WORK_TOOLS | _PARENT_CLEANUP_TOOLS


def _record_for_session(state: Mapping[str, Any], tag: str) -> ControlSnapshot:
    record = state["sessions"].get(tag)
    if record is None:
        raise _error("no current V3.1 task exists for this session")
    return _snapshot_from_mapping(record)


def _store_snapshot(state: dict[str, Any], snapshot: ControlSnapshot) -> None:
    validate_snapshot(snapshot)
    state["sessions"][snapshot.root_session_tag] = asdict(snapshot)


def reserve_spawn(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    tool_use_id: str,
    task_name: str,
    fork_turns: str,
    expected_agent_id: str | None = None,
) -> ControlSnapshot:
    if task_name != "luna_worker":
        raise _error("only luna_worker may be reserved")
    if fork_turns != "none":
        raise _error("luna_worker must use fork_turns=none")
    tool_id = _text(tool_use_id, "tool_use_id")
    expected_id = _text(expected_agent_id, "expected_agent_id", optional=True)
    assert tool_id is not None
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        if (
            snapshot.logical_task_status != "ACTIVE"
            or snapshot.execution_status == "RETIRED"
        ):
            raise _error("current task cannot reserve a Luna spawn")
        if snapshot.pending_spawn is not None or snapshot.luna_agent_id is not None:
            raise _error("a Luna spawn is already pending or bound")
        reservation = SpawnReservation(
            task_epoch=snapshot.task_epoch,
            luna_epoch=snapshot.luna_epoch,
            expected_role="luna_worker",
            root_session_tag=snapshot.root_session_tag,
            expected_parent=snapshot.native_parent_identity,
            tool_use_id=tool_id,
            task_path=None,
            agent_id=None,
            expected_agent_id=expected_id,
        )
        updated = replace(snapshot, pending_spawn=reservation)
        _store_snapshot(state, updated)
        return updated


def _reconcile_spawn(
    snapshot: ControlSnapshot, pending: SpawnReservation
) -> ControlSnapshot:
    if pending.task_path is None or pending.agent_id is None:
        return replace(snapshot, pending_spawn=pending)
    if pending.task_path != "/root/luna_worker":
        raise _error("Luna spawn result task path is invalid")
    return replace(
        snapshot,
        luna_agent_id=pending.agent_id,
        luna_task_path=pending.task_path,
        pending_spawn=None,
    )


def _candidate_field(candidate: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in candidate:
            return candidate[name]
    return None


def _bind_recovery_candidate(
    snapshot: ControlSnapshot, candidate: Mapping[str, Any]
) -> ControlSnapshot:
    if snapshot.logical_task_status != "ACTIVE":
        raise _error("recovery requires an active task epoch")
    if snapshot.execution_status == "RETIRED":
        raise _error("retired Luna epoch cannot be recovered")
    pending = snapshot.pending_spawn
    if pending is None:
        raise _error("recovery requires one pending Luna spawn")

    candidate_task_epoch = _candidate_field(candidate, "task_epoch")
    candidate_luna_epoch = _candidate_field(candidate, "luna_epoch")
    candidate_root_tag = _candidate_field(candidate, "root_session_tag", "session_tag")
    candidate_parent = _candidate_field(
        candidate, "native_parent_identity", "parent_identity", "parent"
    )
    candidate_profile = _candidate_field(
        candidate,
        "native_authority_profile",
        "authority_profile_identity",
        "authority_profile",
    )
    candidate_id = _candidate_field(candidate, "agent_id", "id")
    candidate_role = _candidate_field(candidate, "agent_type", "role")
    candidate_path = _candidate_field(candidate, "task_path", "task")
    values = (
        (candidate_task_epoch, "task_epoch"),
        (candidate_luna_epoch, "luna_epoch"),
        (candidate_root_tag, "root_session_tag"),
        (candidate_parent, "native_parent_identity"),
        (candidate_profile, "native_authority_profile"),
        (candidate_id, "agent_id"),
        (candidate_role, "agent_type"),
        (candidate_path, "task_path"),
    )
    for value, field in values:
        _text(value, field)
    if (
        candidate_task_epoch != snapshot.task_epoch
        or candidate_luna_epoch != snapshot.luna_epoch
        or candidate_root_tag != snapshot.root_session_tag
        or candidate_parent != snapshot.native_parent_identity
        or candidate_profile != snapshot.native_authority_profile
    ):
        raise _error("recovery candidate identity does not match the current epoch")
    if candidate_role != "luna_worker":
        raise _error("recovery candidate role is not Luna")
    if candidate_path != "/root/luna_worker":
        raise _error("recovery candidate task path is invalid")
    if pending.agent_id is not None and pending.agent_id != candidate_id:
        raise _error("recovery candidate conflicts with prior agent observation")
    if (
        pending.expected_agent_id is not None
        and pending.expected_agent_id != candidate_id
    ):
        raise _error("recovery candidate agent identity is not authorized")
    if pending.task_path is not None and pending.task_path != candidate_path:
        raise _error("recovery candidate conflicts with prior task observation")
    return replace(
        snapshot,
        luna_agent_id=candidate_id,
        luna_task_path=candidate_path,
        pending_spawn=None,
    )


def observe_spawn_result(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    tool_use_id: str,
    task_path: str,
) -> ControlSnapshot:
    tool_id = _text(tool_use_id, "tool_use_id")
    path = _text(task_path, "task_path")
    assert tool_id is not None and path is not None
    if path != "/root/luna_worker":
        raise _error("Luna spawn result task path is invalid")
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        pending = snapshot.pending_spawn
        if pending is None or pending.tool_use_id != tool_id:
            raise _error("spawn result does not match the pending reservation")
        if pending.task_path is not None and pending.task_path != path:
            raise _error("spawn result conflicts with prior observation")
        pending = replace(pending, task_path=path)
        updated = _reconcile_spawn(snapshot, pending)
        _store_snapshot(state, updated)
        return updated


def observe_subagent_start(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    agent_id: str,
    agent_type: str,
    task_epoch: str | None = None,
    luna_epoch: str | None = None,
    root_session_tag: str | None = None,
    native_parent_identity: str | None = None,
    native_authority_profile: str | None = None,
) -> ControlSnapshot:
    child_id = _text(agent_id, "agent_id")
    role = _text(agent_type, "agent_type")
    assert child_id is not None and role is not None
    if role != "luna_worker":
        raise _error("non-Luna child cannot satisfy the Luna reservation")
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        pending = snapshot.pending_spawn
        if pending is None:
            raise _error("SubagentStart has no matching pending Luna reservation")
        if pending.agent_id is not None and pending.agent_id != child_id:
            raise _error("SubagentStart conflicts with prior observation")
        if pending.task_path is None:
            supplied_identity = (
                (task_epoch, snapshot.task_epoch, "task_epoch"),
                (luna_epoch, snapshot.luna_epoch, "luna_epoch"),
                (root_session_tag, snapshot.root_session_tag, "root_session_tag"),
                (
                    native_parent_identity,
                    snapshot.native_parent_identity,
                    "native_parent_identity",
                ),
                (
                    native_authority_profile,
                    snapshot.native_authority_profile,
                    "native_authority_profile",
                ),
            )
            for supplied, expected, field in supplied_identity:
                if supplied is not None and supplied != expected:
                    raise _error(f"SubagentStart {field} does not match the pending epoch")
            if (
                pending.expected_agent_id is not None
                and pending.expected_agent_id != child_id
            ):
                raise _error("SubagentStart agent identity is not authorized")
            updated = replace(
                snapshot,
                pending_spawn=replace(pending, agent_id=child_id),
            )
            _store_snapshot(state, updated)
            return updated
        candidate = {
            "task_epoch": snapshot.task_epoch if task_epoch is None else task_epoch,
            "luna_epoch": snapshot.luna_epoch if luna_epoch is None else luna_epoch,
            "root_session_tag": (
                snapshot.root_session_tag
                if root_session_tag is None
                else root_session_tag
            ),
            "native_parent_identity": (
                snapshot.native_parent_identity
                if native_parent_identity is None
                else native_parent_identity
            ),
            "native_authority_profile": (
                snapshot.native_authority_profile
                if native_authority_profile is None
                else native_authority_profile
            ),
            "agent_id": child_id,
            "agent_type": role,
            "task_path": pending.task_path or "/root/luna_worker",
        }
        updated = _bind_recovery_candidate(snapshot, candidate)
        _store_snapshot(state, updated)
        return updated


def current_luna(directory: Path, secret: bytes, session_id: str) -> ControlSnapshot:
    snapshot = read_snapshot(directory, secret, session_id)
    if (
        snapshot is None
        or snapshot.luna_agent_id is None
        or snapshot.luna_task_path is None
        or snapshot.logical_task_status != "ACTIVE"
        or snapshot.execution_status == "RETIRED"
    ):
        raise _error("no Luna is currently bound")
    return snapshot


def authorize_parent_target(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    tool_name: str,
    target: str,
) -> None:
    tool = _text(tool_name, "tool_name")
    requested = _text(target, "target")
    assert tool is not None and requested is not None
    if tool not in _PARENT_TARGET_TOOLS:
        raise _error("unsupported Router parent lifecycle operation")
    snapshot = current_luna(directory, secret, session_id)
    if requested not in {snapshot.luna_agent_id, snapshot.luna_task_path}:
        raise _error("parent lifecycle target is not the current Luna")
    if tool in _PARENT_WORK_TOOLS and snapshot.execution_status not in {
        "IDLE",
        "PAUSED_SETTLED",
    }:
        raise _error("parent work dispatch requires an idle or settled Luna")


def _packet_sequence(value: Any, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise _error(f"{field} is invalid")
    return list(value)


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
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        if snapshot.logical_task_status != "ACTIVE":
            raise _error("current task cannot begin a packet")
        if snapshot.execution_status not in {"IDLE", "PAUSED_SETTLED"}:
            raise _error("current execution cannot begin a packet")
        generation = snapshot.packet_generation + 1
        try:
            wire = build_luna_packet(
                packet_id=packet_id,
                generation=generation,
                objective=objective,
                working_directory=working_directory,
                intended_write_scope=_packet_sequence(
                    intended_write_scope, "intended_write_scope"
                ),
                explicit_side_effect_authorizations=_packet_sequence(
                    explicit_side_effect_authorizations,
                    "explicit_side_effect_authorizations",
                ),
                success_criteria=_packet_sequence(success_criteria, "success_criteria"),
                stop_conditions=_packet_sequence(stop_conditions, "stop_conditions"),
            )
            packet = parse_luna_packet(wire)
        except ProtocolError as error:
            raise _error(str(error)) from error
        updated = replace(
            snapshot,
            packet_generation=packet["generation"],
            active_packet_id=packet["packet_id"],
            active_child_turn_id=None,
            execution_status="IDLE",
            authority_packet_wire=wire,
            intended_write_scope=tuple(packet["intended_write_scope"]),
            explicit_side_effect_authorizations=tuple(
                packet["explicit_side_effect_authorizations"]
            ),
        )
        _store_snapshot(state, updated)
        return updated


def start_execution(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    child_turn_id: str | None,
) -> ControlSnapshot:
    child_turn = _text(child_turn_id, "child_turn_id", optional=True)
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        if snapshot.logical_task_status != "ACTIVE":
            raise _error("current task cannot start execution")
        if snapshot.execution_status in {"QUIESCING", "PAUSED_SETTLED", "RETIRED"}:
            raise _error("current execution cannot start")
        if snapshot.active_packet_id is None:
            raise _error("execution requires an active packet")
        if (
            snapshot.active_child_turn_id is not None
            and child_turn is not None
            and snapshot.active_child_turn_id != child_turn
        ):
            raise _error("execution child turn conflicts with the current packet")
        updated = replace(
            snapshot,
            execution_status="RUNNING",
            active_child_turn_id=(
                snapshot.active_child_turn_id
                if child_turn is None
                else child_turn
            ),
        )
        _store_snapshot(state, updated)
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
        raise _error("generation is invalid")
    child_turn = _text(child_turn_id, "child_turn_id", optional=True)
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        if generation != snapshot.packet_generation:
            return "STALE"
        if snapshot.active_packet_id is None:
            return "STALE"
        if snapshot.execution_status in {
            "QUIESCING",
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
        )
        _store_snapshot(state, updated)
        return "CURRENT"


def freeze_authority(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    reason: str,
    logical_cancel: bool = False,
) -> ControlSnapshot:
    _text(reason, "reason")
    if not isinstance(logical_cancel, bool):
        raise _error("logical_cancel is invalid")
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        if snapshot.logical_task_status != "ACTIVE":
            raise _error("only an active task may freeze authority")
        if snapshot.active_packet_id is None:
            raise _error("authority freeze requires an active packet")
        if snapshot.execution_status == "RETIRED":
            raise _error("retired execution cannot freeze authority")
        if snapshot.execution_status == "PAUSED_SETTLED":
            raise _error("settled execution cannot freeze authority")
        if snapshot.execution_status == "QUIESCING":
            if not logical_cancel:
                return snapshot
            updated = replace(snapshot, logical_task_status="CANCELLED")
            _store_snapshot(state, updated)
            return updated
        updated = replace(
            snapshot,
            logical_task_status=(
                "CANCELLED" if logical_cancel else snapshot.logical_task_status
            ),
            execution_status="QUIESCING",
        )
        _store_snapshot(state, updated)
        return updated


def record_interrupt_ack(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    previous_status: str,
) -> ControlSnapshot:
    _text(previous_status, "previous_status")
    snapshot = read_snapshot(directory, secret, session_id)
    if snapshot is None:
        raise _error("no current V3.1 task exists for this session")
    if snapshot.execution_status != "QUIESCING":
        raise _error("interrupt acknowledgment requires quiescing execution")
    return snapshot


def observe_settlement(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    source: Literal["verified_native_terminal"],
    terminal_status: Literal["completed", "failed", "interrupted", "cancelled"],
    child_turn_id: str | None,
) -> ControlSnapshot:
    if source != _SETTLEMENT_SOURCE:
        raise _error("settlement source is not verified")
    if terminal_status not in _TERMINAL_STATUSES:
        raise _error("terminal status is invalid")
    child_turn = _text(child_turn_id, "child_turn_id", optional=True)
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        if snapshot.execution_status != "QUIESCING":
            raise _error("settlement requires quiescing execution")
        if snapshot.active_packet_id is None:
            raise _error("settlement requires an active packet")
        if snapshot.active_child_turn_id != child_turn:
            raise _error("settlement child turn does not match the frozen packet")
        updated = replace(snapshot, execution_status="PAUSED_SETTLED")
        _store_snapshot(state, updated)
        return updated


def _retirement_settlement(
    snapshot: ControlSnapshot,
    *,
    source: str | None,
    terminal_status: str | None,
    child_turn_id: str | None,
) -> ControlSnapshot:
    if source != _SETTLEMENT_SOURCE:
        raise _error("Luna retirement requires verified native settlement")
    if terminal_status not in _TERMINAL_STATUSES:
        raise _error("terminal status is invalid")
    child_turn = _text(child_turn_id, "child_turn_id", optional=True)
    if snapshot.active_packet_id is None:
        raise _error("settlement requires an active packet")
    if snapshot.active_child_turn_id != child_turn:
        raise _error("settlement child turn does not match the frozen packet")
    return replace(snapshot, execution_status="PAUSED_SETTLED")


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
    """Retire the current Luna only after a required execution barrier."""
    if reason not in _RETIRE_REASONS:
        raise _error("Luna retirement reason is invalid")
    if (settlement_source is None) != (terminal_status is None):
        raise _error("retirement settlement evidence is incomplete")
    if settlement_source is not None and child_turn_id is None:
        raise _error("retirement settlement child turn is required")
    tag = session_tag(secret, session_id)
    initial = read_snapshot(directory, secret, session_id)
    if initial is not None and initial.execution_status == "RUNNING" and settlement_source is None:
        freeze_authority(
            directory,
            secret,
            session_id,
            reason=f"retire:{reason}",
        )
        raise _error("Luna retirement requires verified native settlement")
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        if snapshot.execution_status == "RETIRED":
            raise _error("Luna epoch is already retired")
        if snapshot.pending_spawn is not None:
            raise _error("cannot retire a Luna with an unresolved spawn")

        if snapshot.execution_status == "RUNNING":
            frozen = replace(snapshot, execution_status="QUIESCING")
            if settlement_source is None:
                _store_snapshot(state, frozen)
                _write_state_unlocked(Path(directory), state)
                raise _error("Luna retirement requires verified native settlement")
            snapshot = _retirement_settlement(
                frozen,
                source=settlement_source,
                terminal_status=terminal_status,
                child_turn_id=child_turn_id,
            )
        elif snapshot.execution_status == "QUIESCING":
            if settlement_source is None:
                raise _error("Luna retirement requires verified native settlement")
            snapshot = _retirement_settlement(
                snapshot,
                source=settlement_source,
                terminal_status=terminal_status,
                child_turn_id=child_turn_id,
            )
        elif snapshot.execution_status == "PAUSED_SETTLED":
            if settlement_source is not None:
                raise _error("settlement evidence is not valid for settled execution")
        elif snapshot.execution_status != "IDLE":
            raise _error("Luna execution cannot be retired")

        if reason != "new_task_epoch" and snapshot.luna_agent_id is None:
            raise _error("Luna replacement requires a bound Luna identity")
        retired = replace(
            snapshot,
            logical_task_status=(
                "CANCELLED"
                if reason == "new_task_epoch"
                else snapshot.logical_task_status
            ),
            execution_status="RETIRED",
            active_packet_id=None,
            active_child_turn_id=None,
            intended_write_scope=(),
            explicit_side_effect_authorizations=(),
        )
        _store_snapshot(state, retired)
        return retired


def _replacement_reservation(
    *,
    task_epoch: str,
    luna_epoch: str,
    root_session_tag: str,
    parent: str,
    tool_id: str | None,
    expected_id: str | None,
) -> SpawnReservation | None:
    if tool_id is None:
        return None
    return SpawnReservation(
        task_epoch=task_epoch,
        luna_epoch=luna_epoch,
        expected_role="luna_worker",
        root_session_tag=root_session_tag,
        expected_parent=parent,
        tool_use_id=tool_id,
        task_path=None,
        agent_id=None,
        expected_agent_id=expected_id,
    )


def replace_luna_epoch(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    native_parent_identity: str,
    native_authority_profile: str,
    reason: Literal[
        "unrecoverable_runtime_identity",
        "native_authority_profile_change",
        "runtime_validated_context_reset",
    ],
    tool_use_id: str | None = None,
    expected_agent_id: str | None = None,
) -> ControlSnapshot:
    """Replace only the Luna runtime epoch while preserving the task epoch."""
    if reason not in _LUNA_REPLACEMENT_REASONS:
        raise _error("Luna replacement reason is invalid")
    parent = _text(native_parent_identity, "native_parent_identity")
    profile = _text(native_authority_profile, "native_authority_profile")
    tool_id = _text(tool_use_id, "tool_use_id", optional=True)
    expected_id = _text(expected_agent_id, "expected_agent_id", optional=True)
    assert parent is not None and profile is not None
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        previous = _record_for_session(state, tag)
        if (
            previous.logical_task_status != "ACTIVE"
            or previous.execution_status != "RETIRED"
        ):
            raise _error("Luna replacement requires an active task with a retired Luna")
        if parent != previous.native_parent_identity:
            raise _error("replacement parent identity does not match the task epoch")
        if (
            reason != "native_authority_profile_change"
            and profile != previous.native_authority_profile
        ):
            raise _error("replacement reason cannot change native authority profile")
        luna_epoch = _new_epoch("luna")
        pending = _replacement_reservation(
            task_epoch=previous.task_epoch,
            luna_epoch=luna_epoch,
            root_session_tag=tag,
            parent=parent,
            tool_id=tool_id,
            expected_id=expected_id,
        )
        replacement = ControlSnapshot(
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
        )
        _store_snapshot(state, replacement)
        return replacement


def start_new_task_epoch(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    native_parent_identity: str,
    native_authority_profile: str,
    reason: Literal["new_task_epoch"] | None = None,
    tool_use_id: str | None = None,
    expected_agent_id: str | None = None,
) -> ControlSnapshot:
    """Create a fresh task and Luna epoch after a cancelled retired task."""
    if reason not in {None, "new_task_epoch"}:
        raise _error("new task epoch requires the new_task_epoch reason")
    parent = _text(native_parent_identity, "native_parent_identity")
    profile = _text(native_authority_profile, "native_authority_profile")
    tool_id = _text(tool_use_id, "tool_use_id", optional=True)
    expected_id = _text(expected_agent_id, "expected_agent_id", optional=True)
    assert parent is not None and profile is not None
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        previous = _record_for_session(state, tag)
        if (
            previous.logical_task_status != "CANCELLED"
            or previous.execution_status != "RETIRED"
        ):
            raise _error("new task epoch requires a cancelled retired prior task")
        if parent != previous.native_parent_identity:
            raise _error("replacement parent identity does not match the task epoch")
        task_epoch = _new_epoch("task")
        luna_epoch = _new_epoch("luna")
        pending = _replacement_reservation(
            task_epoch=task_epoch,
            luna_epoch=luna_epoch,
            root_session_tag=tag,
            parent=parent,
            tool_id=tool_id,
            expected_id=expected_id,
        )
        replacement = ControlSnapshot(
            task_epoch=task_epoch,
            luna_epoch=luna_epoch,
            root_session_tag=tag,
            native_parent_identity=parent,
            native_authority_profile=profile,
            luna_agent_id=None,
            luna_task_path=None,
            packet_generation=0,
            active_packet_id=None,
            active_child_turn_id=None,
            logical_task_status="ACTIVE",
            execution_status="IDLE",
            pending_spawn=pending,
        )
        _store_snapshot(state, replacement)
        return replacement


def reconcile_recovery(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    candidate: Mapping[str, Any] | None = None,
    candidates: Any = None,
    task_epoch: str | None = None,
    luna_epoch: str | None = None,
    root_session_tag: str | None = None,
    native_parent_identity: str | None = None,
    native_authority_profile: str | None = None,
    agent_id: str | None = None,
    agent_type: str | None = None,
    task_path: str | None = None,
) -> ControlSnapshot:
    """Bind exactly one identity-qualified recovery candidate to the pending epoch."""
    if candidate is not None and candidates is not None:
        raise _error("recovery candidates are ambiguous")
    if candidates is not None:
        if isinstance(candidates, (str, bytes)):
            raise _error("recovery candidates are invalid")
        try:
            values = tuple(candidates)
        except TypeError as error:
            raise _error("recovery candidates are invalid") from error
        if len(values) != 1 or not isinstance(values[0], Mapping):
            raise _error("recovery candidates are ambiguous")
        candidate = values[0]
    elif candidate is None:
        candidate = {
            "task_epoch": task_epoch,
            "luna_epoch": luna_epoch,
            "root_session_tag": root_session_tag,
            "native_parent_identity": native_parent_identity,
            "native_authority_profile": native_authority_profile,
            "agent_id": agent_id,
            "agent_type": agent_type,
            "task_path": task_path,
        }
    if not isinstance(candidate, Mapping):
        raise _error("recovery candidate is invalid")
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        updated = _bind_recovery_candidate(snapshot, candidate)
        _store_snapshot(state, updated)
        return updated
