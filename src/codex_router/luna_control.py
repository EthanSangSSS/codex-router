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
    pending_spawn: SpawnReservation | None = None


_SNAPSHOT_FIELDS = frozenset(ControlSnapshot.__dataclass_fields__)


def _error(message: str) -> RouterStateError:
    return RouterStateError("conflict", message)


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
        raise _error(f"{field} is invalid")
    return value


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
    if snapshot.logical_task_status == "ACTIVE" and snapshot.execution_status == "RETIRED":
        raise _error("active task cannot have retired execution")
    if snapshot.execution_status in {"RUNNING", "QUIESCING"} and packet_id is None:
        raise _error("running or quiescing execution requires an active packet")
    if snapshot.execution_status == "IDLE" and (
        packet_id is not None or child_turn is not None
    ):
        raise _error("idle execution cannot retain active execution identity")
    if snapshot.execution_status == "RETIRED" and (
        packet_id is not None or child_turn is not None
    ):
        raise _error("retired execution cannot retain active execution identity")
    if child_turn is not None and packet_id is None:
        raise _error("active child turn requires an active packet")
    if snapshot.packet_generation == 0 and packet_id is not None:
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
        if pending_path is not None and pending_path != "/root/luna_worker":
            raise _error("pending spawn task path is invalid")
        if pending.task_path is not None and pending.agent_id is not None:
            raise _error("fully observed spawn must be bound, not pending")
        if snapshot.luna_agent_id is not None:
            raise _error("bound Luna cannot retain a pending spawn")


def _snapshot_from_mapping(value: Any) -> ControlSnapshot:
    if not isinstance(value, Mapping) or set(value) != _SNAPSHOT_FIELDS:
        raise _error("control snapshot schema is invalid")
    data = dict(value)
    pending = data.get("pending_spawn")
    if pending is not None:
        if not isinstance(pending, Mapping) or set(pending) != set(
            SpawnReservation.__dataclass_fields__
        ):
            raise _error("pending spawn schema is invalid")
        try:
            data["pending_spawn"] = SpawnReservation(**dict(pending))
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
        if tag not in sessions and len(sessions) >= _MAX_SESSIONS:
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


_PARENT_TARGET_TOOLS = {
    "send_input",
    "send_message",
    "followup_task",
    "interrupt_agent",
    "close_agent",
    "resume_agent",
}


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
) -> ControlSnapshot:
    if task_name != "luna_worker":
        raise _error("only luna_worker may be reserved")
    if fork_turns != "none":
        raise _error("luna_worker must use fork_turns=none")
    tool_id = _text(tool_use_id, "tool_use_id")
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
        pending = replace(pending, agent_id=child_id)
        updated = _reconcile_spawn(snapshot, pending)
        _store_snapshot(state, updated)
        return updated


def current_luna(directory: Path, secret: bytes, session_id: str) -> ControlSnapshot:
    snapshot = read_snapshot(directory, secret, session_id)
    if (
        snapshot is None
        or snapshot.luna_agent_id is None
        or snapshot.luna_task_path is None
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
