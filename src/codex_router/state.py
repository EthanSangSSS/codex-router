from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Iterator, Mapping
import uuid

from .protocol import (
    RUN_PROTOCOL,
    WEB_RESPONSE_PREFIX,
    ProtocolError,
    build_stage_packet,
    canonical_json_bytes,
    digest_json,
    failure_digest as compute_failure_digest,
    normalize_content,
    submission_digest,
    validate_stage_packet,
    validate_web_response,
)
from .security import (
    sanitize_failure_code,
    sanitize_failure_summary,
    secure_web_payload,
)
from .types import TransitionResult


ERROR_EXIT_CODES = {
    "conflict": 20,
    "invalid-transition": 21,
    "revision-mismatch": 22,
    "packet-mismatch": 23,
    "marker-mismatch": 24,
    "invalid-input": 25,
    "run-not-found": 26,
    "unsafe-state-root": 27,
    "state-corrupt": 28,
    "profile-mismatch": 29,
    "state-root-unowned": 30,
}

_UUID_DRIVER_CONTEXT_PATTERN = re.compile(
    r"ctx-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_HMAC_DRIVER_CONTEXT_PATTERN = re.compile(r"ctx-[0-9a-f]{64}")
_RUN_ID_PATTERN = re.compile(r"run-[A-Za-z0-9][A-Za-z0-9._-]*")
_EVENT_ID_PATTERN = re.compile(r"event-[0-9a-f]{64}")
_PROMPT_DIGEST_PATTERN = re.compile(r"hmac-sha256:[0-9a-f]{64}")
_DRIVER_TYPES = frozenset(("codex_app", "offline_pipeline"))
_PROFILE_PROTOCOL = "codex-router/profile/v1"
_STATE_ROOT_PROTOCOL = "codex-router/state-root/v1"
_STATE_ROOT_MARKER = ".codex-router-root.json"
_ROOT_ID_PATTERN = re.compile(
    r"root-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_LOCAL_STAGES = ("local_sol", "luna")
_STAGE_FILE_NAMES = {
    "local_sol": "local-sol.json",
    "web_sol": "web-sol.json",
    "luna": "luna.json",
}
_STAGE_SOURCE_REVISIONS = {"local_sol": 0, "web_sol": 1, "luna": 2}
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_SECURITY_CATEGORY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
_LOCAL_EXECUTION_FIELDS = (
    "requested_model",
    "requested_reasoning",
    "reported_model",
    "reported_reasoning",
    "verification",
    "thread_id",
    "driver_context_id",
    "packet_digest",
    "profile_id",
    "codex_home",
    "codex_sqlite_home",
    "codex_binary_realpath",
    "codex_binary_sha256",
    "app_server_version",
    "workspace_access",
)
_WEB_EXECUTION_FIELDS = (
    "driver_context_id",
    "web_context_ref",
    "context_mode",
    "context_scope",
    "context_isolation",
    "model_claimed",
    "reasoning_claimed",
    "verification",
    "packet_digest",
)
_OFFLINE_EXECUTION_FIELDS = (
    "driver_context_id",
    "packet_digest",
    "verification",
    "network_used",
)
class RouterStateError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        run_id: str | None = None,
        stage: str | None = None,
        revision: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = ERROR_EXIT_CODES[code]
        self.run_id = run_id
        self.stage = stage
        self.revision = revision


def _raise_invalid(message: str) -> None:
    raise RouterStateError("invalid-input", message)


def _validate_driver_context_id(driver_context_id: str) -> None:
    if not isinstance(driver_context_id, str):
        _raise_invalid("driver_context_id must be text")
    if _HMAC_DRIVER_CONTEXT_PATTERN.fullmatch(driver_context_id):
        return
    if not _UUID_DRIVER_CONTEXT_PATTERN.fullmatch(driver_context_id):
        _raise_invalid("driver_context_id must use a supported canonical identity")
    try:
        parsed = uuid.UUID(driver_context_id[4:])
    except ValueError as error:
        raise RouterStateError("invalid-input", "invalid driver_context_id") from error
    if str(parsed) != driver_context_id[4:]:
        _raise_invalid("driver_context_id must use canonical lowercase UUID text")


def _validate_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        _raise_invalid("invalid run_id")


def _resolve_state_root(state_root: Path | str) -> Path:
    unresolved = Path(os.path.abspath(Path(state_root).expanduser()))
    if unresolved.is_symlink():
        raise RouterStateError("state-root-unowned", "Router state root must not be a symlink")
    candidate = unresolved.resolve(strict=False)
    live_root = (Path.home() / ".codex").resolve(strict=False)
    if candidate == live_root or live_root in candidate.parents:
        raise RouterStateError(
            "unsafe-state-root", "Router state must not use the live Codex profile"
        )
    return candidate


def _resolve_binary(codex_binary: Path | str) -> tuple[Path, str]:
    candidate = Path(codex_binary).expanduser()
    if not candidate.is_absolute():
        _raise_invalid("codex_binary must be an absolute path")
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise RouterStateError("invalid-input", "codex_binary does not exist") from error
    if candidate.is_symlink():
        _raise_invalid("codex_binary must not be a symlink")
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        _raise_invalid("codex_binary must be an executable file")
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RouterStateError("invalid-input", "codex_binary cannot be read") from error
    return resolved, "sha256:" + digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _state_root_error(message: str) -> None:
    raise RouterStateError("state-root-unowned", message)


def _validate_private_directory(path: Path, *, state_root: bool = False) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise
    label = "Router state root" if state_root else "Router-owned directory"
    if stat.S_ISLNK(metadata.st_mode):
        if state_root:
            _state_root_error(f"{label} must not be a symlink")
        raise RouterStateError("state-corrupt", f"{label} must not be a symlink")
    if not stat.S_ISDIR(metadata.st_mode):
        if state_root:
            _state_root_error(f"{label} must be a directory")
        raise RouterStateError("state-corrupt", f"{label} must be a directory")
    if metadata.st_uid != os.geteuid():
        if state_root:
            _state_root_error(f"{label} must be owned by the current user")
        raise RouterStateError("state-corrupt", f"{label} has the wrong owner")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        if state_root:
            _state_root_error(f"{label} must not grant group or other permissions")
        raise RouterStateError("state-corrupt", f"{label} is not private")


def _ensure_private_directory(path: Path, *, parents: bool = False) -> None:
    if os.path.lexists(path):
        _validate_private_directory(path)
        return
    if not parents:
        path.mkdir(mode=0o700, exist_ok=False)
        _fsync_directory(path.parent)
        return
    missing: list[Path] = []
    current = path
    while not os.path.lexists(current):
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=False)
        _fsync_directory(directory.parent)


def _valid_root_marker(marker_path: Path) -> bool:
    try:
        metadata = marker_path.lstat()
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > 4096
    ):
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(marker, dict)
        and set(marker) == {"protocol", "owner", "root_id", "created_by"}
        and marker.get("protocol") == _STATE_ROOT_PROTOCOL
        and marker.get("owner") == "codex-router"
        and marker.get("created_by") == "codex-router"
        and isinstance(marker.get("root_id"), str)
        and _ROOT_ID_PATTERN.fullmatch(marker["root_id"]) is not None
    )


