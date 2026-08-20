"""Router V3.2 usability policy layered over the V3.1 safety core.

V3.2 deliberately leaves the mature journal, K1 capability, lifecycle,
and identity machinery in V3.1.  This module narrows four operator-facing
failure modes:

* semantic K1 fields travel through one strict request file instead of a
  model-extended argv prefix;
* the current PRIMARY state is classified mechanically before local fallback;
* an exact first-line strict marker disables capability degradation;
* the real Codex Bash/pwd bootstrap probe may run while K1 is injected, so
  continuation no longer depends on interpreting an expected denial.

Security ambiguity still fails closed.  Capability degradation never grants
Luna authority or external/A1 side-effect authority.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import shlex
import stat
import sys
from typing import Any, Mapping


_V32_INSTALLED = False
_STRICT_MARKER = "[CODEX_ROUTER_STRICT]"
_REQUEST_DIRECTORY = "stage-requests"
_REQUEST_FIELDS = frozenset(
    {
        "packet_id",
        "objective",
        "working_directory",
        "intended_write_scope",
        "explicit_side_effect_authorizations",
        "success_criteria",
        "stop_conditions",
    }
)

SAFE_LOCAL_FALLBACK = "SAFE_LOCAL_FALLBACK"
BLOCKED_ACTIVE_AUTHORITY = "BLOCKED_ACTIVE_AUTHORITY"
BLOCKED_PENDING_SPAWN = "BLOCKED_PENDING_SPAWN"
BLOCKED_TASK_STATE = "BLOCKED_TASK_STATE"


def _first_nonempty_line_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip():
            return index
    return None


def _is_exact_bash_pwd_probe(event: Mapping[str, Any]) -> bool:
    if event.get("tool_name") != "Bash":
        return False
    tool_input = event.get("tool_input")
    return (
        isinstance(tool_input, Mapping)
        and set(tool_input) == {"command"}
        and tool_input.get("command") == "pwd"
    )


def _ensure_private_request_directory(installation_dir: Path) -> Path:
    directory = Path(installation_dir) / _REQUEST_DIRECTORY
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
        metadata = directory.lstat()
    except OSError as error:
        from .state import RouterStateError

        raise RouterStateError(
            "invalid-input", "Router stage request directory is unavailable"
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        from .state import RouterStateError

        raise RouterStateError(
            "invalid-input", "Router stage request directory is unsafe"
        )
    return directory


def _stage_request_path(
    control: Any,
    installation_dir: Path,
    secret: bytes,
    session_id: str,
    snapshot: Any,
) -> Path:
    root_turn_tag = getattr(snapshot, "current_root_turn_tag", None)
    if not isinstance(root_turn_tag, str) or not root_turn_tag:
        from .state import RouterStateError

        raise RouterStateError("invalid-input", "current root turn is unavailable")
    session = control.session_tag(secret, session_id)
    directory = _ensure_private_request_directory(Path(installation_dir))
    return directory / f"k1-{session}-{root_turn_tag}.json"


def _read_request_file(
    *,
    request_path: Path,
    expected_path: Path,
    maximum_bytes: int,
) -> tuple[dict[str, Any], tuple[int, int]]:
    from .state import RouterStateError

    if not request_path.is_absolute() or request_path != expected_path:
        raise RouterStateError("invalid-input", "K1 stage request path is invalid")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(request_path, flags)
    except OSError as error:
        raise RouterStateError(
            "invalid-input", "K1 stage request file is unavailable"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or mode & 0o022
            or metadata.st_size > maximum_bytes
        ):
            raise RouterStateError("invalid-input", "K1 stage request file is unsafe")
        if mode != 0o600:
            try:
                os.fchmod(descriptor, 0o600)
            except OSError as error:
                raise RouterStateError(
                    "invalid-input", "K1 stage request permissions are unsafe"
                ) from error

        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum_bytes:
            raise RouterStateError(
                "invalid-input", "K1 stage request exceeds the input limit"
            )
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RouterStateError(
                "invalid-input", "K1 stage request must be valid UTF-8 JSON"
            ) from error
        if not isinstance(value, dict) or set(value) != _REQUEST_FIELDS:
            raise RouterStateError(
                "invalid-input", "K1 stage request schema is invalid"
            )
        return value, (metadata.st_dev, metadata.st_ino)
    finally:
        os.close(descriptor)


def _unlink_same_request(path: Path, identity: tuple[int, int]) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and (metadata.st_dev, metadata.st_ino) == identity
    ):
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


def _install_control_fallback(control: Any) -> None:
    def classify_primary_fallback(snapshot: Any) -> str:
        if (
            snapshot is None
            or getattr(snapshot, "logical_task_status", None) != "ACTIVE"
            or getattr(snapshot, "execution_status", None) == "RETIRED"
        ):
            return BLOCKED_TASK_STATE
        if getattr(snapshot, "pending_spawn", None) is not None:
            return BLOCKED_PENDING_SPAWN
        if (
            getattr(snapshot, "execution_status", None) != "IDLE"
            or getattr(snapshot, "active_packet_id", None) is not None
            or getattr(snapshot, "active_child_turn_id", None) is not None
            or getattr(snapshot, "authority_packet_wire", None) is not None
        ):
            return BLOCKED_ACTIVE_AUTHORITY
        return SAFE_LOCAL_FALLBACK

    control.classify_primary_fallback = classify_primary_fallback


def _install_policy(policy_module: Any) -> None:
    original_decision = policy_module.PolicyDecision
    original_classify = policy_module.classify_prompt

    @dataclass(frozen=True)
    class PolicyDecisionV32(original_decision):
        strict_router: bool = False

    policy_module.PolicyDecision = PolicyDecisionV32

    def classify_prompt(prompt: str) -> PolicyDecisionV32:
        normalized = policy_module._normalize_prompt(prompt)
        lines = normalized.split("\n")
        marker_index = _first_nonempty_line_index(lines)
        strict = (
            marker_index is not None
            and lines[marker_index].strip() == _STRICT_MARKER
        )
        if strict:
            remainder = "\n".join(lines[marker_index + 1 :]).strip()
            base = original_classify(remainder if remainder else "router strict work")
            return PolicyDecisionV32(
                "route",
                "explicit_strict_router",
                base.sensitive_categories,
                True,
            )
        result = original_classify(prompt)
        if isinstance(result, PolicyDecisionV32):
            return result
        return PolicyDecisionV32(
            result.decision,
            result.reason_code,
            result.sensitive_categories,
            False,
        )

    policy_module.classify_prompt = classify_prompt
    policy_module.ROUTER_STRICT_MARKER = _STRICT_MARKER


def _install_adapter(adapter: Any) -> None:
    original_primary_gen2 = adapter.primary_gen2_readiness

    def primary_model_is_admitted(
        requested_model: str | None = adapter.PRIMARY_MODEL_INHERIT,
        runtime_capabilities: Any = None,
    ) -> bool:
        if requested_model is not None and (
            not isinstance(requested_model, str) or not requested_model.strip()
        ):
            return False
        compatibility = adapter.native_surface_compatibility(runtime_capabilities)
        return compatibility.primary_gen1_readiness == adapter.PRIMARY_GEN1_PASS

    def primary_gen2_readiness(
        runtime_capabilities: Any,
        *,
        strict_router: bool | None = None,
        primary_fallback_state: str | None = None,
    ) -> dict[str, str | None]:
        # Preserve the one-argument V3.1 API as a compatibility seam.  New
        # callers provide the Router state/strict decision explicitly.
        if strict_router is None and primary_fallback_state is None:
            return original_primary_gen2(runtime_capabilities)
        result = dict(original_primary_gen2(runtime_capabilities))
        if result.get("persistent_followup_availability") == adapter.PERSISTENT_FOLLOWUP_UNAVAILABLE:
            if strict_router:
                result["code"] = "UNAVAILABLE_STRICT_BLOCK"
            elif primary_fallback_state == SAFE_LOCAL_FALLBACK:
                result["code"] = "UNAVAILABLE_DEGRADE_ALLOWED"
            else:
                result["code"] = "UNAVAILABLE_SAFETY_BLOCK"
        return result

    adapter.primary_model_is_admitted = primary_model_is_admitted
    adapter.primary_gen2_readiness = primary_gen2_readiness

    old_primary_text = adapter.AGENTS_BLOCK_V3
    legacy_stage_sentence = (
        "Legacy V3.1 compatibility reference only: use the exact injected "
        "`stage-k1-fields` protected command prefix verbatim. Append only "
        "`--packet-id`, `--objective`, `--working-directory` and the legacy "
        "repeated packet-field options when, and only when, an older installed "
        "session explicitly exposes that legacy prefix. Do not build K1 wire "
        "bytes, JSON, a prefix, a shell pipeline, or an alternate control command. "
        "Successful `stage-k1-fields` is mandatory before native `spawn_agent`/"
        "`followup_task`. The legacy result token "
        "`BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` is diagnostic only under V3.2 and "
        "is not the ordinary non-strict fallback instruction."
    )
    # Preserve native-schema and safety paragraphs from V3.1 while replacing
    # the brittle operator mechanics with a single active V3.2 contract.
    marker = "Honor `[CODEX_ROUTER_POLICY_V1]` Hook context exactly:\n"
    suffix = old_primary_text.split(marker, 1)[1] if marker in old_primary_text else old_primary_text
    # Drop only the first legacy staging bullet; keep the mature safety text.
    suffix_lines = suffix.splitlines()
    suffix_lines = [
        line
        for line in suffix_lines
        if not line.startswith("- For every Luna generation, use the exact injected `stage-k1-fields`")
    ]
    preserved = "\n".join(suffix_lines)
    primary_text = f"""{adapter._core.AGENTS_BEGIN}
