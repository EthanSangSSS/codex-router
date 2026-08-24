from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping

from . import global_install as _core
from .protocol import canonical_json_bytes
from .state import RouterStateError


NATIVE_INSTALL_DIRECTORY_NAME = ".codex-native-primary-luna-v1"
NATIVE_INSTALL_STATE_PROTOCOL = "codex-native-primary-luna/install-state/v1"
NATIVE_AGENTS_BEGIN = "# BEGIN CODEX NATIVE PRIMARY LUNA V1"
NATIVE_AGENTS_END = "# END CODEX NATIVE PRIMARY LUNA V1"

_AGENTS_TARGET = "AGENTS.md"
_LUNA_TARGET = _core.LUNA_AGENT_RELATIVE_PATH
_NATIVE_TARGETS = (_AGENTS_TARGET, _LUNA_TARGET)
_NATIVE_BACKUPS = {
    _AGENTS_TARGET: "backups/AGENTS.md.original",
    _LUNA_TARGET: "backups/luna-worker.toml.original",
}
_ROUTER_HOOK_COMMAND = re.compile(
    r"\bcodex_router\b.*\bhook-(?:user-prompt-submit|pre-tool|post-tool|subagent-start|subagent-stop)\b"
)


@dataclass(frozen=True)
class NativeStatus:
    state: str
    installation_dir: Path
    agents_managed: bool
    luna_agent_configured: bool
    router_hooks_present: bool
    new_session_required: bool

_LUNA_DESCRIPTION = (
    "A disposable native execution subagent for substantial local engineering "
    "delegated by PRIMARY."
)

_LUNA_DEVELOPER_INSTRUCTIONS = """You are Luna, a disposable native execution subagent of PRIMARY.
Execute the delegated task in the current Codex workspace using the normal native sandbox, approvals, and exposed tools.
You may inspect/search/read files; edit/create/delete task-related files; run shell/project tooling; build/test/lint/typecheck; run Playwright/Cypress/headless E2E; debug; refactor; retry; verify; and inspect local Git status/diff/log when relevant.
Do not spawn descendants or another Codex runtime. Do not intentionally daemonize persistent background work.
Do not perform unrelated destructive actions. Do not commit, push, mutate PRs, deploy/publish, communicate externally, mutate cloud resources, or perform system-level installation unless the delegated user objective explicitly requires that action and native platform controls permit/approve it.
Return concise implementation evidence, tests run, blockers, and remaining risks to PRIMARY."""


def render_primary_block() -> str:
    return f"""{NATIVE_AGENTS_BEGIN}
You are PRIMARY: the persistent planner, coordinator, reviewer, and final responder.
Use the native `luna_worker` execution subagent for substantial local engineering when useful; keep simple answers, planning, review, interactive browser/user-session UI work, and the final response in PRIMARY.
If the user explicitly asks not to use Luna for the current turn, do not spawn Luna.
Playwright, Cypress, headless browser tests, local E2E, and browser-code debugging are local engineering and may be delegated to Luna.
Use the native spawn surface actually exposed by the runtime. Do not invent unsupported spawn fields. Prefer one fresh Luna for one delegated execution task; do not rely on child-memory persistence, followup, resume, polling, or a Router protocol.
If native Luna spawn is unavailable or fails, continue the user's task locally when normal Codex tools allow it; delegation failure alone is not a reason to stop the task.
After Luna returns, inspect its evidence/results as needed and own the final answer.
{NATIVE_AGENTS_END}"""


def render_luna_agent_bytes(*, model: str, reasoning: str) -> bytes:
    if not isinstance(model, str) or not model.strip():
        raise _core._error("invalid-input", "Luna model configuration is invalid")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise _core._error("invalid-input", "Luna reasoning configuration is invalid")
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
        "\n[agents]\n"
        "enabled = false\n"
        "\n[features]\n"
        "multi_agent = false\n"
        "multi_agent_v2 = false\n"
    )
    encoded = rendered.encode("utf-8")
    try:
        parsed = tomllib.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise _core._error(
            "conflict", "generated Luna agent configuration is invalid"
        ) from error
    expected = {
        **values,
        "agents": {"enabled": False},
        "features": {"multi_agent": False, "multi_agent_v2": False},
    }
    if parsed != expected:
        raise _core._error(
            "conflict", "generated Luna agent configuration is unstable"
        )
    return encoded


