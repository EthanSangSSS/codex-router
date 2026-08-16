"""Pure supported-surface command intent classification for Luna shell use."""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shlex
from typing import Sequence


@dataclass(frozen=True)
class CommandDecision:
    disposition: str
    reason: str


_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*\Z", re.DOTALL)
_SHELLS = {"sh", "bash", "zsh"}
_TRANSPARENT_WRAPPERS = {"command", "exec", "nohup", "setsid"}
_INTERPRETERS = {"python", "python3", "node", "nodejs", "ruby", "perl"}
_DYNAMIC_EXEC_MARKERS = (
    "subprocess",
    "os.system",
    "popen",
    "child_process",
    "spawn(",
    "exec(",
)
_MAX_DEPTH = 6


def _decision(disposition: str, reason: str) -> CommandDecision:
    return CommandDecision(disposition, reason)


def _basename(token: str) -> str:
    return os.path.basename(token).lower()


def _is_codex_executable(token: str, codex_binary: str) -> bool:
    if _basename(token) in {"codex", "codex.exe"}:
        return True
    if not os.path.isabs(token):
        return False
    return os.path.normcase(os.path.realpath(token)) == os.path.normcase(
        os.path.realpath(codex_binary)
    )


def _strip_options(tokens: Sequence[str], start: int = 1) -> list[str]:
    index = start
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return list(tokens[index + 1 :])
        if not token.startswith("-") or token == "-":
            return list(tokens[index:])
        index += 1
    return []


def _after_env(tokens: Sequence[str]) -> list[str]:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            break
        if token in {"-u", "--unset"}:
            index += 2
            continue
        if token.startswith("--unset=") or token in {
            "-i",
            "--ignore-environment",
            "-0",
            "--null",
        }:
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        if _ASSIGNMENT.fullmatch(token):
            index += 1
            continue
        break
    return list(tokens[index:])


def _shell_script(tokens: Sequence[str]) -> str | None:
    for index, token in enumerate(tokens[1:], start=1):
        if token == "--":
            break
        if token.startswith("-") and "c" in token[1:]:
            if index + 1 < len(tokens):
                return tokens[index + 1]
            return ""
    return None


def _classify_tokens(
    tokens: Sequence[str], *, codex_binary: str, depth: int
) -> CommandDecision:
    if depth > _MAX_DEPTH:
        return _decision("FAIL_CLOSED", "command wrapper depth exceeds supported surface")
    if not tokens:
        return _decision("FAIL_CLOSED", "empty command")

    executable = tokens[0]
    name = _basename(executable)
    if _is_codex_executable(executable, codex_binary):
        return _decision("BLOCK", "effective executable is Codex")

    if name == "env":
        remainder = _after_env(tokens)
        if not remainder:
            return _decision("ALLOW", "environment inspection without child command")
        return _classify_tokens(
            remainder, codex_binary=codex_binary, depth=depth + 1
        )

    if name in _TRANSPARENT_WRAPPERS:
        remainder = _strip_options(tokens)
        if not remainder:
            return _decision("ALLOW", "wrapper has no child executable")
        return _classify_tokens(
            remainder, codex_binary=codex_binary, depth=depth + 1
        )

    if name in _SHELLS:
        script = _shell_script(tokens)
        if script is None:
            return _decision(
                "UNVERIFIED",
                "shell script/file execution is outside supported static surface",
            )
        if not script:
            return _decision("FAIL_CLOSED", "shell -c wrapper is missing its command")
        return classify_shell_command(
            script, codex_binary=codex_binary, _depth=depth + 1
        )

    if name == "script":
        for index, token in enumerate(tokens[1:], start=1):
            if token in {"-c", "--command"} and index + 1 < len(tokens):
                return classify_shell_command(
                    tokens[index + 1],
                    codex_binary=codex_binary,
                    _depth=depth + 1,
                )
        return _decision(
            "UNVERIFIED", "PTY/script wrapper is outside supported static surface"
        )

    if name == "find" and "-exec" in tokens:
        index = tokens.index("-exec") + 1
        if index < len(tokens) and _is_codex_executable(tokens[index], codex_binary):
            return _decision("BLOCK", "find -exec launches Codex")
        return _decision(
            "UNVERIFIED", "find -exec execution is outside supported static surface"
        )

    if name == "xargs":
        remainder = _strip_options(tokens)
        if remainder and _is_codex_executable(remainder[0], codex_binary):
            return _decision("BLOCK", "xargs launches Codex")
        return _decision(
            "UNVERIFIED", "xargs execution is outside supported static surface"
        )

    if name in _INTERPRETERS:
        for index, token in enumerate(tokens[1:], start=1):
            if token in {"-c", "-e"} and index + 1 < len(tokens):
                program = tokens[index + 1].lower()
                if any(marker in program for marker in _DYNAMIC_EXEC_MARKERS):
                    return _decision(
                        "UNVERIFIED",
                        "dynamic interpreter process execution is not statically proven",
                    )
                return _decision(
                    "ALLOW",
                    "interpreter snippet has no recognized process-execution intent",
                )

    return _decision(
        "ALLOW", "ordinary command does not resolve to Codex on supported surface"
    )


def classify_shell_command(
    command: str, *, codex_binary: str, _depth: int = 0
) -> CommandDecision:
    if not isinstance(command, str) or not command.strip():
        return _decision("FAIL_CLOSED", "command must be non-empty text")
    if not isinstance(codex_binary, str) or not os.path.isabs(codex_binary):
        return _decision(
            "FAIL_CLOSED", "configured Codex binary must be an absolute path"
        )
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return _decision(
            "FAIL_CLOSED", "command cannot be parsed on the supported shell surface"
        )
    return _classify_tokens(tokens, codex_binary=codex_binary, depth=_depth)
