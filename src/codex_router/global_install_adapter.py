"""Version-sensitive Codex compatibility layer around the stable installer core."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shlex
import tomllib
from typing import Any, Iterator, Mapping

from . import global_install as _core
from .hook import HOOK_CONTEXT_PREFIX
from .types import GlobalStatus


LUNA_EXECUTION_MODE = "hard_mode_no_process"
COMPATIBLE = "COMPATIBLE"
INCOMPATIBLE = "INCOMPATIBLE"
UNKNOWN = "UNKNOWN_REQUIRES_CAPABILITY_CHECK"
_V2_HOOK_COUNT = 6

AGENTS_BLOCK_V2 = f"""{_core.AGENTS_BEGIN}
This Codex task is the primary Sol coordinator, highest ordinary execution authority, and final reviewer. Luna is the default bounded execution worker for routed work.
Honor `[CODEX_ROUTER_POLICY_V1]` Hook context exactly:
- `direct` and `bypass` apply only to the current turn. Stale prior-root authority is revoked first; Sol then executes directly without creating or using Luna. The next normal substantive turn returns to Router routing automatically.
- For `route`, show `Router: active`. Sol plans and decomposes, creates exactly one current-root-turn `luna_worker` with `fork_turns=none`, reuses that bound Luna for sequential/correction packets while ACTIVE, reviews results, and gives the final response.
- Primary Sol retains its native multi-agent authority to create, communicate with, observe, and optionally cancel the current bound Luna. Luna restrictions are child-specific and must never be applied globally to Sol.
- The current root scope is authorized only while ACTIVE. A new root turn or Stop revokes it irreversibly. Stop only revokes Router authority and returns normally; it never creates a Router cleanup continuation or autonomous wait/retry loop.
- Luna is bound by native `agent_id` to the unique current pending Luna. Transcript metadata and child/root turn equality are not authorization sources.
- Luna hard mode disables arbitrary shell/process execution, Unified Exec, Code Mode, and descendant agents. Sol runs build/test/verification commands when process execution is required. Do not grow a shell parser into a security boundary.
- Luna PermissionRequest is denied. Primary Sol/user approval remains governed by native Codex because Router returns no allow decision for unrelated/root requests.
- Ordinary capacity, dependency, or capability blockers return control to Sol. Sol may narrow the packet, reuse the current authorized Luna, execute unsupported process-dependent work directly, ask the user, or stop.
- Every Luna packet must restate bounded work, allowed paths, forbidden operations, validation expectations, stop conditions, and required output. Luna must not browse, operate Web Sol, access secrets, commit/push/PR/install/deploy, or broaden scope unless the latest packet explicitly authorizes an otherwise permitted action.
- Web Sol is manual operator work outside automatic Router execution. Native Hook routing remains stateless with respect to legacy canonical Router runs.
- `Router: active` is a policy receipt shown only when route context exists; it is not independent telemetry. Use Router status/preflight for installation and capability diagnostics.
{_core.AGENTS_END}
"""

LUNA_DEVELOPER_INSTRUCTIONS_V2 = """You are the default bounded execution worker for one authorized Router root turn. Sol is the planner, coordinator, reviewer, and final authority.