def _managed_primary_bytes() -> bytes:
    return (render_primary_block() + "\n").encode("utf-8")


def _install_primary_block(original: bytes | None) -> bytes:
    if original is not None and not isinstance(original, bytes):
        raise _core._error("conflict", "AGENTS.md original content is invalid")
    existing = b"" if original is None else original
    try:
        text = existing.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _core._error("conflict", "AGENTS.md is not valid UTF-8") from error
    if NATIVE_AGENTS_BEGIN in text or NATIVE_AGENTS_END in text:
        raise _core._error("conflict", "AGENTS.md Native markers are ambiguous")
    managed = _managed_primary_bytes()
    if not existing:
        return managed
    return existing + b"\n\n" + managed


def _strip_primary_block(current: bytes) -> bytes | None:
    if not isinstance(current, bytes):
        raise _core._error("conflict", "AGENTS.md content is invalid")
    try:
        text = current.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _core._error("conflict", "AGENTS.md is not valid UTF-8") from error
    if text.count(NATIVE_AGENTS_BEGIN) != 1 or text.count(NATIVE_AGENTS_END) != 1:
        raise _core._error("conflict", "AGENTS.md Native markers are ambiguous")
    managed = _managed_primary_bytes()
    if current == managed:
        return None
    if not current.endswith(managed):
        raise _core._error("conflict", "AGENTS.md Native block was modified")
    prefix = current[: -len(managed)]
    if not prefix.endswith(b"\n\n"):
        raise _core._error("conflict", "AGENTS.md Native boundary is invalid")
    return prefix[:-2]


def _installation_dir(home: Path) -> Path:
    return home / NATIVE_INSTALL_DIRECTORY_NAME


def _backup_bytes(
    installation_dir: Path, name: str, record: Mapping[str, Any]
) -> bytes | None:
    if record.get("existed") is False:
        return None
    relative = record.get("backup")
    if relative != _NATIVE_BACKUPS.get(name):
        raise _core._error("conflict", "Native backup identity is invalid")
    content = _core._read_private_file(
        installation_dir / relative,
        maximum_bytes=_core._MAX_USER_FILE_BYTES,
    )
    if _core._sha256(content) != record.get("original_sha256"):
        raise _core._error("conflict", "Native backup digest does not match")
    return content


def _validate_state(
    installation_dir: Path, state: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        not isinstance(state, Mapping)
        or set(state) != {"protocol", "phase", "targets"}
        or state.get("protocol") != NATIVE_INSTALL_STATE_PROTOCOL
        or state.get("phase") not in {"prepared", "installed", "uninstalled"}
        or not isinstance(state.get("targets"), Mapping)
        or set(state["targets"]) != set(_NATIVE_TARGETS)
    ):
        raise _core._error("conflict", "Native installation state is invalid")
    agents = state["targets"][_AGENTS_TARGET]
    luna = state["targets"][_LUNA_TARGET]
    if not isinstance(agents, Mapping) or set(agents) != {
        "existed",
        "original_sha256",
        "original_mode",
        "backup",
        "installed_block_sha256",
    }:
        raise _core._error("conflict", "Native AGENTS ownership evidence is invalid")
    if not isinstance(luna, Mapping) or set(luna) != {
        "existed",
        "original_sha256",
        "original_mode",
        "backup",
        "installed_sha256",
        "installed_mode",
    }:
        raise _core._error("conflict", "Native Luna ownership evidence is invalid")
    if not _core._valid_digest(agents.get("installed_block_sha256")):
        raise _core._error("conflict", "Native AGENTS block evidence is invalid")
    for name, record in ((_AGENTS_TARGET, agents), (_LUNA_TARGET, luna)):
        if record.get("existed") is True:
            if (
                not _core._valid_digest(record.get("original_sha256"))
                or not _core._valid_mode(record.get("original_mode"))
                or record.get("backup") != _NATIVE_BACKUPS[name]
            ):
                raise _core._error(
                    "conflict", "Native original ownership evidence is invalid"
                )
            _backup_bytes(installation_dir, name, record)
        elif record.get("existed") is False:
            if any(
                record.get(field) is not None
                for field in ("original_sha256", "original_mode", "backup")
            ):
                raise _core._error(
                    "conflict", "Native absence ownership evidence is invalid"
                )
        else:
            raise _core._error(
                "conflict", "Native target ownership evidence is invalid"
            )
    if (
        not _core._valid_digest(luna.get("installed_sha256"))
        or not _core._valid_mode(luna.get("installed_mode"))
    ):
        raise _core._error("conflict", "Native Luna installed evidence is invalid")
    return {
        "protocol": state["protocol"],
        "phase": state["phase"],
        "targets": {
            _AGENTS_TARGET: dict(agents),
            _LUNA_TARGET: dict(luna),
        },
    }


