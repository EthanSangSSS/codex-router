"""Minimal fail-closed native Luna authorization journal for Codex V2."""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Iterator, Mapping

from .protocol import canonical_json_bytes
from .state import RouterStateError

PROTOCOL = "codex-router/native-luna-safety-v2"
_STATE = "native-luna-safety-v2.json"
_LOCK = "native-luna-safety-v2.lock"
_AUTH = {"ACTIVE", "REVOKED"}
_MAX_SESSIONS = 64
_TARGET_FIELD = {
    "send_input": "target",
    "send_message": "target",
    "followup_task": "target",
    "interrupt_agent": "target",
    "close_agent": "target",
    "resume_agent": "id",
}


def _error(message: str) -> RouterStateError:
    return RouterStateError("conflict", message)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
        raise _error(f"{field} is invalid")
    return value


def _tag(secret: bytes, label: str, values: Mapping[str, str]) -> str:
    return hmac.new(
        secret,
        label.encode("ascii") + b"\0" + canonical_json_bytes(dict(values)),
        hashlib.sha256,
    ).hexdigest()


def session_tag(secret: bytes, session_id: str) -> str:
    return _tag(secret, "session", {"session_id": _text(session_id, "session_id")})


def scope_tag(secret: bytes, session_id: str, turn_id: str) -> str:
    return _tag(
        secret,
        "scope",
        {
            "session_id": _text(session_id, "session_id"),
            "turn_id": _text(turn_id, "turn_id"),
        },
    )


def scope_mac(secret: bytes, session_id: str, turn_id: str) -> str:
    """Compatibility alias for the former scope-MAC helper."""
    return scope_tag(secret, session_id, turn_id)


def _key(session_id: str, turn_id: str) -> str:
    """Legacy test helper retained only for callers outside the security schema."""
    return hashlib.sha256((session_id + "\0" + turn_id).encode()).hexdigest()


def task_path(task_name: str) -> str:
    name = _text(task_name, "task_name")
    if name != "luna_worker":
        raise _error("only luna_worker may be spawned")
    return "/root/luna_worker"


def _target(tool_name: str, tool_input: Mapping[str, Any]) -> str:
    field = _TARGET_FIELD.get(tool_name)
    if field is None:
        raise _error("unsupported parent lifecycle operation")
    return _text(tool_input.get(field), field)


def _empty() -> dict[str, Any]:
    return {"protocol": PROTOCOL, "sessions": {}}


def _hex_tag(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise _error(f"{field} is invalid")
    return text


def _validate_pending(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"tool_use_id", "task_path"}:
        raise _error("native Luna pending spawn is invalid")
    _text(value["tool_use_id"], "tool_use_id")
    if value["task_path"] != "/root/luna_worker":
        raise _error("native Luna pending spawn is invalid")


def _validate_luna(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"agent_id", "task_path"}:
        raise _error("native Luna binding is invalid")
    _text(value["agent_id"], "agent_id")
    if value["task_path"] != "/root/luna_worker":
        raise _error("native Luna binding is invalid")


def _validate_state(value: Any, secret: bytes) -> dict[str, Any]:
    del secret  # opaque HMAC tags are compared against recomputed caller tags on access.
    if (
        not isinstance(value, dict)
        or set(value) != {"protocol", "sessions"}
        or value["protocol"] != PROTOCOL
        or not isinstance(value["sessions"], dict)
        or len(value["sessions"]) > _MAX_SESSIONS
    ):
        raise _error("native Luna lifecycle journal is invalid")
    for key, record in value["sessions"].items():
        _hex_tag(key, "session_tag")
        if (
            not isinstance(record, dict)
            or set(record) != {"scope_tag", "authorization", "pending", "luna"}
        ):
            raise _error("native Luna lifecycle journal is invalid")
        _hex_tag(record["scope_tag"], "scope_tag")
        if record["authorization"] not in _AUTH:
            raise _error("native Luna lifecycle journal is invalid")
        _validate_pending(record["pending"])
        _validate_luna(record["luna"])
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_state_unlocked(directory: Path, secret: bytes) -> dict[str, Any]:
    path = directory / _STATE
    if not path.exists():
        return _empty()
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise _error("native Luna lifecycle journal is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise _error("native Luna lifecycle journal is unsafe")
    try:
        return _validate_state(json.loads(path.read_bytes()), secret)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("native Luna lifecycle journal is unreadable") from exc


def _write_state_unlocked(directory: Path, state: Mapping[str, Any]) -> None:
    path = directory / _STATE
    data = canonical_json_bytes(dict(state)) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".native-luna-", dir=directory)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
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
def _locked_state(
    directory: Path, secret: bytes, *, mutate: bool
) -> Iterator[dict[str, Any]]:
    lock = directory / _LOCK
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise _error("native Luna lifecycle lock is unsafe")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX if mutate else fcntl.LOCK_SH)
        state = _read_state_unlocked(directory, secret)
        before = canonical_json_bytes(state)
        yield state
        if mutate and canonical_json_bytes(state) != before:
            _validate_state(state, secret)
            _write_state_unlocked(directory, state)
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _record(scope: str) -> dict[str, Any]:
    return {
        "scope_tag": scope,
        "authorization": "ACTIVE",
        "pending": None,
        "luna": None,
    }