def _legacy_root_is_recognized(state_root: Path) -> bool:
    for entry in state_root.iterdir():
        if entry.name == ".profiles":
            if entry.is_symlink() or not entry.is_dir():
                return False
            continue
        if _RUN_ID_PATTERN.fullmatch(entry.name):
            if entry.is_symlink() or not entry.is_dir():
                return False
            continue
        return False
    return True


def prepare_state_root(state_root: Path | str) -> Path:
    resolved = _resolve_state_root(state_root)
    marker_path = resolved / _STATE_ROOT_MARKER
    if not os.path.lexists(resolved):
        _ensure_private_directory(resolved, parents=True)
        _atomic_json(
            marker_path,
            {
                "protocol": _STATE_ROOT_PROTOCOL,
                "owner": "codex-router",
                "root_id": f"root-{uuid.uuid4()}",
                "created_by": "codex-router",
            },
        )
        return resolved

    _validate_private_directory(resolved, state_root=True)
    if os.path.lexists(marker_path):
        if not _valid_root_marker(marker_path):
            _state_root_error("Router state root ownership marker is invalid")
        return resolved
    if not _legacy_root_is_recognized(resolved):
        _state_root_error("existing directory is not a recognized Router state root")
    _atomic_json(
        marker_path,
        {
            "protocol": _STATE_ROOT_PROTOCOL,
            "owner": "codex-router",
            "root_id": f"root-{uuid.uuid4()}",
            "created_by": "codex-router",
        },
    )
    return resolved


@contextmanager
def _exclusive_run_lock(run_dir: Path) -> Iterator[None]:
    lock_path = run_dir / ".lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _exclusive_event_lock(state_root: Path, run_id: str) -> Iterator[None]:
    lock_directory = state_root / ".event-locks"
    try:
        lock_directory.mkdir(mode=0o700, exist_ok=False)
        _fsync_directory(state_root)
    except FileExistsError:
        pass
    _validate_private_directory(lock_directory)
    lock_path = lock_directory / f"{run_id}.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise RouterStateError("state-corrupt", "event lock is unsafe") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise RouterStateError("state-corrupt", "event lock is unsafe")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _atomic_bytes(path: Path, content: bytes) -> None:
    _ensure_private_directory(path.parent, parents=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
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


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_bytes(path, canonical_json_bytes(value) + b"\n")


def _commit_state(run_dir: Path, state: Mapping[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".state.json.", dir=run_dir)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(state) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, run_dir / "state.json")
        _fsync_directory(run_dir)
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


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid.uuid4().hex[:12]}"


def _new_packet_id() -> str:
    return f"packet-{uuid.uuid4().hex}"


def _create_profile(
    *,
    state_root: Path,
    driver_context_id: str,
    run_id: str,
    stage: str,
    binary_realpath: Path,
    binary_sha256: str,
) -> dict[str, Any]:
    profile_root = state_root / ".profiles" / driver_context_id / run_id / stage
    codex_home = profile_root / "codex-home"
    sqlite_home = profile_root / "sqlite-home"
    for directory in (profile_root, codex_home, sqlite_home):
        _ensure_private_directory(directory, parents=True)
    marker_path = profile_root / "profile.json"
    marker = {
        "profile_id": f"profile-{uuid.uuid4()}",
        "protocol": _PROFILE_PROTOCOL,
        "driver_context_id": driver_context_id,
        "run_id": run_id,
        "stage": stage,
        "owner": "codex-router",
        "workspace_access": "read_only",
        "codex_home": str(codex_home),
        "codex_sqlite_home": str(sqlite_home),
        "ownership_marker": str(marker_path),
        "codex_binary_realpath": str(binary_realpath),
        "codex_binary_sha256": binary_sha256,
    }
    _atomic_json(marker_path, marker)
    return marker


