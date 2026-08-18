from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import luna_control
from .a1 import validate_packet_authorizations
from .policy import classify_prompt
from .protocol import ProtocolError, canonical_json_bytes, parse_luna_packet
from .state import RouterStateError


HOOK_CONTEXT_PROTOCOL = "codex-router/hook-context/v2"
GLOBAL_CONFIG_PROTOCOL = "codex-router/global-policy-config/v1"
HOOK_CONTEXT_PREFIX = "[CODEX_ROUTER_POLICY_V1] "
MAX_HOOK_INPUT_BYTES = 1024 * 1024
_MAX_CONFIG_BYTES = 64 * 1024
_IDENTITY_FILE_NAME = "installation-" + "sec" + "ret"
_BLOCK_REASON = (
    "Router safety state could not be initialized for this turn. "
    "Repair or re-trust the managed Router Hook before continuing routed work."
)
_CHILD_BLOCK_REASON = "Router Luna child turn is not authorized for this packet."

_PARENT_CREATE_TOOLS = {"spawn_agent"}
_PARENT_COMMUNICATE_TOOLS = {
    "send_input",
    "send_message",
    "followup_task",
    "resume_agent",
}
_PARENT_CLEANUP_TOOLS = {"interrupt_agent", "close_agent"}
_PARENT_OBSERVE_TOOLS = {"list_agents", "wait_agent"}
_DESCENDANT_LIFECYCLE_TOOLS = {"request_permissions"}
_KNOWN_AGENT_TOOLS = (
    _PARENT_CREATE_TOOLS
    | _PARENT_COMMUNICATE_TOOLS
    | _PARENT_CLEANUP_TOOLS
    | _PARENT_OBSERVE_TOOLS
    | _DESCENDANT_LIFECYCLE_TOOLS
)
_PARENT_TARGET_FIELDS = {
    "send_input": "target",
    "send_message": "target",
    "followup_task": "target",
    "interrupt_agent": "target",
    "close_agent": "target",
    "resume_agent": "id",
}
_CURRENT_APP_TOOL_ALIASES = {
    "collaborationspawn_agent": "spawn_agent",
    "collaborationfollowup_task": "followup_task",
    "collaborationsend_message": "send_message",
    "collaborationwait_agent": "wait_agent",
    "collaborationinterrupt_agent": "interrupt_agent",
    "collaborationlist_agents": "list_agents",
}
_ROOT_ACTOR_TYPES = {"root", "primary", "primary_sol", "sol", "local_sol"}
_CHILD_ACTOR_TYPES = {"child", "subagent", "luna_worker"}
_DEFAULT_NATIVE_PARENT_IDENTITY = "root-parent"
_DEFAULT_NATIVE_AUTHORITY_PROFILE = "profile-A"


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
    has_agent_id = "agent_id" in event
    has_agent_type = "agent_type" in event
    if has_agent_id != has_agent_type:
        raise _invalid("UserPromptSubmit child identity is incomplete")
    if has_agent_id:
        for name in ("agent_id", "agent_type"):
            value = event.get(name)
            if not isinstance(value, str) or not value.strip():
                raise _invalid(f"{name} must be non-empty text")
            if len(value.encode("utf-8", errors="strict")) > 512:
                raise _invalid(f"{name} exceeds the identity limit")
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


def _child_block() -> dict[str, str]:
    return {"decision": "block", "reason": _CHILD_BLOCK_REASON}


def _snapshot_matches_luna(snapshot: Any, agent_id: str) -> bool:
    if snapshot is None or snapshot.logical_task_status != "ACTIVE":
        return False
    if snapshot.execution_status in {"RETIRED", "QUARANTINED"}:
        return False
    if snapshot.luna_agent_id == agent_id:
        return True
    pending = snapshot.pending_spawn
    return pending is not None and pending.agent_id == agent_id


def _parse_k1_message(message: Any) -> dict[str, Any]:
    if not isinstance(message, str) or not message.startswith(
        "[CODEX_ROUTER_PACKET_V3_1] "
    ):
        raise _invalid("Router parent work message must use a K1 packet")
    try:
        packet = parse_luna_packet(message)
    except ProtocolError as error:
        raise _invalid("Router work message is not a valid K1 packet") from error
    try:
        validate_packet_authorizations(
            packet["explicit_side_effect_authorizations"]
        )
    except ValueError as error:
        raise _invalid("Router work message contains an unknown A1 category") from error
    return packet