def _load_state(home: Path) -> dict[str, Any] | None:
    installation_dir = _installation_dir(home)
    if not os.path.lexists(installation_dir):
        return None
    _core._validate_install_directory(installation_dir)
    state = _core._private_json(installation_dir / "install-state.json")
    return _validate_state(installation_dir, state)


def _write_state(home: Path, state: Mapping[str, Any]) -> None:
    installation_dir = _installation_dir(home)
    validated = _validate_state(installation_dir, state)
    _core._atomic_write(
        installation_dir / "install-state.json",
        canonical_json_bytes(validated) + b"\n",
    )


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _router_hooks_present(home: Path) -> bool:
    exists, content, _mode = _core._read_user_file(home / "hooks.json")
    if not exists or content is None:
        return False
    try:
        raw = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    if _core.HOOK_MARKER in raw:
        return True
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return any(_ROUTER_HOOK_COMMAND.search(value) for value in _walk_strings(document))


def _legacy_agents_markers_present(home: Path) -> bool:
    exists, content, _mode = _core._read_target_file(home, _AGENTS_TARGET)
    if not exists or content is None:
        return False
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    return _core.AGENTS_BEGIN in text or _core.AGENTS_END in text


def _migrate_legacy_router_if_needed(home: Path) -> bool:
    from . import global_install_adapter as legacy

    status = legacy.global_status(home)
    if status.state == "installed":
        uninstalled = legacy.global_uninstall(home)
        if (
            uninstalled.state != "uninstalled"
            or uninstalled.hook_configured
            or uninstalled.agents_managed
            or uninstalled.luna_agent_configured
            or _router_hooks_present(home)
            or _legacy_agents_markers_present(home)
        ):
            raise _core._error(
                "conflict", "legacy Router managed uninstall did not reverse safely"
            )
        return True
    if status.state in {"not-installed", "uninstalled"}:
        if (
            status.hook_configured
            or status.agents_managed
            or status.luna_agent_configured
            or _router_hooks_present(home)
            or _legacy_agents_markers_present(home)
        ):
            raise _core._error(
                "conflict", "legacy Router ownership is ambiguous"
            )
        return False
    raise _core._error(
        "conflict", "legacy Router installation is modified or ambiguous"
    )


def _native_marker_counts(content: bytes | None) -> tuple[int, int]:
    if content is None:
        return 0, 0
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return -1, -1
    return text.count(NATIVE_AGENTS_BEGIN), text.count(NATIVE_AGENTS_END)


def _status_from_state(
    home: Path, state: Mapping[str, Any] | None
) -> NativeStatus:
    installation_dir = _installation_dir(home)
    router_hooks = _router_hooks_present(home)
    agents_exists, agents_content, _agents_mode = _core._read_target_file(
        home, _AGENTS_TARGET
    )
    if state is None:
        begin_count, end_count = _native_marker_counts(agents_content)
        status_name = "absent" if begin_count == end_count == 0 else "modified"
        return NativeStatus(
            state=status_name,
            installation_dir=installation_dir,
            agents_managed=False,
            luna_agent_configured=False,
            router_hooks_present=router_hooks,
            new_session_required=False,
        )

    agents_record = state["targets"][_AGENTS_TARGET]
    luna_record = state["targets"][_LUNA_TARGET]
    agents_managed = False
    if (
        agents_exists
        and agents_content is not None
        and agents_record.get("installed_block_sha256")
        == _core._sha256(_managed_primary_bytes())
    ):
        try:
            _strip_primary_block(agents_content)
            agents_managed = True
        except RouterStateError:
            agents_managed = False
    luna_exists, luna_content, luna_mode = _core._read_target_file(home, _LUNA_TARGET)
    luna_configured = (
        luna_exists
        and luna_content is not None
        and _core._sha256(luna_content) == luna_record.get("installed_sha256")
        and luna_mode == luna_record.get("installed_mode")
    )

    if (
        state["phase"] == "installed"
        and agents_managed
        and luna_configured
        and not router_hooks
    ):
        status_name = "installed"
    elif state["phase"] == "uninstalled":
        begin_count, end_count = _native_marker_counts(agents_content)
        agents_reversed = begin_count == end_count == 0
        if luna_record.get("existed") is True:
            original_luna = _backup_bytes(installation_dir, _LUNA_TARGET, luna_record)
            luna_reversed = (
                luna_exists
                and luna_content == original_luna
                and luna_mode == luna_record.get("original_mode")
            )
        else:
            luna_reversed = not luna_exists
        status_name = "uninstalled" if agents_reversed and luna_reversed else "modified"
    else:
        status_name = "modified"
    return NativeStatus(
        state=status_name,
        installation_dir=installation_dir,
        agents_managed=agents_managed,
        luna_agent_configured=luna_configured,
        router_hooks_present=router_hooks,
        new_session_required=status_name == "installed",
    )


