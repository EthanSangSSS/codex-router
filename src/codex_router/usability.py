"""Active Router usability policy for V3.3 persistent-task, disposable-Luna routing.

The durable journal schema remains backward-compatible while worker identity is
generation-scoped. This module owns the active request-file, strict-mode,
fallback, bootstrap, CLI compatibility, and offline self-test behavior in one
install layer.

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


_USABILITY_INSTALLED = False
_STRICT_MARKER = "[CODEX_ROUTER_STRICT]"
_REQUEST_DIRECTORY = "stage-requests"
_LEGACY_STAGE_REQUIRED_FLAGS = (
    "--packet-id",
    "--objective",
    "--working-directory",
)
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
            or getattr(snapshot, "luna_agent_id", None) is not None
            or getattr(snapshot, "luna_task_path", None) is not None
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
    class PolicyDecisionV33(original_decision):
        strict_router: bool = False

    policy_module.PolicyDecision = PolicyDecisionV33

    def classify_prompt(prompt: str) -> PolicyDecisionV33:
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
            return PolicyDecisionV33(
                "route",
                "explicit_strict_router",
                base.sensitive_categories,
                True,
            )
        result = original_classify(prompt)
        if isinstance(result, PolicyDecisionV33):
            return result
        return PolicyDecisionV33(
            result.decision,
            result.reason_code,
            result.sensitive_categories,
            False,
        )

    policy_module.classify_prompt = classify_prompt
    policy_module.ROUTER_STRICT_MARKER = _STRICT_MARKER


def _install_adapter_self_test(adapter: Any) -> None:
    original_global_self_test = adapter.global_self_test
    core = adapter._core
    original_self_test_context = core._self_test_context

    def normalize_self_test_context(output: Mapping[str, Any]) -> dict[str, Any]:
        context = original_self_test_context(output)
        if context.get("decision") != "route":
            return context
        normalized = dict(context)
        for key in (
            "K1_STAGE_REQUEST_PATH",
            "K1_STAGE_INTERFACE",
            "capability_failure_policy",
            "primary_fallback_state",
            "strict_router",
            "luna_handshake_mode",
        ):
            normalized.pop(key, None)
        command = normalized.get("K1_STAGE_COMMAND")
        if isinstance(command, str):
            try:
                arguments = shlex.split(command, posix=True)
            except ValueError:
                return normalized
            if "--request-file" in arguments:
                index = arguments.index("--request-file")
                del arguments[index : index + 2]
            normalized["K1_STAGE_COMMAND"] = shlex.join(arguments)
        return normalized

    def global_self_test(*args, **kwargs):
        old = core._self_test_context
        core._self_test_context = normalize_self_test_context
        try:
            return original_global_self_test(*args, **kwargs)
        finally:
            core._self_test_context = old

    adapter.global_self_test = global_self_test


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
                    "stage-k1-fields",
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
            strict = bool(getattr(decision, "strict_router", False))
            has_prior_generation = bool(
                snapshot.packet_generation > 0
                or snapshot.luna_agent_id is not None
                or snapshot.pending_spawn is not None
            )
            context["K1_STAGE_COMMAND"] = command
            for obsolete in (
                "K1_STAGE_REQUEST_PATH",
                "K1_STAGE_INTERFACE",
                "luna_handshake_mode",
            ):
                context.pop(obsolete, None)
            if has_prior_generation or strict:
                context.update(
                    {
                        "capability_failure_policy": "degrade_primary_safe_local",
                        "primary_fallback_state": control.classify_primary_fallback(
                            snapshot
                        ),
                        "strict_router": strict,
                    }
                )
            else:
                context.pop("capability_failure_policy", None)
                context.pop("primary_fallback_state", None)
                context.pop("strict_router", None)
            return hook_module._hook_output(context)
        except Exception:
            return {"decision": "block", "reason": hook_module._BLOCK_REASON}

    def handle_hook_event(
        event: Mapping[str, Any], installation_dir: Path
    ) -> dict[str, Any]:
        if isinstance(event, Mapping) and event.get("hook_event_name") == "PreToolUse":
            # V3.3 applies to the real Codex Bash wire. Non-Bash synthetic or
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
                        return {
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "additionalContext": packet_wire,
                            }
                        }
                except Exception:
                    # Delegate to the mature fail-closed handler; never turn a
                    # diagnostic problem into a permission grant.
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
        if subparsers_action is None:
            return root
        stage_fields = subparsers_action.choices.get("stage-k1-fields")
        if stage_fields is not None:
            if not any(
                action.dest == "request_file" for action in stage_fields._actions
            ):
                stage_fields.add_argument(
                    "--request-file",
                    type=Path,
                    help=(
                        "V3.3 strict seven-field JSON request; mutually exclusive "
                        "with legacy semantic packet flags"
                    ),
                )
            for action in stage_fields._actions:
                if action.dest in {"packet_id", "objective", "working_directory"}:
                    action.required = False
            stage_fields.epilog = (
                "V3.3: use --request-file with the complete Router-injected command "
                "and append no packet flags. Legacy mode requires --packet-id, "
                "--objective, and --working-directory."
            )
        return root

    def _fallback_state(
        installation_dir: str | None, session_id: str | None
    ) -> str:
        if not installation_dir or not session_id:
            return "UNKNOWN"
        try:
            secret, _config = hook_module._load_installation(Path(installation_dir))
            snapshot = control.read_snapshot(
                Path(installation_dir), secret, session_id
            )
            return control.classify_primary_fallback(snapshot)
        except Exception:
            return "UNKNOWN"

    def _print_request_error(
        error: Any,
        *,
        installation_dir: str | None,
        session_id: str | None,
    ) -> int:
        cli_module._print_json(
            {
                "status": "error",
                "code": error.code,
                "message": str(error)[:200],
                "run_id": error.run_id,
                "stage": error.stage,
                "revision": error.revision,
                "capability_failure_policy": "degrade_primary_safe_local",
                "primary_fallback_state": _fallback_state(
                    installation_dir, session_id
                ),
            },
            stream=sys.stderr,
        )
        return error.exit_code

    def stage_request(arguments: list[str]) -> int:
        try:
            local = argparse.ArgumentParser(
                prog="router stage-k1-fields --request-file",
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
        if arguments and arguments[0] == "stage-k1-fields":
            if "--request-file" in arguments:
                installation_dir = None
                session_id = None
                for name in ("--installation-dir", "--session-id"):
                    try:
                        value = arguments[arguments.index(name) + 1]
                    except (ValueError, IndexError):
                        value = None
                    if name == "--installation-dir":
                        installation_dir = value
                    else:
                        session_id = value

                def print_state_error(error):
                    return _print_request_error(
                        error,
                        installation_dir=installation_dir,
                        session_id=session_id,
                    )

                old = cli_module._print_state_error
                cli_module._print_state_error = print_state_error
                try:
                    return stage_request(arguments[1:])
                finally:
                    cli_module._print_state_error = old
            if "--help" not in arguments and "-h" not in arguments:
                missing = [
                    flag
                    for flag in _LEGACY_STAGE_REQUIRED_FLAGS
                    if flag not in arguments
                ]
                if missing:
                    return cli_module._print_state_error(
                        cli_module.RouterStateError(
                            "invalid-input",
                            "missing required arguments: " + ", ".join(missing),
                        )
                    )
        return original_main(argv)

    cli_module.parser = parser
    cli_module.main = main


def install() -> None:
    """Install the one active usability layer after journal compatibility."""
    global _USABILITY_INSTALLED
    if _USABILITY_INSTALLED:
        return

    from . import luna_control as control
    from . import policy as policy_module

    _install_control_fallback(control)
    _install_policy(policy_module)

    from . import hook as hook_module

    _install_hook(hook_module, control, policy_module)

    from . import cli as cli_module
    from . import global_install_adapter as adapter

    _install_cli(cli_module, hook_module, control)
    _install_adapter_self_test(adapter)
    _USABILITY_INSTALLED = True
