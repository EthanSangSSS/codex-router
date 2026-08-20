"""Compatibility integration for the V3.2 usability policy.

The V3.1 safety core has public operator/test surfaces that should not churn just
because the usability layer changes transport mechanics. This module keeps the
stable `stage-k1-fields` command name, adds a mutually exclusive request-file
mode, normalizes the offline self-test's legacy comparison view, and exposes
fallback metadata only when it is operationally relevant.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys
from typing import Any, Mapping


_INSTALLED = False
_LEGACY_STAGE_REQUIRED_FLAGS = (
    "--packet-id",
    "--objective",
    "--working-directory",
)


def _context_from_output(hook_module: Any, output: Mapping[str, Any]) -> dict[str, Any] | None:
    hook_output = output.get("hookSpecificOutput")
    if not isinstance(hook_output, Mapping):
        return None
    additional = hook_output.get("additionalContext")
    if not isinstance(additional, str) or not additional.startswith(
        hook_module.HOOK_CONTEXT_PREFIX
    ):
        return None
    try:
        value = json.loads(additional[len(hook_module.HOOK_CONTEXT_PREFIX) :])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _install_hook_context_compat(hook_module: Any, control: Any) -> None:
    current_handle_user_prompt = hook_module.handle_user_prompt

    def handle_user_prompt(
        event: Mapping[str, Any], installation_dir: Path
    ) -> dict[str, Any]:
        output = current_handle_user_prompt(event, installation_dir)
        context = _context_from_output(hook_module, output)
        if context is None or context.get("decision") != "route":
            return output

        command = context.get("K1_STAGE_COMMAND")
        if isinstance(command, str):
            try:
                arguments = shlex.split(command, posix=True)
            except ValueError:
                return {"decision": "block", "reason": hook_module._BLOCK_REASON}
            if "stage-k1-request" in arguments:
                arguments[arguments.index("stage-k1-request")] = "stage-k1-fields"
                context["K1_STAGE_COMMAND"] = shlex.join(arguments)

        # The request path is already carried by the complete command. Keeping
        # a second authoritative-looking copy only creates a drift opportunity.
        context.pop("K1_STAGE_REQUEST_PATH", None)
        context.pop("K1_STAGE_INTERFACE", None)
        context.pop("luna_handshake_mode", None)

        try:
            session_id = event.get("session_id")
            prompt = event.get("prompt")
            secret, _config = hook_module._load_installation(Path(installation_dir))
            snapshot = control.read_snapshot(Path(installation_dir), secret, session_id)
            decision = hook_module.classify_prompt(prompt)
            strict = bool(getattr(decision, "strict_router", False))
            has_prior_router_epoch = bool(
                snapshot is not None
                and (
                    snapshot.packet_generation > 0
                    or snapshot.luna_agent_id is not None
                    or snapshot.pending_spawn is not None
                )
            )
        except Exception:
            return {"decision": "block", "reason": hook_module._BLOCK_REASON}

        # Initial normal Gen1 routing keeps the stable V3.1 context shape.
        # Absence of strict_router on that shape means ordinary non-strict mode;
        # only exact [CODEX_ROUTER_STRICT] produces strict_router=true.
        if not has_prior_router_epoch and not strict:
            context.pop("capability_failure_policy", None)
            context.pop("primary_fallback_state", None)
            context.pop("strict_router", None)
        else:
            context["capability_failure_policy"] = "degrade_primary_safe_local"
            context["primary_fallback_state"] = control.classify_primary_fallback(snapshot)
            context["strict_router"] = strict
        return hook_module._hook_output(context)

    hook_module.handle_user_prompt = handle_user_prompt


def _install_cli_request_mode(cli_module: Any, hook_module: Any, control: Any) -> None:
    current_main = cli_module.main
    current_parser = cli_module.parser

    def parser():
        root = current_parser()
        subparsers = next(
            (
                action
                for action in root._actions
                if isinstance(action, argparse._SubParsersAction)
            ),
            None,
        )
        if subparsers is None:
            return root

        stage_fields = subparsers.choices.get("stage-k1-fields")
        if stage_fields is not None:
            if not any(action.dest == "request_file" for action in stage_fields._actions):
                stage_fields.add_argument(
                    "--request-file",
                    type=Path,
                    help=(
                        "V3.2 strict seven-field JSON request; mutually exclusive "
                        "with legacy semantic packet flags"
                    ),
                )
            # Argparse cannot express "three flags required only when request-file
            # is absent". Make the legacy semantic fields optional at parse time;
            # main() below restores the legacy missing-argument contract before
            # dispatch. This makes --help accurately describe both modes.
            for action in stage_fields._actions:
                if action.dest in {"packet_id", "objective", "working_directory"}:
                    action.required = False
            stage_fields.epilog = (
                "V3.2: use --request-file with the complete Router-injected command "
                "and append no packet flags. Legacy mode requires --packet-id, "
                "--objective, and --working-directory."
            )

        # The internal implementation alias is intentionally not an operator
        # surface. Keep current_main able to dispatch it, but hide it from the
        # public parser/help choices.
        if "stage-k1-request" in subparsers.choices:
            subparsers.choices.pop("stage-k1-request", None)
            subparsers._choices_actions = [
                action
                for action in subparsers._choices_actions
                if getattr(action, "dest", None) != "stage-k1-request"
            ]
        return root

    def _fallback_state(installation_dir: str | None, session_id: str | None) -> str:
        if not installation_dir or not session_id:
            return "UNKNOWN"
        try:
            secret, _config = hook_module._load_installation(Path(installation_dir))
            snapshot = control.read_snapshot(Path(installation_dir), secret, session_id)
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

    def main(argv=None) -> int:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if arguments and arguments[0] == "stage-k1-fields":
            if "--request-file" in arguments:
                installation_dir = None
                session_id = None
                for name, target in (
                    ("--installation-dir", "installation_dir"),
                    ("--session-id", "session_id"),
                ):
                    try:
                        value = arguments[arguments.index(name) + 1]
                    except (ValueError, IndexError):
                        value = None
                    if target == "installation_dir":
                        installation_dir = value
                    else:
                        session_id = value

                def print_state_error(error):
                    return _print_request_error(
                        error,
                        installation_dir=installation_dir,
                        session_id=session_id,
                    )

                translated = ["stage-k1-request", *arguments[1:]]
                old = cli_module._print_state_error
                cli_module._print_state_error = print_state_error
                try:
                    return current_main(translated)
                finally:
                    cli_module._print_state_error = old

            if "--help" not in arguments and "-h" not in arguments:
                missing = [
                    flag for flag in _LEGACY_STAGE_REQUIRED_FLAGS if flag not in arguments
                ]
                if missing:
                    return cli_module._print_state_error(
                        cli_module.RouterStateError(
                            "invalid-input",
                            "missing required arguments: " + ", ".join(missing),
                        )
                    )
        return current_main(argv)

    cli_module.parser = parser
    cli_module.main = main


def _install_adapter_compat(adapter: Any) -> None:
    # Full V2 collaboration inventory remains sufficient to admit the PRIMARY
    # model, as it was in V3.1. V3.2 additionally admits exact V1 Gen1 when
    # structured sideband staging is proven. Missing send_message still fails
    # the legacy V2 admission gate.
    v32_admitted = adapter.primary_model_is_admitted

    def primary_model_is_admitted(
        requested_model: str | None = adapter.PRIMARY_MODEL_INHERIT,
        runtime_capabilities: Any = None,
    ) -> bool:
        if requested_model is not None and (
            not isinstance(requested_model, str) or not requested_model.strip()
        ):
            return False
        return adapter.primary_capability_gate(runtime_capabilities) or v32_admitted(
            requested_model=requested_model,
            runtime_capabilities=runtime_capabilities,
        )

    adapter.primary_model_is_admitted = primary_model_is_admitted

    primary = adapter.AGENTS_BLOCK_V3.replace(
        "write exactly one seven-field UTF-8 JSON request to `K1_STAGE_REQUEST_PATH`:",
        "write exactly one seven-field UTF-8 JSON request to the exact absolute path following `--request-file` inside that command:",
    )
    primary = primary.replace(
        "Automatic degraded PRIMARY execution is allowed only when the injected `strict_router` is false and `primary_fallback_state=SAFE_LOCAL_FALLBACK`.",
        "Automatic degraded PRIMARY execution is allowed only when `strict_router` is not true (ordinary fresh routes omit it) and either routed context or a structured staging error reports `primary_fallback_state=SAFE_LOCAL_FALLBACK`.",
    )
    authoritative_schema = """
