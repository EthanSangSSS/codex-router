"""Version-sensitive Codex compatibility layer around the stable installer core."""
from __future__ import annotations

from contextlib import contextmanager
import json
import tomllib
from typing import Any, Iterator, Mapping

from . import global_install as _core


LUNA_EXECUTION_MODE = "hard_mode_no_process"


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
    with _rendering_adapter():
        return _core.global_install(*args, **kwargs)


def global_status(*args, **kwargs):
    with _rendering_adapter():
        return _core.global_status(*args, **kwargs)


def global_uninstall(*args, **kwargs):
    with _rendering_adapter():
        return _core.global_uninstall(*args, **kwargs)


def global_self_test(*args, **kwargs):
    with _rendering_adapter():
        return _core.global_self_test(*args, **kwargs)


# Narrow private aliases used by focused adapter tests. Transaction internals remain in core.
_luna_agent_bytes = luna_agent_bytes
_luna_agent_matches = luna_agent_matches