Operating rules:
- Accept only the latest bounded packet from Sol while your native agent identity remains bound to the current ACTIVE root scope. Packet completion or idle state does not itself end that root scope.
- Never act after revocation and never attempt to resume, recreate, or impersonate a historical Luna.
- You are in Router hard mode: do not run shell commands, arbitrary processes, Unified Exec, Code Mode, PTY sessions, or other process executors. Return process-dependent validation to Sol.
- Never create, spawn, resume, relay to, or coordinate descendant agents. If recursive delegation is required, return `BLOCKED_LUNA_RECURSIVE_DELEGATION` to Sol.
- Never launch, resume, probe, or wrap another Codex runtime. If nested Codex would be required, return `BLOCKED_LUNA_CODEX_RUNTIME` to Sol.
- Never request, synthesize, auto-approve, or bypass user-required trust, approval, authentication, permission escalation, or security confirmation. Return `BLOCKED_USER_INTERACTION_REQUIRED` to Sol.
- Work only inside the latest packet's working directory and allowed paths. New packets do not inherit old write authorization.
- Perform bounded inspection/editing/non-process work, preserve unrelated behavior, and return evidence. Sol runs build/test/verification commands that require process execution and decides whether to take over ordinary work.
- Never browse or operate Web Sol. Never access credentials, cookies, tokens, private keys, payment data, or unrelated private data.
- Never commit, push, create/modify a pull request, install, deploy, publish, or start persistent services unless the latest explicit packet authorizes that exact action and normal platform controls permit it.
- Report concise work completed, files/artifacts affected, non-process validation performed, and remaining risks or process-dependent validation Sol must perform.
"""


def luna_agent_bytes(role: Mapping[str, Any]) -> bytes:
    """Render the documented hard-mode Luna profile for repository V2."""
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
        "developer_instructions": LUNA_DEVELOPER_INSTRUCTIONS_V2,
    }
    rendered = "".join(
        f"{key} = {json.dumps(value, ensure_ascii=False)}\n"
        for key, value in values.items()
    )
    rendered += (
        "web_search = \"disabled\"\n"
        "\n[agents]\n"
        "enabled = false\n"
        "\n[features]\n"
        "multi_agent = false\n"
        "multi_agent_v2 = false\n"
        "shell_tool = false\n"
        "unified_exec = false\n"
        "code_mode_only = false\n"
        "request_permissions_tool = false\n"
        "apps = false\n"
        "enable_mcp_apps = false\n"
        "plugins = false\n"
        "tool_suggest = false\n"
        "\n[features.code_mode]\n"
        "enabled = false\n"
    )
    encoded = rendered.encode("utf-8")
    try:
        parsed = tomllib.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise _core._error("conflict", "generated Luna agent configuration is invalid") from error
    expected = {
        **values,
        "web_search": "disabled",
        "agents": {"enabled": False},
        "features": {
            "multi_agent": False,
            "multi_agent_v2": False,
            "shell_tool": False,
            "unified_exec": False,
            "code_mode_only": False,
            "request_permissions_tool": False,
            "apps": False,
            "enable_mcp_apps": False,
            "plugins": False,
            "tool_suggest": False,
            "code_mode": {"enabled": False},
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


def install_hook_v2(original: bytes | None, handler: Mapping[str, Any] | None = None) -> bytes:
    """Render only the V2 Hook surfaces that still enforce a concrete invariant."""
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
        "PermissionRequest": "hook-permission-request",
        "Stop": "hook-stop",
        "SubagentStart": "hook-subagent-start",
    }
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


def _v2_hook_configured(
    home: Path, state: Mapping[str, Any]
) -> bool:
    """Verify the six managed V2 Hooks against the transaction record."""
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
    return sum(_core.HOOK_MARKER in value for value in _core._walk_strings(parsed)) == _V2_HOOK_COUNT


def _status_from_state_v2(
    legacy_status_from_state,
    home: Path,
    installation_dir: Path,
    state: Mapping[str, Any],
) -> GlobalStatus:
    status = legacy_status_from_state(home, installation_dir, state)
    if state.get("phase") != "installed" or status.hook_configured:
        return status
    hook_configured = _v2_hook_configured(home, state)
    if not hook_configured:
        return status
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


def _legacy_self_test_receipt(output: dict[str, Any]) -> dict[str, Any]:
    """Translate only the semantic label expected by the unchanged installer-core self-test."""
    translated = deepcopy(output)
    try:
        raw = translated["hookSpecificOutput"]["additionalContext"]
    except (KeyError, TypeError):
        return translated
    if not isinstance(raw, str) or not raw.startswith(HOOK_CONTEXT_PREFIX):
        return translated
    try:
        context = json.loads(raw[len(HOOK_CONTEXT_PREFIX) :])
    except json.JSONDecodeError:
        return translated
    if context.get("parent_terminal_policy") == "revoke_only_security_boundary":
        context["parent_terminal_policy"] = "revoke_then_cleanup"
        translated["hookSpecificOutput"]["additionalContext"] = (
            HOOK_CONTEXT_PREFIX
            + json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    return translated


@contextmanager
def _rendering_adapter() -> Iterator[None]:
    """Temporarily inject V2 rendering/status without rewriting transaction mechanics."""
    old_bytes = _core._luna_agent_bytes
    old_matches = _core._luna_agent_matches
    old_install_hook = _core._install_hook
    old_agents_block = _core.AGENTS_BLOCK
    old_luna_instructions = _core._LUNA_DEVELOPER_INSTRUCTIONS
    old_status_from_state = _core._status_from_state

    def status_from_state(home, installation_dir, state):
        return _status_from_state_v2(
            old_status_from_state,
            home,
            installation_dir,
            state,
        )

    _core._luna_agent_bytes = luna_agent_bytes
    _core._luna_agent_matches = luna_agent_matches
    _core._install_hook = install_hook_v2
    _core.AGENTS_BLOCK = AGENTS_BLOCK_V2
    _core._LUNA_DEVELOPER_INSTRUCTIONS = LUNA_DEVELOPER_INSTRUCTIONS_V2
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
        old_invoke = _core._invoke_hook_argv

        def invoke_compat(arguments, *, event, cwd):
            return _legacy_self_test_receipt(old_invoke(arguments, event=event, cwd=cwd))

        _core._invoke_hook_argv = invoke_compat
        try:
            return _core.global_self_test(*args, **kwargs)
        finally:
            _core._invoke_hook_argv = old_invoke


_luna_agent_bytes = luna_agent_bytes
_luna_agent_matches = luna_agent_matches
