"""Durable Router V4 authority state with generation-scoped leases."""
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

from .protocol import ProtocolError, parse_luna_packet
from .state import RouterStateError


PROTOCOL = "codex-router/lease-control/v4.0"
_STATE = "lease-control-v4-0.json"
_LOCK = "lease-control-v4-0.lock"
_MAX_SESSIONS = 64
_MAX_STATE_BYTES = 256 * 1024
_MAX_RETIRED_WORKER_TAGS = 2048
_TAG_RE = re.compile(r"[0-9a-f]{64}\Z")
_TASK_EPOCH_RE = re.compile(r"task-[0-9a-f]{32}\Z")
_LEASE_ID_RE = re.compile(r"lease-[0-9a-f]{32}\Z")
_TASK_NAME_RE = re.compile(r"luna_g[1-9][0-9]*_[0-9a-f]{8}\Z")
_BOOTSTRAP_CAPABILITY_RE = re.compile(r"v4b1\.[0-9a-f]{64}\Z")
_STAGE_CAPABILITY_RE = re.compile(r"v4s1\.[0-9a-f]{64}\Z")

LeaseStatus = Literal["STAGED", "ACTIVE"]
ObservationDisposition = Literal["CURRENT", "STALE", "NOOP"]
_LEASE_STATUSES = {"STAGED", "ACTIVE"}


@dataclass(frozen=True)
class LeaseRecord:
    lease_id: str
    task_epoch: str
    generation: int
    root_session_tag: str
    root_turn_tag: str
    packet_id: str
    authority_packet_wire: str
    expected_task_name: str
    spawn_tool_use_id: str | None = None
    worker_agent_id: str | None = None
    worker_task_path: str | None = None
    child_turn_id: str | None = None
    status: LeaseStatus = "STAGED"
    intended_write_scope: tuple[str, ...] = ()
    explicit_side_effect_authorizations: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeaseSnapshot:
    task_epoch: str
    root_session_tag: str
    generation: int
    active_lease: LeaseRecord | None
    retired_worker_tags: tuple[str, ...] = ()
    current_root_turn_tag: str | None = None


_SNAPSHOT_FIELDS = frozenset(LeaseSnapshot.__dataclass_fields__)
_LEASE_FIELDS = frozenset(LeaseRecord.__dataclass_fields__)


def _error(message: str) -> RouterStateError:
    return RouterStateError("conflict", message)


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise _error(f"{field} is invalid")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _error(f"{field} is invalid") from exc
    if len(encoded) > 512:
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
        b"v4-session\0" + session.encode("utf-8", errors="strict"),
        hashlib.sha256,
    ).hexdigest()


def _root_turn_tag(secret: bytes, turn_id: str) -> str:
    key = _secret(secret)
    turn = _text(turn_id, "root_turn_id")
    assert turn is not None
    return hmac.new(
        key,
        b"v4-root-turn\0" + turn.encode("utf-8", errors="strict"),
        hashlib.sha256,
    ).hexdigest()


def _new_task_epoch() -> str:
    return f"task-{uuid.uuid4().hex}"


def _new_lease_id() -> str:
    return f"lease-{uuid.uuid4().hex}"


def _expected_task_name(generation: int, lease_id: str) -> str:
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise _error("generation is invalid")
    if _LEASE_ID_RE.fullmatch(lease_id) is None:
        raise _error("lease_id is invalid")
    return f"luna_g{generation}_{lease_id.removeprefix('lease-')[:8]}"


def _expected_task_path(lease: LeaseRecord) -> str:
    return f"/root/{lease.expected_task_name}"


def _bootstrap_capability_mac(secret: bytes, lease: LeaseRecord) -> str:
    key = _secret(secret)
    validate_lease(lease)
    fields = (
        lease.root_session_tag,
        lease.task_epoch,
        str(lease.generation),
        lease.lease_id,
        lease.root_turn_tag,
        lease.packet_id,
        lease.expected_task_name,
    )
    payload = b"v4-lease-bootstrap\0" + b"\0".join(
        field.encode("utf-8", errors="strict") for field in fields
    )
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def build_bootstrap_capability(secret: bytes, lease: LeaseRecord) -> str:
    """Return the current lease-scoped worker bootstrap capability."""
    return f"v4b1.{_bootstrap_capability_mac(secret, lease)}"


def verify_bootstrap_capability(
    secret: bytes, lease: LeaseRecord, capability: str
) -> None:
    """Fail closed unless ``capability`` belongs to exactly ``lease``."""
    candidate = _text(capability, "bootstrap capability")
    assert candidate is not None
    if _BOOTSTRAP_CAPABILITY_RE.fullmatch(candidate) is None:
        raise _error("bootstrap capability is invalid")
    expected = build_bootstrap_capability(secret, lease)
    if not hmac.compare_digest(candidate, expected):
        raise _error("bootstrap capability does not match the current lease")


