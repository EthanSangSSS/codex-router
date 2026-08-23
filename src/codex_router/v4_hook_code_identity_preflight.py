"""Fail closed when the future Hook Python resolves a stale Router policy.

The managed Hook executes ``sys.executable -E -P -m codex_router``. That
isolates it from the current working tree and environment, so a source checkout
can otherwise generate hooks that later import an older site-packages build.
This overlay extends the existing subprocess preflight with V4 route identity
plus explicit DIRECT/BYPASS probes against a private disposable installation.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Mapping


_INSTALLED = False


def _private_probe_installation(
    core: Any,
    lease_control: Any,
    installation_dir: Path,
    root: Path,
) -> Path:
    probe = root / core.INSTALL_DIRECTORY_NAME
    probe.mkdir(mode=0o700)
    probe.chmod(0o700)
    core._atomic_write(
        probe / "config.json",
        core._read_private_file(installation_dir / "config.json"),
    )
    core._atomic_write(
        probe / core._IDENTITY_FILE_NAME,
        core._read_private_file(
            installation_dir / core._IDENTITY_FILE_NAME,
            maximum_bytes=32,
        ),
    )
    lease_control.activate_installation(probe)
    return probe


def _probe_policy_identity(
    core: Any,
    lease_control: Any,
    arguments: list[str],
    *,
    installation_dir: Path,
) -> None:
    probes = (
        (
            "[CODEX_ROUTER_DIRECT]\n修改 Router",
            "direct",
            "explicit_one_turn_direct",
            None,
        ),
        (
            "仅本地执行\n修改 Router",
            "bypass",
            "explicit_one_turn_bypass",
            None,
        ),
        (
            "修改 Router identity probe",
            "route",
            "substantive_request",
            "generation_lease_v4",
        ),
    )
    with tempfile.TemporaryDirectory(prefix="codex-router-hook-preflight-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        probe_installation = _private_probe_installation(
            core,
            lease_control,
            Path(installation_dir),
            root,
        )
        probe_arguments = list(arguments)
        probe_arguments[-1] = str(probe_installation)

        for index, (
            prompt,
            expected_decision,
            expected_reason,
            expected_workflow,
        ) in enumerate(probes):
            session_id = f"synthetic-hook-identity-session-{index}"
            turn_id = f"synthetic-hook-identity-turn-{index}"
            output = core._invoke_hook_argv(
                probe_arguments,
                event={
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "prompt": prompt,
                    "cwd": str(root),
                },
                cwd=root,
            )
            context = core._self_test_context(output)
            encoded_output = core.canonical_json_bytes(output).decode("utf-8")
            if (
                context.get("protocol") != core.HOOK_CONTEXT_PROTOCOL
                or context.get("decision") != expected_decision
                or context.get("reason") != expected_reason
                or (
                    expected_workflow is not None
                    and context.get("workflow") != expected_workflow
                )
                or session_id in encoded_output
                or turn_id in encoded_output
                or prompt in encoded_output
            ):
                observed = "/".join(
                    str(context.get(field))[:80]
                    for field in ("decision", "reason", "workflow")
                )
                expected = "/".join(
                    str(value)[:80]
                    for value in (
                        expected_decision,
                        expected_reason,
                        expected_workflow,
                    )
                )
                raise core._error(
                    "conflict",
                    (
                        "Router hook command policy identity failed preflight "
                        f"probe={index} observed={observed} expected={expected}"
                    )[:240],
                )


def install(core: Any, lease_control: Any) -> None:
    """Extend the existing Hook preflight without changing installer targets."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_preflight = core._preflight_hook_handler

    def preflight(
        handler: Mapping[str, Any], *, installation_dir: Path, cwd: Path
    ) -> None:
        original_preflight(
            handler,
            installation_dir=installation_dir,
            cwd=cwd,
        )
        arguments = core._handler_argv(
            handler, expected_installation_dir=Path(installation_dir)
        )
        _probe_policy_identity(
            core,
            lease_control,
            arguments,
            installation_dir=Path(installation_dir),
        )

    core._preflight_hook_handler = preflight
    _INSTALLED = True