def _require_next_k1(
    packet: Mapping[str, Any],
    installation_dir: Path,
    secret: bytes,
    session_id: str,
) -> Any:
    snapshot = luna_control.read_snapshot(installation_dir, secret, session_id)
    if snapshot is None:
        raise _invalid("K1 packet admission requires a current task epoch")
    if packet["generation"] != snapshot.packet_generation + 1:
        raise _invalid("K1 packet generation is not the next task generation")
    return snapshot


def _begin_k1_packet(
    packet: Mapping[str, Any],
    installation_dir: Path,
    secret: bytes,
    session_id: str,
) -> None:
    luna_control.begin_packet(
        installation_dir,
        secret,
        session_id,
        packet_id=packet["packet_id"],
        objective=packet["objective"],
        working_directory=packet["working_directory"],
        intended_write_scope=packet["intended_write_scope"],
        explicit_side_effect_authorizations=packet[
            "explicit_side_effect_authorizations"
        ],
        success_criteria=packet["success_criteria"],
        stop_conditions=packet["stop_conditions"],
    )


def _validate_current_child_packet(snapshot: Any, packet: Mapping[str, Any]) -> None:
    if snapshot.active_packet_id is None:
        raise _invalid("Luna child turn has no active K1 packet")
    if packet["packet_id"] != snapshot.active_packet_id:
        raise _invalid("Luna child packet id does not match current authority")
    if packet["generation"] != snapshot.packet_generation:
        raise _invalid("Luna child packet generation does not match current authority")
    if tuple(packet["intended_write_scope"]) != tuple(snapshot.intended_write_scope):
        raise _invalid("Luna child write scope does not match current authority")
    if tuple(packet["explicit_side_effect_authorizations"]) != tuple(
        snapshot.explicit_side_effect_authorizations
    ):
        raise _invalid("Luna child A1 authority does not match current authority")


def handle_user_prompt(
    event: Mapping[str, Any], installation_dir: Path
) -> dict[str, Any]:
    validated = _validate_event(event)

    # Exact Codex runs UserPromptSubmit for a thread-spawn child before the
    # child's tools. Use that native turn identity to bind the already-admitted
    # K1 packet, while never letting child input replace root-turn authority.
    if "agent_id" in validated:
        if validated["agent_type"] != "luna_worker":
            return {}
        try:
            secret, _config = _load_installation(Path(installation_dir))
            snapshot = luna_control.read_snapshot(
                Path(installation_dir), secret, validated["session_id"]
            )
            if not _snapshot_matches_luna(snapshot, validated["agent_id"]):
                raise _invalid("Luna child identity is not current")
            packet = _parse_k1_message(validated["prompt"])
            _validate_current_child_packet(snapshot, packet)
            luna_control.start_execution(
                Path(installation_dir),
                secret,
                validated["session_id"],
                child_turn_id=validated["turn_id"],
            )
            return {}
        except Exception:
            return _child_block()

    policy = classify_prompt(validated["prompt"])
    try:
        secret, config = _load_installation(Path(installation_dir))
        snapshot = luna_control.read_snapshot(
            Path(installation_dir),
            secret,
            validated["session_id"],
        )
        if snapshot is not None and snapshot.execution_status == "RUNNING":
            snapshot = luna_control.freeze_authority(
                Path(installation_dir),
                secret,
                validated["session_id"],
                reason="user_prompt_supersession",
            )
        if policy.decision in ("direct", "bypass"):
            if snapshot is not None:
                luna_control.set_current_root_turn(
                    Path(installation_dir),
                    secret,
                    validated["session_id"],
                    turn_id=None,
                )
        else:
            if snapshot is None:
                luna_control.new_task(
                    Path(installation_dir),
                    secret,
                    validated["session_id"],
                    native_parent_identity=_DEFAULT_NATIVE_PARENT_IDENTITY,
                    native_authority_profile=_DEFAULT_NATIVE_AUTHORITY_PROFILE,
                )
            luna_control.set_current_root_turn(
                Path(installation_dir),
                secret,
                validated["session_id"],
                turn_id=validated["turn_id"],
            )
    except Exception:
        return {"decision": "block", "reason": _BLOCK_REASON}

    if policy.decision in ("direct", "bypass"):
        return _hook_output(
            {
                "protocol": HOOK_CONTEXT_PROTOCOL,
                "decision": policy.decision,
                "reason": policy.reason_code,
            }
        )

    luna = config["role_config"]["luna"]
    return _hook_output(
        {
            "protocol": HOOK_CONTEXT_PROTOCOL,
            "decision": "route",
            "reason": policy.reason_code,
            "workflow": "persistent_native_luna",
            "sol_role": "plan_review_final_authority",
            "luna_role": "default_execution",
            "delegation_mode": "sequential_work_packets",
            "luna_agent": "luna_worker",
            "luna_model": luna["requested_model"],
            "luna_reasoning": luna["requested_reasoning"],
            "luna_lifecycle": "persistent_task_epoch",
            "parent_terminal_policy": "hard_authority_pause",
            "capacity_failure_policy": "return_to_sol",
            "luna_descendant_policy": "forbidden",
            "luna_codex_runtime_policy": "forbidden",
            "interactive_blocker_policy": "return_to_sol_or_user",
            "initial_context_mode": "packet_only",
            "web_mode": "manual_operator",
            "pause_semantics": "hard_authority_pause",
            "sol_supervision": "event_driven",
            "luna_execution_mode": "full_executor",
        }
    )


