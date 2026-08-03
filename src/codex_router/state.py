from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator, Mapping
import uuid

from .protocol import (
    RUN_PROTOCOL,
    WEB_RESPONSE_PREFIX,
    ProtocolError,
    build_stage_packet,
    canonical_json_bytes,
    failure_digest as compute_failure_digest,
    normalize_content,
    submission_digest,
    validate_web_response,
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
}

_DRIVER_CONTEXT_PATTERN = re.compile(
    r"ctx-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_RUN_ID_PATTERN = re.compile(r"run-[A-Za-z0-9][A-Za-z0-9._-]*")
_DRIVER_TYPES = frozenset(("codex_app", "offline_pipeline"))
_PROFILE_PROTOCOL = "codex-router/profile/v1"
_LOCAL_STAGES = ("local_sol", "luna")
_STAGE_FILE_NAMES = {
    "local_sol": "local-sol.json",
    "web_sol": "web-sol.json",
    "luna": "luna.json",
}
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
_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(
        r"(?i)(authorization|cookie|password|secret|token|api[_-]?key)"
        r"\s*[:=]\s*\S+"
    ),
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
    if not isinstance(driver_context_id, str) or not _DRIVER_CONTEXT_PATTERN.fullmatch(
        driver_context_id
    ):
        _raise_invalid("driver_context_id must be ctx- followed by a canonical UUID")
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
    candidate = Path(state_root).expanduser().resolve(strict=False)
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


def _ensure_private_directory(path: Path, *, parents: bool = False) -> None:
    path.mkdir(mode=0o700, parents=parents, exist_ok=True)
    os.chmod(path, 0o700)


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


def _projection_payloads(state: Mapping[str, Any]) -> dict[Path, bytes]:
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


def _build_next_packet(state: Mapping[str, Any], completed_stage: str) -> dict[str, Any] | None:
    driver_context_id = state["driver"]["driver_context_id"]
    run_id = state["run_id"]
    task = state["request"]["task"]
    if completed_stage == "local_sol":
        local_output = state["submissions"]["local_sol"]["content"]
        return build_stage_packet(
            driver_context_id=driver_context_id,
            run_id=run_id,
            packet_id=_new_packet_id(),
            target_stage="web_sol",
            source_revision=1,
            payload={
                "task": task,
                "local_sol_output": local_output,
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
            },
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


def _sanitize_failure(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _raise_invalid("failure must be an object")
    code = " ".join(str(value.get("code", "stage-failed")).splitlines())[:64]
    code = re.sub(r"[^A-Za-z0-9._-]+", "-", code).strip("-._") or "stage-failed"
    summary = " ".join(str(value.get("summary", "stage failed")).splitlines())[:500]
    for pattern in _SECRET_PATTERNS:
        summary = pattern.sub(
            lambda match: (
                f"{match.group(1)}=<redacted>" if match.lastindex else "<redacted>"
            ),
            summary,
        )
    return {"code": code, "summary": summary or "stage failed"}


def start_run(
    *,
    state_root: Path | str,
    task: str,
    driver_context_id: str,
    role_config: Mapping[str, Any],
    codex_binary: Path | str,
    driver_type: str = "codex_app",
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

    _ensure_private_directory(resolved_root, parents=True)
    run_dir = None
    run_id = None
    for _ in range(3):
        candidate_id = _new_run_id()
        candidate_dir = resolved_root / candidate_id
        try:
            candidate_dir.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError:
            continue
        run_id = candidate_id
        run_dir = candidate_dir
        _fsync_directory(resolved_root)
        break
    if run_dir is None or run_id is None:
        raise RouterStateError("conflict", "could not allocate a unique run directory")

    with _exclusive_run_lock(run_dir):
        profiles = {
            stage: _create_profile(
                state_root=resolved_root,
                driver_context_id=driver_context_id,
                run_id=run_id,
                stage=stage,
                binary_realpath=binary_realpath,
                binary_sha256=binary_sha256,
            )
            for stage in _LOCAL_STAGES
        }
        initial_packet = _initial_packet(
            driver_context_id=driver_context_id,
            run_id=run_id,
            task=normalized_task,
            role_config=copied_role_config,
            profiles=profiles,
        )
        state = {
            "protocol": RUN_PROTOCOL,
            "run_id": run_id,
            "driver": {
                "driver_type": driver_type,
                "driver_context_id": driver_context_id,
            },
            "status": "awaiting_local_sol",
            "revision": 0,
            "next_stage": "local_sol",
            "request": {"task": normalized_task},
            "role_config": copied_role_config,
            "profiles": profiles,
            "submissions": {},
            "failures": {},
            "next_packet": initial_packet,
            "final_result": None,
            "history": [{"revision": 0, "event": "run_started", "stage": "local_sol"}],
        }
        _commit_state(run_dir, state)
        _rebuild_projections(run_dir, state)
        return _result(run_dir, state)


def get_status(*, state_root: Path | str, run_id: str) -> TransitionResult:
    _validate_run_id(run_id)
    resolved_root = _resolve_state_root(state_root)
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
    resolved_root = _resolve_state_root(state_root)
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
            next_state["status"] = "awaiting_web_sol"
            next_state["next_stage"] = "web_sol"
            next_state["next_packet"] = _build_next_packet(next_state, stage)
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
    resolved_root = _resolve_state_root(state_root)
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
