from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from .policy import (
    classify_prompt,
)
from .protocol import canonical_json_bytes
from .state import RouterStateError
from . import native_lifecycle


HOOK_CONTEXT_PROTOCOL = "codex-router/hook-context/v2"
GLOBAL_CONFIG_PROTOCOL = "codex-router/global-policy-config/v1"
HOOK_CONTEXT_PREFIX = "[CODEX_ROUTER_POLICY_V1] "
MAX_HOOK_INPUT_BYTES = 1024 * 1024
_MAX_CONFIG_BYTES = 64 * 1024
_IDENTITY_FILE_NAME = "installation-" + "sec" + "ret"
_BLOCK_REASON = (
    "Router could not initialize this routed turn. "
    "To proceed locally for this turn, begin the prompt with 仅本地执行."
)


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
        secret, config = _load_installation(Path(installation_dir))
        native_lifecycle.revoke_stale(Path(installation_dir), secret, validated["session_id"], validated["turn_id"])
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
            "capacity_failure_policy": "reuse_or_block",
            "luna_descendant_policy": "forbidden",
            "initial_context_mode": "packet_only",
            "web_mode": "manual_operator",
        }
    )


_LUNA_TOOL_ALLOW = {"exec_command"}
_PARENT_TOOL_ALLOW = {"spawn_agent", "followup_task", "send_message", "interrupt_agent", "list_agents", "wait_agent"}


def _event_text(event: Mapping[str, Any], name: str) -> str:
    value = event.get(name)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{name} must be non-empty text")
    return value


def _event_base(event: Mapping[str, Any], expected: str, required: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(event, Mapping) or event.get("hook_event_name") != expected:
        raise _invalid(f"hook_event_name must be {expected}")
    return {name: _event_text(event, name) for name in required}


def _block(reason: str) -> dict[str, Any]:
    return {"decision": "block", "reason": reason[:500]}


def _pretool_output(decision: str, reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": reason[:500]}}


def _read_child_metadata(event: Mapping[str, Any]) -> Mapping[str, Any]:
    path = event.get("transcript_path")
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise _invalid("transcript_path must be absolute")
    target = Path(path)
    meta = target.lstat()
    if not stat.S_ISREG(meta.st_mode) or stat.S_ISLNK(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_size > MAX_HOOK_INPUT_BYTES:
        raise _invalid("child transcript is unsafe")
    # Only the first JSONL session metadata record is used; no follow-on content is read.
    first = target.open("rb").readline(MAX_HOOK_INPUT_BYTES)
    try:
        value = json.loads(first)
        source = value.get("payload", {}).get("source", {}).get("subagent", {}).get("thread_spawn", {})
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        raise _invalid("child session metadata is invalid") from exc
    if not isinstance(source, Mapping): raise _invalid("child session metadata is invalid")
    return source


def handle_hook_event(event: Mapping[str, Any], installation_dir: Path) -> dict[str, Any]:
    name = event.get("hook_event_name") if isinstance(event, Mapping) else None
    if name == "UserPromptSubmit": return handle_user_prompt(event, installation_dir)
    try:
        secret, _ = _load_installation(Path(installation_dir))
        if name == "PreToolUse":
            base = _event_base(event, name, ("session_id", "turn_id", "tool_name", "tool_use_id"))
            agent_id, agent_type = event.get("agent_id"), event.get("agent_type")
            tool_input = event.get("tool_input")
            if not isinstance(tool_input, Mapping): raise _invalid("tool_input must be an object")
            if agent_type == "luna_worker":
                native_lifecycle.authorize_luna(Path(installation_dir), secret, _event_text(event, "agent_id"))
                if base["tool_name"] not in _LUNA_TOOL_ALLOW: return _pretool_output("deny", "Luna tool surface is restricted")
                command = tool_input.get("cmd")
                if not isinstance(command, str) or "codex" in command.lower() or "agy" in command.lower(): return _pretool_output("deny", "Luna may not invoke Codex, Router, or external executors")
                return _pretool_output("allow", "Luna one-shot shell command allowed")
            if base["tool_name"] not in _PARENT_TOOL_ALLOW: return _pretool_output("allow", "not a Router lifecycle operation")
            if base["tool_name"] == "spawn_agent":
                native_lifecycle.pre_spawn(Path(installation_dir), secret, base["session_id"], base["turn_id"], base["tool_use_id"], tool_input)
            elif base["tool_name"] == "interrupt_agent":
                native_lifecycle.begin_interrupt(Path(installation_dir), secret, base["session_id"], base["turn_id"], tool_input)
            elif base["tool_name"] in {"followup_task", "send_message"}:
                native_lifecycle.authorize_parent_operation(Path(installation_dir), secret, base["session_id"], base["turn_id"], tool_input)
            return _pretool_output("allow", "native Luna lifecycle operation allowed")
        if name == "PostToolUse":
            base = _event_base(event, name, ("session_id", "turn_id", "tool_name", "tool_use_id"))
            response = event.get("tool_response")
            if base["tool_name"] == "spawn_agent": native_lifecycle.post_spawn(Path(installation_dir), secret, base["session_id"], base["turn_id"], base["tool_use_id"], response)
            elif base["tool_name"] == "interrupt_agent": native_lifecycle.finish_interrupt(Path(installation_dir), secret, base["session_id"], base["turn_id"], response)
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}
        if name == "PermissionRequest":
            _event_base(event, name, ("session_id", "turn_id", "tool_name"))
            if event.get("agent_type") == "luna_worker": return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "deny", "message": "Luna permission requests are denied"}}}
            return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
        if name == "SubagentStart":
            _event_base(event, name, ("session_id", "turn_id", "agent_id", "agent_type", "transcript_path"))
            if event.get("agent_type") == "luna_worker": native_lifecycle.bind_child(Path(installation_dir), secret, event, _read_child_metadata(event))
            return {"hookSpecificOutput": {"hookEventName": "SubagentStart"}}
        if name in ("Stop", "SubagentStop"):
            base = _event_base(event, name, ("session_id", "turn_id"))
            if name == "Stop" and native_lifecycle.stop_once(Path(installation_dir), secret, base["session_id"], base["turn_id"]): return _block("An active Luna worker requires one native interrupt_agent cleanup attempt before stopping")
            return {}
        raise _invalid("unsupported hook event")
    except RouterStateError as error:
        if name == "PreToolUse": return _pretool_output("deny", str(error))
        if name == "PermissionRequest": return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "deny", "message": str(error)[:500]}}}
        if name in ("Stop", "SubagentStop"): return _block(str(error))
        return {"continue": False, "stopReason": str(error)[:500]}


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
