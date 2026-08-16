"""Fail-closed, turn-scoped native Luna lifecycle journal for Codex V2."""
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
from typing import Any, Iterator, Mapping

from .protocol import canonical_json_bytes
from .state import RouterStateError

PROTOCOL = "codex-router/native-luna-safety-v2"
_STATE = "native-luna-safety-v2.json"
_LOCK = "native-luna-safety-v2.lock"
_AUTH = {"ACTIVE", "REVOKED"}
_CLEANUP = {"NONE", "REQUESTED", "OBSERVED", "UNVERIFIED"}
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


def scope_mac(secret: bytes, session_id: str, turn_id: str) -> str:
    return hmac.new(
        secret,
        canonical_json_bytes({"session_id": session_id, "turn_id": turn_id}),
        hashlib.sha256,
    ).hexdigest()


def task_path(task_name: str) -> str:
    name = _text(task_name, "task_name")
    if name != "luna_worker":
        raise _error("only luna_worker may be spawned")
    return "/root/luna_worker"


def _key(session_id: str, turn_id: str) -> str:
    return hashlib.sha256((session_id + "\0" + turn_id).encode()).hexdigest()


def _target(tool_name: str, tool_input: Mapping[str, Any]) -> str:
    field = _TARGET_FIELD.get(tool_name)
    if field is None:
        raise _error("unsupported parent lifecycle operation")
    return _text(tool_input.get(field), field)


def _empty() -> dict[str, Any]:
    return {"protocol": PROTOCOL, "bindings": {}}


def _validate_state(value: Any, secret: bytes) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"protocol", "bindings"}
        or value["protocol"] != PROTOCOL
        or not isinstance(value["bindings"], dict)
    ):
        raise _error("native Luna lifecycle journal is invalid")
    for key, record in value["bindings"].items():
        if not isinstance(key, str) or not isinstance(record, dict):
            raise _error("native Luna lifecycle journal is invalid")
        scope = record.get("scope")
        if not isinstance(scope, dict) or set(scope) != {"session_id", "turn_id", "mac"}:
            raise _error("native Luna lifecycle journal is invalid")
        session_id = _text(scope["session_id"], "session_id")
        turn_id = _text(scope["turn_id"], "turn_id")
        if key != _key(session_id, turn_id) or not hmac.compare_digest(
            scope["mac"], scope_mac(secret, session_id, turn_id)
        ):
            raise _error("native Luna lifecycle journal authentication failed")
        if (
            record.get("authorization") not in _AUTH
            or record.get("cleanup") not in _CLEANUP
            or not isinstance(record.get("stop_blocked"), bool)
        ):
            raise _error("native Luna lifecycle journal is invalid")
        for optional in ("pending", "luna"):
            item = record.get(optional)
            if item is not None and not isinstance(item, dict):
                raise _error("native Luna lifecycle journal is invalid")
    return value


@contextmanager
def _journal(directory: Path, secret: bytes) -> Iterator[dict[str, Any]]:
    lock = directory / _LOCK
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        path = directory / _STATE
        if path.exists():
            meta = path.lstat()
            if (
                not stat.S_ISREG(meta.st_mode)
                or stat.S_ISLNK(meta.st_mode)
                or meta.st_uid != os.geteuid()
                or stat.S_IMODE(meta.st_mode) != 0o600
            ):
                raise _error("native Luna lifecycle journal is unsafe")
            try:
                value = _validate_state(json.loads(path.read_bytes()), secret)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _error("native Luna lifecycle journal is unreadable") from exc
        else:
            value = _empty()
        yield value
        data = canonical_json_bytes(value) + b"\n"
        temp_fd, temp_name = tempfile.mkstemp(prefix=".native-luna-", dir=directory)
        try:
            os.fchmod(temp_fd, 0o600)
            os.write(temp_fd, data)
            os.fsync(temp_fd)
            os.close(temp_fd)
            os.replace(temp_name, path)
            os.chmod(path, 0o600)
        finally:
            try:
                os.close(temp_fd)
            except OSError:
                pass
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    finally:
        os.close(fd)


def _record(secret: bytes, session_id: str, turn_id: str) -> dict[str, Any]:
    return {
        "scope": {
            "session_id": session_id,
            "turn_id": turn_id,
            "mac": scope_mac(secret, session_id, turn_id),
        },
        "authorization": "ACTIVE",
        "cleanup": "NONE",
        "stop_blocked": False,
        "pending": None,
        "luna": None,
    }