def native_status(codex_home: Path | str) -> NativeStatus:
    home = _core._validate_codex_home(codex_home)
    installation_dir = _installation_dir(home)
    try:
        state = _load_state(home)
    except RouterStateError:
        return NativeStatus(
            state="modified",
            installation_dir=installation_dir,
            agents_managed=False,
            luna_agent_configured=False,
            router_hooks_present=_router_hooks_present(home),
            new_session_required=False,
        )
    return _status_from_state(home, state)


def _create_installation_directories(home: Path) -> Path:
    installation_dir = _installation_dir(home)
    try:
        installation_dir.mkdir(mode=0o700)
        os.chmod(installation_dir, 0o700)
        backups = installation_dir / "backups"
        backups.mkdir(mode=0o700)
        os.chmod(backups, 0o700)
        _core._fsync_directory(installation_dir)
        _core._fsync_directory(home)
    except OSError as error:
        raise _core._error(
            "conflict", "Native installation directory cannot be created safely"
        ) from error
    return installation_dir


def _target_record(
    *, existed: bool, original: bytes | None, original_mode: int | None
) -> dict[str, Any]:
    return {
        "existed": existed,
        "original_sha256": _core._sha256(original) if original is not None else None,
        "original_mode": original_mode,
        "backup": None,
    }


def native_install(
    codex_home: Path | str,
    *,
    luna_model: str = "gpt-5.6-luna",
    luna_reasoning: str = "max",
) -> NativeStatus:
    expected_luna = render_luna_agent_bytes(
        model=luna_model, reasoning=luna_reasoning
    )
    home = _core._validate_codex_home(codex_home)
    existing_native_state = _load_state(home)
    if (
        existing_native_state is None
        or existing_native_state["phase"] == "uninstalled"
    ):
        _migrate_legacy_router_if_needed(home)
    with _core._home_lock(home):
        state = _load_state(home)
        if state is not None:
            current_status = _status_from_state(home, state)
            if current_status.state == "installed":
                _exists, current_luna, _mode = _core._read_target_file(
                    home, _LUNA_TARGET
                )
                if current_luna != expected_luna:
                    raise _core._error(
                        "conflict",
                        "Native Luna configuration differs; uninstall before reinstall",
                    )
                return current_status
            if current_status.state != "uninstalled":
                raise _core._error(
                    "conflict", "Native installation ownership is modified or ambiguous"
                )
        if _router_hooks_present(home):
            raise _core._error(
                "conflict", "Router routing hooks must be managed-uninstalled first"
            )

        agents_exists, agents_original, agents_mode = _core._read_target_file(
            home, _AGENTS_TARGET
        )
        luna_exists, luna_original, luna_mode = _core._read_target_file(
            home, _LUNA_TARGET
        )
        installed_agents = _install_primary_block(agents_original)
        if state is None:
            installation_dir = _create_installation_directories(home)
        else:
            installation_dir = _installation_dir(home)
        _core._validate_install_directory(installation_dir)
        _core._validate_agents_directory(home, create=True)

        agents_record = _target_record(
            existed=agents_exists,
            original=agents_original,
            original_mode=agents_mode,
        )
        agents_record["installed_block_sha256"] = _core._sha256(
            _managed_primary_bytes()
        )
        luna_record = _target_record(
            existed=luna_exists,
            original=luna_original,
            original_mode=luna_mode,
        )
        luna_record["installed_sha256"] = _core._sha256(expected_luna)
        luna_record["installed_mode"] = 0o600
        for name, original, record in (
            (_AGENTS_TARGET, agents_original, agents_record),
            (_LUNA_TARGET, luna_original, luna_record),
        ):
            if original is not None:
                relative = _NATIVE_BACKUPS[name]
                _core._atomic_write(installation_dir / relative, original)
                record["backup"] = relative
        state = {
            "protocol": NATIVE_INSTALL_STATE_PROTOCOL,
            "phase": "prepared",
            "targets": {
                _AGENTS_TARGET: agents_record,
                _LUNA_TARGET: luna_record,
            },
        }
        _write_state(home, state)

        agents_expected = agents_original if agents_exists else _core._MISSING
        installed_agents_mode = agents_mode if agents_mode is not None else 0o600
        _core._replace_expected(
            home / _AGENTS_TARGET,
            expected=agents_expected,
            expected_mode=agents_mode,
            replacement=installed_agents,
            mode=installed_agents_mode,
        )
        luna_expected = luna_original if luna_exists else _core._MISSING
        _core._replace_expected(
            home / _LUNA_TARGET,
            expected=luna_expected,
            expected_mode=luna_mode,
            replacement=expected_luna,
            mode=0o600,
        )
        state["phase"] = "installed"
        _write_state(home, state)
        status = _status_from_state(home, state)
        if status.state != "installed":
            raise _core._error("conflict", "Native installation did not commit completely")
        return status


