from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest

from codex_router.native_primary_luna import (
    NATIVE_AGENTS_BEGIN,
    NATIVE_AGENTS_END,
    NATIVE_INSTALL_DIRECTORY_NAME,
    NATIVE_INSTALL_STATE_PROTOCOL,
    NativeStatus,
    _install_primary_block,
    _strip_primary_block,
    native_install,
    native_status,
    native_uninstall,
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


class NativeInstallLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "codex-home"
        self.home.mkdir(mode=0o700)
        os.chmod(self.home, 0o700)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, relative: str, content: bytes, mode: int = 0o600) -> Path:
        path = self.home / relative
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(content)
        os.chmod(path, mode)
        return path

    def test_fresh_install_preserves_unrelated_files_and_records_exact_state(self):
        agents_original = b"# Existing guidance\n"
        hooks_original = json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "/usr/bin/true"}]}
                    ]
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        other_agent = b'name = "other"\n'
        self.write("AGENTS.md", agents_original, 0o644)
        self.write("hooks.json", hooks_original, 0o600)
        self.write("agents/other-agent.toml", other_agent, 0o600)

        status = native_install(self.home)

        self.assertIsInstance(status, NativeStatus)
        self.assertEqual(status.state, "installed")
        self.assertTrue(status.agents_managed)
        self.assertTrue(status.luna_agent_configured)
        self.assertFalse(status.router_hooks_present)
        self.assertTrue(status.new_session_required)
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_original)
        self.assertEqual(
            (self.home / "agents/other-agent.toml").read_bytes(), other_agent
        )
        installed_agents = (self.home / "AGENTS.md").read_bytes()
        self.assertTrue(installed_agents.startswith(agents_original))
        self.assertEqual(installed_agents.count(NATIVE_AGENTS_BEGIN.encode()), 1)
        self.assertEqual(installed_agents.count(NATIVE_AGENTS_END.encode()), 1)
        self.assertEqual(
            (self.home / "agents/luna-worker.toml").read_bytes(),
            render_luna_agent_bytes(model="gpt-5.6-luna", reasoning="max"),
        )
        self.assertEqual(native_status(self.home), status)

        state_path = (
            self.home
            / NATIVE_INSTALL_DIRECTORY_NAME
            / "install-state.json"
        )
        state = json.loads(state_path.read_bytes())
        self.assertEqual(set(state), {"protocol", "phase", "targets"})
        self.assertEqual(state["protocol"], NATIVE_INSTALL_STATE_PROTOCOL)
        self.assertEqual(state["phase"], "installed")
        self.assertEqual(set(state["targets"]), {"AGENTS.md", "agents/luna-worker.toml"})
        self.assertEqual(
            set(state["targets"]["AGENTS.md"]),
            {
                "existed",
                "original_sha256",
                "original_mode",
                "backup",
                "installed_block_sha256",
            },
        )
        self.assertEqual(
            set(state["targets"]["agents/luna-worker.toml"]),
            {
                "existed",
                "original_sha256",
                "original_mode",
                "backup",
                "installed_sha256",
                "installed_mode",
            },
        )

    def test_reinstall_is_idempotent_and_different_executor_fails_closed(self):
        self.write("AGENTS.md", b"existing\n", 0o644)
        first = native_install(self.home)
        agents_after_first = (self.home / "AGENTS.md").read_bytes()
        luna_after_first = (self.home / "agents/luna-worker.toml").read_bytes()

        second = native_install(self.home)

        self.assertEqual(first, second)
        self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_after_first)
        self.assertEqual(
            (self.home / "agents/luna-worker.toml").read_bytes(), luna_after_first
        )
        self.assertEqual(agents_after_first.count(NATIVE_AGENTS_BEGIN.encode()), 1)
        with self.assertRaisesRegex(RouterStateError, "uninstall"):
            native_install(self.home, luna_model="gpt-5.6-terra")
        self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_after_first)
        self.assertEqual(
            (self.home / "agents/luna-worker.toml").read_bytes(), luna_after_first
        )

    def test_uninstall_preserves_post_install_agents_prefix_and_unrelated_files(self):
        agents_original = b"# Existing guidance\n"
        hooks_original = b'{"hooks":{"SessionStart":[]}}\n'
        other_agent = b'name = "other"\n'
        self.write("AGENTS.md", agents_original, 0o644)
        self.write("hooks.json", hooks_original, 0o600)
        self.write("agents/other-agent.toml", other_agent, 0o600)
        native_install(self.home)
        installed_agents = (self.home / "AGENTS.md").read_bytes()
        user_edit = b"# User edit after install\n"
        (self.home / "AGENTS.md").write_bytes(user_edit + installed_agents)

        status = native_uninstall(self.home)

        self.assertEqual(status.state, "uninstalled")
        self.assertFalse(status.agents_managed)
        self.assertFalse(status.luna_agent_configured)
        self.assertFalse(status.new_session_required)
        self.assertEqual(
            (self.home / "AGENTS.md").read_bytes(), user_edit + agents_original
        )
        self.assertFalse((self.home / "agents/luna-worker.toml").exists())
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_original)
        self.assertEqual(
            (self.home / "agents/other-agent.toml").read_bytes(), other_agent
        )
        self.assertEqual(native_uninstall(self.home), status)

    def test_uninstall_restores_preexisting_luna_file_and_mode(self):
        original_luna = b'name = "user-luna"\n'
        self.write("AGENTS.md", b"existing\n", 0o644)
        luna = self.write("agents/luna-worker.toml", original_luna, 0o640)
        native_install(self.home)
        self.assertNotEqual(luna.read_bytes(), original_luna)

        native_uninstall(self.home)

        self.assertEqual(luna.read_bytes(), original_luna)
        self.assertEqual(luna.stat().st_mode & 0o777, 0o640)

    def test_modified_luna_blocks_uninstall_before_agents_change(self):
        self.write("AGENTS.md", b"existing\n", 0o644)
        native_install(self.home)
        agents_before = (self.home / "AGENTS.md").read_bytes()
        luna = self.home / "agents/luna-worker.toml"
        luna.write_bytes(b'user_modified = true\n')

        with self.assertRaisesRegex(RouterStateError, "Luna"):
            native_uninstall(self.home)

        self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_before)
        self.assertEqual(luna.read_bytes(), b'user_modified = true\n')

    def test_absent_status_does_not_claim_ownership(self):
        status = native_status(self.home)
        self.assertEqual(status.state, "absent")
        self.assertFalse(status.agents_managed)
        self.assertFalse(status.luna_agent_configured)
        self.assertFalse(status.new_session_required)


if __name__ == "__main__":
    unittest.main()