def revoke_stale(
    directory: Path, secret: bytes, session_id: str, turn_id: str
) -> None:
    if not (directory / _STATE).exists():
        return
    with _journal(directory, secret) as state:
        for record in state["bindings"].values():
            scope = record["scope"]
            if (
                scope["session_id"] == session_id
                and scope["turn_id"] != turn_id
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
    with _journal(directory, secret) as state:
        for record in state["bindings"].values():
            if (
                record["scope"]["session_id"] == session_id
                and record["scope"]["turn_id"] != turn_id
                and record["authorization"] == "ACTIVE"
            ):
                record["authorization"] = "REVOKED"
        key = _key(session_id, turn_id)
        record = state["bindings"].setdefault(
            key, _record(secret, session_id, turn_id)
        )
        if (
            record["authorization"] != "ACTIVE"
            or record["pending"] is not None
            or record["luna"] is not None
        ):
            raise _error("a Luna worker is already bound for this turn")
        record["pending"] = {
            "tool_use_id": tool_use_id,
            "task_path": path,
            "confirmed": False,
        }


def post_spawn(
    directory: Path,
    secret: bytes,
    session_id: str,
    turn_id: str,
    tool_use_id: str,
    response: Any,
) -> None:
    deferred_error: RouterStateError | None = None
    with _journal(directory, secret) as state:
        record = state["bindings"].get(_key(session_id, turn_id))
        if (
            record is None
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
        else:
            record["pending"]["confirmed"] = True
    if deferred_error is not None:
        raise deferred_error


def bind_child(
    directory: Path,
    secret: bytes,
    event: Mapping[str, Any],
    child_metadata: Mapping[str, Any],
) -> None:
    agent_id = _text(event.get("agent_id"), "agent_id")
    agent_type = _text(event.get("agent_type"), "agent_type")
    if agent_type != "luna_worker":
        raise _error("non-Luna child is not eligible")
    parent = _text(child_metadata.get("parent_thread_id"), "parent_thread_id")
    path = _text(child_metadata.get("agent_path"), "agent_path")
    deferred_error: RouterStateError | None = None
    with _journal(directory, secret) as state:
        parent_candidates = [
            record
            for record in state["bindings"].values()
            if record["authorization"] == "ACTIVE"
            and isinstance(record["pending"], dict)
            and record["pending"].get("confirmed") is True
            and record["scope"]["session_id"] == parent
        ]
        candidates = [
            record
            for record in parent_candidates
            if path == "/root/luna_worker"
            and record["pending"].get("task_path") == path
        ]
        if len(candidates) != 1:
            for record in parent_candidates:
                record["authorization"] = "REVOKED"
            deferred_error = _error("Luna child binding cannot be verified")
        else:
            record = candidates[0]
            if record["luna"] is not None:
                record["authorization"] = "REVOKED"
                deferred_error = _error("Luna child is already bound")
            else:
                record["luna"] = {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "task_path": path,
                }
    if deferred_error is not None:
        raise deferred_error


def authorize_luna(
    directory: Path,
    secret: bytes,
    session_id: str,
    turn_id: str,
    agent_id: str,
) -> dict[str, Any]:
    agent_id = _text(agent_id, "agent_id")
    deferred_error: RouterStateError | None = None
    authorized: dict[str, Any] | None = None
    with _journal(directory, secret) as state:
        key = _key(session_id, turn_id)
        current = state["bindings"].get(key)
        if (
            isinstance(current, dict)
            and current["authorization"] == "ACTIVE"
            and isinstance(current.get("luna"), dict)
            and current["luna"].get("agent_id") == agent_id
        ):
            authorized = dict(current)
        else:
            for record in state["bindings"].values():
                luna = record.get("luna")
                if (
                    isinstance(luna, dict)
                    and luna.get("agent_id") == agent_id
                    and record["authorization"] == "ACTIVE"
                ):
                    record["authorization"] = "REVOKED"
            if isinstance(current, dict) and current["authorization"] == "ACTIVE":
                current["authorization"] = "REVOKED"
            deferred_error = _error("Luna parent scope is revoked, mismatched, or unknown")
    if deferred_error is not None:
        raise deferred_error
    if authorized is None:
        raise _error("Luna authorization is unavailable")
    return authorized


def begin_interrupt(
    directory: Path,
    secret: bytes,
    session_id: str,
    turn_id: str,
    tool_name: str,
    tool_input: Mapping[str, Any],
) -> None:
    target = _target(tool_name, tool_input)
    with _journal(directory, secret) as state:
        record = state["bindings"].get(_key(session_id, turn_id))
        if not isinstance(record, dict) or not isinstance(record.get("luna"), dict):
            raise _error("no bound Luna worker may be interrupted")
        if target not in {record["luna"]["agent_id"], record["luna"]["task_path"]}:
            raise _error("Luna interrupt is unauthorized")
        if record["authorization"] == "ACTIVE" and record["cleanup"] == "NONE":
            record["authorization"] = "REVOKED"
            record["cleanup"] = "REQUESTED"
            return
        if (
            record["authorization"] == "REVOKED"
            and record["stop_blocked"]
            and record["cleanup"] == "NONE"
        ):
            record["cleanup"] = "REQUESTED"
            return
        raise _error("Luna interrupt is unauthorized")


def authorize_parent_operation(
    directory: Path,
    secret: bytes,
    session_id: str,
    turn_id: str,
    tool_name: str,
    tool_input: Mapping[str, Any],
) -> None:
    target = _target(tool_name, tool_input)
    with _journal(directory, secret) as state:
        record = state["bindings"].get(_key(session_id, turn_id))
        if (
            not isinstance(record, dict)
            or record["authorization"] != "ACTIVE"
            or not isinstance(record.get("luna"), dict)
        ):
            raise _error("no active Luna worker may receive lifecycle operations")
        if target not in {record["luna"]["agent_id"], record["luna"]["task_path"]}:
            raise _error("parent lifecycle operation is not bound to the active Luna worker")


def finish_interrupt(
    directory: Path,
    secret: bytes,
    session_id: str,
    turn_id: str,
    response: Any,
) -> None:
    with _journal(directory, secret) as state:
        record = state["bindings"].get(_key(session_id, turn_id))
        if not isinstance(record, dict) or record["cleanup"] != "REQUESTED":
            raise _error("unrecognized Luna interrupt response")
        parsed = _response(response)
        record["cleanup"] = (
            "OBSERVED"
            if isinstance(parsed, Mapping) and "previous_status" in parsed
            else "UNVERIFIED"
        )


def stop_once(
    directory: Path, secret: bytes, session_id: str, turn_id: str
) -> bool:
    with _journal(directory, secret) as state:
        record = state["bindings"].get(_key(session_id, turn_id))
        if (
            not isinstance(record, dict)
            or record["luna"] is None
            or record["authorization"] != "ACTIVE"
            or record["stop_blocked"]
        ):
            return False
        record["authorization"] = "REVOKED"
        record["stop_blocked"] = True
        return True


def _response(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value
