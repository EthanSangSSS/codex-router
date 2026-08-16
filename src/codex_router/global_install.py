from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import sys
import tempfile
import tomllib
from typing import Any, Iterator, Mapping

from .hook import (
    GLOBAL_CONFIG_PROTOCOL,
    HOOK_CONTEXT_PREFIX,
    HOOK_CONTEXT_PROTOCOL,
)
from .protocol import canonical_json_bytes
from .state import RouterStateError
from .types import GlobalStatus


INSTALL_DIRECTORY_NAME = ".codex-router-policy-v1"
INSTALL_STATE_PROTOCOL = "codex-router/global-install-state/v1"
HOOK_MARKER = "codex-router-global-policy-v1"
AGENTS_BEGIN = "# BEGIN CODEX ROUTER GLOBAL POLICY V1"
AGENTS_END = "# END CODEX ROUTER GLOBAL POLICY V1"
_IDENTITY_FILE_NAME = "installation-" + "sec" + "ret"
_MAX_USER_FILE_BYTES = 1024 * 1024
_MAX_PRIVATE_FILE_BYTES = 256 * 1024
_MAX_HOOK_PROBE_BYTES = 16 * 1024
_HOOK_PROBE_TIMEOUT_SECONDS = 5
_MISSING = object()
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
LUNA_AGENT_RELATIVE_PATH = "agents/luna-worker.toml"
_LEGACY_TARGET_NAMES = ("hooks.json", "AGENTS.md")
_TARGET_NAMES = (*_LEGACY_TARGET_NAMES, LUNA_AGENT_RELATIVE_PATH)
_TARGET_BACKUPS = {
    "hooks.json": "backups/hooks.json.original",
    "AGENTS.md": "backups/agents.md.original",
    LUNA_AGENT_RELATIVE_PATH: "backups/luna-worker.toml.original",
}
_TARGET_SLUGS = {
    "hooks.json": "hooks",
    "AGENTS.md": "agents",
    LUNA_AGENT_RELATIVE_PATH: "luna",
}
_UPGRADE_FIELDS = {
    "upgrade_from_sha256",
    "upgrade_from_mode",
    "upgrade_source_sha256",
    "upgrade_source_mode",
    "upgrade_original_sha256",
    "upgrade_original_mode",
    "upgrade_backup",
}
_UPGRADE_BACKUP_PATTERN = re.compile(
    r"backups/upgrades/(hooks|agents|luna)-[0-9a-f]{64}\.original\Z"
)

AGENTS_BLOCK = f"""{AGENTS_BEGIN}
This Codex task is the primary Sol coordinator, highest ordinary execution authority, and final reviewer. Luna is the default bounded writable execution worker for routed work.
Honor `[CODEX_ROUTER_POLICY_V1]` hook context exactly:
- `direct` and `bypass` apply only to the current turn. Sol executes that turn directly and does not create or use Luna; the next normal substantive turn returns to Router routing automatically.
- For `route`, show `Router: active`. Sol plans and decomposes; create or reuse exactly one current-root-turn `luna_worker` for bounded executable work by default; Sol reviews results, sends bounded corrections when useful, and gives the final response.
- The primary Sol must retain the native multi-agent capability needed to create, communicate with, observe, and perform one bounded cleanup operation on the current authorized Luna. Do not apply Luna's descendant restriction globally to Sol.
- Luna and all child agents must not create descendants. Luna must not start or resume another Codex runtime, use a hidden executor to bypass the Router gate, or bypass user-required trust, approval, authentication, or security confirmation.
- Each routed root turn may bind at most one Router-managed `luna_worker`. While that root turn remains ACTIVE, reuse the same Luna across sequential work packets and correction packets, including after a Luna packet becomes completed or idle. A revoked or turn-mismatched historical Luna is permanently ineligible for new work or reuse.
- Every new Luna delegation must restate its packet id, working directory, allowed paths, forbidden operations, validation, stop conditions, and required output. The previous packet's path authorization expires automatically; keep a single writable executor for each file set.
- Luna capacity exhaustion or another ordinary execution blocker returns control to Sol. Sol may retry with new evidence, narrow the packet, reuse the authorized Luna, take over ordinary execution, ask the user, or stop. Only stale-Luna resurrection, Luna process recursion, and interactive-security bypass are non-overridable Router guards.
- A parent terminal boundary revokes Luna authorization before any best-effort cleanup. If Stop requests cleanup, perform at most one native cleanup attempt and then finalize without further Luna work; never create an autonomous cleanup/wait/retry loop.
- Luna must not browse, operate Web Sol, access authentication or secrets, or commit, push, open a PR, install, deploy, or broaden scope unless the latest bounded packet explicitly authorizes an otherwise permitted action.
- Web Sol is manual operator work outside automatic Router execution. Never open, close, or control browser pages on Router's behalf.
- The Hook route is stateless with respect to legacy Router runs. Do not create or resume a canonical run unless the user explicitly invokes the legacy Router CLI workflow. Native Luna lifecycle authorization is maintained only by the dedicated bounded safety journal.
- Verify delegated results before using them and report only observed outcomes. Never treat `interrupt_agent` or a model message as proof that a child process was fully terminated.
{AGENTS_END}
"""

_LUNA_DESCRIPTION = (
    "The default execution worker for planned, bounded implementation, testing, "
    "and verification with explicit acceptance criteria."
)
_LUNA_DEVELOPER_INSTRUCTIONS = """You are the default bounded execution worker for one authorized Router root turn. Sol is the planner, coordinator, reviewer, and final authority.

Operating rules:
- Accept sequential implementation, test, verification, and bounded correction packets only while the current parent/root-turn binding remains authorized. Packet completion or idle state does not itself end that active parent turn.
- Never act on a packet from another turn or after the parent binding has been revoked. Do not attempt to resume or recreate a historical Luna identity.
- New packets do not inherit previous write permissions. Obey only the latest packet's id, working directory, allowed paths, forbidden operations, validation, stop conditions, and required output.
- Never create, spawn, fork, relay, resume, or delegate any child or descendant agent. Do not ask or instruct another agent to do so on your behalf. If work requires recursive delegation, return `BLOCKED_LUNA_RECURSIVE_DELEGATION` to Sol.
- Never launch, resume, probe, or wrap another Codex runtime through shell, PTY, subprocess, environment, script, or another executor. If work requires nested Codex, return `BLOCKED_LUNA_CODEX_RUNTIME` to Sol.
- Inherit the parent task's sandbox and approval controls. Never request, synthesize, or bypass user-required trust, approval, authentication, permission escalation, or security confirmation; return `BLOCKED_USER_INTERACTION_REQUIRED` instead.
- Work only on the exact packet delegated by Sol. Treat allowed paths as a hard write boundary and preserve every unrelated file and behavior.
- Do not broaden scope, redesign unrelated components, or become a second workflow coordinator. Inspect relevant files and conventions before acting.
- Complete planned multi-step work across the explicitly allowed paths, including focused tests and verification. Prefer the smallest defensible change and remain the single writable executor for the delegated file set until returning control.
- If capacity, dependencies, permissions, ambiguity, or another ordinary blocker prevents completion, stop and report evidence to Sol. Do not create autonomous wait/interrupt/retry loops; Sol decides whether to narrow, take over, ask the user, retry with new evidence, or stop.
- Never browse or operate Web Sol. Never access authentication, credentials, cookies, tokens, private keys, payment data, or unrelated user data.
- Never commit, push, create or modify a pull request, install, deploy, publish, or start persistent services unless the latest explicit packet authorizes that exact action and normal platform controls permit it.
- Validate with the narrowest relevant checks. Never claim a command or test passed unless you ran it and observed the result.
- Return a concise summary of work completed, files or artifacts affected, validation performed with observed results, and remaining risks or blockers.
"""