def _initial_packet(
    *,
    driver_context_id: str,
    run_id: str,
    task: str,
    role_config: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> dict[str, Any]:
    return build_stage_packet(
        driver_context_id=driver_context_id,
        run_id=run_id,
        packet_id=_new_packet_id(),
        target_stage="local_sol",
        source_revision=0,
        payload={
            "task": task,
            "role": deepcopy(role_config["local_sol"]),
            "permission": "read_only",
            "execution_profile": deepcopy(profiles["local_sol"]),
            "output_contract": {"type": "text"},
        },
    )


def _validate_accepted_record(
    *,
    state: Mapping[str, Any],
    stage: str,
    record: Mapping[str, Any],
    failure: bool,
) -> None:
    driver_context_id = state["driver"]["driver_context_id"]
    run_id = state["run_id"]
    if failure and record.get("execution") == {
        "verification": "locally_verified",
        "source": "router_security_gate",
        "network_used": False,
    }:
        evidence = record.get("security")
        failure_value = record.get("failure")
        expected_digest = _security_gate_failure_digest(
            driver_context_id=driver_context_id,
            run_id=run_id,
            evidence=evidence,
        )
        if (
            stage != "web_sol"
            or set(record)
            != {
                "stage",
                "source_revision",
                "failure_digest",
                "failure",
                "execution",
                "telemetry",
                "security",
            }
            or record.get("stage") != "web_sol"
            or record.get("source_revision") != 1
            or record.get("failure_digest") != expected_digest
            or failure_value
            != {
                "code": "router-security-gate",
                "summary": "Web payload blocked by Router security policy",
            }
            or record.get("telemetry") != {}
        ):
            raise ProtocolError("Router security failure record is invalid")
        return
    packet = record.get("packet")
    validate_stage_packet(
        packet,
        expected_driver_context_id=driver_context_id,
        expected_run_id=run_id,
        expected_target_stage=stage,
        expected_source_revision=_STAGE_SOURCE_REVISIONS[stage],
    )
    if (
        record.get("stage") != stage
        or record.get("source_revision") != _STAGE_SOURCE_REVISIONS[stage]
        or record.get("packet_digest") != packet["packet_digest"]
        or not isinstance(record.get("execution"), Mapping)
        or not isinstance(record.get("telemetry"), Mapping)
    ):
        raise ProtocolError("accepted stage record identity is invalid")
    if failure:
        evidence = record.get("failure")
        if (
            not isinstance(evidence, Mapping)
            or not isinstance(evidence.get("code"), str)
            or not isinstance(evidence.get("summary"), str)
        ):
            raise ProtocolError("accepted failure record is invalid")
        stored_digest = record.get("failure_digest")
        recomputed = compute_failure_digest(
            driver_context_id,
            run_id,
            stage,
            packet["packet_digest"],
            evidence,
            record["execution"],
        )
    else:
        if not isinstance(record.get("content"), str):
            raise ProtocolError("accepted submission record is invalid")
        stored_digest = record.get("submission_digest")
        recomputed = submission_digest(
            driver_context_id,
            run_id,
            stage,
            packet["packet_digest"],
            record["content"],
            record["execution"],
        )
    if (
        not isinstance(stored_digest, str)
        or _DIGEST_PATTERN.fullmatch(stored_digest) is None
        or not hmac.compare_digest(stored_digest, recomputed)
    ):
        raise ProtocolError("accepted stage record digest is invalid")
    canonical_json_bytes(record["telemetry"])


def _validate_state_packets(state: Mapping[str, Any], run_id: str) -> None:
    try:
        driver = state["driver"]
        driver_context_id = driver["driver_context_id"]
        if not isinstance(driver, Mapping) or not isinstance(driver_context_id, str):
            raise ProtocolError("canonical driver identity is invalid")
        submissions = state["submissions"]
        failures = state["failures"]
        if not isinstance(submissions, Mapping) or not isinstance(failures, Mapping):
            raise ProtocolError("canonical stage records are invalid")
        for collection, is_failure in ((submissions, False), (failures, True)):
            for stage, record in collection.items():
                if stage not in _STAGE_SOURCE_REVISIONS or not isinstance(record, Mapping):
                    raise ProtocolError("canonical stage record is invalid")
                _validate_accepted_record(
                    state=state, stage=stage, record=record, failure=is_failure
                )
        if "web_security" in state:
            _validate_security_evidence(state["web_security"])
        gate_failure = failures.get("web_sol")
        if (
            isinstance(gate_failure, Mapping)
            and gate_failure.get("execution", {}).get("source")
            == "router_security_gate"
            and gate_failure.get("security") != state.get("web_security")
        ):
            raise ProtocolError("Router security evidence is inconsistent")
        packet = state.get("next_packet")
        if packet is None:
            if state.get("next_stage") is not None:
                raise ProtocolError("canonical next packet is missing")
        else:
            validate_stage_packet(
                packet,
                expected_driver_context_id=driver_context_id,
                expected_run_id=run_id,
                expected_target_stage=state.get("next_stage"),
                expected_source_revision=state.get("revision"),
            )
    except (KeyError, TypeError, ValueError, UnicodeEncodeError, ProtocolError) as error:
        raise RouterStateError(
            "state-corrupt", "canonical packet integrity validation failed", run_id=run_id
        ) from error


def _projection_payloads(state: Mapping[str, Any]) -> dict[Path, bytes]:
    _validate_state_packets(state, state.get("run_id", "invalid"))
    request = {
        "protocol": RUN_PROTOCOL,
        "run_id": state["run_id"],
        "driver_context_id": state["driver"]["driver_context_id"],
        "request": state["request"],
    }
    history = state["history"]
    event_bytes = b"".join(canonical_json_bytes(event) + b"\n" for event in history)
    payloads = {
        Path("request.json"): canonical_json_bytes(request) + b"\n",
        Path("events.jsonl"): event_bytes,
    }
    packets = [
        record["packet"]
        for record in (*state["submissions"].values(), *state["failures"].values())
        if isinstance(record, Mapping) and isinstance(record.get("packet"), Mapping)
    ]
    packet = state.get("next_packet")
    if isinstance(packet, Mapping):
        packets.append(packet)
    for packet in packets:
        payloads[Path("packets") / f"{packet['packet_id']}.json"] = (
            canonical_json_bytes(packet) + b"\n"
        )
    for stage, record in state["submissions"].items():
        projection = {
            "protocol": RUN_PROTOCOL,
            "run_id": state["run_id"],
            "stage": stage,
            "status": "submitted",
            "submission": record,
        }
        payloads[Path(_STAGE_FILE_NAMES[stage])] = canonical_json_bytes(projection) + b"\n"
    for stage, record in state["failures"].items():
        projection = {
            "protocol": RUN_PROTOCOL,
            "run_id": state["run_id"],
            "stage": stage,
            "status": "failed",
            "failure": record,
        }
        payloads[Path(_STAGE_FILE_NAMES[stage])] = canonical_json_bytes(projection) + b"\n"
    if state["status"] == "completed":
        result = {
            "protocol": RUN_PROTOCOL,
            "run_id": state["run_id"],
            "revision": state["revision"],
            "status": "completed",
            "result": state["final_result"],
        }
        payloads[Path("result.json")] = canonical_json_bytes(result) + b"\n"
    return payloads


def _rebuild_projections(run_dir: Path, state: Mapping[str, Any]) -> None:
    for relative_path, expected in _projection_payloads(state).items():
        path = run_dir / relative_path
        try:
            current = path.read_bytes()
        except FileNotFoundError:
            current = None
        if current != expected:
            _atomic_bytes(path, expected)
        elif path.is_file():
            os.chmod(path, 0o600)


def _load_state(run_dir: Path, run_id: str) -> dict[str, Any]:
    state_path = run_dir / "state.json"
    try:
        raw = state_path.read_bytes()
    except FileNotFoundError as error:
        raise RouterStateError(
            "state-corrupt", "run directory has no canonical state", run_id=run_id
        ) from error
    try:
        state = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RouterStateError(
            "state-corrupt", "canonical state is not valid JSON", run_id=run_id
        ) from error
    if not isinstance(state, dict):
        raise RouterStateError("state-corrupt", "canonical state must be an object", run_id=run_id)
    if state.get("protocol") != RUN_PROTOCOL or state.get("run_id") != run_id:
        raise RouterStateError("state-corrupt", "canonical state identity mismatch", run_id=run_id)
    required = (
        "driver",
        "status",
        "revision",
        "next_stage",
        "request",
        "role_config",
        "profiles",
        "submissions",
        "failures",
        "next_packet",
        "final_result",
        "history",
    )
    if any(key not in state for key in required):
        raise RouterStateError("state-corrupt", "canonical state is incomplete", run_id=run_id)
    _validate_state_packets(state, run_id)
    return state


def _result(
    run_dir: Path,
    state: Mapping[str, Any],
    *,
    idempotent: bool = False,
    projection_warnings: tuple[str, ...] = (),
) -> TransitionResult:
    packet = state.get("next_packet")
    packet_path = None
    if packet is not None:
        packet_path = run_dir / "packets" / f"{packet['packet_id']}.json"
    return TransitionResult(
        run_id=state["run_id"],
        run_dir=run_dir,
        revision=state["revision"],
        status=state["status"],
        next_stage=state["next_stage"],
        stage_packet_path=packet_path,
        idempotent=idempotent,
        projection_warnings=projection_warnings,
    )


def _normalize_execution(
    *,
    state: Mapping[str, Any],
    stage: str,
    execution: Mapping[str, Any],
    driver_context_id: str,
    packet_digest_value: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(execution, Mapping):
        _raise_invalid("execution must be an object")
    driver_type = state["driver"]["driver_type"]
    if driver_type == "offline_pipeline":
        fields = _OFFLINE_EXECUTION_FIELDS
        stable = {name: deepcopy(execution[name]) for name in fields if name in execution}
        required = {
            "driver_context_id": driver_context_id,
            "packet_digest": packet_digest_value,
            "verification": "fake_offline",
            "network_used": False,
        }
        if any(stable.get(name) != value for name, value in required.items()):
            raise RouterStateError(
                "profile-mismatch", "offline execution evidence does not match the run"
            )
    elif stage in _LOCAL_STAGES:
        fields = _LOCAL_EXECUTION_FIELDS
        stable = {name: deepcopy(execution[name]) for name in fields if name in execution}
        profile = state["profiles"][stage]
        required = {
            "verification": "app_server_reported",
            "driver_context_id": driver_context_id,
            "packet_digest": packet_digest_value,
            "profile_id": profile["profile_id"],
            "codex_home": profile["codex_home"],
            "codex_sqlite_home": profile["codex_sqlite_home"],
            "codex_binary_realpath": profile["codex_binary_realpath"],
            "codex_binary_sha256": profile["codex_binary_sha256"],
            "workspace_access": "read_only",
        }
        role = state["role_config"][stage]
        for role_field in ("requested_model", "requested_reasoning"):
            if role_field in role:
                required[role_field] = role[role_field]
        if any(stable.get(name) != value for name, value in required.items()):
            raise RouterStateError(
                "profile-mismatch", "App Server execution evidence does not match the profile"
            )
        for required_text in ("thread_id", "app_server_version"):
            if not isinstance(stable.get(required_text), str) or not stable[required_text]:
                raise RouterStateError(
                    "profile-mismatch", "App Server execution evidence is incomplete"
                )
        if not isinstance(stable.get("reported_model"), str) or not stable[
            "reported_model"
        ].strip():
            raise RouterStateError(
                "profile-mismatch", "App Server reported_model evidence is incomplete"
            )
        if "reported_reasoning" not in stable or (
            stable["reported_reasoning"] is not None
            and (
                not isinstance(stable["reported_reasoning"], str)
                or not stable["reported_reasoning"].strip()
            )
        ):
            raise RouterStateError(
                "profile-mismatch", "App Server reported_reasoning evidence is incomplete"
            )
    elif stage == "web_sol":
        fields = _WEB_EXECUTION_FIELDS
        stable = {name: deepcopy(execution[name]) for name in fields if name in execution}
        required = {
            "driver_context_id": driver_context_id,
            "packet_digest": packet_digest_value,
            "context_mode": "continuous",
            "context_scope": "driver_context_id",
            "context_isolation": "operator_managed",
            "verification": "operator_attested",
        }
        role = state["role_config"][stage]
        for role_field in ("model_claimed", "reasoning_claimed"):
            if role_field in role:
                required[role_field] = role[role_field]
        if any(stable.get(name) != value for name, value in required.items()):
            raise RouterStateError(
                "profile-mismatch", "Web execution attestation does not match the run"
            )
        if not isinstance(stable.get("web_context_ref"), str) or not stable["web_context_ref"]:
            raise RouterStateError("profile-mismatch", "Web execution attestation is incomplete")
    else:
        raise RouterStateError("invalid-transition", "unknown stage", stage=stage)

    telemetry: dict[str, Any] = {}
    if "duration_ms" in execution:
        duration = execution["duration_ms"]
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration < 0
            or duration != duration
            or duration in (float("inf"), float("-inf"))
        ):
            _raise_invalid("duration_ms must be a finite non-negative number")
        telemetry["duration_ms"] = duration
    try:
        canonical_json_bytes(stable)
        canonical_json_bytes(telemetry)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise RouterStateError("invalid-input", "execution evidence is not canonical JSON") from error
    return stable, telemetry


def _proposed_web_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task": state["request"]["task"],
        "local_sol_output": state["submissions"]["local_sol"]["content"],
        "role": deepcopy(state["role_config"]["web_sol"]),
        "permission": "no_local_filesystem",
        "response_marker_contract": {
            "prefix": WEB_RESPONSE_PREFIX,
            "placement": "first_nonempty_line",
            "occurrences": 1,
            "required_fields": [
                "driver_context_id",
                "run_id",
                "stage",
                "revision",
                "packet_id",
                "packet_digest",
            ],
        },
        "output_contract": {"type": "text"},
    }