def _lookup(
    state: Mapping[str, Any], secret: bytes, session_id: str
) -> tuple[str, dict[str, Any] | None]:
    key = session_tag(secret, session_id)
    record = state["sessions"].get(key)
    return key, record if isinstance(record, dict) else None


def _compact_for_new_session(state: dict[str, Any], keep_key: str) -> None:
    sessions = state["sessions"]
    for key in list(sessions):
        if key != keep_key and sessions[key]["authorization"] == "REVOKED":
            del sessions[key]
    if keep_key not in sessions and len(sessions) >= _MAX_SESSIONS:
        raise _error("native Luna lifecycle journal active-session capacity is exhausted")


def revoke_stale(
    directory: Path, secret: bytes, session_id: str, turn_id: str
) -> None:
    if not (directory / _STATE).exists():
        return
    current_scope = scope_tag(secret, session_id, turn_id)
    with _locked_state(directory, secret, mutate=True) as state:
        _, record = _lookup(state, secret, session_id)
        if (
            record is not None
            and record["scope_tag"] != current_scope
            and record["authorization"] == "ACTIVE"
        ):
            record["authorization"] = "REVOKED"


def pre_spawn(
    directory: Path,
    secret: bytes,
    session_id: str,
    turn_id: str,
    tool_use_id: str,
    tool_input: Mapping[str, Any],
) -> None:
    path = task_path(tool_input.get("task_name"))
    if tool_input.get("fork_turns") != "none":
        raise _error("luna_worker must be spawned with fork_turns=none")
    tool_use_id = _text(tool_use_id, "tool_use_id")
    current_scope = scope_tag(secret, session_id, turn_id)
    with _locked_state(directory, secret, mutate=True) as state:
        key, record = _lookup(state, secret, session_id)
        _compact_for_new_session(state, key)
        if record is None or record["scope_tag"] != current_scope:
            state["sessions"][key] = _record(current_scope)
            record = state["sessions"][key]
        if (
            record["scope_tag"] != current_scope
            or record["authorization"] != "ACTIVE"
            or record["pending"] is not None
            or record["luna"] is not None
        ):
            raise _error("a Luna worker is already bound or revoked for this root turn")
        record["pending"] = {"tool_use_id": tool_use_id, "task_path": path}


def post_spawn(
    directory: Path,
    secret: bytes,
    session_id: str,
    turn_id: str,
    tool_use_id: str,
    response: Any,
) -> None:
    current_scope = scope_tag(secret, session_id, turn_id)
    deferred_error: RouterStateError | None = None
    with _locked_state(directory, secret, mutate=True) as state:
        _, record = _lookup(state, secret, session_id)
        if (
            record is None
            or record["scope_tag"] != current_scope
            or record["authorization"] != "ACTIVE"
            or not isinstance(record["pending"], dict)
            or record["pending"].get("tool_use_id") != tool_use_id
        ):
            raise _error("unrecognized Luna spawn response")
        parsed = _response(response)
        if (
            not isinstance(parsed, Mapping)
            or parsed.get("task_name") != record["pending"]["task_path"]
        ):
            record["authorization"] = "REVOKED"
            deferred_error = _error("Luna spawn response failed identity verification")
    if deferred_error is not None:
        raise deferred_error


