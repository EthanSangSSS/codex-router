"""V4 lease staging overlay for the existing ``stage-k1-fields`` CLI surface."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import lease_control
from .protocol import ProtocolError, build_luna_packet
from .state import RouterStateError


_INSTALLED = False


def spawn_message(capability: str) -> str:
    """Return the exact current-lease bootstrap message expected by the Hook."""
    bootstrap = f"pwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4={capability}"
    return (
        "[CODEX_ROUTER_V4_LEASE_BOOTSTRAP]\n"
        "Your first tool call MUST be Bash with exactly this command:\n"
        f"{bootstrap}\n"
        "Do not perform substantive work before the Router injects the canonical K1 "
        "additionalContext. After K1 is visible, execute only that bounded K1 task."
    )


def install(cli_module: Any) -> None:
    """Use V4 staging only for sessions already activated in the V4 journal."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_stage_k1_fields = cli_module._stage_k1_fields

    def stage_k1_fields(args):
        installation_dir = Path(args.installation_dir)
        journal = installation_dir / "lease-control-v4-0.json"
        if not journal.exists() and not journal.is_symlink():
            return original_stage_k1_fields(args)

        secret, _config = cli_module._load_installation(installation_dir)
        snapshot = lease_control.read_snapshot(
            installation_dir, secret, args.session_id
        )
        if snapshot is None or snapshot.current_root_turn_tag is None:
            return original_stage_k1_fields(args)

        packet_id = cli_module._validate_structured_packet_text(
            args.packet_id, "packet_id"
        )
        objective = cli_module._validate_structured_packet_text(
            args.objective, "objective"
        )
        working_directory = cli_module._validate_structured_packet_text(
            args.working_directory, "working_directory"
        )
        if not Path(working_directory).is_absolute():
            raise RouterStateError(
                "invalid-input", "working_directory must be absolute"
            )
        intended_write_scope = cli_module._validated_structured_packet_list(
            args.intended_write_scope, "intended_write_scope"
        )
        authorizations = cli_module._validated_structured_packet_list(
            args.explicit_side_effect_authorization,
            "explicit_side_effect_authorizations",
        )
        success_criteria = cli_module._validated_structured_packet_list(
            args.success_criterion, "success_criteria"
        )
        stop_conditions = cli_module._validated_structured_packet_list(
            args.stop_condition, "stop_conditions"
        )

        try:
            packet_wire = build_luna_packet(
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
                args.session_id,
                root_turn_id=args.root_turn_id,
                capability=args.capability,
                packet_wire=packet_wire,
            )
        except ProtocolError as error:
            raise RouterStateError(
                "invalid-input", "structured K1 packet is invalid"
            ) from error

        lease = staged.active_lease
        if lease is None:
            raise RouterStateError(
                "conflict", "V4 staging completed without an active lease"
            )
        bootstrap_capability = lease_control.build_bootstrap_capability(
            secret, lease
        )
        return {
            "status": "staged",
            "packet_id": packet_id,
            "generation": staged.generation,
            "task_name": lease.expected_task_name,
            "bootstrap_capability": bootstrap_capability,
            "spawn_message": spawn_message(bootstrap_capability),
        }

    cli_module._stage_k1_fields = stage_k1_fields
    _INSTALLED = True