def _event_text(event: Mapping[str, Any], name: str) -> str:
    value = event.get(name)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{name} must be non-empty text")
    return value


def _event_base(
    event: Mapping[str, Any], expected: str, required: tuple[str, ...]
) -> dict[str, Any]:
    if not isinstance(event, Mapping) or event.get("hook_event_name") != expected:
        raise _invalid(f"hook_event_name must be {expected}")
    return {name: _event_text(event, name) for name in required}


def _pretool_output(decision: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason[:500],
        }
    }


def _permission_deny(message: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": message[:500]},
        }
    }


def _looks_like_agent_lifecycle_tool(tool_name: str) -> bool:
    return (
        tool_name in _KNOWN_AGENT_TOOLS
        or tool_name.startswith("agent_")
        or tool_name.endswith("_agent")
    )


def _canonical_hook_tool_name(name: str) -> str:
    return _CURRENT_APP_TOOL_ALIASES.get(name, name)


def _actor_identity(event: Mapping[str, Any]) -> tuple[str | None, str | None, bool]:
    has_actor_fields = "actor_id" in event or "actor_type" in event
    has_agent_fields = "agent_id" in event or "agent_type" in event
    if has_actor_fields and has_agent_fields:
        return None, None, True
    if has_actor_fields:
        return event.get("actor_id"), event.get("actor_type"), False
    if has_agent_fields:
        return event.get("agent_id"), event.get("agent_type"), False
    return None, None, False


def _identity_kind(event: Mapping[str, Any], *, lifecycle: bool = False) -> str:
    actor_id, actor_type, ambiguous_sources = _actor_identity(event)
    if ambiguous_sources:
        return "ambiguous"
    has_id = isinstance(actor_id, str) and bool(actor_id)
    has_type = isinstance(actor_type, str) and bool(actor_type)
    if not has_id and not has_type:
        return "missing" if lifecycle else "root"
    if not has_id or not has_type:
        return "ambiguous"
    if actor_type in _ROOT_ACTOR_TYPES:
        return "root"
    if actor_type in _CHILD_ACTOR_TYPES:
        return "child"
    return "ambiguous"


def _child_identity(event: Mapping[str, Any]) -> tuple[str | None, str | None]:
    actor_id, actor_type, ambiguous_sources = _actor_identity(event)
    if ambiguous_sources:
        return None, None
    if actor_type in _CHILD_ACTOR_TYPES:
        return actor_id, actor_type
    return None, None


def _root_lifecycle_identity(
    event: Mapping[str, Any],
    base: Mapping[str, Any],
    installation_dir: Path,
    secret: bytes,
) -> str:
    identity = _identity_kind(event, lifecycle=True)
    if identity != "missing":
        return identity
    if luna_control.is_current_root_turn(
        installation_dir,
        secret,
        base["session_id"],
        turn_id=base["turn_id"],
    ):
        return "root"
    return "missing"


def _mapping_text(tool_input: Mapping[str, Any], name: str) -> str:
    value = tool_input.get(name)
    if not isinstance(value, str) or not value:
        raise _invalid(f"tool_input.{name} must be non-empty text")
    return value


def _admit_k1_packet(
    *,
    tool_input: Mapping[str, Any],
    installation_dir: Path,
    secret: bytes,
    session_id: str,
) -> None:
    packet = _parse_k1_message(tool_input.get("message"))
    _require_next_k1(packet, installation_dir, secret, session_id)
    _begin_k1_packet(packet, installation_dir, secret, session_id)