def _error(code: str, message: str) -> RouterStateError:
    return RouterStateError(code, message)


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST_PATTERN.fullmatch(value) is not None


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_codex_home(codex_home: Path | str) -> Path:
    candidate = Path(codex_home).expanduser()
    if not candidate.is_absolute():
        raise _error("invalid-input", "codex_home must be absolute")
    try:
        metadata = candidate.lstat()
    except OSError as error:
        raise _error("invalid-input", "codex_home must already exist") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
    ):
        raise _error("conflict", "codex_home is unsafe")
    return candidate


@contextmanager
def _home_lock(codex_home: Path) -> Iterator[None]:
    descriptor = os.open(codex_home, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_user_file(path: Path) -> tuple[bool, bytes | None, int | None]:
    if not os.path.lexists(path):
        return False, None, None
    try:
        metadata = path.lstat()
    except OSError as error:
        raise _error("conflict", "managed user file is unavailable") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_size > _MAX_USER_FILE_BYTES
        or stat.S_IMODE(metadata.st_mode) & 0o7000
    ):
        raise _error("conflict", "managed user file is unsafe")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise _error("conflict", "managed user file is unreadable") from error
    if len(content) > _MAX_USER_FILE_BYTES:
        raise _error("conflict", "managed user file exceeds the size limit")
    return True, content, stat.S_IMODE(metadata.st_mode)


def _validate_agents_directory(codex_home: Path, *, create: bool) -> Path:
    agents_directory = codex_home / "agents"
    if not os.path.lexists(agents_directory):
        if not create:
            return agents_directory
        try:
            agents_directory.mkdir(mode=0o700)
            os.chmod(agents_directory, 0o700)
            _fsync_directory(codex_home)
        except OSError as error:
            raise _error("conflict", "Codex agents directory cannot be created safely") from error
        return agents_directory
    try:
        metadata = agents_directory.lstat()
    except OSError as error:
        raise _error("conflict", "Codex agents directory is unavailable") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o7000
    ):
        raise _error("conflict", "Codex agents directory is unsafe")
    return agents_directory


def _read_target_file(
    codex_home: Path, name: str
) -> tuple[bool, bytes | None, int | None]:
    if name == LUNA_AGENT_RELATIVE_PATH:
        agents_directory = _validate_agents_directory(codex_home, create=False)
        if not os.path.lexists(agents_directory):
            return False, None, None
    return _read_user_file(codex_home / name)


def _valid_mode(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 0o777
    )


def _upgrade_backup_name(name: str, digest: str) -> str:
    if name not in _TARGET_SLUGS or not _valid_digest(digest):
        raise _error("conflict", "Router upgrade backup identity is invalid")
    return (
        f"backups/upgrades/{_TARGET_SLUGS[name]}-"
        f"{digest.removeprefix('sha256:')}.original"
    )


def _validate_upgrade_directory(installation_dir: Path, *, create: bool) -> Path:
    backups = installation_dir / "backups"
    try:
        backups_metadata = backups.lstat()
    except OSError as error:
        raise _error("conflict", "Router backup directory is unavailable") from error
    if (
        not stat.S_ISDIR(backups_metadata.st_mode)
        or stat.S_ISLNK(backups_metadata.st_mode)
        or backups_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(backups_metadata.st_mode) != 0o700
    ):
        raise _error("conflict", "Router backup directory is unsafe")
    upgrades = backups / "upgrades"
    if not os.path.lexists(upgrades):
        if not create:
            return upgrades
        try:
            upgrades.mkdir(mode=0o700)
            os.chmod(upgrades, 0o700)
            _fsync_directory(backups)
        except OSError as error:
            raise _error("conflict", "Router upgrade directory cannot be created safely") from error
        return upgrades
    try:
        metadata = upgrades.lstat()
    except OSError as error:
        raise _error("conflict", "Router upgrade directory is unavailable") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise _error("conflict", "Router upgrade directory is unsafe")
    return upgrades


def _upgrade_backup_path(
    installation_dir: Path, name: str, relative: str
) -> Path:
    if (
        not isinstance(relative, str)
        or _UPGRADE_BACKUP_PATTERN.fullmatch(relative) is None
        or not relative.startswith(
            f"backups/upgrades/{_TARGET_SLUGS.get(name, 'invalid')}-"
        )
    ):
        raise _error("conflict", "Router upgrade backup path is invalid")
    _validate_upgrade_directory(installation_dir, create=False)
    return installation_dir / relative


def _target_backup_path(
    installation_dir: Path, name: str, relative: str
) -> Path:
    if relative == _TARGET_BACKUPS.get(name):
        return installation_dir / relative
    return _upgrade_backup_path(installation_dir, name, relative)


def _write_upgrade_backup(
    *,
    installation_dir: Path,
    name: str,
    original: bytes | object,
) -> str | None:
    if original is _MISSING:
        return None
    if not isinstance(original, bytes):
        raise _error("conflict", "Router upgrade original is invalid")
    digest = _sha256(original)
    relative = _upgrade_backup_name(name, digest)
    upgrades = _validate_upgrade_directory(installation_dir, create=True)
    path = upgrades / Path(relative).name
    if os.path.lexists(path):
        existing = _read_private_file(path, maximum_bytes=_MAX_USER_FILE_BYTES)
        if existing != original:
            raise _error("conflict", "Router upgrade backup already differs")
        return relative
    _atomic_write(path, original)
    return relative


def _read_private_file(path: Path, *, maximum_bytes: int = _MAX_PRIVATE_FILE_BYTES) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise _error("conflict", "Router installation evidence is incomplete") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > maximum_bytes
    ):
        raise _error("conflict", "Router installation evidence is unsafe")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise _error("conflict", "Router installation evidence is unreadable") from error
    if len(content) > maximum_bytes:
        raise _error("conflict", "Router installation evidence exceeds its size limit")
    return content