def bind_child(
    directory: Path,
    secret: bytes,
    session_id: str,
    agent_id: str,
    agent_type: str,
) -> None:
    session_id = _text(session_id, "session_id")
    agent_id = _text(agent_id, "agent_id")
    if _text(agent_type, "agent_type") != "luna_worker":
        raise _error("non-Luna child is not eligible")
    deferred_error: RouterStateError | None = None
    with _locked_state(directory, secret, mutate=True) as state:
        _, record = _lookup(state, secret, session_id)
        if (
            record is None
            or record["authorization"] != "ACTIVE"
            or not isinstance(record.get("pending"), dict)
        ):
            deferred_error = _error("Luna child binding cannot be verified")
        elif record.get("luna") is not None:
            record["authorization"] = "REVOKED"
            deferred_error = _error("Luna child is already bound")
        else:
            record["luna"] = {
                "agent_id": agent_id,
                "task_path": record["pending"]["task_path"],
            }
    if deferred_error is not None:
        raise deferred_error


def authorize_luna(
    directory: Path,
    secret: bytes,
    session_id: str,
    agent_id: str,
) -> dict[str, Any]:
    agent_id = _text(agent_id, "agent_id")
    with _locked_state(directory, secret, mutate=False) as state:
        _, record = _lookup(state, secret, session_id)
        if (
            record is None
            or record["authorization"] != "ACTIVE"
            or not isinstance(record.get("luna"), dict)
            or record["luna"].get("agent_id") != agent_id
        ):
            raise _error("Luna parent scope is revoked, mismatched, or unknown")
        return deepcopy(record)


def authorize_parent_operation(
    directory: Path,
    secret: bytes,
    session_id: str,
    turn_id: str,
    tool_name: str,
    tool_input: Mapping[str, Any],
) -> None:
    target = _target(tool_name, tool_input)
    expected_scope = scope_tag(secret, session_id, turn_id)
    with _locked_state(directory, secret, mutate=False) as state:
        _, record = _lookup(state, secret, session_id)
        if (
            record is None
            or record["scope_tag"] != expected_scope
            or record["authorization"] != "ACTIVE"
            or not isinstance(record.get("luna"), dict)
        ):
            raise _error("no active Luna worker may receive lifecycle operations")
        if target not in {record["luna"]["agent_id"], record["luna"]["task_path"]}:
            raise _error("parent lifecycle operation is not bound to the active Luna worker")


def begin_interrupt(
    directory: Path,
    secret: bytes,
    session_id: str,
    turn_id: str,
    tool_name: str,
    tool_input: Mapping[str, Any],
) -> None:
    """Authorize one parent cleanup by revoking first; cleanup result is non-authoritative."""
    target = _target(tool_name, tool_input)
    expected_scope = scope_tag(secret, session_id, turn_id)
    with _locked_state(directory, secret, mutate=True) as state:
        _, record = _lookup(state, secret, session_id)
        if (
            record is None
            or record["scope_tag"] != expected_scope
            or record["authorization"] != "ACTIVE"
            or not isinstance(record.get("luna"), dict)
        ):
            raise _error("no active Luna worker may be cleaned up")
        if target not in {record["luna"]["agent_id"], record["luna"]["task_path"]}:
            raise _error("Luna cleanup target is unauthorized")
        record["authorization"] = "REVOKED"


def stop_once(
    directory: Path, secret: bytes, session_id: str, turn_id: str
) -> bool:
    """Durably revoke the current root scope. The Hook must never create a continuation."""
    expected_scope = scope_tag(secret, session_id, turn_id)
    changed = False
    with _locked_state(directory, secret, mutate=True) as state:
        _, record = _lookup(state, secret, session_id)
        if (
            record is not None
            and record["scope_tag"] == expected_scope
            and record["authorization"] == "ACTIVE"
        ):
            record["authorization"] = "REVOKED"
            changed = True
    return changed


def _response(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value