def _is_bound_luna(
    event: Mapping[str, Any], installation_dir: Path, secret: bytes
) -> bool:
    agent_id, agent_type = _child_identity(event)
    session_id = event.get("session_id")
    if agent_type != "luna_worker" or not isinstance(agent_id, str) or not agent_id:
        return False
    if not isinstance(session_id, str) or not session_id:
        return False
    try:
        snapshot = luna_control.read_snapshot(
            installation_dir,
            secret,
            session_id,
        )
    except RouterStateError:
        return False
    return _snapshot_matches_luna(snapshot, agent_id)


def _handle_luna_pretool(
    *,
    event: Mapping[str, Any],
    base: Mapping[str, Any],
    installation_dir: Path,
    secret: bytes,
) -> dict[str, Any]:
    tool_name = base["tool_name"]
    if _looks_like_agent_lifecycle_tool(tool_name):
        return _pretool_output(
            "deny", "Luna tool surface forbids agent lifecycle continuation"
        )
    luna_control.start_execution(
        installation_dir,
        secret,
        base["session_id"],
        child_turn_id=base["turn_id"],
    )
    return {}


def _handle_parent_pretool(
    *,
    base: Mapping[str, Any],
    tool_input: Mapping[str, Any],
    installation_dir: Path,
    secret: bytes,
) -> dict[str, Any]:
    tool_name = base["tool_name"]
    if tool_name in _PARENT_CREATE_TOOLS:
        if _mapping_text(tool_input, "task_name") != "luna_worker":
            raise _invalid("Router spawn task_name must be luna_worker")
        if _mapping_text(tool_input, "agent_type") != "luna_worker":
            raise _invalid("Router spawn agent_type must be luna_worker")
        if _mapping_text(tool_input, "fork_turns") != "none":
            raise _invalid("Router Luna spawn must use fork_turns=none")
        packet = _parse_k1_message(tool_input.get("message"))
        _require_next_k1(packet, installation_dir, secret, base["session_id"])
        luna_control.reserve_spawn(
            installation_dir,
            secret,
            base["session_id"],
            tool_use_id=base["tool_use_id"],
            task_name="luna_worker",
            fork_turns="none",
        )
        _begin_k1_packet(packet, installation_dir, secret, base["session_id"])
        return {}
    if tool_name in _PARENT_COMMUNICATE_TOOLS | _PARENT_CLEANUP_TOOLS:
        luna_control.authorize_parent_target(
            installation_dir,
            secret,
            base["session_id"],
            tool_name=tool_name,
            target=_mapping_text(tool_input, _PARENT_TARGET_FIELDS[tool_name]),
        )
        if tool_name == "send_message":
            raise _invalid(
                "Router K1 dispatch requires followup_task; send_message is queue-only"
            )
        if tool_name == "interrupt_agent":
            snapshot = luna_control.read_snapshot(
                installation_dir, secret, base["session_id"]
            )
            if snapshot is not None and snapshot.execution_status == "RUNNING":
                luna_control.freeze_authority(
                    installation_dir,
                    secret,
                    base["session_id"],
                    reason="parent_interrupt",
                )
        if tool_name in _PARENT_COMMUNICATE_TOOLS:
            _admit_k1_packet(
                tool_input=tool_input,
                installation_dir=installation_dir,
                secret=secret,
                session_id=base["session_id"],
            )
        return {}
    if tool_name in _PARENT_OBSERVE_TOOLS:
        return {}
    if _looks_like_agent_lifecycle_tool(tool_name):
        return _pretool_output("deny", "unknown agent lifecycle operation fails closed")
    return {}


def _spawn_task_path(tool_response: Any) -> str:
    if isinstance(tool_response, str):
        try:
            tool_response = json.loads(tool_response)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _invalid("spawn tool_response must be a JSON object") from error
    if not isinstance(tool_response, Mapping):
        raise _invalid("spawn tool_response must be an object")
    return _mapping_text(tool_response, "task_name")


def _event_a1_category(event: Mapping[str, Any]) -> str | None:
    value = event.get("a1_category")
    tool_input = event.get("tool_input")
    if value is None and isinstance(tool_input, Mapping):
        value = tool_input.get("a1_category")
    if value is None:
        return None
    try:
        return validate_packet_authorizations((value,))[0]
    except (IndexError, TypeError, ValueError) as error:
        raise _invalid("A1 category is invalid") from error