This Codex task is the primary Sol coordinator and final reviewer. Luna is a persistent Luna per task epoch and the single Full Executor for that epoch.
Honor `[CODEX_ROUTER_POLICY_V1]` Hook context exactly:
- V3.2 active staging uses the complete injected `K1_STAGE_COMMAND` verbatim. Before running it, write exactly one seven-field UTF-8 JSON request to `K1_STAGE_REQUEST_PATH`: `packet_id`, `objective`, `working_directory`, `intended_write_scope`, `explicit_side_effect_authorizations`, `success_criteria`, and `stop_conditions`. Do not append command arguments and do not write generation, session identity, task/luna epoch, capability, agent identity, or K1 wire into the request. Router alone constructs canonical K1.
- Capability failure and safety failure are different. Automatic degraded PRIMARY execution is allowed only when the injected `strict_router` is false and `primary_fallback_state=SAFE_LOCAL_FALLBACK`. In that state PRIMARY may perform bounded workspace-local read/edit/test/build/local-Git/debug work. It may not use degraded mode for deploy, publish, release, credentials/tokens/cookies/private keys, cloud/service mutation, package publication, external A1 effects, privilege/authentication changes, or agent creation/delegation.
- `[CODEX_ROUTER_STRICT]` on the exact first non-empty line forces `strict_router=true`; any Router capability failure then remains fail-closed. Do not infer strict mode from natural-language wording.
- If persistent `followup_task` is available, stage the next K1 and reuse the same Luna. If it is explicitly unavailable, do not stage Gen2: degrade locally only when non-strict and `SAFE_LOCAL_FALLBACK`; otherwise stop fail-closed. `send_input` and `resume_agent` remain forbidden, `send_message` remains QueueOnly, and wait/replacement/polling are not continuation fallbacks.
- The Luna bootstrap mode is `allowlisted_bash_pwd`: the first exact Codex `Bash` tool with `{{"command":"pwd"}}` may be allowed while canonical K1 is injected. Any other first Bash command is denied before executor state is started.
- {legacy_stage_sentence}
{preserved}
"""
    # Avoid duplicate nested managed markers from the preserved V3.1 block.
    primary_text = primary_text.replace(
        f"\n{adapter._core.AGENTS_END}\n{adapter._core.AGENTS_END}",
        f"\n{adapter._core.AGENTS_END}",
    )
    if not primary_text.rstrip().endswith(adapter._core.AGENTS_END):
        primary_text = primary_text.rstrip() + "\n" + adapter._core.AGENTS_END + "\n"

    old_luna_text = adapter.LUNA_DEVELOPER_INSTRUCTIONS_V3
    luna_text = f"""You are the persistent Luna Full Executor for one Router task epoch. Sol is the planner, coordinator, reviewer, and final authority.