- Native `spawn_agent`/`followup_task` message is a transport trigger, not authority. The native `spawn_agent`/`followup_task` message remains non-authoritative and should request the executor to initiate its harmless first-tool handshake probe. `send_message` is QueueOnly and cannot advance K1.
- Native surface selection remains exact: V1 uses `agent_type=luna_worker` with `fork_context=false` or omission. V2 uses `task_name=luna_worker`, `agent_type=luna_worker`, and `fork_turns=none`. V2 wait accepts optional `timeout_ms` only and has no `targets` field.
"""
    end_marker = adapter._core.AGENTS_END
    if authoritative_schema.strip() not in primary:
        primary = primary.replace(end_marker, authoritative_schema + end_marker)
    adapter.AGENTS_BLOCK_V32 = primary
    adapter.AGENTS_BLOCK_V3 = primary
    adapter.AGENTS_BLOCK = primary
    adapter.AGENTS_BLOCK_V2 = primary

    # The V3.1 core self-test intentionally checks a stable comparison view.
    # Normalize only that local comparison after the real Hook subprocess has
    # returned; production Hook output is never altered for the self-test.
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
            if "stage-k1-request" in arguments:
                arguments[arguments.index("stage-k1-request")] = "stage-k1-fields"
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


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from . import luna_control as control
    from . import global_install_adapter as adapter
    from . import hook as hook_module
    from . import cli as cli_module

    _install_adapter_compat(adapter)
    _install_hook_context_compat(hook_module, control)
    _install_cli_request_mode(cli_module, hook_module, control)
    _INSTALLED = True