def native_uninstall(codex_home: Path | str) -> NativeStatus:
    home = _core._validate_codex_home(codex_home)
    with _core._home_lock(home):
        state = _load_state(home)
        if state is None:
            return _status_from_state(home, None)
        current_status = _status_from_state(home, state)
        if state["phase"] == "uninstalled" and current_status.state == "uninstalled":
            return current_status
        if state["phase"] != "installed":
            raise _core._error(
                "conflict", "Native installation is not safely uninstallable"
            )

        agents_record = state["targets"][_AGENTS_TARGET]
        luna_record = state["targets"][_LUNA_TARGET]
        agents_exists, agents_content, agents_mode = _core._read_target_file(
            home, _AGENTS_TARGET
        )
        if not agents_exists or agents_content is None:
            raise _core._error("conflict", "Native AGENTS block is unavailable")
        installed_agents_mode = (
            agents_record.get("original_mode")
            if agents_record.get("original_mode") is not None
            else 0o600
        )
        if agents_mode != installed_agents_mode:
            raise _core._error("conflict", "Native AGENTS mode changed")
        if agents_record.get("installed_block_sha256") != _core._sha256(
            _managed_primary_bytes()
        ):
            raise _core._error("conflict", "Native AGENTS block evidence changed")
        stripped_agents = _strip_primary_block(agents_content)

        luna_exists, luna_content, luna_mode = _core._read_target_file(
            home, _LUNA_TARGET
        )
        if (
            not luna_exists
            or luna_content is None
            or _core._sha256(luna_content) != luna_record.get("installed_sha256")
            or luna_mode != luna_record.get("installed_mode")
        ):
            raise _core._error("conflict", "Native Luna file changed after installation")
        original_luna = _backup_bytes(
            _installation_dir(home), _LUNA_TARGET, luna_record
        )

        if stripped_agents is None and agents_record.get("existed") is False:
            _core._unlink_expected(
                home / _AGENTS_TARGET,
                expected=agents_content,
                expected_mode=agents_mode,
            )
        else:
            replacement_agents = b"" if stripped_agents is None else stripped_agents
            replacement_mode = (
                agents_record.get("original_mode")
                if agents_record.get("original_mode") is not None
                else agents_mode
            )
            _core._replace_expected(
                home / _AGENTS_TARGET,
                expected=agents_content,
                expected_mode=agents_mode,
                replacement=replacement_agents,
                mode=replacement_mode,
            )

        if luna_record.get("existed") is False:
            _core._unlink_expected(
                home / _LUNA_TARGET,
                expected=luna_content,
                expected_mode=luna_mode,
            )
        else:
            assert original_luna is not None
            _core._replace_expected(
                home / _LUNA_TARGET,
                expected=luna_content,
                expected_mode=luna_mode,
                replacement=original_luna,
                mode=luna_record["original_mode"],
            )
        state["phase"] = "uninstalled"
        _write_state(home, state)
        status = _status_from_state(home, state)
        if status.state != "uninstalled":
            raise _core._error("conflict", "Native uninstall did not commit completely")
        return status