def _stage_capability_mac(
    secret: bytes, snapshot: LeaseSnapshot, *, root_turn_id: str
) -> str:
    key = _secret(secret)
    validate_snapshot(snapshot)
    expected_root = _root_turn_tag(secret, root_turn_id)
    if (
        snapshot.current_root_turn_tag is None
        or not hmac.compare_digest(snapshot.current_root_turn_tag, expected_root)
    ):
        raise _error("stage capability root turn is not current")
    fields = (
        snapshot.root_session_tag,
        snapshot.task_epoch,
        str(snapshot.generation + 1),
        snapshot.current_root_turn_tag,
    )
    payload = b"v4-stage-capability\0" + b"\0".join(
        field.encode("utf-8", errors="strict") for field in fields
    )
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def build_stage_capability(
    secret: bytes, snapshot: LeaseSnapshot, *, root_turn_id: str
) -> str:
    """Return a current-root, next-generation staging capability."""
    return f"v4s1.{_stage_capability_mac(secret, snapshot, root_turn_id=root_turn_id)}"


def verify_stage_capability(
    secret: bytes,
    snapshot: LeaseSnapshot,
    *,
    root_turn_id: str,
    capability: str,
) -> None:
    candidate = _text(capability, "stage capability")
    assert candidate is not None
    if _STAGE_CAPABILITY_RE.fullmatch(candidate) is None:
        raise _error("stage capability is invalid")
    expected = build_stage_capability(
        secret, snapshot, root_turn_id=root_turn_id
    )
    if not hmac.compare_digest(candidate, expected):
        raise _error("stage capability does not match current root authority")


