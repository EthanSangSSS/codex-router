"""Version-sensitive Codex compatibility layer around the stable installer core."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import shlex
import tomllib
from typing import Any, Iterable, Iterator, Mapping

from . import a1 as _a1
from . import global_install as _core
from .types import GlobalStatus


LUNA_EXECUTION_MODE = "full_executor_v3_1"
BASELINE_HOOK_EVENTS = (
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
)
COMPATIBLE = "COMPATIBLE"
INCOMPATIBLE = "INCOMPATIBLE"
UNKNOWN = "UNKNOWN_REQUIRES_CAPABILITY_CHECK"
AGENTS_BLOCK_V3 = f"""{_core.AGENTS_BEGIN}
This Codex task is the primary Sol coordinator and final reviewer. Luna is a persistent Luna per task epoch and the single Full Executor for that epoch.
Honor `[CODEX_ROUTER_POLICY_V1]` Hook context exactly:
- `direct` and `bypass` keep their native local meaning. A substantive `route` creates one Luna bound to the persistent task epoch, and later packets reuse that same native Luna identity.
- Full Executor ordinary inspect/research/edit/test/debug/retry/verify work is allowed, including ordinary shell, Unified Exec, Code Mode, code, apps, plugins, and web capabilities when the runtime exposes them.
- Luna has no descendants and no nested Codex delegation. If a packet would require recursive delegation or another Codex runtime, return the appropriate blocked result to Sol.
- packet generation replaces prior authority. Only the latest packet's working directory, allowed paths, forbidden operations, validation, stop conditions, and output requirements apply.
- Hard Authority Pause freezes Router authority immediately. It is an authority state, not a process-death claim or a settlement shortcut.
- There is no N/N+1 overlap before settlement. A new generation is not admitted while the prior generation is unsettled; only proven native terminal evidence can settle it.
- A1 hard claims only on proven pre-action surfaces. Hook receipts, packet metadata, and ordinary acknowledgements do not prove terminal settlement or completed external work.
- Sol remains the planner and reviewer, while the persistent Luna performs the bounded packet. Web Sol is manual operator work outside automatic Router execution.
- Every packet must be independently bounded and must not broaden scope or access secrets, authentication, or unrelated private data.
{_core.AGENTS_END}
"""

LUNA_DEVELOPER_INSTRUCTIONS_V3 = """You are the persistent Luna Full Executor for one Router task epoch. Sol is the planner, coordinator, reviewer, and final authority.

