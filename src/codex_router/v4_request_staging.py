"""Secure request-file staging for Router V4 generation leases.

V3.3 already moved semantic K1 fields out of model-extended shell argv into a
strict private request file. V4 keeps that boundary while staging into the
independent lease journal.
"""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import sys
from typing import Any, Mapping

from . import lease_control
from .state import RouterStateError
from .v4_cli import spawn_message


_INSTALLED = False


def _v4_request_result(
    cli_module: Any,
    *,
    installation_dir: Path,
    secret: bytes,
    session_id: str,
    root_turn_id: str,
    capability: str,
    request_file: Path,
) -> dict[str, Any]:
    from . import usability

    snapshot = lease_control.read_snapshot(
        installation_dir,
        secret,
        session_id,
    )
    if snapshot is None:
        raise RouterStateError("invalid-input", "current V4 task is unavailable")
    expected_path = usability._stage_request_path(
        lease_control,
        installation_dir,
        secret,
        session_id,
        snapshot,
    )
    request, file_identity = usability._read_request_file(
        request_path=request_file,
        expected_path=expected_path,
        maximum_bytes=cli_module.MAX_HOOK_INPUT_BYTES,
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
        raise RouterStateError(
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
            generation=snapshot.generation + 1,
            objective=objective,
            working_directory=working_directory,
            intended_write_scope=intended_write_scope,
            explicit_side_effect_authorizations=authorizations,
            success_criteria=success_criteria,
            stop_conditions=stop_conditions,
        )
        staged = lease_control.stage_authorized_lease(
            installation_dir,
            secret,
            session_id,
            root_turn_id=root_turn_id,
            capability=capability,
            packet_wire=packet_wire,
        )
    except cli_module.ProtocolError as error:
        raise RouterStateError(
            "invalid-input", "structured K1 packet is invalid"
        ) from error

    lease = staged.active_lease
    if lease is None:
        raise RouterStateError(
            "conflict", "V4 staging completed without an active lease"
        )
    bootstrap_capability = lease_control.build_bootstrap_capability(secret, lease)
    cleaned = usability._unlink_same_request(request_file, file_identity)
    return {
        "status": "staged",
        "packet_id": packet_id,
        "generation": staged.generation,
        "task_name": lease.expected_task_name,
        "bootstrap_capability": bootstrap_capability,
        "spawn_message": spawn_message(bootstrap_capability),
        "request_cleanup": "removed" if cleaned else "retained",
    }


def install(hook_module: Any, cli_module: Any) -> None:
    """Install V4 request-file routing after the V4 Hook and CLI overlays."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import usability

    original_handle_hook_event = hook_module.handle_hook_event
    original_main = cli_module.main

    def handle_hook_event(
        event: Mapping[str, Any], installation_dir: Path
    ) -> dict[str, Any]:
        output = original_handle_hook_event(event, installation_dir)
        if (
            not isinstance(event, Mapping)
            or event.get("hook_event_name") != "UserPromptSubmit"
            or not isinstance(output, Mapping)
        ):
            return output

        hook_output = output.get("hookSpecificOutput")
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
        if (
            not isinstance(context, dict)
            or context.get("decision") != "route"
            or context.get("workflow") != "generation_lease_v4"
        ):
            return output

        try:
            session_id = event.get("session_id")
            root_turn_id = event.get("turn_id")
            capability = context.get("K1_STAGE_CAPABILITY")
            if not all(
                isinstance(value, str) and value
                for value in (session_id, root_turn_id, capability)
            ):
                raise RouterStateError(
                    "invalid-input", "V4 request staging identity is unavailable"
                )
            secret, _config = hook_module._load_installation(Path(installation_dir))
            snapshot = lease_control.read_snapshot(
                Path(installation_dir), secret, session_id
            )
            if snapshot is None:
                raise RouterStateError(
                    "invalid-input", "current V4 task is unavailable"
                )
            request_path = usability._stage_request_path(
                lease_control,
                Path(installation_dir),
                secret,
                session_id,
                snapshot,
            )
            command = context.get("K1_STAGE_COMMAND")
            if not isinstance(command, str) or not command:
                raise RouterStateError(
                    "invalid-input", "V4 K1 stage command is unavailable"
                )
            context["K1_STAGE_COMMAND"] = (
                command
                + " --request-file "
                + shlex.quote(str(request_path))
            )
            context["K1_STAGE_INTERFACE"] = "private_request_file_v4"
            return hook_module._hook_output(context)
        except RouterStateError as error:
            return {"decision": "block", "reason": str(error)[:500]}
        except Exception:
            return {"decision": "block", "reason": hook_module._BLOCK_REASON}

    def main(argv=None) -> int:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if (
            not arguments
            or arguments[0] != "stage-k1-fields"
            or "--request-file" not in arguments
        ):
            return original_main(argv)

        try:
            local = cli_module.RouterArgumentParser(
                prog="router stage-k1-fields --request-file",
                add_help=True,
            )
            local.add_argument("--installation-dir", type=Path, required=True)
            local.add_argument("--session-id", required=True)
            local.add_argument("--root-turn-id", required=True)
            local.add_argument("--capability", required=True)
            local.add_argument("--request-file", type=Path, required=True)
            args = local.parse_args(arguments[1:])

            journal = args.installation_dir / "lease-control-v4-0.json"
            if not journal.exists() and not journal.is_symlink():
                return original_main(argv)

            secret, _config = cli_module._load_installation(args.installation_dir)
            snapshot = lease_control.read_snapshot(
                args.installation_dir,
                secret,
                args.session_id,
            )
            if snapshot is None:
                # The installation may already support V4 while this historical
                # session still belongs to the V3 request-file path.
                return original_main(argv)

            result = _v4_request_result(
                cli_module,
                installation_dir=args.installation_dir,
                secret=secret,
                session_id=args.session_id,
                root_turn_id=args.root_turn_id,
                capability=args.capability,
                request_file=args.request_file,
            )
            cli_module._print_json(result)
            return 0
        except RouterStateError as error:
            return cli_module._print_state_error(error)
        except (OSError, TypeError, ValueError) as error:
            return cli_module._print_state_error(
                RouterStateError(
                    "invalid-input", "V4 K1 stage request could not be processed"
                )
            )

    hook_module.handle_hook_event = handle_hook_event
    cli_module.main = main
    _INSTALLED = True
