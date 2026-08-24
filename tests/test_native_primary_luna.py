from __future__ import annotations

import tomllib
import unittest

from codex_router.native_primary_luna import (
    NATIVE_AGENTS_BEGIN,
    NATIVE_AGENTS_END,
    NATIVE_INSTALL_DIRECTORY_NAME,
    NATIVE_INSTALL_STATE_PROTOCOL,
    _install_primary_block,
    _strip_primary_block,
    render_luna_agent_bytes,
    render_primary_block,
)
from codex_router.state import RouterStateError


EXPECTED_LUNA_DESCRIPTION = (
    "A disposable native execution subagent for substantial local engineering "
    "delegated by PRIMARY."
)

EXPECTED_LUNA_INSTRUCTIONS = """You are Luna, a disposable native execution subagent of PRIMARY.
Execute the delegated task in the current Codex workspace using the normal native sandbox, approvals, and exposed tools.
You may inspect/search/read files; edit/create/delete task-related files; run shell/project tooling; build/test/lint/typecheck; run Playwright/Cypress/headless E2E; debug; refactor; retry; verify; and inspect local Git status/diff/log when relevant.
Do not spawn descendants or another Codex runtime. Do not intentionally daemonize persistent background work.
Do not perform unrelated destructive actions. Do not commit, push, mutate PRs, deploy/publish, communicate externally, mutate cloud resources, or perform system-level installation unless the delegated user objective explicitly requires that action and native platform controls permit/approve it.
Return concise implementation evidence, tests run, blockers, and remaining risks to PRIMARY."""


class NativeContractRenderingTests(unittest.TestCase):
    def test_native_identity_constants_are_distinct_from_router_install(self):
        self.assertEqual(
            NATIVE_INSTALL_DIRECTORY_NAME, ".codex-native-primary-luna-v1"
        )
        self.assertEqual(
            NATIVE_INSTALL_STATE_PROTOCOL,
            "codex-native-primary-luna/install-state/v1",
        )
        self.assertEqual(
            NATIVE_AGENTS_BEGIN, "# BEGIN CODEX NATIVE PRIMARY LUNA V1"
        )
        self.assertEqual(NATIVE_AGENTS_END, "# END CODEX NATIVE PRIMARY LUNA V1")

    def test_primary_block_contains_native_orchestration_and_no_router_ceremony(self):
        block = render_primary_block()
        required = (
            "PRIMARY: the persistent planner, coordinator, reviewer, and final responder",
            "substantial local engineering when useful",
            "explicitly asks not to use Luna",
            "do not spawn Luna",
            "interactive browser/user-session UI work",
            "Playwright, Cypress, headless browser tests",
            "may be delegated to Luna",
            "native Luna spawn is unavailable or fails",
            "continue the user's task locally",
            "After Luna returns",
            "own the final answer",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, block)
        for forbidden in (
            "K1",
            "generation lease",
            "K1_STAGE_COMMAND",
            "request-file",
            "bootstrap capability",
            "HMAC",
            "sensitive_detected",
            "route/direct/bypass",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, block)
        self.assertEqual(block.count(NATIVE_AGENTS_BEGIN), 1)
        self.assertEqual(block.count(NATIVE_AGENTS_END), 1)

    def test_luna_toml_is_exact_native_executor_profile(self):
        parsed = tomllib.loads(
            render_luna_agent_bytes(
                model="gpt-5.6-luna", reasoning="max"
            ).decode("utf-8")
        )
        self.assertEqual(
            parsed,
            {
                "name": "luna_worker",
                "description": EXPECTED_LUNA_DESCRIPTION,
                "model": "gpt-5.6-luna",
                "model_reasoning_effort": "max",
                "developer_instructions": EXPECTED_LUNA_INSTRUCTIONS,
                "agents": {"enabled": False},
                "features": {"multi_agent": False, "multi_agent_v2": False},
            },
        )
        instructions = parsed["developer_instructions"]
        for phrase in (
            "inspect/search/read files",
            "edit/create/delete task-related files",
            "build/test/lint/typecheck",
            "Playwright/Cypress/headless E2E",
            "Do not spawn descendants",
            "another Codex runtime",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, instructions)
        for forbidden in ("K1", "generation", "bootstrap", "request-file"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, instructions)


class NativePrimaryBlockBoundaryTests(unittest.TestCase):
    def test_install_and_strip_round_trip_absent_or_existing_agents(self):
        managed = (render_primary_block() + "\n").encode("utf-8")
        self.assertEqual(_install_primary_block(None), managed)
        self.assertIsNone(_strip_primary_block(managed))

        original = b"# Existing\n"
        installed = _install_primary_block(original)
        self.assertEqual(installed, original + b"\n\n" + managed)
        self.assertEqual(_strip_primary_block(installed), original)

    def test_install_rejects_existing_native_markers(self):
        for original in (
            (NATIVE_AGENTS_BEGIN + "\n").encode("utf-8"),
            (NATIVE_AGENTS_END + "\n").encode("utf-8"),
        ):
            with self.subTest(original=original):
                with self.assertRaises(RouterStateError):
                    _install_primary_block(original)

    def test_strip_fails_closed_on_ambiguous_or_modified_boundaries(self):
        exact = (render_primary_block() + "\n").encode("utf-8")
        cases = (
            exact + exact,
            exact.replace(
                b"After Luna returns", b"After a modified Luna returns", 1
            ),
            exact.replace(NATIVE_AGENTS_END.encode("utf-8"), b"", 1),
            exact + b"unrelated trailing bytes\n",
        )
        for current in cases:
            with self.subTest(current=current[-80:]):
                with self.assertRaises(RouterStateError):
                    _strip_primary_block(current)


if __name__ == "__main__":
    unittest.main()
