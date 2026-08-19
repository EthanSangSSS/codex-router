import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

from .adapters import adapters_for_mode
from .global_install_adapter import (
    DEFERRED_ACCEPTANCE_EVIDENCE,
    LIVE_ACTIVATION_BLOCKERS,
    PRIMARY_MODEL_INHERIT,
    global_install,
    global_self_test,
    global_status,
    global_uninstall,
)
from . import luna_control
from .hook import MAX_HOOK_INPUT_BYTES, _load_installation, handle_hook_event, read_hook_event
from .protocol import ProtocolError, build_luna_packet, parse_luna_packet
from .pipeline import Router, RouterRunError
from .state import RouterStateError, fail_stage, get_status, start_run, submit_stage
from .types import GlobalStatus, TransitionResult


def _bounded_parser_message(message: str) -> str:
    if "unrecognized arguments" in message:
        return "unexpected arguments"
    if "the following arguments are required" in message:
        names = re.findall(r"--[A-Za-z0-9-]+|\bcommand\b", message)
        return ("missing required arguments: " + ", ".join(dict.fromkeys(names)))[:200]
    argument = re.search(r"argument ([^:]+):", message)
    if argument:
        name = argument.group(1)
        if name == "command":
            return "invalid subcommand"
        if re.fullmatch(r"--[A-Za-z0-9-]+", name):
            return f"invalid value for {name}"
    return "invalid command usage"


class RouterArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise RouterStateError("invalid-input", _bounded_parser_message(message))


