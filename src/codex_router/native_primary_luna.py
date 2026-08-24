from __future__ import annotations

import json
import tomllib

from . import global_install as _core


NATIVE_INSTALL_DIRECTORY_NAME = ".codex-native-primary-luna-v1"
NATIVE_INSTALL_STATE_PROTOCOL = "codex-native-primary-luna/install-state/v1"
NATIVE_AGENTS_BEGIN = "# BEGIN CODEX NATIVE PRIMARY LUNA V1"
NATIVE_AGENTS_END = "# END CODEX NATIVE PRIMARY LUNA V1"

_LUNA_DESCRIPTION = (
    "A disposable native execution subagent for substantial local engineering "
    "delegated by PRIMARY."
)

_LUNA_DEVELOPER_INSTRUCTIONS = """You are Luna, a disposable native execution subagent of PRIMARY.
Execute the delegated task in the current Codex workspace using the normal native sandbox, approvals, and exposed tools.
You may inspect/search/read files; edit/create/delete task-related files; run shell/project tooling; build/test/lint/typecheck; run Playwright/Cypress/headless E2E; debug; refactor; retry; verify; and inspect local Git status/diff/log when relevant.
Do not spawn descendants or another Codex runtime. Do not intentionally daemonize persistent background work.
Do not perform unrelated destructive actions. Do not commit, push, mutate PRs, deploy/publish, communicate externally, mutate cloud resources, or perform system-level installation unless the delegated user objective explicitly requires that action and native platform controls permit/approve it.
Return concise implementation evidence, tests run, blockers, and remaining risks to PRIMARY."""


def render_primary_block() -> str:
    return f"""{NATIVE_AGENTS_BEGIN}
You are PRIMARY: the persistent planner, coordinator, reviewer, and final responder.
Use the native `luna_worker` execution subagent for substantial local engineering when useful; keep simple answers, planning, review, interactive browser/user-session UI work, and the final response in PRIMARY.
If the user explicitly asks not to use Luna for the current turn, do not spawn Luna.
Playwright, Cypress, headless browser tests, local E2E, and browser-code debugging are local engineering and may be delegated to Luna.
Use the native spawn surface actually exposed by the runtime. Do not invent unsupported spawn fields. Prefer one fresh Luna for one delegated execution task; do not rely on child-memory persistence, followup, resume, polling, or a Router protocol.
If native Luna spawn is unavailable or fails, continue the user's task locally when normal Codex tools allow it; delegation failure alone is not a reason to stop the task.
After Luna returns, inspect its evidence/results as needed and own the final answer.
{NATIVE_AGENTS_END}"""


def render_luna_agent_bytes(*, model: str, reasoning: str) -> bytes:
    if not isinstance(model, str) or not model.strip():
        raise _core._error("invalid-input", "Luna model configuration is invalid")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise _core._error("invalid-input", "Luna reasoning configuration is invalid")
    values = {
        "name": "luna_worker",
        "description": _LUNA_DESCRIPTION,
        "model": model,
        "model_reasoning_effort": reasoning,
        "developer_instructions": _LUNA_DEVELOPER_INSTRUCTIONS,
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
        "multi_agent_v2 = false\n"
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
        "features": {"multi_agent": False, "multi_agent_v2": False},
    }
    if parsed != expected:
        raise _core._error(
            "conflict", "generated Luna agent configuration is unstable"
        )
    return encoded


def _managed_primary_bytes() -> bytes:
    return (render_primary_block() + "\n").encode("utf-8")


def _install_primary_block(original: bytes | None) -> bytes:
    if original is not None and not isinstance(original, bytes):
        raise _core._error("conflict", "AGENTS.md original content is invalid")
    existing = b"" if original is None else original
    try:
        text = existing.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _core._error("conflict", "AGENTS.md is not valid UTF-8") from error
    if NATIVE_AGENTS_BEGIN in text or NATIVE_AGENTS_END in text:
        raise _core._error("conflict", "AGENTS.md Native markers are ambiguous")
    managed = _managed_primary_bytes()
    if not existing:
        return managed
    return existing + b"\n\n" + managed


def _strip_primary_block(current: bytes) -> bytes | None:
    if not isinstance(current, bytes):
        raise _core._error("conflict", "AGENTS.md content is invalid")
    try:
        text = current.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _core._error("conflict", "AGENTS.md is not valid UTF-8") from error
    if text.count(NATIVE_AGENTS_BEGIN) != 1 or text.count(NATIVE_AGENTS_END) != 1:
        raise _core._error("conflict", "AGENTS.md Native markers are ambiguous")
    managed = _managed_primary_bytes()
    if current == managed:
        return None
    if not current.endswith(managed):
        raise _core._error("conflict", "AGENTS.md Native block was modified")
    prefix = current[: -len(managed)]
    if not prefix.endswith(b"\n\n"):
        raise _core._error("conflict", "AGENTS.md Native boundary is invalid")
    return prefix[:-2]