def _build_next_packet(
    state: Mapping[str, Any],
    completed_stage: str,
    *,
    secured_web_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    driver_context_id = state["driver"]["driver_context_id"]
    run_id = state["run_id"]
    task = state["request"]["task"]
    if completed_stage == "local_sol":
        if not isinstance(secured_web_payload, Mapping):
            raise ProtocolError("secured Web payload is required")
        return build_stage_packet(
            driver_context_id=driver_context_id,
            run_id=run_id,
            packet_id=_new_packet_id(),
            target_stage="web_sol",
            source_revision=1,
            payload=deepcopy(dict(secured_web_payload)),
        )
    if completed_stage == "web_sol":
        return build_stage_packet(
            driver_context_id=driver_context_id,
            run_id=run_id,
            packet_id=_new_packet_id(),
            target_stage="luna",
            source_revision=2,
            payload={
                "task": task,
                "local_sol_output": state["submissions"]["local_sol"]["content"],
                "web_sol_output": state["submissions"]["web_sol"]["content"],
                "role": deepcopy(state["role_config"]["luna"]),
                "permission": "no_repository_writes",
                "output_contract": {"type": "text"},
            },
        )
    return None


def _validate_security_evidence(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "decision",
        "categories",
        "counts",
    }:
        raise ProtocolError("Router security evidence schema is invalid")
    decision = value.get("decision")
    categories = value.get("categories")
    counts = value.get("counts")
    if decision not in ("allow", "redacted", "block"):
        raise ProtocolError("Router security decision is invalid")
    if (
        not isinstance(categories, list)
        or categories != sorted(set(categories))
        or any(
            not isinstance(category, str)
            or _SECURITY_CATEGORY_PATTERN.fullmatch(category) is None
            for category in categories
        )
    ):
        raise ProtocolError("Router security categories are invalid")
    if (
        not isinstance(counts, Mapping)
        or set(counts) != set(categories)
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count <= 0
            for count in counts.values()
        )
    ):
        raise ProtocolError("Router security counts are invalid")
    if (decision == "allow") != (not categories):
        raise ProtocolError("Router security evidence is inconsistent")