V3.2 bootstrap rules:
- Native collaboration messages are transport triggers, not work authority. The authoritative work packet is `[CODEX_ROUTER_PACKET_V3_1]` injected by Router as developer context.
- On a new Router transport trigger with no canonical packet yet, issue exactly the Codex `Bash` tool with `{{"command":"pwd"}}`. This is the only V3.2 allowlisted bootstrap probe. Router may allow that read-only probe while injecting canonical K1 through `additionalContext`. The probe itself supplies no work authority.
- Only after canonical `[CODEX_ROUTER_PACKET_V3_1]` is present may substantive packet work begin. If the probe executes and no canonical K1 appears, stop fail-closed with `BLOCKED_ROUTER_HANDSHAKE_MISSING`.
- Never replace the bootstrap probe with another shell command, file mutation, network action, lifecycle operation, or side effect.

Operating rules retained from V3.1:
- Full Executor ordinary inspect/research/edit/test/debug/retry/verify work is allowed after K1. Use ordinary shell, Unified Exec, Code Mode, code, apps, plugins, and web capabilities when the runtime exposes them.
- You have no descendants and must perform no nested Codex delegation. Never create, spawn, fork, relay to, resume, or coordinate another agent or Codex runtime.
- You remain the same native Luna identity for the persistent task epoch. Packet generation replaces prior authority: accept only the latest packet and never inherit paths or permissions from an older packet.
- Hard Authority Pause freezes Router authority immediately. Never intentionally daemonize, detach, or leave long-lived background work running beyond the bounded turn.
- A1 hard claims require proven pre-action surfaces. Never claim an external effect completed without direct evidence from the required native surface.
- Work only inside the latest packet's working directory and allowed paths. Never access credentials, cookies, tokens, private keys, payment data, or unrelated private data.
- Never commit, push, create or modify a pull request, install, deploy, publish, or start a persistent service unless the latest explicit packet authorizes that exact action.