def handle_hook_event(event: Mapping[str, Any], installation_dir: Path) -> dict[str, Any]:
    name = event.get("hook_event_name") if isinstance(event, Mapping) else None
    if name == "UserPromptSubmit":
        return handle_user_prompt(event, installation_dir)
    try:
        secret, _config = _load_installation(Path(installation_dir))
        if name == "PreToolUse":
            base = _event_base(
                event, name, ("session_id", "turn_id", "tool_name", "tool_use_id")
            )
            base["tool_name"] = _canonical_hook_tool_name(base["tool_name"])
            tool_input = event.get("tool_input")
            if not isinstance(tool_input, Mapping):
                raise _invalid("tool_input must be an object")
            lifecycle = _looks_like_agent_lifecycle_tool(base["tool_name"])
            identity = _identity_kind(event, lifecycle=lifecycle)
            if lifecycle:
                identity = _root_lifecycle_identity(
                    event,
                    base,
                    Path(installation_dir),
                    secret,
                )
                if identity in {"missing", "ambiguous"}:
                    return _pretool_output(
                        "deny", "Router actor identity is missing or ambiguous"
                    )
            if _is_bound_luna(event, Path(installation_dir), secret):
                return _handle_luna_pretool(
                    event=event,
                    base=base,
                    installation_dir=Path(installation_dir),
                    secret=secret,
                )
            _agent_id, agent_type = _child_identity(event)
            if agent_type == "luna_worker":
                return _pretool_output("deny", "unbound Luna identity fails closed")
            if identity == "child":
                if lifecycle:
                    return _pretool_output(
                        "deny", "Router agent lifecycle control is reserved for primary Sol"
                    )
                return {}
            if identity != "root":
                if lifecycle:
                    return _pretool_output(
                        "deny", "Router actor identity is missing or ambiguous"
                    )
                return {}
            return _handle_parent_pretool(
                base=base,
                tool_input=tool_input,
                installation_dir=Path(installation_dir),
                secret=secret,
            )

        if name == "PostToolUse":
            base = _event_base(
                event, name, ("session_id", "turn_id", "tool_name", "tool_use_id")
            )
            base["tool_name"] = _canonical_hook_tool_name(base["tool_name"])
            if base["tool_name"] != "spawn_agent":
                return {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}
            if (
                _root_lifecycle_identity(
                    event, base, Path(installation_dir), secret
                )
                != "root"
            ):
                raise _invalid("Router actor identity is missing or ambiguous")
            luna_control.observe_spawn_result(
                Path(installation_dir),
                secret,
                base["session_id"],
                tool_use_id=base["tool_use_id"],
                task_path=_spawn_task_path(event.get("tool_response")),
            )
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}

        if name == "PermissionRequest":
            _event_base(event, name, ("session_id", "turn_id", "tool_name"))
            _event_a1_category(event)
            if _is_bound_luna(event, Path(installation_dir), secret):
                return _permission_deny("BLOCKED_USER_INTERACTION_REQUIRED")
            _agent_id, agent_type = _child_identity(event)
            if agent_type == "luna_worker":
                return _permission_deny("BLOCKED_USER_INTERACTION_REQUIRED")
            return {}

        if name == "SubagentStart":
            base = _event_base(
                event, name, ("session_id", "turn_id", "agent_id", "agent_type")
            )
            if base["agent_type"] == "luna_worker":
                luna_control.observe_subagent_start(
                    Path(installation_dir),
                    secret,
                    base["session_id"],
                    agent_id=base["agent_id"],
                    agent_type=base["agent_type"],
                )
            return {"hookSpecificOutput": {"hookEventName": "SubagentStart"}}

        if name == "Stop":
            _event_base(event, name, ("session_id", "turn_id"))
            return {}

        if name == "SubagentStop":
            base = _event_base(
                event, name, ("session_id", "turn_id", "agent_id", "agent_type")
            )
            if base["agent_type"] == "luna_worker":
                snapshot = luna_control.read_snapshot(
                    Path(installation_dir), secret, base["session_id"]
                )
                if _snapshot_matches_luna(snapshot, base["agent_id"]):
                    luna_control.observe_turn_boundary(
                        Path(installation_dir),
                        secret,
                        base["session_id"],
                        child_turn_id=base["turn_id"],
                    )
            return {"hookSpecificOutput": {"hookEventName": "SubagentStop"}}

        raise _invalid("unsupported hook event")
    except RouterStateError as error:
        if name == "PreToolUse":
            return _pretool_output("deny", str(error))
        if name == "PermissionRequest":
            return _permission_deny(str(error))
        if name in ("Stop", "SubagentStop"):
            return {}
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