def _atomic_write(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
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


def _matches_current(
    path: Path,
    expected: bytes | object,
    *,
    expected_mode: int | None = None,
) -> tuple[bool, bytes | None, int | None]:
    exists, content, mode = _read_user_file(path)
    if expected is _MISSING:
        return not exists, content, mode
    return (
        exists
        and content == expected
        and (expected_mode is None or mode == expected_mode)
    ), content, mode


def _replace_expected(
    path: Path,
    *,
    expected: bytes | object,
    expected_mode: int | None = None,
    replacement: bytes,
    mode: int,
) -> None:
    matches, _, _ = _matches_current(
        path, expected, expected_mode=expected_mode
    )
    if not matches:
        raise _error("conflict", "managed user file changed concurrently")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        matches, _, _ = _matches_current(
            path, expected, expected_mode=expected_mode
        )
        if not matches:
            raise _error("conflict", "managed user file changed concurrently")
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


def _unlink_expected(
    path: Path, *, expected: bytes, expected_mode: int | None = None
) -> None:
    matches, _, _ = _matches_current(
        path, expected, expected_mode=expected_mode
    )
    if not matches:
        raise _error("conflict", "managed user file changed concurrently")
    path.unlink()
    _fsync_directory(path.parent)


def _validate_defaults(defaults: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(defaults, Mapping) or set(defaults) != {
        "local_sol",
        "web_sol",
        "luna",
    }:
        raise _error("invalid-input", "defaults must define all Router roles")
    copied = deepcopy(dict(defaults))
    required = {
        "local_sol": ("requested_model", "requested_reasoning"),
        "web_sol": ("model_claimed", "reasoning_claimed", "verification"),
        "luna": ("requested_model", "requested_reasoning"),
    }
    for stage, fields in required.items():
        role = copied.get(stage)
        if not isinstance(role, Mapping) or any(
            not isinstance(role.get(field), str) or not role[field].strip()
            for field in fields
        ):
            raise _error("invalid-input", "Router role defaults are invalid")
    if copied["web_sol"]["verification"] != "operator_attested":
        raise _error("invalid-input", "Web role verification must be operator_attested")
    try:
        canonical_json_bytes(copied)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise _error("invalid-input", "Router role defaults are invalid") from error
    return copied


def _luna_agent_bytes(role: Mapping[str, Any]) -> bytes:
    model = role.get("requested_model")
    reasoning = role.get("requested_reasoning")
    if not isinstance(model, str) or not model.strip():
        raise _error("invalid-input", "Luna model configuration is invalid")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise _error("invalid-input", "Luna reasoning configuration is invalid")
    values = {
        "name": "luna_worker",
        "description": _LUNA_DESCRIPTION,
        "model": model,
        "model_reasoning_effort": reasoning,
        "developer_instructions": _LUNA_DEVELOPER_INSTRUCTIONS,
    }
    rendered = "".join(
        f"{key} = {json.dumps(value, ensure_ascii=False)}\n"
        for key, value in values.items()
    )
    rendered += (
        "\n[agents]\nenabled = false\n\n[features]\nmulti_agent = false\n"
        "multi_agent_v2 = false\nunified_exec = false\ncode_mode = false\n"
        "code_mode_only = false\nrequest_permissions_tool = false\n"
    )
    encoded = rendered.encode("utf-8")
    try:
        parsed = tomllib.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise _error("conflict", "generated Luna agent configuration is invalid") from error
    expected = {
        **values,
        "agents": {"enabled": False},
        "features": {
            "multi_agent": False,
            "multi_agent_v2": False,
            "unified_exec": False,
            "code_mode": False,
            "code_mode_only": False,
            "request_permissions_tool": False,
        },
    }
    if parsed != expected:
        raise _error("conflict", "generated Luna agent configuration is unstable")
    return encoded


def _luna_agent_matches(content: bytes | None, role: Mapping[str, Any]) -> bool:
    if content is None:
        return False
    try:
        parsed = tomllib.loads(content.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    return parsed == tomllib.loads(_luna_agent_bytes(role).decode("utf-8"))


def _validate_install_inputs(
    *,
    codex_home: Path,
    state_root: Path | str,
    codex_binary: Path | str,
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    state_path = Path(state_root).expanduser()
    binary_path = Path(codex_binary).expanduser()
    if not state_path.is_absolute():
        raise _error("invalid-input", "state_root must be absolute")
    if codex_home == state_path or codex_home in state_path.parents:
        raise _error("invalid-input", "state_root must be outside codex_home")
    if not binary_path.is_absolute():
        raise _error("invalid-input", "codex_binary must be absolute")
    try:
        binary_metadata = binary_path.lstat()
    except OSError as error:
        raise _error("invalid-input", "codex_binary is unavailable") from error
    if (
        not stat.S_ISREG(binary_metadata.st_mode)
        or stat.S_ISLNK(binary_metadata.st_mode)
        or not os.access(binary_path, os.X_OK)
    ):
        raise _error("invalid-input", "codex_binary must be an executable regular file")
    return {
        "protocol": GLOBAL_CONFIG_PROTOCOL,
        "state_root": str(state_path),
        "codex_binary": str(binary_path),
        "role_config": _validate_defaults(defaults),
    }


def _walk_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                yield key
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _hook_argv(
    installation_dir: Path, subcommand: str = "hook-user-prompt"
) -> list[str]:
    python_path = Path(sys.executable)
    if not python_path.is_absolute():
        raise _error("conflict", "Router hook Python must be absolute")
    python = str(python_path)
    return [
        python,
        "-E",
        "-P",
        "-m",
        "codex_router",
        subcommand,
        "--installation-dir",
        str(installation_dir),
    ]


def _hook_handler(
    installation_dir: Path, subcommand: str = "hook-user-prompt"
) -> dict[str, Any]:
    command = shlex.join(_hook_argv(installation_dir, subcommand))
    return {
        "type": "command",
        "command": command,
        "timeout": 10,
        "statusMessage": f"Routing with Codex Router [{HOOK_MARKER}]",
        "additionalContextLimit": 2500,
    }


def _handler_argv(
    handler: Mapping[str, Any], *, expected_installation_dir: Path
) -> list[str]:
    command = handler.get("command")
    if not isinstance(command, str):
        raise _error("conflict", "Router hook command is invalid")
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError as error:
        raise _error("conflict", "Router hook command is invalid") from error
    expected_tail = [
        "-E",
        "-P",
        "-m",
        "codex_router",
        "hook-user-prompt",
        "--installation-dir",
        str(expected_installation_dir),
    ]
    if len(arguments) != 8 or arguments[1:] != expected_tail:
        raise _error("conflict", "Router hook command does not match its contract")
    python = Path(arguments[0])
    if not python.is_absolute():
        raise _error("conflict", "Router hook Python must be absolute")
    try:
        real_python = python.resolve(strict=True)
        metadata = real_python.stat()
    except OSError as error:
        raise _error("conflict", "Router hook Python is unavailable") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or not os.access(real_python, os.X_OK)
        or not os.access(python, os.X_OK)
    ):
        raise _error("conflict", "Router hook Python is unsafe")
    return arguments


def _invoke_hook_argv(
    arguments: list[str], *, event: Mapping[str, Any], cwd: Path
) -> dict[str, Any]:
    try:
        encoded_event = canonical_json_bytes(dict(event)) + b"\n"
        completed = subprocess.run(
            arguments,
            input=encoded_event,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            check=False,
            timeout=_HOOK_PROBE_TIMEOUT_SECONDS,
        )
    except (
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
        UnicodeEncodeError,
    ) as error:
        raise _error("conflict", "Router hook command failed preflight") from error
    if (
        completed.returncode != 0
        or completed.stderr
        or not completed.stdout
        or len(completed.stdout) > _MAX_HOOK_PROBE_BYTES
    ):
        raise _error("conflict", "Router hook command failed preflight")
    try:
        output = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error("conflict", "Router hook command returned invalid JSON") from error
    if not isinstance(output, dict):
        raise _error("conflict", "Router hook command returned invalid JSON")
    return output


def _preflight_hook_handler(
    handler: Mapping[str, Any], *, installation_dir: Path, cwd: Path
) -> None:
    arguments = _handler_argv(
        handler, expected_installation_dir=installation_dir
    )
    raw_values = (
        "synthetic-install-probe-session",
        "synthetic-install-probe-turn",
        "你好",
    )
    output = _invoke_hook_argv(
        arguments,
        event={
            "hook_event_name": "UserPromptSubmit",
            "session_id": raw_values[0],
            "turn_id": raw_values[1],
            "prompt": "你好",
            "cwd": str(cwd),
        },
        cwd=cwd,
    )
    context = _self_test_context(output)
    encoded_output = canonical_json_bytes(output).decode("utf-8")
    if (
        context.get("protocol") != HOOK_CONTEXT_PROTOCOL
        or context.get("decision") != "direct"
        or any(value in encoded_output for value in raw_values)
    ):
        raise _error("conflict", "Router hook command failed preflight")


def _install_hook(original: bytes | None, handler: Mapping[str, Any] | None = None) -> bytes:
    if original is None:
        document: dict[str, Any] = {}
    else:
        try:
            document = json.loads(original)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _error("conflict", "hooks.json is not valid JSON") from error
        if not isinstance(document, dict):
            raise _error("conflict", "hooks.json must contain a JSON object")
    if any(
        HOOK_MARKER in value
        or ("codex_router" in value and "hook-user-prompt" in value)
        for value in _walk_strings(document)
    ):
        raise _error("conflict", "a conflicting Router hook marker already exists")
    hooks = document.get("hooks")
    if hooks is None:
        hooks = {}
        document["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise _error("conflict", "hooks.json hooks field is invalid")
    subcommands = {
        "UserPromptSubmit": "hook-user-prompt",
        "PreToolUse": "hook-pre-tool",
        "PostToolUse": "hook-post-tool",
        "PermissionRequest": "hook-permission-request",
        "Stop": "hook-stop",
        "SubagentStart": "hook-subagent-start",
        "SubagentStop": "hook-subagent-stop",
    }
    if handler is None:
        raise _error("invalid-input", "Router hook handler is required")
    try:
        base_arguments = shlex.split(str(handler["command"]), posix=True)
    except (KeyError, TypeError, ValueError) as error:
        raise _error("conflict", "Router hook handler is invalid") from error
    if len(base_arguments) != 8 or base_arguments[3:6] != [
        "-m",
        "codex_router",
        "hook-user-prompt",
    ]:
        raise _error("conflict", "Router hook handler is invalid")
    for event, subcommand in subcommands.items():
        groups = hooks.get(event)
        if groups is None:
            groups = []
            hooks[event] = groups
        if not isinstance(groups, list):
            raise _error("conflict", f"{event} hook groups are invalid")
        for group in groups:
            if (
                not isinstance(group, Mapping)
                or not isinstance(group.get("hooks"), list)
                or any(not isinstance(item, Mapping) for item in group["hooks"])
            ):
                raise _error("conflict", f"{event} hook group is invalid")
        current = dict(handler)
        arguments = list(base_arguments)
        arguments[5] = subcommand
        current["command"] = shlex.join(arguments)
        groups.append({"hooks": [current]})
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _install_agents(original: bytes | None) -> bytes:
    raw = original or b""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _error("conflict", "AGENTS.md must be valid UTF-8") from error
    begin_count = text.count(AGENTS_BEGIN)
    end_count = text.count(AGENTS_END)
    if begin_count or end_count:
        raise _error("conflict", "a conflicting Router AGENTS marker already exists")
    if not raw:
        return AGENTS_BLOCK.encode("utf-8")
    separator = b"\n" if raw.endswith(b"\n") else b"\n\n"
    return raw + separator + AGENTS_BLOCK.encode("utf-8")


def _target_record(
    *,
    existed: bool,
    original: bytes | None,
    original_mode: int | None,
    installed: bytes,
    backup: str | None,
    installed_mode: int,
) -> dict[str, Any]:
    return {
        "existed": existed,
        "original_sha256": _sha256(original) if original is not None else None,
        "original_mode": original_mode,
        "backup": backup,
        "installed_sha256": _sha256(installed),
        "installed_mode": installed_mode,
    }


def _private_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_private_file(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error("conflict", "Router installation JSON is invalid") from error
    if not isinstance(value, dict):
        raise _error("conflict", "Router installation JSON must be an object")
    return value


def _validate_install_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise _error("conflict", "Router installation directory is unavailable") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise _error("conflict", "Router installation directory is unsafe")


def _load_install_state(installation_dir: Path) -> dict[str, Any]:
    state = _private_json(installation_dir / "install-state.json")
    if (
        set(state) != {"protocol", "phase", "config_sha256", "targets"}
        or not _valid_digest(state.get("config_sha256"))
        or state.get("protocol") != INSTALL_STATE_PROTOCOL
        or state.get("phase") not in ("prepared", "installed", "uninstalled")
        or not isinstance(state.get("targets"), Mapping)
        or set(state["targets"])
        not in (set(_LEGACY_TARGET_NAMES), set(_TARGET_NAMES))
    ):
        raise _error("conflict", "Router installation state is invalid")
    base_record_fields = {
        "existed",
        "original_sha256",
        "original_mode",
        "backup",
        "installed_sha256",
        "installed_mode",
    }
    migration_seen: bool | None = None
    for name, record in state["targets"].items():
        if not isinstance(record, Mapping):
            raise _error("conflict", "Router target evidence is invalid")
        record_fields = set(record)
        has_migration = record_fields == base_record_fields | _UPGRADE_FIELDS
        if record_fields not in (base_record_fields, base_record_fields | _UPGRADE_FIELDS):
            raise _error("conflict", "Router target evidence is invalid")
        if migration_seen is None:
            migration_seen = has_migration
        elif migration_seen != has_migration:
            raise _error("conflict", "Router migration evidence is incomplete")
        if has_migration and state["phase"] != "prepared":
            raise _error("conflict", "Router migration evidence is not resumable")
        installed_mode = record.get("installed_mode")
        if (
            not _valid_digest(record.get("installed_sha256"))
            or not _valid_mode(installed_mode)
        ):
            raise _error("conflict", "Router installed target evidence is invalid")
        if record.get("existed") is True:
            original_mode = record.get("original_mode")
            backup = record.get("backup")
            if (
                not _valid_digest(record.get("original_sha256"))
                or not _valid_mode(original_mode)
                or not isinstance(backup, str)
                or (
                    backup != _TARGET_BACKUPS[name]
                    and _UPGRADE_BACKUP_PATTERN.fullmatch(backup) is None
                )
                or (
                    backup != _TARGET_BACKUPS[name]
                    and not backup.startswith(
                        f"backups/upgrades/{_TARGET_SLUGS[name]}-"
                    )
                )
            ):
                raise _error("conflict", "Router original target evidence is invalid")
        elif record.get("existed") is False:
            if any(
                record.get(field) is not None
                for field in ("original_sha256", "original_mode", "backup")
            ):
                raise _error("conflict", "Router absence evidence is invalid")
        else:
            raise _error("conflict", "Router target ownership evidence is invalid")
        if has_migration:
            if (
                not _valid_digest(record.get("upgrade_from_sha256"))
                or not _valid_mode(record.get("upgrade_from_mode"))
                or not _valid_digest(record.get("upgrade_source_sha256"))
                or not _valid_mode(record.get("upgrade_source_mode"))
            ):
                raise _error("conflict", "Router migration source evidence is invalid")
            upgrade_backup = record.get("upgrade_backup")
            upgrade_original_sha256 = record.get("upgrade_original_sha256")
            upgrade_original_mode = record.get("upgrade_original_mode")
            if record.get("existed") is True:
                if (
                    not isinstance(upgrade_backup, str)
                    or _upgrade_backup_path(
                        installation_dir, name, upgrade_backup
                    )
                    is None
                    or not _valid_digest(upgrade_original_sha256)
                    or not _valid_mode(upgrade_original_mode)
                ):
                    raise _error("conflict", "Router migration backup evidence is invalid")
            elif any(
                value is not None
                for value in (
                    upgrade_backup,
                    upgrade_original_sha256,
                    upgrade_original_mode,
                )
            ):
                raise _error("conflict", "Router migration absence evidence is invalid")
    return state


def _target_original(
    installation_dir: Path, name: str, record: Mapping[str, Any]
) -> bytes | object:
    if "upgrade_backup" in record:
        if record.get("existed") is False:
            if any(
                record.get(field) is not None
                for field in (
                    "upgrade_backup",
                    "upgrade_original_sha256",
                    "upgrade_original_mode",
                )
            ):
                raise _error("conflict", "Router migration absence evidence is invalid")
            return _MISSING
        backup = record.get("upgrade_backup")
        if not isinstance(backup, str):
            raise _error("conflict", "Router migration backup evidence is invalid")
        original = _read_private_file(
            _upgrade_backup_path(installation_dir, name, backup),
            maximum_bytes=_MAX_USER_FILE_BYTES,
        )
        if _sha256(original) != record.get("upgrade_original_sha256"):
            raise _error("conflict", "Router migration backup digest does not match")
        return original
    if record.get("existed") is False:
        if any(record.get(name) is not None for name in ("original_sha256", "original_mode", "backup")):
            raise _error("conflict", "Router absence evidence is invalid")
        return _MISSING
    backup = record.get("backup")
    if record.get("existed") is not True or not isinstance(backup, str):
        raise _error("conflict", "Router backup evidence is invalid")
    original = _read_private_file(
        _target_backup_path(installation_dir, name, backup),
        maximum_bytes=_MAX_USER_FILE_BYTES,
    )
    if _sha256(original) != record.get("original_sha256"):
        raise _error("conflict", "Router backup digest does not match")
    return original


def _migration_source_if_matches(
    *, home: Path, name: str, record: Mapping[str, Any]
) -> tuple[bytes, int] | None:
    if "upgrade_source_sha256" not in record:
        return None
    exists, content, mode = _read_target_file(home, name)
    if (
        not exists
        or content is None
        or _sha256(content) != record.get("upgrade_source_sha256")
        or mode != record.get("upgrade_source_mode")
    ):
        return None
    return content, mode


def _installed_state_matches(
    *, codex_home: Path, installation_dir: Path, state: Mapping[str, Any]
) -> bool:
    for name, record in state["targets"].items():
        exists, content, mode = _read_target_file(codex_home, name)
        if (
            not exists
            or content is None
            or _sha256(content) != record.get("installed_sha256")
            or mode != record.get("installed_mode")
        ):
            return False
    return True


def _install_plan(
    *, home: Path, installation_dir: Path, state: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    handler = _hook_handler(installation_dir)
    config = _private_json(installation_dir / "config.json")
    role_config = _validate_defaults(config.get("role_config"))
    plan: dict[str, dict[str, Any]] = {}
    for name in _TARGET_NAMES:
        if name not in state["targets"]:
            continue
        record = state["targets"][name]
        original = _target_original(installation_dir, name, record)
        raw_original = None if original is _MISSING else original
        if name == "hooks.json":
            installed = _install_hook(raw_original, handler)
        elif name == "AGENTS.md":
            installed = _install_agents(raw_original)
        else:
            installed = _luna_agent_bytes(role_config["luna"])
        if _sha256(installed) != record.get("installed_sha256"):
            raise _error("conflict", "Router installation plan digest changed")
        migration_source = _migration_source_if_matches(
            home=home, name=name, record=record
        )
        plan[name] = {
            "original": original,
            "original_mode": record.get("original_mode"),
            "installed": installed,
            "installed_mode": record["installed_mode"],
            "migration_source": (
                migration_source[0] if migration_source is not None else None
            ),
            "migration_source_mode": (
                migration_source[1] if migration_source is not None else None
            ),
        }
    return handler, plan


def _apply_prepared_install(
    *,
    home: Path,
    installation_dir: Path,
    state: dict[str, Any],
) -> GlobalStatus:
    if state.get("phase") != "prepared":
        raise _error("conflict", "Router installation is not resumable")
    handler, plan = _install_plan(
        home=home, installation_dir=installation_dir, state=state
    )
    target_names = tuple(name for name in _TARGET_NAMES if name in state["targets"])
    if LUNA_AGENT_RELATIVE_PATH in target_names:
        _validate_agents_directory(home, create=False)
    for name in target_names:
        target = home / name
        item = plan[name]
        original_match = _matches_current(
            target,
            item["original"],
            expected_mode=item["original_mode"],
        )[0]
        installed_match = _matches_current(
            target,
            item["installed"],
            expected_mode=item["installed_mode"],
        )[0]
        migration_source_match = (
            item["migration_source"] is not None
            and _matches_current(
                target,
                item["migration_source"],
                expected_mode=item["migration_source_mode"],
            )[0]
        )
        if not (original_match or installed_match or migration_source_match):
            raise _error("conflict", "managed user file changed during installation")

    _preflight_hook_handler(
        handler, installation_dir=installation_dir, cwd=home
    )
    if LUNA_AGENT_RELATIVE_PATH in target_names:
        _validate_agents_directory(home, create=True)
    for name in target_names:
        target = home / name
        item = plan[name]
        if _matches_current(
            target,
            item["installed"],
            expected_mode=item["installed_mode"],
        )[0]:
            continue
        expected = (
            item["migration_source"]
            if item["migration_source"] is not None
            else item["original"]
        )
        expected_mode = (
            item["migration_source_mode"]
            if item["migration_source"] is not None
            else item["original_mode"]
        )
        _replace_expected(
            target,
            expected=expected,
            expected_mode=expected_mode,
            replacement=item["installed"],
            mode=item["installed_mode"],
        )
    if not _installed_state_matches(
        codex_home=home, installation_dir=installation_dir, state=state
    ):
        raise _error("conflict", "Router installation did not commit completely")
    _finalize_upgrade_state(state)
    state["phase"] = "installed"
    _atomic_write(
        installation_dir / "install-state.json",
        canonical_json_bytes(state) + b"\n",
    )
    return global_status(home)


def _finalize_upgrade_state(state: dict[str, Any]) -> None:
    for record in state["targets"].values():
        if "upgrade_backup" not in record:
            continue
        record["original_sha256"] = record.pop("upgrade_original_sha256")
        record["original_mode"] = record.pop("upgrade_original_mode")
        record["backup"] = record.pop("upgrade_backup")
        record.pop("upgrade_from_sha256")
        record.pop("upgrade_from_mode")
        record.pop("upgrade_source_sha256")
        record.pop("upgrade_source_mode")


def _build_target_records(
    *,
    home: Path,
    installation_dir: Path,
    config: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, bytes | None]]:
    handler = _hook_handler(installation_dir)
    originals: dict[str, bytes | None] = {}
    evidence: dict[str, tuple[bool, int | None]] = {}
    for name in _TARGET_NAMES:
        exists, original, mode = _read_target_file(home, name)
        originals[name] = original
        evidence[name] = (exists, mode)
    installed = {
        "hooks.json": _install_hook(originals["hooks.json"], handler),
        "AGENTS.md": _install_agents(originals["AGENTS.md"]),
        LUNA_AGENT_RELATIVE_PATH: _luna_agent_bytes(
            config["role_config"]["luna"]
        ),
    }
    records: dict[str, dict[str, Any]] = {}
    for name in _TARGET_NAMES:
        existed, original_mode = evidence[name]
        installed_mode = (
            0o600
            if name == LUNA_AGENT_RELATIVE_PATH
            else original_mode if original_mode is not None else 0o600
        )
        records[name] = _target_record(
            existed=existed,
            original=originals[name],
            original_mode=original_mode,
            installed=installed[name],
            backup=_TARGET_BACKUPS[name] if existed else None,
            installed_mode=installed_mode,
        )
    return records, originals


def _write_target_backups(
    *, installation_dir: Path, originals: Mapping[str, bytes | None]
) -> None:
    for name in _TARGET_NAMES:
        original = originals[name]
        if original is not None:
            _atomic_write(installation_dir / _TARGET_BACKUPS[name], original)


def _reprepare_uninstalled_install(
    *,
    home: Path,
    installation_dir: Path,
    state: dict[str, Any],
    config: Mapping[str, Any],
) -> GlobalStatus:
    if state.get("phase") != "uninstalled":
        raise _error("conflict", "Router installation is not safely re-installable")
    for name, record in state["targets"].items():
        original = _target_original(installation_dir, name, record)
        if not _matches_current(
            home / name,
            original,
            expected_mode=record.get("original_mode"),
        )[0]:
            raise _error("conflict", "managed user file changed after uninstallation")
    records, originals = _build_target_records(
        home=home,
        installation_dir=installation_dir,
        config=config,
    )
    _write_target_backups(
        installation_dir=installation_dir,
        originals=originals,
    )
    state["targets"] = records
    state["phase"] = "prepared"
    _atomic_write(
        installation_dir / "install-state.json",
        canonical_json_bytes(state) + b"\n",
    )
    return _apply_prepared_install(
        home=home,
        installation_dir=installation_dir,
        state=state,
    )


def _read_exact_installed_target(
    *, home: Path, name: str, record: Mapping[str, Any]
) -> tuple[bytes, int]:
    exists, content, mode = _read_target_file(home, name)
    if (
        not exists
        or content is None
        or _sha256(content) != record.get("installed_sha256")
        or mode != record.get("installed_mode")
    ):
        raise _error("conflict", "managed Router target changed before refresh")
    return content, mode


def _derive_refresh_agents_target(
    *,
    home: Path,
    old_original: bytes | object,
    record: Mapping[str, Any],
) -> tuple[bytes, int, bytes | object, int | None]:
    exists, content, mode = _read_target_file(home, "AGENTS.md")
    if not exists or content is None or mode is None:
        raise _error("conflict", "AGENTS.md changed before refresh")
    current = content
    current_mode = mode
    if current_mode != record.get("installed_mode"):
        raise _error("conflict", "AGENTS.md mode changed before refresh")
    if _sha256(current) == record.get("installed_sha256"):
        return (
            current,
            current_mode,
            old_original,
            record.get("original_mode"),
        )

    try:
        current.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _error("conflict", "AGENTS.md is not valid UTF-8") from error
    begin = AGENTS_BEGIN.encode("utf-8")
    end = AGENTS_END.encode("utf-8")
    if current.count(begin) != 1 or current.count(end) != 1:
        raise _error("conflict", "AGENTS.md Router markers are ambiguous")
    begin_index = current.find(begin)
    suffix = current[begin_index:]
    if not (suffix.endswith(end) or suffix.endswith(end + b"\n")):
        raise _error("conflict", "AGENTS.md Router block is not at file end")

    if old_original is _MISSING:
        if begin_index != 0:
            raise _error("conflict", "AGENTS.md missing-original boundary is ambiguous")
        new_original: bytes | object = _MISSING
        separator = b""
    else:
        if not isinstance(old_original, bytes):
            raise _error("conflict", "AGENTS.md original evidence is invalid")
        separator = (
            b""
            if not old_original
            else b"\n" if old_original.endswith(b"\n") else b"\n\n"
        )
        if separator:
            prefix = current[:begin_index]
            if not prefix.endswith(separator):
                raise _error("conflict", "AGENTS.md separator boundary is invalid")
            new_original = prefix[: -len(separator)]
        else:
            if begin_index != 0:
                raise _error("conflict", "AGENTS.md empty-original boundary is ambiguous")
            new_original = b""

    reconstructed = (
        suffix if old_original is _MISSING else old_original + separator + suffix
    )
    if _sha256(reconstructed) != record.get("installed_sha256"):
        raise _error("conflict", "AGENTS.md old Router block does not match evidence")
    if new_original is _MISSING or new_original == b"":
        canonical_current = suffix
    else:
        canonical_separator = (
            b"\n" if new_original.endswith(b"\n") else b"\n\n"
        )
        canonical_current = new_original + canonical_separator + suffix
    if canonical_current != current:
        raise _error("conflict", "AGENTS.md user boundary is not reversible")
    return current, current_mode, new_original, record.get("original_mode")


def _prepare_installed_refresh(
    *,
    home: Path,
    installation_dir: Path,
    state: dict[str, Any],
) -> GlobalStatus:
    if (
        state.get("phase") != "installed"
        or set(state.get("targets", {})) != set(_TARGET_NAMES)
    ):
        raise _error("conflict", "Router installation is not refreshable")
    handler = _hook_handler(installation_dir)
    config = _private_json(installation_dir / "config.json")
    role_config = _validate_defaults(config.get("role_config"))
    sources: dict[str, tuple[bytes, int]] = {}
    strategy_generated: dict[str, bytes] = {}
    installed_outputs: dict[str, bytes] = {}
    new_originals: dict[str, bytes | object] = {}
    new_original_modes: dict[str, int | None] = {}

    for name in _TARGET_NAMES:
        record = state["targets"][name]
        old_original = _target_original(installation_dir, name, record)
        raw_original = None if old_original is _MISSING else old_original
        if name == "hooks.json":
            sources[name] = _read_exact_installed_target(
                home=home, name=name, record=record
            )
            strategy_generated[name] = _install_hook(raw_original, handler)
            installed_outputs[name] = strategy_generated[name]
            new_originals[name] = old_original
            new_original_modes[name] = record.get("original_mode")
        elif name == "AGENTS.md":
            (
                source_content,
                source_mode,
                new_original,
                new_original_mode,
            ) = _derive_refresh_agents_target(
                home=home,
                old_original=old_original,
                record=record,
            )
            sources[name] = (source_content, source_mode)
            strategy_generated[name] = _install_agents(raw_original)
            installed_outputs[name] = _install_agents(
                None if new_original is _MISSING else new_original
            )
            new_originals[name] = new_original
            new_original_modes[name] = new_original_mode
        else:
            sources[name] = _read_exact_installed_target(
                home=home, name=name, record=record
            )
            strategy_generated[name] = _luna_agent_bytes(role_config["luna"])
            installed_outputs[name] = strategy_generated[name]
            new_originals[name] = old_original
            new_original_modes[name] = record.get("original_mode")

    changed = any(
        _sha256(strategy_generated[name])
        != state["targets"][name].get("installed_sha256")
        for name in _TARGET_NAMES
    )
    if not changed:
        if _installed_state_matches(
            codex_home=home,
            installation_dir=installation_dir,
            state=state,
        ):
            return global_status(home)
        raise _error("conflict", "Router policy has no refreshable strategy change")

    prepared = deepcopy(state)
    for name in _TARGET_NAMES:
        old_record = state["targets"][name]
        record = prepared["targets"][name]
        new_original = new_originals[name]
        new_digest = None if new_original is _MISSING else _sha256(new_original)
        upgrade_backup = _write_upgrade_backup(
            installation_dir=installation_dir,
            name=name,
            original=new_original,
        )
        record.update(
            {
                "upgrade_from_sha256": old_record["installed_sha256"],
                "upgrade_from_mode": old_record["installed_mode"],
                "upgrade_source_sha256": _sha256(sources[name][0]),
                "upgrade_source_mode": sources[name][1],
                "upgrade_original_sha256": new_digest,
                "upgrade_original_mode": (
                    None
                    if new_original is _MISSING
                    else new_original_modes[name]
                ),
                "upgrade_backup": upgrade_backup,
                "installed_sha256": _sha256(installed_outputs[name]),
                "installed_mode": old_record["installed_mode"],
            }
        )
    prepared["phase"] = "prepared"
    _atomic_write(
        installation_dir / "install-state.json",
        canonical_json_bytes(prepared) + b"\n",
    )
    return _apply_prepared_install(
        home=home,
        installation_dir=installation_dir,
        state=prepared,
    )


def global_install(
    *,
    codex_home: Path | str,
    state_root: Path | str,
    codex_binary: Path | str,
    defaults: Mapping[str, Any],
) -> GlobalStatus:
    home = _validate_codex_home(codex_home)
    config = _validate_install_inputs(
        codex_home=home,
        state_root=state_root,
        codex_binary=codex_binary,
        defaults=defaults,
    )
    installation_dir = home / INSTALL_DIRECTORY_NAME
    with _home_lock(home):
        if os.path.lexists(installation_dir):
            _validate_install_directory(installation_dir)
            state = _load_install_state(installation_dir)
            raw_config = _read_private_file(installation_dir / "config.json")
            installed_config = _private_json(installation_dir / "config.json")
            identity_material = _read_private_file(
                installation_dir / _IDENTITY_FILE_NAME, maximum_bytes=32
            )
            if (
                installed_config == config
                and _sha256(raw_config) == state["config_sha256"]
                and len(identity_material) == 32
            ):
                if state["phase"] == "prepared":
                    return _apply_prepared_install(
                        home=home,
                        installation_dir=installation_dir,
                        state=state,
                    )
                if (
                    state["phase"] == "installed"
                    and set(state["targets"]) == set(_TARGET_NAMES)
                ):
                    return _prepare_installed_refresh(
                        home=home,
                        installation_dir=installation_dir,
                        state=state,
                    )
                if state["phase"] == "uninstalled":
                    return _reprepare_uninstalled_install(
                        home=home,
                        installation_dir=installation_dir,
                        state=state,
                        config=config,
                    )
            raise _error("conflict", "an incompatible Router installation already exists")

        records, originals = _build_target_records(
            home=home,
            installation_dir=installation_dir,
            config=config,
        )

        installation_dir.mkdir(mode=0o700, exist_ok=False)
        os.chmod(installation_dir, 0o700)
        backups = installation_dir / "backups"
        backups.mkdir(mode=0o700, exist_ok=False)
        os.chmod(backups, 0o700)
        _fsync_directory(home)
        _write_target_backups(
            installation_dir=installation_dir,
            originals=originals,
        )
        config_bytes = canonical_json_bytes(config) + b"\n"
        _atomic_write(installation_dir / "config.json", config_bytes)
        _atomic_write(installation_dir / _IDENTITY_FILE_NAME, secrets.token_bytes(32))
        install_state = {
            "protocol": INSTALL_STATE_PROTOCOL,
            "phase": "prepared",
            "config_sha256": _sha256(config_bytes),
            "targets": records,
        }
        _atomic_write(
            installation_dir / "install-state.json",
            canonical_json_bytes(install_state) + b"\n",
        )
        return _apply_prepared_install(
            home=home,
            installation_dir=installation_dir,
            state=install_state,
        )


def _status_from_state(home: Path, installation_dir: Path, state: Mapping[str, Any]) -> GlobalStatus:
    config_valid = False
    identity_valid = False
    role_config: dict[str, Any] | None = None
    try:
        raw_config = _read_private_file(installation_dir / "config.json")
        config = json.loads(raw_config)
        role_config = _validate_defaults(config.get("role_config"))
        config_valid = (
            isinstance(config, dict)
            and config.get("protocol") == GLOBAL_CONFIG_PROTOCOL
            and set(config)
            == {"protocol", "state_root", "codex_binary", "role_config"}
            and isinstance(config.get("state_root"), str)
            and Path(config["state_root"]).is_absolute()
            and Path(config["state_root"]) != home
            and home not in Path(config["state_root"]).parents
            and isinstance(config.get("codex_binary"), str)
            and Path(config["codex_binary"]).is_absolute()
            and config["role_config"] == role_config
            and _sha256(raw_config) == state.get("config_sha256")
        )
    except (RouterStateError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        pass
    try:
        identity_valid = (
            len(
                _read_private_file(
                    installation_dir / _IDENTITY_FILE_NAME, maximum_bytes=32
                )
            )
            == 32
        )
    except RouterStateError:
        pass

    hook_configured = False
    agents_managed = False
    luna_agent_configured = False
    targets_match_installed = True
    targets_match_original = True
    for name, record in state["targets"].items():
        path = home / name
        exists, content, mode = _read_target_file(home, name)
        installed_match = (
            exists
            and content is not None
            and _sha256(content) == record.get("installed_sha256")
            and mode == record.get("installed_mode")
        )
        targets_match_installed &= installed_match
        try:
            original = _target_original(installation_dir, name, record)
            original_match = _matches_current(
                path,
                original,
                expected_mode=record.get("original_mode"),
            )[0]
        except RouterStateError:
            original_match = False
        targets_match_original &= original_match
        if name == "hooks.json" and installed_match:
            try:
                parsed = json.loads(content)
                hook_configured = sum(
                    HOOK_MARKER in value for value in _walk_strings(parsed)
                ) == 7
            except (UnicodeDecodeError, json.JSONDecodeError):
                hook_configured = False
        elif name == "AGENTS.md" and installed_match:
            try:
                text = content.decode("utf-8", errors="strict")
                agents_managed = (
                    text.count(AGENTS_BEGIN) == 1
                    and text.count(AGENTS_END) == 1
                    and AGENTS_BLOCK.strip() in text
                )
            except UnicodeDecodeError:
                agents_managed = False
        elif (
            name == LUNA_AGENT_RELATIVE_PATH
            and installed_match
            and role_config is not None
        ):
            luna_agent_configured = _luna_agent_matches(
                content, role_config["luna"]
            )

    phase = state["phase"]
    if (
        phase == "installed"
        and targets_match_installed
        and hook_configured
        and agents_managed
        and luna_agent_configured
        and config_valid
        and identity_valid
    ):
        status_state = "installed"
    elif phase == "uninstalled" and targets_match_original:
        status_state = "uninstalled"
    elif phase == "prepared":
        status_state = "partial"
    else:
        status_state = "modified"
    return GlobalStatus(
        state=status_state,
        installation_dir=installation_dir,
        hook_configured=hook_configured,
        agents_managed=agents_managed,
        luna_agent_configured=luna_agent_configured,
        config_valid=config_valid,
        identity_material_valid=identity_valid,
        hook_trust=("requires-user-check" if status_state == "installed" else "unknown"),
        new_session_required=status_state in ("installed", "uninstalled"),
    )


def global_status(codex_home: Path | str) -> GlobalStatus:
    home = _validate_codex_home(codex_home)
    installation_dir = home / INSTALL_DIRECTORY_NAME
    if not os.path.lexists(installation_dir):
        return GlobalStatus(
            state="not-installed",
            installation_dir=installation_dir,
            hook_configured=False,
            agents_managed=False,
            luna_agent_configured=False,
            config_valid=False,
            identity_material_valid=False,
            hook_trust="unknown",
            new_session_required=False,
        )
    _validate_install_directory(installation_dir)
    try:
        state = _load_install_state(installation_dir)
        return _status_from_state(home, installation_dir, state)
    except RouterStateError:
        return GlobalStatus(
            state="partial",
            installation_dir=installation_dir,
            hook_configured=False,
            agents_managed=False,
            luna_agent_configured=False,
            config_valid=False,
            identity_material_valid=False,
            hook_trust="unknown",
            new_session_required=False,
        )


def global_uninstall(codex_home: Path | str) -> GlobalStatus:
    home = _validate_codex_home(codex_home)
    installation_dir = home / INSTALL_DIRECTORY_NAME
    with _home_lock(home):
        if not os.path.lexists(installation_dir):
            return global_status(home)
        _validate_install_directory(installation_dir)
        state = _load_install_state(installation_dir)
        if LUNA_AGENT_RELATIVE_PATH in state["targets"]:
            _validate_agents_directory(home, create=False)
        originals: dict[str, bytes | object] = {}
        current: dict[str, bytes | object] = {}
        current_modes: dict[str, int | None] = {}
        for name, record in state["targets"].items():
            path = home / name
            original = _target_original(installation_dir, name, record)
            originals[name] = original
            exists, content, mode = _read_target_file(home, name)
            current[name] = content if exists and content is not None else _MISSING
            current_modes[name] = mode
            installed_match = (
                exists
                and content is not None
                and _sha256(content) == record.get("installed_sha256")
                and mode == record.get("installed_mode")
            )
            original_match = _matches_current(
                path,
                original,
                expected_mode=record.get("original_mode"),
            )[0]
            migration_source = _migration_source_if_matches(
                home=home, name=name, record=record
            )
            migration_source_match = migration_source is not None
            if state["phase"] == "uninstalled":
                allowed = original_match
            else:
                allowed = installed_match or original_match or migration_source_match
            if not allowed:
                raise _error("conflict", "managed user file changed after installation")

        for name, record in state["targets"].items():
            path = home / name
            original = originals[name]
            installed = current[name]
            if _matches_current(
                path,
                original,
                expected_mode=record.get("original_mode"),
            )[0]:
                continue
            if original is _MISSING:
                if installed is _MISSING:
                    raise _error("conflict", "managed user file changed during recovery")
                _unlink_expected(
                    path,
                    expected=installed,
                    expected_mode=current_modes[name],
                )
            else:
                if installed is _MISSING:
                    raise _error("conflict", "managed user file changed during recovery")
                _replace_expected(
                    path,
                    expected=installed,
                    expected_mode=current_modes[name],
                    replacement=original,
                    mode=record["original_mode"],
                )
        if any("upgrade_backup" in record for record in state["targets"].values()):
            _finalize_upgrade_state(state)
        state["phase"] = "uninstalled"
        _atomic_write(
            installation_dir / "install-state.json",
            canonical_json_bytes(state) + b"\n",
        )
        return global_status(home)


def _self_test_context(output: Mapping[str, Any]) -> dict[str, Any]:
    try:
        hook_output = output["hookSpecificOutput"]
        additional_context = hook_output["additionalContext"]
        if (
            hook_output.get("hookEventName") != "UserPromptSubmit"
            or not isinstance(additional_context, str)
            or not additional_context.startswith(HOOK_CONTEXT_PREFIX)
        ):
            raise ValueError
        value = json.loads(additional_context[len(HOOK_CONTEXT_PREFIX) :])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _error("conflict", "global self-test received invalid hook output") from error
    if not isinstance(value, dict):
        raise _error("conflict", "global self-test hook context is invalid")
    return value


def _managed_fingerprints(home: Path) -> dict[str, str]:
    paths = [
        home / "hooks.json",
        home / "AGENTS.md",
        home / LUNA_AGENT_RELATIVE_PATH,
    ]
    installation_dir = home / INSTALL_DIRECTORY_NAME
    if installation_dir.is_dir():
        paths.extend(
            path for path in installation_dir.rglob("*") if path.is_file()
        )
    fingerprints: dict[str, str] = {}
    for path in paths:
        if path.is_file() and not path.is_symlink():
            fingerprints[str(path.relative_to(home))] = _sha256(path.read_bytes())
    return fingerprints


def _configured_hook_handler(home: Path) -> dict[str, Any]:
    exists, raw_hooks, _ = _read_user_file(home / "hooks.json")
    if not exists or raw_hooks is None:
        raise _error("conflict", "configured Router hook is unavailable")
    try:
        document = json.loads(raw_hooks)
        groups = document["hooks"]["UserPromptSubmit"]
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as error:
        raise _error("conflict", "configured Router hook is invalid") from error
    matches: list[dict[str, Any]] = []
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, Mapping) or not isinstance(
                group.get("hooks"), list
            ):
                continue
            for item in group["hooks"]:
                if (
                    isinstance(item, Mapping)
                    and item.get("type") == "command"
                    and item.get("statusMessage")
                    == f"Routing with Codex Router [{HOOK_MARKER}]"
                ):
                    matches.append(deepcopy(dict(item)))
    if len(matches) != 1:
        raise _error("conflict", "configured Router hook is invalid")
    return matches[0]


def global_self_test(codex_home: Path | str) -> dict[str, Any]:
    home = _validate_codex_home(codex_home)
    live_home = (Path.home() / ".codex").resolve(strict=False)
    if home.resolve(strict=True) == live_home:
        raise _error("invalid-input", "global self-test refuses the live Codex home")
    status = global_status(home)
    if status.state != "installed":
        raise _error("conflict", "global self-test requires a complete installation")

    installation_dir = home / INSTALL_DIRECTORY_NAME
    config = _private_json(installation_dir / "config.json")
    configured_handler = _configured_hook_handler(home)
    configured_arguments = _handler_argv(
        configured_handler, expected_installation_dir=installation_dir
    )
    before_fingerprints = _managed_fingerprints(home)
    configured_state_root = Path(config["state_root"])
    configured_state_existed = configured_state_root.exists()
    session_a = "synthetic-self-test-session-" + "a"
    session_b = "synthetic-self-test-session-" + "b"
    turn_a = "synthetic-self-test-turn-" + "a"
    turn_b = "synthetic-self-test-turn-" + "b"
    route_prompt = "修改 synthetic-self-test-route artifact"
    direct_prompt = "你好"
    bypass_prompt = "仅本地执行\n" + route_prompt
    raw_values = (session_a, session_b, turn_a, turn_b, route_prompt)
    ephemeral_path: Path | None = None

    with tempfile.TemporaryDirectory(prefix="codex-router-self-test-") as temporary:
        ephemeral_path = Path(temporary)
        ephemeral_path.chmod(0o700)

        def event(*, prompt: str, session: str, turn: str) -> dict[str, str]:
            return {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session,
                "turn_id": turn,
                "prompt": prompt,
                "cwd": str(ephemeral_path),
            }

        direct = _self_test_context(
            _invoke_hook_argv(
                configured_arguments,
                event=event(
                    prompt=direct_prompt,
                    session=session_a,
                    turn="direct-turn",
                ),
                cwd=ephemeral_path,
            )
        )
        bypass = _self_test_context(
            _invoke_hook_argv(
                configured_arguments,
                event=event(
                    prompt=bypass_prompt,
                    session=session_a,
                    turn="bypass-turn",
                ),
                cwd=ephemeral_path,
            )
        )
        route = _self_test_context(
            _invoke_hook_argv(
                configured_arguments,
                event=event(prompt=route_prompt, session=session_a, turn=turn_a),
                cwd=ephemeral_path,
            )
        )
        duplicate = _self_test_context(
            _invoke_hook_argv(
                configured_arguments,
                event=event(prompt=route_prompt, session=session_a, turn=turn_a),
                cwd=ephemeral_path,
            )
        )
        changed_session = _self_test_context(
            _invoke_hook_argv(
                configured_arguments,
                event=event(prompt=route_prompt, session=session_b, turn=turn_a),
                cwd=ephemeral_path,
            )
        )
        changed_turn = _self_test_context(
            _invoke_hook_argv(
                configured_arguments,
                event=event(prompt=route_prompt, session=session_a, turn=turn_b),
                cwd=ephemeral_path,
            )
        )

        route_contexts = (route, duplicate, changed_session, changed_turn)
        output_text = json.dumps(
            {
                "direct": direct,
                "bypass": bypass,
                "routes": route_contexts,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        expected_route = {
            "protocol": HOOK_CONTEXT_PROTOCOL,
            "decision": "route",
            "reason": "substantive_request",
            "workflow": "native_luna_worker",
            "sol_role": "plan_review_final_authority",
            "luna_role": "default_execution",
            "delegation_mode": "sequential_work_packets",
            "luna_agent": "luna_worker",
            "luna_model": config["role_config"]["luna"]["requested_model"],
            "luna_reasoning": config["role_config"]["luna"][
                "requested_reasoning"
            ],
            "luna_lifecycle": "persistent_while_root_turn_active",
            "parent_terminal_policy": "revoke_then_cleanup",
            "capacity_failure_policy": "return_to_sol",
            "luna_descendant_policy": "forbidden",
            "luna_codex_runtime_policy": "forbidden",
            "interactive_blocker_policy": "return_to_sol_or_user",
            "initial_context_mode": "packet_only",
            "web_mode": "manual_operator",
        }

        checks = {
            "hook_protocol": all(
                context.get("protocol") == HOOK_CONTEXT_PROTOCOL
                for context in (direct, bypass, *route_contexts)
            ),
            "direct_policy": direct.get("decision") == "direct",
            "bypass_policy": bypass.get("decision") == "bypass",
            "route_policy": all(
                context.get("decision") == "route" for context in route_contexts
            ),
            "stateless_native_luna_route": all(
                context == expected_route for context in route_contexts
            ),
            "no_router_run_created": (
                configured_state_root.exists() == configured_state_existed
            ),
            "raw_values_not_returned": all(value not in output_text for value in raw_values),
            "luna_agent_configured": status.luna_agent_configured,
            "hook_command_subprocess": True,
        }

    checks["ephemeral_artifacts_removed"] = (
        ephemeral_path is not None and not ephemeral_path.exists()
    )
    checks["persistent_installation_unchanged"] = (
        _managed_fingerprints(home) == before_fingerprints
    )
    checks["configured_state_root_untouched"] = (
        configured_state_root.exists() == configured_state_existed
    )
    if not all(checks.values()):
        raise _error("conflict", "global self-test failed closed")
    return {
        "protocol": "codex-router/global-self-test/v1",
        "status": "pass",
        "checks": checks,
        "network_used": False,
        "browser_used": False,
        "installation_activated": False,
        "hook_trust": "unknown",
    }