def _security_evidence(result) -> dict[str, Any]:
    evidence = {
        "decision": result.decision,
        "categories": list(result.categories),
        "counts": dict(result.counts),
    }
    _validate_security_evidence(evidence)
    return evidence


def _security_gate_failure_digest(
    *, driver_context_id: str, run_id: str, evidence: Mapping[str, Any]
) -> str:
    _validate_security_evidence(evidence)
    return digest_json(
        {
            "driver_context_id": driver_context_id,
            "run_id": run_id,
            "stage": "web_sol",
            "source_revision": 1,
            "failure": {
                "code": "router-security-gate",
                "summary": "Web payload blocked by Router security policy",
            },
            "execution": {
                "verification": "locally_verified",
                "source": "router_security_gate",
                "network_used": False,
            },
            "security": dict(evidence),
        }
    )


def _sanitize_failure(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _raise_invalid("failure must be an object")
    code = value.get("code")
    summary = value.get("summary")
    if not isinstance(code, str):
        _raise_invalid("failure code must be text")
    if not isinstance(summary, str):
        _raise_invalid("failure summary must be text")
    try:
        return {
            "code": sanitize_failure_code(code),
            "summary": sanitize_failure_summary(summary),
        }
    except UnicodeEncodeError as error:
        raise RouterStateError("invalid-input", "failure text must be valid UTF-8") from error


def start_run(
    *,
    state_root: Path | str,
    task: str,
    driver_context_id: str,
    role_config: Mapping[str, Any],
    codex_binary: Path | str,
    driver_type: str = "codex_app",
    run_id: str | None = None,
    idempotency_key: str | None = None,
    prompt_digest: str | None = None,
) -> TransitionResult:
    _validate_driver_context_id(driver_context_id)
    if driver_type not in _DRIVER_TYPES:
        _raise_invalid("driver_type must be codex_app or offline_pipeline")
    try:
        normalized_task = normalize_content(task)
    except ProtocolError as error:
        raise RouterStateError("invalid-input", str(error)) from error
    if not isinstance(role_config, Mapping) or any(
        stage not in role_config or not isinstance(role_config[stage], Mapping)
        for stage in ("local_sol", "web_sol", "luna")
    ):
        _raise_invalid("role_config must define local_sol, web_sol, and luna")
    copied_role_config = deepcopy(dict(role_config))
    try:
        canonical_json_bytes(copied_role_config)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise RouterStateError("invalid-input", "role_config is not canonical JSON") from error
    resolved_root = _resolve_state_root(state_root)
    binary_realpath, binary_sha256 = _resolve_binary(codex_binary)

    deterministic_values = (run_id, idempotency_key, prompt_digest)
    deterministic = any(value is not None for value in deterministic_values)
    if deterministic and not all(isinstance(value, str) for value in deterministic_values):
        _raise_invalid(
            "run_id, idempotency_key, and prompt_digest must be provided together"
        )
    if deterministic:
        _validate_run_id(run_id)
        if _EVENT_ID_PATTERN.fullmatch(idempotency_key) is None:
            _raise_invalid("idempotency_key must use the canonical event identity")
        if _PROMPT_DIGEST_PATTERN.fullmatch(prompt_digest) is None:
            _raise_invalid("prompt_digest must use the canonical keyed digest")

    resolved_root = prepare_state_root(resolved_root)
    if deterministic:
        allocation_lock = _exclusive_event_lock(resolved_root, run_id)
    else:
        allocation_lock = nullcontext()

    with allocation_lock:
        run_dir = None
        allocated_run_id = run_id
        if deterministic:
            candidate_dir = resolved_root / allocated_run_id
            if os.path.lexists(candidate_dir):
                _validate_private_directory(candidate_dir)
                with _exclusive_run_lock(candidate_dir):
                    existing = _load_state(candidate_dir, allocated_run_id)
                    request = existing.get("request")
                    profiles = existing.get("profiles")
                    matching_binary = isinstance(profiles, Mapping) and all(
                        isinstance(profiles.get(stage), Mapping)
                        and profiles[stage].get("codex_binary_realpath")
                        == str(binary_realpath)
                        and profiles[stage].get("codex_binary_sha256") == binary_sha256
                        for stage in _LOCAL_STAGES
                    )
                    matches = (
                        isinstance(request, Mapping)
                        and request.get("task") == normalized_task
                        and isinstance(request.get("idempotency_key"), str)
                        and hmac.compare_digest(
                            request["idempotency_key"], idempotency_key
                        )
                        and isinstance(request.get("prompt_digest"), str)
                        and hmac.compare_digest(request["prompt_digest"], prompt_digest)
                        and existing.get("driver")
                        == {
                            "driver_type": driver_type,
                            "driver_context_id": driver_context_id,
                        }
                        and existing.get("role_config") == copied_role_config
                        and matching_binary
                    )
                    if not matches:
                        raise RouterStateError(
                            "conflict",
                            "deterministic run identity does not match existing state",
                            run_id=allocated_run_id,
                        )
                    _rebuild_projections(candidate_dir, existing)
                    return _result(candidate_dir, existing, idempotent=True)
            else:
                candidate_dir.mkdir(mode=0o700, exist_ok=False)
                _fsync_directory(resolved_root)
            run_dir = candidate_dir
        else:
            for _ in range(3):
                candidate_id = _new_run_id()
                candidate_dir = resolved_root / candidate_id
                try:
                    candidate_dir.mkdir(mode=0o700, exist_ok=False)
                except FileExistsError:
                    continue
                allocated_run_id = candidate_id
                run_dir = candidate_dir
                _fsync_directory(resolved_root)
                break
            if run_dir is None or allocated_run_id is None:
                raise RouterStateError("conflict", "could not allocate a unique run directory")

        with _exclusive_run_lock(run_dir):
            profiles = {
                stage: _create_profile(
                    state_root=resolved_root,
                    driver_context_id=driver_context_id,
                    run_id=allocated_run_id,
                    stage=stage,
                    binary_realpath=binary_realpath,
                    binary_sha256=binary_sha256,
                )
                for stage in _LOCAL_STAGES
            }
            initial_packet = _initial_packet(
                driver_context_id=driver_context_id,
                run_id=allocated_run_id,
                task=normalized_task,
                role_config=copied_role_config,
                profiles=profiles,
            )
            request = {"task": normalized_task}
            if deterministic:
                request.update(
                    {
                        "idempotency_key": idempotency_key,
                        "prompt_digest": prompt_digest,
                    }
                )
            state = {
                "protocol": RUN_PROTOCOL,
                "run_id": allocated_run_id,
                "driver": {
                    "driver_type": driver_type,
                    "driver_context_id": driver_context_id,
                },
                "status": "awaiting_local_sol",
                "revision": 0,
                "next_stage": "local_sol",
                "request": request,
                "role_config": copied_role_config,
                "profiles": profiles,
                "submissions": {},
                "failures": {},
                "next_packet": initial_packet,
                "final_result": None,
                "history": [
                    {"revision": 0, "event": "run_started", "stage": "local_sol"}
                ],
            }
            _commit_state(run_dir, state)
            _rebuild_projections(run_dir, state)
            return _result(run_dir, state)


def get_status(*, state_root: Path | str, run_id: str) -> TransitionResult:
    _validate_run_id(run_id)
    resolved_root = prepare_state_root(state_root)
    run_dir = resolved_root / run_id
    if not run_dir.is_dir():
        raise RouterStateError("run-not-found", "run does not exist", run_id=run_id)
    with _exclusive_run_lock(run_dir):
        state = _load_state(run_dir, run_id)
        _rebuild_projections(run_dir, state)
        return _result(run_dir, state)


def submit_stage(
    *,
    state_root: Path | str,
    run_id: str,
    driver_context_id: str,
    stage: str,
    expected_revision: int,
    packet_digest_value: str,
    content: str,
    execution: Mapping[str, Any],
) -> TransitionResult:
    _validate_run_id(run_id)
    _validate_driver_context_id(driver_context_id)
    if stage not in ("local_sol", "web_sol", "luna"):
        raise RouterStateError("invalid-transition", "unknown stage", run_id=run_id, stage=stage)
    try:
        normalized = normalize_content(content)
    except ProtocolError as error:
        raise RouterStateError(
            "invalid-input", str(error), run_id=run_id, stage=stage
        ) from error
    resolved_root = prepare_state_root(state_root)
    run_dir = resolved_root / run_id
    if not run_dir.is_dir():
        raise RouterStateError("run-not-found", "run does not exist", run_id=run_id)

    with _exclusive_run_lock(run_dir):
        state = _load_state(run_dir, run_id)
        revision = state["revision"]
        if state["driver"].get("driver_context_id") != driver_context_id:
            raise RouterStateError(
                "conflict",
                "driver context does not own this run",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        existing = state["submissions"].get(stage)
        if existing is not None:
            stable_execution, _ = _normalize_execution(
                state=state,
                stage=stage,
                execution=execution,
                driver_context_id=driver_context_id,
                packet_digest_value=packet_digest_value,
            )
            incoming_digest = submission_digest(
                driver_context_id,
                run_id,
                stage,
                packet_digest_value,
                normalized,
                stable_execution,
            )
            if existing["submission_digest"] == incoming_digest:
                return _result(run_dir, state, idempotent=True)
            raise RouterStateError(
                "conflict",
                "stage already has different content",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        if state["failures"].get(stage) is not None or state["status"] in {
            "completed",
            "failed",
        }:
            raise RouterStateError(
                "conflict",
                "run is terminal or stage already failed",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        if state["next_stage"] != stage:
            raise RouterStateError(
                "invalid-transition",
                "stage is not the current next stage",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision != revision
        ):
            raise RouterStateError(
                "revision-mismatch",
                "expected revision does not match canonical state",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        packet = state["next_packet"]
        if not isinstance(packet, Mapping) or packet.get("packet_digest") != packet_digest_value:
            raise RouterStateError(
                "packet-mismatch",
                "packet digest does not match the current stage packet",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        stable_execution, telemetry = _normalize_execution(
            state=state,
            stage=stage,
            execution=execution,
            driver_context_id=driver_context_id,
            packet_digest_value=packet_digest_value,
        )
        incoming_digest = submission_digest(
            driver_context_id,
            run_id,
            stage,
            packet_digest_value,
            normalized,
            stable_execution,
        )
        if stage == "web_sol":
            try:
                validate_web_response(normalized, packet)
            except ProtocolError as error:
                raise RouterStateError(
                    "marker-mismatch",
                    str(error),
                    run_id=run_id,
                    stage=stage,
                    revision=revision,
                ) from error

        next_state = deepcopy(state)
        next_revision = revision + 1
        next_state["submissions"][stage] = {
            "stage": stage,
            "source_revision": revision,
            "packet_digest": packet_digest_value,
            "submission_digest": incoming_digest,
            "packet": deepcopy(dict(packet)),
            "content": normalized,
            "execution": stable_execution,
            "telemetry": telemetry,
        }
        next_state["revision"] = next_revision
        next_state["history"].append(
            {
                "revision": next_revision,
                "event": "stage_submitted",
                "stage": stage,
                "submission_digest": incoming_digest,
                "telemetry": telemetry,
            }
        )
        if stage == "local_sol":
            security_result = secure_web_payload(_proposed_web_payload(next_state))
            evidence = _security_evidence(security_result)
            next_state["web_security"] = evidence
            if security_result.decision == "block":
                failure = {
                    "stage": "web_sol",
                    "source_revision": 1,
                    "failure": {
                        "code": "router-security-gate",
                        "summary": "Web payload blocked by Router security policy",
                    },
                    "execution": {
                        "verification": "locally_verified",
                        "source": "router_security_gate",
                        "network_used": False,
                    },
                    "telemetry": {},
                    "security": deepcopy(evidence),
                }
                failure["failure_digest"] = _security_gate_failure_digest(
                    driver_context_id=driver_context_id,
                    run_id=run_id,
                    evidence=evidence,
                )
                next_state["failures"]["web_sol"] = failure
                next_state["status"] = "failed"
                next_state["revision"] = next_revision + 1
                next_state["next_stage"] = None
                next_state["next_packet"] = None
                next_state["failed_stage"] = "web_sol"
                next_state["history"].append(
                    {
                        "revision": next_revision + 1,
                        "event": "stage_failed",
                        "stage": "web_sol",
                        "failure_digest": failure["failure_digest"],
                        "source": "router_security_gate",
                    }
                )
            else:
                secured_payload = deepcopy(dict(security_result.value))
                secured_payload["security_evidence"] = deepcopy(evidence)
                next_state["status"] = "awaiting_web_sol"
                next_state["next_stage"] = "web_sol"
                next_state["next_packet"] = _build_next_packet(
                    next_state, stage, secured_web_payload=secured_payload
                )
        elif stage == "web_sol":
            next_state["status"] = "awaiting_luna"
            next_state["next_stage"] = "luna"
            next_state["next_packet"] = _build_next_packet(next_state, stage)
        else:
            next_state["status"] = "completed"
            next_state["next_stage"] = None
            next_state["next_packet"] = None
            next_state["final_result"] = normalized

        _commit_state(run_dir, next_state)
        warnings: tuple[str, ...] = ()
        try:
            _rebuild_projections(run_dir, next_state)
        except OSError:
            warnings = ("projection-rebuild-failed",)
        return _result(run_dir, next_state, projection_warnings=warnings)


def fail_stage(
    *,
    state_root: Path | str,
    run_id: str,
    driver_context_id: str,
    stage: str,
    expected_revision: int,
    packet_digest_value: str,
    failure: Mapping[str, Any],
    execution: Mapping[str, Any],
) -> TransitionResult:
    _validate_run_id(run_id)
    _validate_driver_context_id(driver_context_id)
    if stage not in ("local_sol", "web_sol", "luna"):
        raise RouterStateError("invalid-transition", "unknown stage", run_id=run_id, stage=stage)
    sanitized_failure = _sanitize_failure(failure)
    resolved_root = prepare_state_root(state_root)
    run_dir = resolved_root / run_id
    if not run_dir.is_dir():
        raise RouterStateError("run-not-found", "run does not exist", run_id=run_id)

    with _exclusive_run_lock(run_dir):
        state = _load_state(run_dir, run_id)
        revision = state["revision"]
        if state["driver"].get("driver_context_id") != driver_context_id:
            raise RouterStateError(
                "conflict",
                "driver context does not own this run",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        existing_failure = state["failures"].get(stage)
        if existing_failure is not None:
            stable_execution, _ = _normalize_execution(
                state=state,
                stage=stage,
                execution=execution,
                driver_context_id=driver_context_id,
                packet_digest_value=packet_digest_value,
            )
            incoming_digest = compute_failure_digest(
                driver_context_id,
                run_id,
                stage,
                packet_digest_value,
                sanitized_failure,
                stable_execution,
            )
            if existing_failure["failure_digest"] == incoming_digest:
                return _result(run_dir, state, idempotent=True)
            raise RouterStateError(
                "conflict",
                "stage already has a different failure",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        if state["submissions"].get(stage) is not None:
            raise RouterStateError(
                "conflict",
                "stage already completed successfully",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        if state["status"] in {"completed", "failed"}:
            raise RouterStateError(
                "conflict",
                "run is terminal",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        if state["next_stage"] != stage:
            raise RouterStateError(
                "invalid-transition",
                "stage is not the current next stage",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision != revision
        ):
            raise RouterStateError(
                "revision-mismatch",
                "expected revision does not match canonical state",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        packet = state["next_packet"]
        if not isinstance(packet, Mapping) or packet.get("packet_digest") != packet_digest_value:
            raise RouterStateError(
                "packet-mismatch",
                "packet digest does not match the current stage packet",
                run_id=run_id,
                stage=stage,
                revision=revision,
            )
        stable_execution, telemetry = _normalize_execution(
            state=state,
            stage=stage,
            execution=execution,
            driver_context_id=driver_context_id,
            packet_digest_value=packet_digest_value,
        )
        incoming_digest = compute_failure_digest(
            driver_context_id,
            run_id,
            stage,
            packet_digest_value,
            sanitized_failure,
            stable_execution,
        )

        next_state = deepcopy(state)
        next_revision = revision + 1
        next_state["failures"][stage] = {
            "stage": stage,
            "source_revision": revision,
            "packet_digest": packet_digest_value,
            "failure_digest": incoming_digest,
            "packet": deepcopy(dict(packet)),
            "failure": sanitized_failure,
            "execution": stable_execution,
            "telemetry": telemetry,
        }
        next_state["status"] = "failed"
        next_state["revision"] = next_revision
        next_state["next_stage"] = None
        next_state["next_packet"] = None
        next_state["failed_stage"] = stage
        next_state["history"].append(
            {
                "revision": next_revision,
                "event": "stage_failed",
                "stage": stage,
                "failure_digest": incoming_digest,
                "telemetry": telemetry,
            }
        )

        _commit_state(run_dir, next_state)
        warnings: tuple[str, ...] = ()
        try:
            _rebuild_projections(run_dir, next_state)
        except OSError:
            warnings = ("projection-rebuild-failed",)
        return _result(run_dir, next_state, projection_warnings=warnings)