Operating rules:
- Full Executor ordinary inspect/research/edit/test/debug/retry/verify work is allowed. Use ordinary shell, Unified Exec, Code Mode, code, apps, plugins, and web capabilities when the runtime exposes them.
- You have no descendants and must perform no nested Codex delegation. Never create, spawn, fork, relay to, resume, or coordinate another agent or Codex runtime. Return `BLOCKED_LUNA_RECURSIVE_DELEGATION` or `BLOCKED_LUNA_CODEX_RUNTIME` when required.
- You remain the same native Luna identity for the persistent task epoch. Packet generation replaces prior authority: accept only the latest packet and never inherit paths or permissions from an older packet.
- Hard Authority Pause freezes Router authority immediately. Treat the pause as authoritative and do not continue or claim settlement from an interrupt acknowledgement, a timeout, a sleep, polling, a PID observation, or guessed process death.
- Enforce no N/N+1 overlap before settlement. A new generation cannot be admitted while the prior generation is unsettled; only verified native terminal evidence can establish settlement.
- A1 hard claims only on proven pre-action surfaces. Do not claim that an action, process, generation, or external effect completed without direct evidence from the required native surface.
- Work only inside the latest packet's working directory and allowed paths. Preserve unrelated behavior and return concise evidence, blockers, and remaining risks.
- Never browse or operate Web Sol. Never access credentials, cookies, tokens, private keys, payment data, or unrelated private data.
- Never commit, push, create or modify a pull request, install, deploy, publish, or start a persistent service unless the latest explicit packet authorizes that exact action.
"""

# Compatibility names are retained for callers that imported the previous adapter
# seam; their rendered content is the V3.1 contract above.
AGENTS_BLOCK = AGENTS_BLOCK_V3
AGENTS_BLOCK_V2 = AGENTS_BLOCK_V3
LUNA_DEVELOPER_INSTRUCTIONS = LUNA_DEVELOPER_INSTRUCTIONS_V3
LUNA_DEVELOPER_INSTRUCTIONS_V2 = LUNA_DEVELOPER_INSTRUCTIONS_V3


def luna_agent_bytes(role: Mapping[str, Any]) -> bytes:
    """Render the V3.1 Full Executor profile with only descendant controls off."""
    model = role.get("requested_model")
    reasoning = role.get("requested_reasoning")
    if not isinstance(model, str) or not model.strip():
        raise _core._error("invalid-input", "Luna model configuration is invalid")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise _core._error("invalid-input", "Luna reasoning configuration is invalid")
    values = {
        "name": "luna_worker",
        "description": _core._LUNA_DESCRIPTION,
        "model": model,
        "model_reasoning_effort": reasoning,
        "developer_instructions": LUNA_DEVELOPER_INSTRUCTIONS_V3,
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
        raise _core._error("conflict", "generated Luna agent configuration is invalid") from error
    expected = {
        **values,
        "agents": {"enabled": False},
        "features": {
            "multi_agent": False,
            "multi_agent_v2": False,
        },
    }
    if parsed != expected:
        raise _core._error("conflict", "generated Luna agent configuration is unstable")
    return encoded


def luna_agent_matches(content: bytes | None, role: Mapping[str, Any]) -> bool:
    if content is None:
        return False
    try:
        parsed = tomllib.loads(content.decode("utf-8", errors="strict"))
        expected = tomllib.loads(luna_agent_bytes(role).decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    return parsed == expected


def _capability_matrix_from_record(
    value: Any,
) -> tuple[_a1.A1SurfaceCapability, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        record_type = value.get("record_type")
        runtime = value.get("runtime")
        exact_runtime = (
            value.get("exact_runtime") is True
            or record_type in {"exact_runtime", "EXACT_RUNTIME"}
            or runtime in {"exact", "exact_runtime", "EXACT_RUNTIME"}
        )
        if not exact_runtime:
            return ()
        value = next(
            (
                value.get(name)
                for name in ("capabilities", "a1_matrix", "surfaces", "matrix")
                if name in value
            ),
            (),
        )
    if isinstance(value, (str, bytes)):
        raise _core._error("conflict", "A1 capability matrix is invalid")
    try:
        matrix = tuple(value)
    except TypeError as error:
        raise _core._error("conflict", "A1 capability matrix is invalid") from error
    if not all(isinstance(item, _a1.A1SurfaceCapability) for item in matrix):
        raise _core._error("conflict", "A1 capability matrix is invalid")
    return matrix


def permission_request_registration_enabled(
    capability_matrix: Iterable[_a1.A1SurfaceCapability] | Mapping[str, Any] | None,
) -> bool:
    """Return whether an exact runtime record proves a narrow A1 gate."""
    matrix = _capability_matrix_from_record(capability_matrix)
    return _a1.permission_request_gate_ready(matrix)


def install_hook_v3(
    original: bytes | None,
    handler: Mapping[str, Any] | None = None,
    capability_matrix: Iterable[_a1.A1SurfaceCapability]
    | Mapping[str, Any]
    | None = None,
    *,
    a1_matrix: Iterable[_a1.A1SurfaceCapability]
    | Mapping[str, Any]
    | None = None,
    runtime_capabilities: Iterable[_a1.A1SurfaceCapability]
    | Mapping[str, Any]
    | None = None,
    runtime_record: Iterable[_a1.A1SurfaceCapability]
    | Mapping[str, Any]
    | None = None,
) -> bytes:
    """Render the exact V3.1 baseline Hook surfaces."""
    candidates = tuple(
        value
        for value in (
            capability_matrix,
            a1_matrix,
            runtime_capabilities,
            runtime_record,
        )
        if value is not None
    )
    if len(candidates) > 1:
        raise _core._error("invalid-input", "A1 capability matrix was specified more than once")
    matrix = _capability_matrix_from_record(candidates[0] if candidates else None)
    if original is None:
        document: dict[str, Any] = {}
    else:
        try:
            document = json.loads(original)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _core._error("conflict", "hooks.json is not valid JSON") from error
        if not isinstance(document, dict):
            raise _core._error("conflict", "hooks.json must contain a JSON object")
    if any(
        _core.HOOK_MARKER in value
        or ("codex_router" in value and "hook-user-prompt" in value)
        for value in _core._walk_strings(document)
    ):
        raise _core._error("conflict", "a conflicting Router hook marker already exists")
    hooks = document.get("hooks")
    if hooks is None:
        hooks = {}
        document["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise _core._error("conflict", "hooks.json hooks field is invalid")

    subcommands = {
        "UserPromptSubmit": "hook-user-prompt",
        "PreToolUse": "hook-pre-tool",
        "PostToolUse": "hook-post-tool",
        "SubagentStart": "hook-subagent-start",
    }
    if _a1.permission_request_gate_ready(matrix):
        subcommands["PermissionRequest"] = "hook-permission-request"
    if handler is None:
        raise _core._error("invalid-input", "Router hook handler is required")
    try:
        base_arguments = shlex.split(str(handler["command"]), posix=True)
    except (KeyError, TypeError, ValueError) as error:
        raise _core._error("conflict", "Router hook handler is invalid") from error
    if len(base_arguments) != 8 or base_arguments[3:6] != [
        "-m",
        "codex_router",
        "hook-user-prompt",
    ]:
        raise _core._error("conflict", "Router hook handler is invalid")

    for event, subcommand in subcommands.items():
        groups = hooks.get(event)
        if groups is None:
            groups = []
            hooks[event] = groups
        if not isinstance(groups, list):
            raise _core._error("conflict", f"{event} hook groups are invalid")
        for group in groups:
            if (
                not isinstance(group, Mapping)
                or not isinstance(group.get("hooks"), list)
                or any(not isinstance(item, Mapping) for item in group["hooks"])
            ):
                raise _core._error("conflict", f"{event} hook group is invalid")
        current = dict(handler)
        arguments = list(base_arguments)
        arguments[5] = subcommand
        current["command"] = shlex.join(arguments)
        groups.append({"hooks": [current]})
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


# Keep the old callable name as a compatibility seam; it now renders V3.1.
install_hook_v2 = install_hook_v3


def _primary_capability(codex_home: Path) -> tuple[str, str]:
    """Classify only statically observable primary capabilities; never mutate config."""
    config_path = codex_home / "config.toml"
    if not config_path.exists():
        return (
            UNKNOWN,
            "primary config.toml is absent; effective layered capability requires runtime validation",
        )
    try:
        value = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return (UNKNOWN, "primary config.toml could not be safely interpreted for compatibility")
    if not isinstance(value, dict):
        return (UNKNOWN, "primary configuration shape is unverified")
    agents = value.get("agents")
    features = value.get("features")
    agents = agents if isinstance(agents, Mapping) else {}
    features = features if isinstance(features, Mapping) else {}
    if agents.get("enabled") is False:
        return (INCOMPATIBLE, "primary agents.enabled=false disables Router Luna management")
    if features.get("multi_agent") is False:
        return (INCOMPATIBLE, "primary features.multi_agent=false disables Router Luna management")
    if features.get("hooks") is False:
        return (INCOMPATIBLE, "primary features.hooks=false disables Router Hooks")
    if (
        agents.get("enabled") is True
        and features.get("multi_agent") is True
        and features.get("hooks") is True
    ):
        return (COMPATIBLE, "required primary agents, multi-agent, and Hook capabilities are explicitly enabled")
    return (
        UNKNOWN,
        "required primary capabilities are not all explicit; effective layered config needs validation",
    )


def _enrich(status: GlobalStatus, codex_home: Path | str) -> GlobalStatus:
    compatibility, reason = _primary_capability(Path(codex_home).expanduser())
    return replace(
        status,
        compatibility=compatibility,
        compatibility_reason=reason,
        luna_execution_mode=LUNA_EXECUTION_MODE,
    )


def _v3_hook_configured(
    home: Path, state: Mapping[str, Any]
) -> bool:
    """Verify exactly the four managed V3.1 Hooks against the transaction record."""
    targets = state.get("targets")
    if not isinstance(targets, Mapping):
        return False
    record = targets.get("hooks.json")
    if not isinstance(record, Mapping):
        return False
    try:
        exists, content, mode = _core._read_target_file(home, "hooks.json")
    except Exception:
        return False
    if (
        not exists
        or content is None
        or _core._sha256(content) != record.get("installed_sha256")
        or mode != record.get("installed_mode")
    ):
        return False
    try:
        parsed = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    hooks = parsed.get("hooks") if isinstance(parsed, Mapping) else None
    if not isinstance(hooks, Mapping):
        return False
    managed_events: list[str] = []
    for event, groups in hooks.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, Mapping) or not isinstance(group.get("hooks"), list):
                continue
            for item in group["hooks"]:
                if (
                    isinstance(item, Mapping)
                    and item.get("statusMessage")
                    == f"Routing with Codex Router [{_core.HOOK_MARKER}]"
                ):
                    managed_events.append(event)
    return (
        len(managed_events) == len(BASELINE_HOOK_EVENTS)
        and len(set(managed_events)) == len(BASELINE_HOOK_EVENTS)
        and set(managed_events) == set(BASELINE_HOOK_EVENTS)
    )


def _status_from_state_v3(
    legacy_status_from_state,
    home: Path,
    installation_dir: Path,
    state: Mapping[str, Any],
) -> GlobalStatus:
    status = legacy_status_from_state(home, installation_dir, state)
    if state.get("phase") != "installed":
        return status
    hook_configured = _v3_hook_configured(home, state)
    if not hook_configured:
        return replace(
            status,
            state="modified",
            hook_configured=False,
            hook_trust="unknown",
            new_session_required=False,
        )
    installed = (
        status.agents_managed
        and status.luna_agent_configured
        and status.config_valid
        and status.identity_material_valid
    )
    return replace(
        status,
        state="installed" if installed else status.state,
        hook_configured=True,
        hook_trust="requires-user-check" if installed else status.hook_trust,
        new_session_required=True if installed else status.new_session_required,
    )


# Compatibility alias for code that imported the adapter's status seam.
_status_from_state_v2 = _status_from_state_v3


@contextmanager
def _rendering_adapter() -> Iterator[None]:
    """Temporarily inject V3.1 rendering/status without rewriting transactions."""
    old_bytes = _core._luna_agent_bytes
    old_matches = _core._luna_agent_matches
    old_install_hook = _core._install_hook
    old_agents_block = _core.AGENTS_BLOCK
    old_luna_instructions = _core._LUNA_DEVELOPER_INSTRUCTIONS
    old_status_from_state = _core._status_from_state

    def status_from_state(home, installation_dir, state):
        return _status_from_state_v3(
            old_status_from_state,
            home,
            installation_dir,
            state,
        )

    _core._luna_agent_bytes = luna_agent_bytes
    _core._luna_agent_matches = luna_agent_matches
    _core._install_hook = install_hook_v3
    _core.AGENTS_BLOCK = AGENTS_BLOCK_V3
    _core._LUNA_DEVELOPER_INSTRUCTIONS = LUNA_DEVELOPER_INSTRUCTIONS_V3
    _core._status_from_state = status_from_state
    try:
        yield
    finally:
        _core._luna_agent_bytes = old_bytes
        _core._luna_agent_matches = old_matches
        _core._install_hook = old_install_hook
        _core.AGENTS_BLOCK = old_agents_block
        _core._LUNA_DEVELOPER_INSTRUCTIONS = old_luna_instructions
        _core._status_from_state = old_status_from_state


def global_install(*args, **kwargs):
    codex_home = kwargs.get("codex_home", args[0] if args else None)
    with _rendering_adapter():
        status = _core.global_install(*args, **kwargs)
    return _enrich(status, codex_home)


def global_status(*args, **kwargs):
    codex_home = kwargs.get("codex_home", args[0] if args else None)
    with _rendering_adapter():
        status = _core.global_status(*args, **kwargs)
    return _enrich(status, codex_home)


def global_uninstall(*args, **kwargs):
    codex_home = kwargs.get("codex_home", args[0] if args else None)
    with _rendering_adapter():
        status = _core.global_uninstall(*args, **kwargs)
    return _enrich(status, codex_home)


def global_self_test(*args, **kwargs):
    with _rendering_adapter():
        return _core.global_self_test(*args, **kwargs)


_luna_agent_bytes = luna_agent_bytes
_luna_agent_matches = luna_agent_matches