class _UniqueStore(argparse.Action):
    """Reject duplicate structured packet singleton options during parsing."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        value: str,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(self, f"{option_string} may occur once")
        setattr(namespace, self.dest, value)


def _add_transition_identity_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--run-id", required=True)
    command.add_argument("--driver-context-id", required=True)
    command.add_argument("--state-dir", type=Path, required=True)
    command.add_argument("--stage", choices=("local_sol", "web_sol", "luna"), required=True)
    command.add_argument("--expected-revision", type=int, required=True)
    command.add_argument("--packet-digest", required=True)


def parser() -> argparse.ArgumentParser:
    root = RouterArgumentParser(prog="router")
    subcommands = root.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="run Local Sol → Web Sol → Luna")
    run.add_argument("--task", required=True)
    run.add_argument("--adapter-mode", choices=("fake", "real"), default="real")
    run.add_argument("--state-dir", type=Path, default=Path(".router/runs"))
    run.add_argument("--timeout", type=float, default=60)

    start = subcommands.add_parser("start", help="create a canonical App-driven run")
    start.add_argument("--task", required=True)
    start.add_argument("--driver-context-id", required=True)
    start.add_argument("--state-dir", type=Path, required=True)
    start.add_argument("--codex-bin", type=Path, required=True)
    start.add_argument("--local-model", required=True)
    start.add_argument("--local-reasoning", required=True)
    start.add_argument("--web-model", required=True)
    start.add_argument("--web-reasoning", required=True)
    start.add_argument("--luna-model", required=True)
    start.add_argument("--luna-reasoning", required=True)

    submit = subcommands.add_parser("submit-stage", help="submit one successful stage")
    _add_transition_identity_arguments(submit)
    submit.add_argument("--output-file", type=Path, required=True)
    submit.add_argument("--execution-file", type=Path, required=True)

    fail = subcommands.add_parser("fail-stage", help="finish a run with a stage failure")
    _add_transition_identity_arguments(fail)
    fail.add_argument("--error-file", type=Path, required=True)
    fail.add_argument("--execution-file", type=Path, required=True)

    status = subcommands.add_parser("status", help="read and repair derived run views")
    status.add_argument("--run-id", required=True)
    status.add_argument("--state-dir", type=Path, required=True)

    for command, event in (
        ("hook-user-prompt", "UserPromptSubmit"),
        ("hook-pre-tool", "PreToolUse"),
        ("hook-post-tool", "PostToolUse"),
        ("hook-permission-request", "PermissionRequest"),
        ("hook-stop", "Stop"),
        ("hook-subagent-start", "SubagentStart"),
        ("hook-subagent-stop", "SubagentStop"),
    ):
        hook = subcommands.add_parser(command, help=f"handle one Codex {event} event")
        hook.add_argument("--installation-dir", type=Path, required=True)

    stage_k1 = subcommands.add_parser("stage-k1", help="stage one canonical K1 authority packet")
    stage_k1.add_argument("--installation-dir", type=Path, required=True)
    stage_k1.add_argument("--session-id", required=True)
    stage_k1.add_argument("--root-turn-id", required=True)
    stage_k1.add_argument("--capability", required=True)

    stage_fields = subcommands.add_parser(
        "stage-k1-fields", help="stage one canonical K1 authority packet from fields"
    )
    stage_fields.add_argument("--installation-dir", type=Path, required=True)
    stage_fields.add_argument("--session-id", required=True)
    stage_fields.add_argument("--root-turn-id", required=True)
    stage_fields.add_argument("--capability", required=True)
    stage_fields.add_argument("--packet-id", action=_UniqueStore, required=True)
    stage_fields.add_argument("--objective", action=_UniqueStore, required=True)
    stage_fields.add_argument("--working-directory", action=_UniqueStore, required=True)
    stage_fields.add_argument("--intended-write-scope", action="append", default=[])
    stage_fields.add_argument(
        "--explicit-side-effect-authorization", action="append", default=[]
    )
    stage_fields.add_argument("--success-criterion", action="append", default=[])
    stage_fields.add_argument("--stop-condition", action="append", default=[])

    install = subcommands.add_parser(
        "global-install", help="install the reversible global Router policy"
    )
    install.add_argument("--codex-home", type=Path, required=True)
    install.add_argument("--state-dir", type=Path, required=True)
    install.add_argument("--codex-bin", type=Path, required=True)
    install.add_argument("--local-model", default=PRIMARY_MODEL_INHERIT)
    install.add_argument("--local-reasoning", default="max")
    install.add_argument("--web-model", default="sol")
    install.add_argument("--web-reasoning", default="xhigh")
    install.add_argument("--luna-model", default="gpt-5.6-luna")
    install.add_argument("--luna-reasoning", default="max")

    global_status_parser = subcommands.add_parser(
        "global-status", help="inspect the global Router policy installation"
    )
    global_status_parser.add_argument("--codex-home", type=Path, required=True)
    uninstall = subcommands.add_parser(
        "global-uninstall", help="reversibly remove the global Router policy"
    )
    uninstall.add_argument("--codex-home", type=Path, required=True)
    self_test = subcommands.add_parser(
        "global-self-test", help="run the offline global Router policy self-test"
    )
    self_test.add_argument("--codex-home", type=Path, required=True)
    return root


def _result_payload(result: TransitionResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "revision": result.revision,
        "status": result.status,
        "next_stage": result.next_stage,
        "stage_packet_path": (
            str(result.stage_packet_path) if result.stage_packet_path else None
        ),
        "idempotent": result.idempotent,
        "projection_warnings": list(result.projection_warnings),
    }


def _print_json(value: dict[str, Any], *, stream=sys.stdout) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), file=stream)


def _global_status_payload(status: GlobalStatus) -> dict[str, Any]:
    blockers = status.live_activation_blockers or LIVE_ACTIVATION_BLOCKERS
    deferred = status.deferred_acceptance_evidence or DEFERRED_ACCEPTANCE_EVIDENCE
    return {
        "state": status.state,
        "installation_dir": str(status.installation_dir),
        "hook_configured": status.hook_configured,
        "agents_managed": status.agents_managed,
        "luna_agent_configured": status.luna_agent_configured,
        "config_valid": status.config_valid,
        "identity_material_valid": status.identity_material_valid,
        "hook_trust": status.hook_trust,
        "new_session_required": status.new_session_required,
        "compatibility": status.compatibility,
        "compatibility_reason": status.compatibility_reason,
        "luna_execution_mode": status.luna_execution_mode,
        "router_design": status.router_design,
        "live_activation": status.live_activation,
        "live_activation_blockers": list(blockers),
        "deferred_acceptance_evidence": list(deferred),
    }


def _print_state_error(error: RouterStateError) -> int:
    _print_json(
        {
            "status": "error",
            "code": error.code,
            "message": str(error)[:200],
            "run_id": error.run_id,
            "stage": error.stage,
            "revision": error.revision,
        },
        stream=sys.stderr,
    )
    return error.exit_code


def _read_utf8(path: Path, description: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RouterStateError(
            "invalid-input", f"{description} must be a readable UTF-8 file"
        ) from error


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    raw = _read_utf8(path, description)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RouterStateError("invalid-input", f"{description} must contain valid JSON") from error
    if not isinstance(value, dict):
        raise RouterStateError("invalid-input", f"{description} must contain a JSON object")
    return value


def _read_stage_packet() -> str:
    raw = sys.stdin.buffer.read(MAX_HOOK_INPUT_BYTES + 1)
    if len(raw) > MAX_HOOK_INPUT_BYTES:
        raise RouterStateError("invalid-input", "K1 packet exceeds the hook input limit")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RouterStateError("invalid-input", "K1 packet must be UTF-8") from error


def _validate_structured_packet_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RouterStateError("invalid-input", f"{field} must be non-empty text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise RouterStateError("invalid-input", f"{field} must be valid UTF-8") from error
    if len(encoded) > MAX_HOOK_INPUT_BYTES:
        raise RouterStateError("invalid-input", f"{field} exceeds the input limit")
    return value


def _validated_structured_packet_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise RouterStateError("invalid-input", f"{field} is invalid")
    return [_validate_structured_packet_text(item, field) for item in value]


def _stage_k1_fields(args: argparse.Namespace) -> dict[str, object]:
    packet_id = _validate_structured_packet_text(args.packet_id, "packet_id")
    objective = _validate_structured_packet_text(args.objective, "objective")
    working_directory = _validate_structured_packet_text(
        args.working_directory, "working_directory"
    )
    if not Path(working_directory).is_absolute():
        raise RouterStateError("invalid-input", "working_directory must be absolute")
    intended_write_scope = _validated_structured_packet_list(
        args.intended_write_scope, "intended_write_scope"
    )
    authorizations = _validated_structured_packet_list(
        args.explicit_side_effect_authorization,
        "explicit_side_effect_authorizations",
    )
    success_criteria = _validated_structured_packet_list(
        args.success_criterion, "success_criteria"
    )
    stop_conditions = _validated_structured_packet_list(
        args.stop_condition, "stop_conditions"
    )
    secret, _config = _load_installation(args.installation_dir)
    snapshot = luna_control.read_snapshot(args.installation_dir, secret, args.session_id)
    if snapshot is None:
        raise RouterStateError("invalid-input", "current task is unavailable")
    try:
        packet_wire = build_luna_packet(
            packet_id=packet_id,
            generation=snapshot.packet_generation + 1,
            objective=objective,
            working_directory=working_directory,
            intended_write_scope=intended_write_scope,
            explicit_side_effect_authorizations=authorizations,
            success_criteria=success_criteria,
            stop_conditions=stop_conditions,
        )
        staged = luna_control.stage_authority_packet(
            args.installation_dir,
            secret,
            args.session_id,
            root_turn_id=args.root_turn_id,
            capability=args.capability,
            packet_wire=packet_wire,
        )
    except ProtocolError as error:
        raise RouterStateError("invalid-input", "structured K1 packet is invalid") from error
    return {
        "status": "staged",
        "packet_id": packet_id,
        "generation": staged.packet_generation + 1,
    }


def _role_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "local_sol": {
            "requested_model": args.local_model,
            "requested_reasoning": args.local_reasoning,
        },
        "web_sol": {
            "model_claimed": args.web_model,
            "reasoning_claimed": args.web_reasoning,
            "verification": "operator_attested",
        },
        "luna": {
            "requested_model": args.luna_model,
            "requested_reasoning": args.luna_reasoning,
        },
    }


def _run_legacy(args: argparse.Namespace) -> int:
    router = Router(
        adapters=adapters_for_mode(args.adapter_mode),
        state_root=args.state_dir,
        timeout_seconds=args.timeout,
        adapter_mode=args.adapter_mode,
    )
    try:
        outcome = router.run(args.task)
    except RouterRunError as error:
        _print_json(
            {
                "status": "failed",
                "code": error.code,
                "stage": error.stage,
                "error": error.summary,
                "run_id": error.run_id,
                "run_dir": str(error.run_dir),
            },
            stream=sys.stderr,
        )
        return 1
    print(outcome.final_result)
    return 0


def main(argv=None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command == "run":
            return _run_legacy(args)
        if args.command.startswith("hook-"):
            output = handle_hook_event(read_hook_event(sys.stdin.buffer), args.installation_dir)
            _print_json(output)
            return 0
        if args.command == "stage-k1":
            secret, _config = _load_installation(args.installation_dir)
            packet_wire = _read_stage_packet()
            snapshot = luna_control.stage_authority_packet(
                args.installation_dir,
                secret,
                args.session_id,
                root_turn_id=args.root_turn_id,
                capability=args.capability,
                packet_wire=packet_wire,
            )
            try:
                packet = parse_luna_packet(packet_wire)
            except ProtocolError as error:
                raise RouterStateError("invalid-input", "K1 packet is invalid") from error
            _print_json(
                {
                    "status": "staged",
                    "generation": snapshot.packet_generation + 1,
                    "packet_id": packet["packet_id"],
                }
            )
            return 0
        if args.command == "stage-k1-fields":
            _print_json(_stage_k1_fields(args))
            return 0
        if args.command == "global-install":
            global_result = global_install(
                codex_home=args.codex_home,
                state_root=args.state_dir,
                codex_binary=args.codex_bin,
                defaults=_role_config(args),
            )
            _print_json(_global_status_payload(global_result))
            return 0
        if args.command == "global-status":
            _print_json(_global_status_payload(global_status(args.codex_home)))
            return 0
        if args.command == "global-uninstall":
            _print_json(_global_status_payload(global_uninstall(args.codex_home)))
            return 0
        if args.command == "global-self-test":
            _print_json(global_self_test(args.codex_home))
            return 0
        if args.command == "start":
            result = start_run(
                state_root=args.state_dir,
                task=args.task,
                driver_context_id=args.driver_context_id,
                role_config=_role_config(args),
                codex_binary=args.codex_bin,
            )
        elif args.command == "submit-stage":
            result = submit_stage(
                state_root=args.state_dir,
                run_id=args.run_id,
                driver_context_id=args.driver_context_id,
                stage=args.stage,
                expected_revision=args.expected_revision,
                packet_digest_value=args.packet_digest,
                content=_read_utf8(args.output_file, "output file"),
                execution=_read_json_object(args.execution_file, "execution file"),
            )
        elif args.command == "fail-stage":
            result = fail_stage(
                state_root=args.state_dir,
                run_id=args.run_id,
                driver_context_id=args.driver_context_id,
                stage=args.stage,
                expected_revision=args.expected_revision,
                packet_digest_value=args.packet_digest,
                failure=_read_json_object(args.error_file, "error file"),
                execution=_read_json_object(args.execution_file, "execution file"),
            )
        else:
            result = get_status(state_root=args.state_dir, run_id=args.run_id)
    except RouterStateError as error:
        return _print_state_error(error)
    _print_json(_result_payload(result))
    return 0
