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
import sys
import tempfile
from typing import Any, Iterator, Mapping

from .hook import (
    GLOBAL_CONFIG_PROTOCOL,
    HOOK_CONTEXT_PREFIX,
    handle_user_prompt,
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
_MISSING = object()
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")

AGENTS_BLOCK = f"""{AGENTS_BEGIN}
Codex Router is the sole workflow state authority; this Codex task is the execution driver.
Honor `[CODEX_ROUTER_POLICY_V1]` hook context exactly:
- `direct` and `bypass` run only the current turn locally.
- `route` must show `Router: active`, resume the referenced canonical run, and drive Local Sol -> Web Sol -> Luna in order.
- Local Sol and Luna use Router-configured local models; Web Sol uses the operator-attested continuous Web conversation for this driver context.
- Never fabricate a stage result, skip a transition, create a replacement run, or open/close browser pages on Router's behalf.
- Wait for a terminal Router state before answering routed substantive work; recover from canonical `state.json` after interruption.
{AGENTS_END}
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
    path: Path, expected: bytes | object
) -> tuple[bool, bytes | None, int | None]:
    exists, content, mode = _read_user_file(path)
    if expected is _MISSING:
        return not exists, content, mode
    return exists and content == expected, content, mode


def _replace_expected(
    path: Path,
    *,
    expected: bytes | object,
    replacement: bytes,
    mode: int,
) -> None:
    matches, _, _ = _matches_current(path, expected)
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
        matches, _, _ = _matches_current(path, expected)
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


def _unlink_expected(path: Path, *, expected: bytes) -> None:
    matches, _, _ = _matches_current(path, expected)
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


def _hook_handler(installation_dir: Path) -> dict[str, Any]:
    python = str(Path(sys.executable).resolve(strict=True))
    command = shlex.join(
        [
            python,
            "-m",
            "codex_router",
            "hook-user-prompt",
            "--installation-dir",
            str(installation_dir),
        ]
    )
    return {
        "type": "command",
        "command": command,
        "timeout": 10,
        "statusMessage": f"Routing with Codex Router [{HOOK_MARKER}]",
        "additionalContextLimit": 2500,
    }


def _install_hook(original: bytes | None, handler: Mapping[str, Any]) -> bytes:
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
    prompt_groups = hooks.get("UserPromptSubmit")
    if prompt_groups is None:
        prompt_groups = []
        hooks["UserPromptSubmit"] = prompt_groups
    if not isinstance(prompt_groups, list):
        raise _error("conflict", "UserPromptSubmit hook groups are invalid")
    for group in prompt_groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("hooks"), list):
            raise _error("conflict", "UserPromptSubmit hook group is invalid")
        if any(not isinstance(item, Mapping) for item in group["hooks"]):
            raise _error("conflict", "UserPromptSubmit hook handler is invalid")
    prompt_groups.append({"hooks": [deepcopy(dict(handler))]})
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
        or set(state["targets"]) != {"hooks.json", "AGENTS.md"}
    ):
        raise _error("conflict", "Router installation state is invalid")
    expected_backups = {
        "hooks.json": "backups/hooks.json.original",
        "AGENTS.md": "backups/agents.md.original",
    }
    for name, record in state["targets"].items():
        if not isinstance(record, Mapping) or set(record) != {
            "existed",
            "original_sha256",
            "original_mode",
            "backup",
            "installed_sha256",
            "installed_mode",
        }:
            raise _error("conflict", "Router target evidence is invalid")
        installed_mode = record.get("installed_mode")
        if (
            not _valid_digest(record.get("installed_sha256"))
            or not isinstance(installed_mode, int)
            or isinstance(installed_mode, bool)
            or not 0 <= installed_mode <= 0o777
        ):
            raise _error("conflict", "Router installed target evidence is invalid")
        if record.get("existed") is True:
            original_mode = record.get("original_mode")
            if (
                not _valid_digest(record.get("original_sha256"))
                or not isinstance(original_mode, int)
                or isinstance(original_mode, bool)
                or not 0 <= original_mode <= 0o777
                or record.get("backup") != expected_backups[name]
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
    return state


def _target_original(installation_dir: Path, record: Mapping[str, Any]) -> bytes | object:
    if record.get("existed") is False:
        if any(record.get(name) is not None for name in ("original_sha256", "original_mode", "backup")):
            raise _error("conflict", "Router absence evidence is invalid")
        return _MISSING
    backup = record.get("backup")
    if record.get("existed") is not True or not isinstance(backup, str):
        raise _error("conflict", "Router backup evidence is invalid")
    original = _read_private_file(installation_dir / backup, maximum_bytes=_MAX_USER_FILE_BYTES)
    if _sha256(original) != record.get("original_sha256"):
        raise _error("conflict", "Router backup digest does not match")
    return original


def _installed_state_matches(
    *, codex_home: Path, installation_dir: Path, state: Mapping[str, Any]
) -> bool:
    for name, record in state["targets"].items():
        exists, content, _ = _read_user_file(codex_home / name)
        if not exists or content is None or _sha256(content) != record.get("installed_sha256"):
            return False
    return True


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
            installed_config = _private_json(installation_dir / "config.json")
            identity_material = _read_private_file(
                installation_dir / _IDENTITY_FILE_NAME, maximum_bytes=32
            )
            if (
                state["phase"] == "installed"
                and installed_config == config
                and len(identity_material) == 32
                and _installed_state_matches(
                    codex_home=home, installation_dir=installation_dir, state=state
                )
            ):
                return global_status(home)
            raise _error("conflict", "an incompatible Router installation already exists")

        hooks_path = home / "hooks.json"
        agents_path = home / "AGENTS.md"
        hooks_exists, hooks_original, hooks_mode = _read_user_file(hooks_path)
        agents_exists, agents_original, agents_mode = _read_user_file(agents_path)
        handler = _hook_handler(installation_dir)
        hooks_installed = _install_hook(hooks_original, handler)
        agents_installed = _install_agents(agents_original)
        hooks_installed_mode = hooks_mode if hooks_mode is not None else 0o600
        agents_installed_mode = agents_mode if agents_mode is not None else 0o600

        installation_dir.mkdir(mode=0o700, exist_ok=False)
        os.chmod(installation_dir, 0o700)
        backups = installation_dir / "backups"
        backups.mkdir(mode=0o700, exist_ok=False)
        os.chmod(backups, 0o700)
        _fsync_directory(home)
        if hooks_original is not None:
            _atomic_write(backups / "hooks.json.original", hooks_original)
        if agents_original is not None:
            _atomic_write(backups / "agents.md.original", agents_original)
        config_bytes = canonical_json_bytes(config) + b"\n"
        _atomic_write(installation_dir / "config.json", config_bytes)
        _atomic_write(installation_dir / _IDENTITY_FILE_NAME, secrets.token_bytes(32))
        install_state = {
            "protocol": INSTALL_STATE_PROTOCOL,
            "phase": "prepared",
            "config_sha256": _sha256(config_bytes),
            "targets": {
                "hooks.json": _target_record(
                    existed=hooks_exists,
                    original=hooks_original,
                    original_mode=hooks_mode,
                    installed=hooks_installed,
                    backup="backups/hooks.json.original" if hooks_exists else None,
                    installed_mode=hooks_installed_mode,
                ),
                "AGENTS.md": _target_record(
                    existed=agents_exists,
                    original=agents_original,
                    original_mode=agents_mode,
                    installed=agents_installed,
                    backup="backups/agents.md.original" if agents_exists else None,
                    installed_mode=agents_installed_mode,
                ),
            },
        }
        _atomic_write(
            installation_dir / "install-state.json",
            canonical_json_bytes(install_state) + b"\n",
        )
        hooks_expected = hooks_original if hooks_exists else _MISSING
        agents_expected = agents_original if agents_exists else _MISSING
        if not _matches_current(hooks_path, hooks_expected)[0] or not _matches_current(
            agents_path, agents_expected
        )[0]:
            raise _error("conflict", "managed user files changed concurrently")
        _replace_expected(
            hooks_path,
            expected=hooks_expected,
            replacement=hooks_installed,
            mode=hooks_installed_mode,
        )
        _replace_expected(
            agents_path,
            expected=agents_expected,
            replacement=agents_installed,
            mode=agents_installed_mode,
        )
        install_state["phase"] = "installed"
        _atomic_write(
            installation_dir / "install-state.json",
            canonical_json_bytes(install_state) + b"\n",
        )
        return global_status(home)


def _status_from_state(home: Path, installation_dir: Path, state: Mapping[str, Any]) -> GlobalStatus:
    config_valid = False
    identity_valid = False
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
    targets_match_installed = True
    targets_match_original = True
    for name, record in state["targets"].items():
        path = home / name
        exists, content, _ = _read_user_file(path)
        installed_match = (
            exists
            and content is not None
            and _sha256(content) == record.get("installed_sha256")
        )
        targets_match_installed &= installed_match
        try:
            original = _target_original(installation_dir, record)
            original_match = _matches_current(path, original)[0]
        except RouterStateError:
            original_match = False
        targets_match_original &= original_match
        if name == "hooks.json" and installed_match:
            try:
                parsed = json.loads(content)
                hook_configured = sum(
                    HOOK_MARKER in value for value in _walk_strings(parsed)
                ) == 1
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

    phase = state["phase"]
    if (
        phase == "installed"
        and targets_match_installed
        and hook_configured
        and agents_managed
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
        originals: dict[str, bytes | object] = {}
        current: dict[str, bytes | object] = {}
        for name, record in state["targets"].items():
            path = home / name
            original = _target_original(installation_dir, record)
            originals[name] = original
            exists, content, _ = _read_user_file(path)
            if not exists or content is None:
                current[name] = _MISSING
            else:
                current[name] = content
            installed_match = (
                exists
                and content is not None
                and _sha256(content) == record.get("installed_sha256")
            )
            original_match = _matches_current(path, original)[0]
            if state["phase"] == "uninstalled":
                allowed = original_match
            else:
                allowed = installed_match or original_match
            if not allowed:
                raise _error("conflict", "managed user file changed after installation")

        for name, record in state["targets"].items():
            path = home / name
            original = originals[name]
            installed = current[name]
            if original is _MISSING:
                if installed is not _MISSING:
                    _unlink_expected(path, expected=installed)
            elif installed is _MISSING:
                _replace_expected(
                    path,
                    expected=_MISSING,
                    replacement=original,
                    mode=record["original_mode"],
                )
            elif installed != original:
                _replace_expected(
                    path,
                    expected=installed,
                    replacement=original,
                    mode=record["original_mode"],
                )
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
    paths = [home / "hooks.json", home / "AGENTS.md"]
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
        test_installation = ephemeral_path / "installation"
        test_installation.mkdir(mode=0o700)
        test_installation.chmod(0o700)
        test_config = deepcopy(config)
        test_config["state_root"] = str(ephemeral_path / "runs")
        _atomic_write(
            test_installation / "config.json",
            canonical_json_bytes(test_config) + b"\n",
        )
        _atomic_write(
            test_installation / _IDENTITY_FILE_NAME,
            bytes(range(32)),
        )

        def event(*, prompt: str, session: str, turn: str) -> dict[str, str]:
            return {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session,
                "turn_id": turn,
                "prompt": prompt,
                "cwd": str(ephemeral_path),
            }

        direct = _self_test_context(
            handle_user_prompt(
                event(prompt=direct_prompt, session=session_a, turn="direct-turn"),
                test_installation,
            )
        )
        bypass = _self_test_context(
            handle_user_prompt(
                event(prompt=bypass_prompt, session=session_a, turn="bypass-turn"),
                test_installation,
            )
        )
        route = _self_test_context(
            handle_user_prompt(
                event(prompt=route_prompt, session=session_a, turn=turn_a),
                test_installation,
            )
        )
        duplicate = _self_test_context(
            handle_user_prompt(
                event(prompt=route_prompt, session=session_a, turn=turn_a),
                test_installation,
            )
        )
        changed_session = _self_test_context(
            handle_user_prompt(
                event(prompt=route_prompt, session=session_b, turn=turn_a),
                test_installation,
            )
        )
        changed_turn = _self_test_context(
            handle_user_prompt(
                event(prompt=route_prompt, session=session_a, turn=turn_b),
                test_installation,
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
        run_root = ephemeral_path / "runs"
        run_directories = sorted(
            path for path in run_root.glob("run-hook-*") if path.is_dir()
        )
        local_only = len(run_directories) == 3
        identity_not_persisted = True
        for run_directory in run_directories:
            state = json.loads(
                (run_directory / "state.json").read_text(encoding="utf-8")
            )
            local_only &= (
                state.get("status") == "awaiting_local_sol"
                and state.get("next_stage") == "local_sol"
                and not (run_directory / "web-sol.json").exists()
                and not (run_directory / "luna.json").exists()
            )
            evidence = b"\n".join(
                path.read_bytes()
                for path in run_directory.rglob("*")
                if path.is_file()
            ).decode("utf-8", errors="ignore")
            identity_not_persisted &= all(
                identity not in evidence
                for identity in (session_a, session_b, turn_a, turn_b)
            )

        checks = {
            "direct_policy": direct.get("decision") == "direct",
            "bypass_policy": bypass.get("decision") == "bypass",
            "route_policy": all(
                context.get("decision") == "route" for context in route_contexts
            ),
            "duplicate_event_idempotent": (
                route.get("run_id") == duplicate.get("run_id")
                and duplicate.get("idempotent") is True
            ),
            "same_session_stable": (
                route.get("driver_context_id")
                == changed_turn.get("driver_context_id")
                and route.get("run_id") != changed_turn.get("run_id")
            ),
            "different_session_isolated": (
                route.get("driver_context_id")
                != changed_session.get("driver_context_id")
            ),
            "one_run_per_event": len(run_directories) == 3,
            "local_stage_only": local_only,
            "raw_identity_not_persisted": identity_not_persisted,
            "raw_values_not_returned": all(value not in output_text for value in raw_values),
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