def _authority_packet_wire(value: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(value, str) or not value:
        raise _error("authority_packet_wire is invalid")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _error("authority_packet_wire is invalid") from exc
    if len(encoded) > _MAX_STATE_BYTES:
        raise _error("authority_packet_wire exceeds lease journal capacity")
    try:
        packet = parse_luna_packet(value)
    except ProtocolError as exc:
        raise _error(str(exc)) from exc
    return value, packet


def validate_lease(lease: LeaseRecord) -> None:
    if not isinstance(lease, LeaseRecord):
        raise _error("lease record type is invalid")
    if _LEASE_ID_RE.fullmatch(lease.lease_id) is None:
        raise _error("lease_id is invalid")
    if _TASK_EPOCH_RE.fullmatch(lease.task_epoch) is None:
        raise _error("lease task_epoch is invalid")
    if _TAG_RE.fullmatch(lease.root_session_tag) is None:
        raise _error("lease root_session_tag is invalid")
    if _TAG_RE.fullmatch(lease.root_turn_tag) is None:
        raise _error("lease root_turn_tag is invalid")
    if not isinstance(lease.generation, int) or isinstance(lease.generation, bool) or lease.generation < 1:
        raise _error("lease generation is invalid")
    if lease.status not in _LEASE_STATUSES:
        raise _error("lease status is invalid")
    packet_id = _text(lease.packet_id, "lease packet_id")
    assert packet_id is not None
    wire, packet = _authority_packet_wire(lease.authority_packet_wire)
    if wire != lease.authority_packet_wire:
        raise _error("lease authority wire is invalid")
    if packet["generation"] != lease.generation or packet["packet_id"] != packet_id:
        raise _error("lease packet identity is inconsistent")
    if not isinstance(lease.expected_task_name, str) or _TASK_NAME_RE.fullmatch(lease.expected_task_name) is None:
        raise _error("lease expected_task_name is invalid")
    if lease.expected_task_name != _expected_task_name(lease.generation, lease.lease_id):
        raise _error("lease expected_task_name is inconsistent")
    spawn_tool_use_id = _text(
        lease.spawn_tool_use_id, "lease spawn_tool_use_id", optional=True
    )
    _text(lease.worker_agent_id, "lease worker_agent_id", optional=True)
    worker_task_path = _text(
        lease.worker_task_path, "lease worker_task_path", optional=True
    )
    _text(lease.child_turn_id, "lease child_turn_id", optional=True)
    if worker_task_path is not None:
        if spawn_tool_use_id is None:
            raise _error("lease worker task path requires a spawn reservation")
        if worker_task_path != _expected_task_path(lease):
            raise _error("lease worker task path is inconsistent")
    scope = _text_sequence(lease.intended_write_scope, "lease intended_write_scope", unique=True)
    authorizations = _text_sequence(
        lease.explicit_side_effect_authorizations,
        "lease explicit_side_effect_authorizations",
    )
    if tuple(packet["intended_write_scope"]) != scope:
        raise _error("lease intended_write_scope is inconsistent")
    if tuple(packet["explicit_side_effect_authorizations"]) != authorizations:
        raise _error("lease side-effect authorizations are inconsistent")


def validate_snapshot(snapshot: LeaseSnapshot) -> None:
    if not isinstance(snapshot, LeaseSnapshot):
        raise _error("lease snapshot type is invalid")
    if _TASK_EPOCH_RE.fullmatch(snapshot.task_epoch) is None:
        raise _error("task_epoch is invalid")
    if _TAG_RE.fullmatch(snapshot.root_session_tag) is None:
        raise _error("root_session_tag is invalid")
    if not isinstance(snapshot.generation, int) or isinstance(snapshot.generation, bool) or snapshot.generation < 0:
        raise _error("generation is invalid")
    root_turn_tag = _text(
        snapshot.current_root_turn_tag,
        "current_root_turn_tag",
        optional=True,
    )
    if root_turn_tag is not None and _TAG_RE.fullmatch(root_turn_tag) is None:
        raise _error("current_root_turn_tag is invalid")
    retired = _text_sequence(
        snapshot.retired_worker_tags,
        "retired_worker_tags",
        unique=True,
    )
    if len(retired) > _MAX_RETIRED_WORKER_TAGS or any(_TAG_RE.fullmatch(tag) is None for tag in retired):
        raise _error("retired worker history is invalid")
    lease = snapshot.active_lease
    if lease is None:
        return
    validate_lease(lease)
    if snapshot.generation < 1 or lease.generation != snapshot.generation:
        raise _error("active lease generation is inconsistent")
    if lease.task_epoch != snapshot.task_epoch or lease.root_session_tag != snapshot.root_session_tag:
        raise _error("active lease session identity is inconsistent")


def _lease_from_mapping(value: Any) -> LeaseRecord:
    if not isinstance(value, Mapping) or set(value) != _LEASE_FIELDS:
        raise _error("lease record schema is invalid")
    data = dict(value)
    for field in ("intended_write_scope", "explicit_side_effect_authorizations"):
        if isinstance(data[field], list):
            data[field] = tuple(data[field])
    try:
        lease = LeaseRecord(**data)
    except TypeError as exc:
        raise _error("lease record schema is invalid") from exc
    validate_lease(lease)
    return lease


def _snapshot_from_mapping(value: Any) -> LeaseSnapshot:
    if not isinstance(value, Mapping):
        raise _error("lease snapshot schema is invalid")
    data = dict(value)
    legacy_fields = _SNAPSHOT_FIELDS - {"current_root_turn_tag"}
    if set(data) == legacy_fields:
        data["current_root_turn_tag"] = None
    elif set(data) != _SNAPSHOT_FIELDS:
        raise _error("lease snapshot schema is invalid")
    if isinstance(data["retired_worker_tags"], list):
        data["retired_worker_tags"] = tuple(data["retired_worker_tags"])
    if data["active_lease"] is not None:
        data["active_lease"] = _lease_from_mapping(data["active_lease"])
    try:
        snapshot = LeaseSnapshot(**data)
    except TypeError as exc:
        raise _error("lease snapshot schema is invalid") from exc
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
        raise _error("lease control journal schema is invalid")
    for key, record in value["sessions"].items():
        if not isinstance(key, str) or _TAG_RE.fullmatch(key) is None:
            raise _error("lease control session key is invalid")
        snapshot = _snapshot_from_mapping(record)
        if snapshot.root_session_tag != key:
            raise _error("lease control session tag is inconsistent")
    return value


def _validate_directory(directory: Path) -> None:
    try:
        metadata = directory.lstat()
    except OSError as exc:
        raise _error("lease control directory is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise _error("lease control directory is unsafe")


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
        raise _error("lease control journal is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > _MAX_STATE_BYTES
    ):
        raise _error("lease control journal is unsafe")
    try:
        raw = path.read_bytes()
        if len(raw) > _MAX_STATE_BYTES:
            raise _error("lease control journal exceeds the size limit")
        value = json.loads(raw)
    except RouterStateError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("lease control journal is unreadable") from exc
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
        raise _error("lease control journal exceeds the size limit")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".lease-control-v4-0.", dir=directory)
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
    directory = Path(directory)
    _validate_directory(directory)
    lock_path = directory / _LOCK
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise _error("lease control lock is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise _error("lease control lock is unsafe")
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


def _record_for_session(state: Mapping[str, Any], tag: str) -> LeaseSnapshot:
    record = state["sessions"].get(tag)
    if record is None:
        raise _error("no current V4 lease session exists")
    return _snapshot_from_mapping(record)


def _store_snapshot(state: dict[str, Any], snapshot: LeaseSnapshot) -> None:
    validate_snapshot(snapshot)
    candidate = dict(state)
    candidate_sessions = dict(state["sessions"])
    candidate_sessions[snapshot.root_session_tag] = asdict(snapshot)
    candidate["sessions"] = candidate_sessions
    if len(_canonical_state_bytes(candidate)) > _MAX_STATE_BYTES:
        raise _error("lease control journal capacity is insufficient")
    state["sessions"][snapshot.root_session_tag] = asdict(snapshot)


def initialize_session(directory: Path, secret: bytes, session_id: str) -> LeaseSnapshot:
    directory = Path(directory)
    tag = session_tag(secret, session_id)
    with _locked_state(directory, mutate=True) as state:
        existing = state["sessions"].get(tag)
        if existing is not None:
            return _snapshot_from_mapping(existing)
        if len(state["sessions"]) >= _MAX_SESSIONS:
            raise _error("lease control session capacity is exhausted")
        snapshot = LeaseSnapshot(
            task_epoch=_new_task_epoch(),
            root_session_tag=tag,
            generation=0,
            active_lease=None,
            retired_worker_tags=(),
            current_root_turn_tag=None,
        )
        _store_snapshot(state, snapshot)
        return snapshot


def read_snapshot(directory: Path, secret: bytes, session_id: str) -> LeaseSnapshot | None:
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=False) as state:
        record = state["sessions"].get(tag)
        if record is None:
            return None
        return _snapshot_from_mapping(record)


def set_current_root_turn(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    turn_id: str | None,
) -> LeaseSnapshot:
    """Bind or clear the current root-turn authority without changing generation."""
    tag = session_tag(secret, session_id)
    root_tag = None if turn_id is None else _root_turn_tag(secret, turn_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        if snapshot.current_root_turn_tag == root_tag:
            return snapshot
        updated = replace(snapshot, current_root_turn_tag=root_tag)
        _store_snapshot(state, updated)
        return updated


def _stage_lease_from_snapshot(
    snapshot: LeaseSnapshot,
    secret: bytes,
    *,
    root_turn_id: str,
    packet_wire: str,
) -> LeaseSnapshot:
    if snapshot.active_lease is not None:
        raise _error("current V4 lease must be revoked before staging another")
    wire, packet = _authority_packet_wire(packet_wire)
    generation = snapshot.generation + 1
    if packet["generation"] != generation:
        raise _error("staged lease generation is not current")
    lease_id = _new_lease_id()
    lease = LeaseRecord(
        lease_id=lease_id,
        task_epoch=snapshot.task_epoch,
        generation=generation,
        root_session_tag=snapshot.root_session_tag,
        root_turn_tag=_root_turn_tag(secret, root_turn_id),
        packet_id=packet["packet_id"],
        authority_packet_wire=wire,
        expected_task_name=_expected_task_name(generation, lease_id),
        status="STAGED",
        intended_write_scope=tuple(packet["intended_write_scope"]),
        explicit_side_effect_authorizations=tuple(
            packet["explicit_side_effect_authorizations"]
        ),
    )
    return replace(snapshot, generation=generation, active_lease=lease)


def stage_lease(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    root_turn_id: str,
    packet_wire: str,
) -> LeaseSnapshot:
    """Low-level trusted staging API retained for unit-level state construction."""
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        updated = _stage_lease_from_snapshot(
            snapshot,
            secret,
            root_turn_id=root_turn_id,
            packet_wire=packet_wire,
        )
        _store_snapshot(state, updated)
        return updated


def stage_authorized_lease(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    root_turn_id: str,
    capability: str,
    packet_wire: str,
) -> LeaseSnapshot:
    """Verify current root authority and stage in one locked transaction."""
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        verify_stage_capability(
            secret,
            snapshot,
            root_turn_id=root_turn_id,
            capability=capability,
        )
        updated = _stage_lease_from_snapshot(
            snapshot,
            secret,
            root_turn_id=root_turn_id,
            packet_wire=packet_wire,
        )
        _store_snapshot(state, updated)
        return updated


def revoke_current_lease(
    directory: Path, secret: bytes, session_id: str
) -> LeaseSnapshot:
    """Logically revoke current authority without waiting for native terminal state."""
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        if snapshot.active_lease is None:
            return snapshot
        updated = replace(snapshot, active_lease=None)
        _store_snapshot(state, updated)
        return updated


def reserve_spawn(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    tool_use_id: str,
    task_name: str,
    agent_type: str,
    fork_turns: str,
) -> LeaseSnapshot:
    """Reserve one native spawn inside the current lease only."""
    tool_id = _text(tool_use_id, "spawn tool_use_id")
    task = _text(task_name, "spawn task_name")
    role = _text(agent_type, "spawn agent_type")
    fork = _text(fork_turns, "spawn fork_turns")
    assert tool_id is not None and task is not None and role is not None and fork is not None
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        lease = snapshot.active_lease
        if lease is None or lease.status != "STAGED":
            raise _error("current V4 lease cannot reserve a spawn")
        if task != lease.expected_task_name:
            raise _error("spawn task_name does not match the current lease")
        if role != "luna_worker":
            raise _error("spawn agent_type must be luna_worker")
        if fork != "none":
            raise _error("luna_worker must use fork_turns=none")
        if lease.spawn_tool_use_id is not None:
            if lease.spawn_tool_use_id == tool_id:
                return snapshot
            raise _error("current V4 lease already has a spawn reservation")
        updated_lease = replace(lease, spawn_tool_use_id=tool_id)
        updated = replace(snapshot, active_lease=updated_lease)
        _store_snapshot(state, updated)
        return updated


def observe_spawn_result(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    tool_use_id: str,
    task_path: str,
) -> tuple[LeaseSnapshot, ObservationDisposition]:
    """Corroborate the current spawn path without inferring a worker agent id."""
    tool_id = _text(tool_use_id, "spawn result tool_use_id")
    path = _text(task_path, "spawn result task_path")
    assert tool_id is not None and path is not None
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        lease = snapshot.active_lease
        if lease is None or lease.spawn_tool_use_id != tool_id:
            return snapshot, "STALE"
        expected_path = _expected_task_path(lease)
        if path != expected_path:
            raise _error("spawn result task path does not match the current lease")
        if lease.worker_task_path == path:
            return snapshot, "NOOP"
        if lease.worker_task_path is not None:
            raise _error("spawn result conflicts with prior current observation")
        updated_lease = replace(lease, worker_task_path=path)
        updated = replace(snapshot, active_lease=updated_lease)
        _store_snapshot(state, updated)
        return updated, "CURRENT"


def observe_subagent_start(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    agent_id: str,
    agent_type: str,
    turn_id: str,
) -> tuple[LeaseSnapshot, ObservationDisposition]:
    """Observe native start telemetry without granting uncorrelated authority."""
    _text(agent_id, "SubagentStart agent_id")
    _text(agent_type, "SubagentStart agent_type")
    _text(turn_id, "SubagentStart turn_id")
    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=False) as state:
        snapshot = _record_for_session(state, tag)
        return snapshot, "NOOP"


def authorize_executor_tool(
    directory: Path,
    secret: bytes,
    session_id: str,
    *,
    agent_id: str,
    agent_type: str,
    child_turn_id: str,
    bootstrap_capability: str | None,
) -> tuple[LeaseSnapshot, str | None]:
    """Bind or validate the exact native worker for the current V4 lease."""
    agent = _text(agent_id, "executor agent_id")
    role = _text(agent_type, "executor agent_type")
    child = _text(child_turn_id, "executor child_turn_id")
    assert agent is not None and role is not None and child is not None
    if role != "luna_worker":
        raise _error("executor agent_type must be luna_worker")

    tag = session_tag(secret, session_id)
    with _locked_state(Path(directory), mutate=True) as state:
        snapshot = _record_for_session(state, tag)
        lease = snapshot.active_lease
        if lease is None:
            raise _error("Luna tool has no active V4 lease")

        if lease.status == "STAGED":
            if lease.worker_agent_id is not None or lease.child_turn_id is not None:
                raise _error("staged V4 lease has inconsistent worker identity")
            if bootstrap_capability is None:
                raise _error("current V4 lease bootstrap capability is required")
            verify_bootstrap_capability(secret, lease, bootstrap_capability)
            updated_lease = replace(
                lease,
                worker_agent_id=agent,
                child_turn_id=child,
                status="ACTIVE",
            )
            updated = replace(snapshot, active_lease=updated_lease)
            _store_snapshot(state, updated)
            return updated, lease.authority_packet_wire

        if lease.status != "ACTIVE":
            raise _error("current V4 lease status is invalid for executor work")
        if lease.worker_agent_id != agent:
            raise _error("executor agent_id does not match the current V4 lease")
        if lease.child_turn_id != child:
            raise _error("executor child turn does not match the current V4 lease")
        return snapshot, None
