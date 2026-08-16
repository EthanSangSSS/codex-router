"""Version-sensitive Codex compatibility layer around the stable installer core."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import tomllib
from typing import Any, Iterator, Mapping

from . import global_install as _core
from .types import GlobalStatus


LUNA_EXECUTION_MODE = "hard_mode_no_process"
COMPATIBLE = "COMPATIBLE"
INCOMPATIBLE = "INCOMPATIBLE"
UNKNOWN = "UNKNOWN_REQUIRES_CAPABILITY_CHECK"


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
        "developer_instructions": _core._LUNA_DEVELOPER_INSTRUCTIONS,
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
        "shell_tool = false\n"
        "unified_exec = false\n"
        "\n[features.code_mode]\n"
        "enabled = false\n"
    )
    encoded = rendered.encode("utf-8")
    try:
        parsed = tomllib.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise _core._error(
            "conflict", "generated Luna agent configuration is invalid"
        ) from error
    expected = {
        **values,
        "agents": {"enabled": False},
        "features": {
            "multi_agent": False,
            "shell_tool": False,
            "unified_exec": False,
            "code_mode": {"enabled": False},
        },
    }
    if parsed != expected:
        raise _core._error(
            "conflict", "generated Luna agent configuration is unstable"
        )
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
        return (
            UNKNOWN,
            "primary config.toml could not be safely interpreted for compatibility",
        )
    if not isinstance(value, dict):
        return (UNKNOWN, "primary configuration shape is unverified")
    agents = value.get("agents")
    features = value.get("features")
    agents = agents if isinstance(agents, Mapping) else {}
    features = features if isinstance(features, Mapping) else {}

    if agents.get("enabled") is False:
        return (INCOMPATIBLE, "primary agents.enabled=false disables Router Luna management")
    if features.get("multi_agent") is False:
        return (
            INCOMPATIBLE,
            "primary features.multi_agent=false disables Router Luna management",
        )
    if features.get("hooks") is False:
        return (INCOMPATIBLE, "primary features.hooks=false disables Router Hooks")

    if (
        agents.get("enabled") is True
        and features.get("multi_agent") is True
        and features.get("hooks") is True
    ):
        return (
            COMPATIBLE,
            "required primary agents, multi-agent, and Hook capabilities are explicitly enabled",
        )
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


@contextmanager
def _rendering_adapter() -> Iterator[None]:
    """Temporarily inject V2 rendering without rewriting the transaction core."""
    old_bytes = _core._luna_agent_bytes
    old_matches = _core._luna_agent_matches
    _core._luna_agent_bytes = luna_agent_bytes
    _core._luna_agent_matches = luna_agent_matches
    try:
        yield
    finally:
        _core._luna_agent_bytes = old_bytes
        _core._luna_agent_matches = old_matches


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


# Narrow private aliases used by focused adapter tests. Transaction internals remain in core.
_luna_agent_bytes = luna_agent_bytes
_luna_agent_matches = luna_agent_matches
