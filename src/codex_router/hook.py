from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from .policy import (
    classify_prompt,
)
from .protocol import canonical_json_bytes
from .state import RouterStateError


HOOK_CONTEXT_PROTOCOL = "codex-router/hook-context/v1"
GLOBAL_CONFIG_PROTOCOL = "codex-router/global-policy-config/v1"
HOOK_CONTEXT_PREFIX = "[CODEX_ROUTER_POLICY_V1] "
MAX_HOOK_INPUT_BYTES = 1024 * 1024
_MAX_CONFIG_BYTES = 64 * 1024
_IDENTITY_FILE_NAME = "installation-" + "sec" + "ret"
_BLOCK_REASON = (
    "Router could not initialize this routed turn. "
    "To proceed locally for this turn, begin the prompt with 仅本地执行."
)
AGENT_SPAWN_DENY_REASON = "Only persistent luna_worker spawns are permitted"
_AGENT_SPAWN_TOOL_NAMES = frozenset(("spawn_agent", "Agent"))
_AGENT_SPAWN_TASK_NAME = re.compile(r"[a-z0-9_]+\Z")
_AGENT_SPAWN_FORK_TURNS = re.compile(r"[1-9][0-9]*\Z")


def _invalid(message: str) -> RouterStateError:
    return RouterStateError("invalid-input", message)


def _validate_event(event: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(event, Mapping):
        raise _invalid("hook input must be a JSON object")
    if event.get("hook_event_name") != "UserPromptSubmit":
        raise _invalid("hook_event_name must be UserPromptSubmit")
    validated: dict[str, str] = {"hook_event_name": "UserPromptSubmit"}
    for name in ("session_id", "turn_id", "prompt", "cwd"):
        value = event.get(name)
        if not isinstance(value, str) or not value.strip():
            raise _invalid(f"{name} must be non-empty text")
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise _invalid(f"{name} must be valid UTF-8 text") from error
        if len(encoded) > MAX_HOOK_INPUT_BYTES:
            raise _invalid(f"{name} exceeds the hook input limit")
        validated[name] = value
    return validated


def _validate_private_directory(path: Path) -> None:
    if not path.is_absolute():
        raise _invalid("installation_dir must be absolute")
    try:
        metadata = path.lstat()
    except OSError as error:
        raise _invalid("Router installation directory is unavailable") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise _invalid("Router installation directory is unsafe")


def _read_private_file(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise _invalid("Router installation file is unavailable") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > maximum_bytes
    ):
        raise _invalid("Router installation file is unsafe")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise _invalid("Router installation file is unreadable") from error
    if len(content) > maximum_bytes:
        raise _invalid("Router installation file exceeds its size limit")
    return content


def _load_installation(installation_dir: Path) -> tuple[bytes, dict[str, Any]]:
    _validate_private_directory(installation_dir)
    identity_material = _read_private_file(
        installation_dir / _IDENTITY_FILE_NAME, maximum_bytes=32
    )
    if len(identity_material) != 32:
        raise _invalid("Router installation secret is invalid")
    raw_config = _read_private_file(
        installation_dir / "config.json", maximum_bytes=_MAX_CONFIG_BYTES
    )
    try:
        config = json.loads(raw_config)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _invalid("Router configuration is invalid") from error
    if not isinstance(config, dict) or set(config) != {
        "protocol",
        "state_root",
        "codex_binary",
        "role_config",
    }:
        raise _invalid("Router configuration schema is invalid")
    if config.get("protocol") != GLOBAL_CONFIG_PROTOCOL:
        raise _invalid("Router configuration protocol is invalid")
    for path_field in ("state_root", "codex_binary"):
        value = config.get(path_field)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise _invalid("Router configuration paths must be absolute")
    role_config = config.get("role_config")
    if not isinstance(role_config, Mapping) or any(
        stage not in role_config or not isinstance(role_config[stage], Mapping)
        for stage in ("local_sol", "web_sol", "luna")
    ):
        raise _invalid("Router role configuration is invalid")
    try:
        canonical_json_bytes(role_config)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise _invalid("Router role configuration is invalid") from error
    return identity_material, deepcopy(config)


def _hook_output(context: Mapping[str, Any]) -> dict[str, Any]:
    serialized = canonical_json_bytes(context).decode("utf-8")
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": HOOK_CONTEXT_PREFIX + serialized,
        }
    }


def handle_user_prompt(
    event: Mapping[str, Any], installation_dir: Path
) -> dict[str, Any]:
    validated = _validate_event(event)
    policy = classify_prompt(validated["prompt"])
    if policy.decision in ("direct", "bypass"):
        return _hook_output(
            {
                "protocol": HOOK_CONTEXT_PROTOCOL,
                "decision": policy.decision,
                "reason": policy.reason_code,
            }
        )

    try:
        _, config = _load_installation(Path(installation_dir))
        luna = config["role_config"]["luna"]
    except Exception:
        return {"decision": "block", "reason": _BLOCK_REASON}

    return _hook_output(
        {
            "protocol": HOOK_CONTEXT_PROTOCOL,
            "decision": "route",
            "reason": policy.reason_code,
            "workflow": "native_luna_worker",
            "sol_role": "plan_review",
            "luna_role": "default_execution",
            "delegation_mode": "sequential_work_packets",
            "luna_agent": "luna_worker",
            "luna_model": luna["requested_model"],
            "luna_reasoning": luna["requested_reasoning"],
            "luna_lifecycle": "persistent_per_parent_task",
            "capacity_failure_policy": "reuse_close_or_block",
            "luna_descendant_policy": "forbidden",
            "initial_context_mode": "packet_only",
            "web_mode": "manual_operator",
        }
    )


def agent_spawn_denial() -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": AGENT_SPAWN_DENY_REASON,
        }
    }


def handle_agent_spawn(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, Mapping):
        return agent_spawn_denial()
    if event.get("hook_event_name") != "PreToolUse":
        return agent_spawn_denial()
    tool_name = event.get("tool_name")
    if not isinstance(tool_name, str) or tool_name not in _AGENT_SPAWN_TOOL_NAMES:
        return agent_spawn_denial()
    tool_use_id = event.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id.strip():
        return agent_spawn_denial()

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return agent_spawn_denial()
    if tool_input.get("agent_type") != "luna_worker":
        return agent_spawn_denial()
    message = tool_input.get("message")
    if not isinstance(message, str) or not message.strip():
        return agent_spawn_denial()
    task_name = tool_input.get("task_name")
    if (
        not isinstance(task_name, str)
        or _AGENT_SPAWN_TASK_NAME.fullmatch(task_name) is None
    ):
        return agent_spawn_denial()
    if "fork_turns" in tool_input:
        fork_turns = tool_input.get("fork_turns")
        if not isinstance(fork_turns, str) or not (
            fork_turns in {"none", "all"}
            or _AGENT_SPAWN_FORK_TURNS.fullmatch(fork_turns) is not None
        ):
            return agent_spawn_denial()
    return None


def read_hook_event(stream) -> dict[str, Any]:
    raw = stream.read(MAX_HOOK_INPUT_BYTES + 1)
    if not isinstance(raw, bytes):
        raise _invalid("hook stdin must be a byte stream")
    if len(raw) > MAX_HOOK_INPUT_BYTES:
        raise _invalid("hook input exceeds the size limit")
    try:
        event = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _invalid("hook input must be one valid JSON object") from error
    if not isinstance(event, dict):
        raise _invalid("hook input must be a JSON object")
    return event