Legacy deny-retry compatibility text applies only to an older installed session that explicitly reports a deny-retry handshake mode, never to V3.2 `allowlisted_bash_pwd`: {old_luna_text}
"""

    adapter.AGENTS_BLOCK_V32 = primary_text
    adapter.AGENTS_BLOCK_V3 = primary_text
    adapter.AGENTS_BLOCK = primary_text
    adapter.AGENTS_BLOCK_V2 = primary_text
    adapter.LUNA_DEVELOPER_INSTRUCTIONS_V32 = luna_text
    adapter.LUNA_DEVELOPER_INSTRUCTIONS_V3 = luna_text
    adapter.LUNA_DEVELOPER_INSTRUCTIONS = luna_text
    adapter.LUNA_DEVELOPER_INSTRUCTIONS_V2 = luna_text


def _install_hook(hook_module: Any, control: Any, policy_module: Any) -> None:
    original_handle_user_prompt = hook_module.handle_user_prompt
    original_handle_hook_event = hook_module.handle_hook_event
    hook_module.classify_prompt = policy_module.classify_prompt

    def handle_user_prompt(
        event: Mapping[str, Any], installation_dir: Path
    ) -> dict[str, Any]:
        output = original_handle_user_prompt(event, installation_dir)
        hook_output = output.get("hookSpecificOutput") if isinstance(output, Mapping) else None
        if not isinstance(hook_output, Mapping):
            return output
        additional = hook_output.get("additionalContext")
        if not isinstance(additional, str) or not additional.startswith(
            hook_module.HOOK_CONTEXT_PREFIX
        ):
            return output
        try:
            context = json.loads(additional[len(hook_module.HOOK_CONTEXT_PREFIX) :])
        except json.JSONDecodeError:
            return {"decision": "block", "reason": hook_module._BLOCK_REASON}
        if not isinstance(context, dict) or context.get("decision") != "route":
            return output
        try:
            session_id = event.get("session_id")
            root_turn_id = event.get("turn_id")
            prompt = event.get("prompt")
            if not all(isinstance(value, str) and value for value in (session_id, root_turn_id, prompt)):
                raise ValueError("route identity is unavailable")
            secret, _config = hook_module._load_installation(Path(installation_dir))
            snapshot = control.read_snapshot(Path(installation_dir), secret, session_id)
            if snapshot is None:
                raise ValueError("route state is unavailable")
            request_path = _stage_request_path(
                control,
                Path(installation_dir),
                secret,
                session_id,
                snapshot,
            )
            capability = context.get("K1_STAGE_CAPABILITY")
            if not isinstance(capability, str) or not capability:
                raise ValueError("stage capability is unavailable")
            command = shlex.join(
                (
                    sys.executable,
                    "-E",
                    "-P",
                    "-m",
                    "codex_router",
                    "stage-k1-request",
                    "--installation-dir",
                    str(Path(installation_dir)),
                    "--session-id",
                    session_id,
                    "--root-turn-id",
                    root_turn_id,
                    "--capability",
                    capability,
                    "--request-file",
                    str(request_path),
                )
            )
            decision = policy_module.classify_prompt(prompt)
            context.update(
                {
                    "K1_STAGE_REQUEST_PATH": str(request_path),
                    "K1_STAGE_COMMAND": command,
                    "K1_STAGE_INTERFACE": "request_file_v1",
                    "capability_failure_policy": "degrade_primary_safe_local",
                    "primary_fallback_state": control.classify_primary_fallback(snapshot),
                    "strict_router": bool(getattr(decision, "strict_router", False)),
                    "luna_handshake_mode": "allowlisted_bash_pwd",
                }
            )
            return hook_module._hook_output(context)
        except Exception:
            return {"decision": "block", "reason": hook_module._BLOCK_REASON}

    def handle_hook_event(
        event: Mapping[str, Any], installation_dir: Path
    ) -> dict[str, Any]:
        if isinstance(event, Mapping) and event.get("hook_event_name") == "PreToolUse":
            # V3.2 applies to the real Codex Bash wire.  Non-Bash synthetic or
            # older tool names retain the V3.1 deny-retry compatibility path.
            if event.get("tool_name") == "Bash":
                try:
                    secret, _config = hook_module._load_installation(
                        Path(installation_dir)
                    )
                    session_id = event.get("session_id")
                    agent_id = event.get("agent_id")
                    child_turn_id = event.get("turn_id")
                    if not all(
                        isinstance(value, str) and value
                        for value in (session_id, agent_id, child_turn_id)
                    ):
                        return original_handle_hook_event(event, installation_dir)
                    snapshot = control.read_snapshot(
                        Path(installation_dir), secret, session_id
                    )
                    first_bootstrap = (
                        hook_module._is_bound_luna(
                            event, Path(installation_dir), secret
                        )
                        and snapshot is not None
                        and snapshot.logical_task_status == "ACTIVE"
                        and snapshot.execution_status == "IDLE"
                        and snapshot.active_packet_id is not None
                        and snapshot.active_child_turn_id is None
                        and snapshot.authority_packet_wire is not None
                    )
                    if first_bootstrap:
                        if not _is_exact_bash_pwd_probe(event):
                            return hook_module._pretool_output(
                                "deny",
                                "Router K1 bootstrap requires exact Bash pwd probe",
                            )
                        _updated, packet_wire = control.authorize_executor_tool(
                            Path(installation_dir),
                            secret,
                            session_id,
                            agent_id=agent_id,
                            child_turn_id=child_turn_id,
                        )
                        if packet_wire is None:
                            return hook_module._pretool_output(
                                "deny", "Router K1 bootstrap authority is unavailable"
                            )
                        return hook_module._pretool_output(
                            "allow",
                            "Router allowlisted read-only K1 bootstrap probe",
                            additional_context=packet_wire,
                        )
                except Exception:
                    # Delegate to the mature fail-closed handler; never turn a
                    # V3.2 diagnostic problem into a permission grant.
                    return original_handle_hook_event(event, installation_dir)
        return original_handle_hook_event(event, installation_dir)

    hook_module.handle_user_prompt = handle_user_prompt
    hook_module.handle_hook_event = handle_hook_event


def _install_cli(cli_module: Any, hook_module: Any, control: Any) -> None:
    original_main = cli_module.main
    original_parser = cli_module.parser

    def parser() -> argparse.ArgumentParser:
        root = original_parser()
        subparsers_action = next(
            (
                action
                for action in root._actions
                if isinstance(action, argparse._SubParsersAction)
            ),
            None,
        )
        if subparsers_action is not None and "stage-k1-request" not in subparsers_action.choices:
            command = subparsers_action.add_parser(
                "stage-k1-request",
                help="stage canonical K1 from one strict request file",
            )
            command.add_argument("--installation-dir", type=Path, required=True)
            command.add_argument("--session-id", required=True)
            command.add_argument("--root-turn-id", required=True)
            command.add_argument("--capability", required=True)
            command.add_argument("--request-file", type=Path, required=True)
        return root

    def stage_request(arguments: list[str]) -> int:
        try:
            local = argparse.ArgumentParser(
                prog="router stage-k1-request",
                add_help=True,
            )
            local.add_argument("--installation-dir", type=Path, required=True)
            local.add_argument("--session-id", required=True)
            local.add_argument("--root-turn-id", required=True)
            local.add_argument("--capability", required=True)
            local.add_argument("--request-file", type=Path, required=True)
            try:
                args = local.parse_args(arguments)
            except SystemExit as error:
                if error.code == 0:
                    return 0
                raise cli_module.RouterArgumentParser().error("invalid command usage")

            secret, _config = hook_module._load_installation(args.installation_dir)
            snapshot = control.read_snapshot(
                args.installation_dir, secret, args.session_id
            )
            if snapshot is None:
                raise cli_module.RouterStateError(
                    "invalid-input", "current task is unavailable"
                )
            expected_path = _stage_request_path(
                control,
                args.installation_dir,
                secret,
                args.session_id,
                snapshot,
            )
            request, file_identity = _read_request_file(
                request_path=args.request_file,
                expected_path=expected_path,
                maximum_bytes=hook_module.MAX_HOOK_INPUT_BYTES,
            )
            packet_id = cli_module._validate_structured_packet_text(
                request["packet_id"], "packet_id"
            )
            objective = cli_module._validate_structured_packet_text(
                request["objective"], "objective"
            )
            working_directory = cli_module._validate_structured_packet_text(
                request["working_directory"], "working_directory"
            )
            if not Path(working_directory).is_absolute():
                raise cli_module.RouterStateError(
                    "invalid-input", "working_directory must be absolute"
                )
            intended_write_scope = cli_module._validated_structured_packet_list(
                request["intended_write_scope"], "intended_write_scope"
            )
            authorizations = cli_module._validated_structured_packet_list(
                request["explicit_side_effect_authorizations"],
                "explicit_side_effect_authorizations",
            )
            success_criteria = cli_module._validated_structured_packet_list(
                request["success_criteria"], "success_criteria"
            )
            stop_conditions = cli_module._validated_structured_packet_list(
                request["stop_conditions"], "stop_conditions"
            )
            try:
                packet_wire = cli_module.build_luna_packet(
                    packet_id=packet_id,
                    generation=snapshot.packet_generation + 1,
                    objective=objective,
                    working_directory=working_directory,
                    intended_write_scope=intended_write_scope,
                    explicit_side_effect_authorizations=authorizations,
                    success_criteria=success_criteria,
                    stop_conditions=stop_conditions,
                )
                staged = control.stage_authority_packet(
                    args.installation_dir,
                    secret,
                    args.session_id,
                    root_turn_id=args.root_turn_id,
                    capability=args.capability,
                    packet_wire=packet_wire,
                )
            except cli_module.ProtocolError as error:
                raise cli_module.RouterStateError(
                    "invalid-input", "structured K1 packet is invalid"
                ) from error
            cleaned = _unlink_same_request(args.request_file, file_identity)
            cli_module._print_json(
                {
                    "status": "staged",
                    "packet_id": packet_id,
                    "generation": staged.packet_generation + 1,
                    "request_cleanup": "removed" if cleaned else "retained",
                }
            )
            return 0
        except cli_module.RouterStateError as error:
            return cli_module._print_state_error(error)
        except (OSError, ValueError, TypeError) as error:
            return cli_module._print_state_error(
                cli_module.RouterStateError(
                    "invalid-input", "K1 stage request could not be processed"
                )
            )

    def main(argv=None) -> int:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if arguments and arguments[0] == "stage-k1-request":
            return stage_request(arguments[1:])
        return original_main(argv)

    cli_module.parser = parser
    cli_module.main = main


def install() -> None:
    """Install V3.2 once after the V3.1 recovery overlay is active."""
    global _V32_INSTALLED
    if _V32_INSTALLED:
        return

    from . import luna_control as control
    from . import policy as policy_module

    _install_control_fallback(control)
    _install_policy(policy_module)

    from . import global_install_adapter as adapter

    _install_adapter(adapter)

    from . import hook as hook_module

    _install_hook(hook_module, control, policy_module)

    from . import cli as cli_module

    _install_cli(cli_module, hook_module, control)
    _V32_INSTALLED = True
