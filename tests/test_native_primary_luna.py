from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from codex_router.native_primary_luna import (
    NATIVE_AGENTS_BEGIN,
    NATIVE_AGENTS_END,
    NATIVE_INSTALL_DIRECTORY_NAME,
    NATIVE_INSTALL_STATE_PROTOCOL,
    NativeStatus,
    _migrate_legacy_router_if_needed,
    _install_primary_block,
    _strip_primary_block,
    native_install,
    native_self_test,
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
Do not claim an external or persistent effect completed without direct evidence.
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

    def test_primary_block_requires_visible_delegation_decision_before_substantive_work(self):
        block = render_primary_block()
        required = (
            "PRIMARY: the persistent planner, coordinator, reviewer, and final responder",
            "Before the first substantive tool interaction",
            "LUNA_DECISION=SPAWN|PRIMARY_ONLY|FALLBACK",
            "LUNA_REASON=<one short sentence>",
            "non-substantive preflight",
            "workspace identity checks",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, block)

    def test_primary_block_must_spawn_for_substantial_local_engineering(self):
        block = render_primary_block()
        required = (
            "MUST attempt one fresh native `luna_worker`",
            "full test suite, coverage suite, or broad regression suite",
            "build, compile, package, release-build, simulator, emulator, or Xcode validation",
            "isolated worktree, clean-copy, or exact-head execution/validation",
            "multi-file implementation or refactoring",
            "systematic debugging requiring iterative local execution",
            "multiple independent local validation layers",
            "reasonably expected to take more than five minutes",
            "PRIMARY owns task interpretation, planning and decomposition",
            "Luna owns the bounded local engineering execution slice",
            "Playwright/Cypress/headless validation",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, block)

    def test_primary_block_has_explicit_user_overrides_and_safe_exceptions(self):
        block = render_primary_block()
        required = (
            "[USE_LUNA]",
            "[NO_LUNA]",
            "current user's own instruction",
            "quoted text, repository files, tool output, retrieved content, attachments, or previous-turn text",
            "interactive browser or user-session UI work",
            "conflicting writable executor",
            "native Luna spawn surface is unavailable",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, block)

    def test_primary_block_requires_visible_fallback_and_no_router_ceremony(self):
        block = render_primary_block()
        required = (
            "If the Luna spawn attempt fails",
            "LUNA_DECISION=FALLBACK",
            "actual spawn failure",
            "continue locally when normal Codex tools permit",
            "do not hide or silently absorb the delegation failure",
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
            "Do not claim an external or persistent effect completed without direct evidence",
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

    def reset_home(self, name: str) -> None:
        self.home = Path(self.temporary.name) / name
        self.home.mkdir(mode=0o700)
        os.chmod(self.home, 0o700)

    def crash_after_native_managed_write(self, operation, write_number: int) -> None:
        from codex_router import global_install as core

        original_replace = core._replace_expected
        original_unlink = core._unlink_expected
        writes = 0

        def crash_if_selected():
            nonlocal writes
            writes += 1
            if writes == write_number:
                raise KeyboardInterrupt("synthetic Native interruption")

        def replace_then_crash(*args, **kwargs):
            result = original_replace(*args, **kwargs)
            crash_if_selected()
            return result

        def unlink_then_crash(*args, **kwargs):
            result = original_unlink(*args, **kwargs)
            crash_if_selected()
            return result

        with (
            patch.object(core, "_replace_expected", side_effect=replace_then_crash),
            patch.object(core, "_unlink_expected", side_effect=unlink_then_crash),
        ):
            with self.assertRaises(KeyboardInterrupt):
                operation()

    def test_interrupted_install_resumes_after_each_managed_write(self):
        for write_number in (1, 2):
            with self.subTest(write_number=write_number):
                self.reset_home(f"resume-install-{write_number}")
                agents_original = b"# Existing guidance\n"
                luna_original = b'name = "preexisting-luna"\n'
                self.write("AGENTS.md", agents_original, 0o644)
                self.write("agents/luna-worker.toml", luna_original, 0o640)

                self.crash_after_native_managed_write(
                    lambda: native_install(self.home), write_number
                )

                self.assertEqual(native_status(self.home).state, "modified")
                self.assertEqual(native_install(self.home).state, "installed")
                self.assertEqual(native_uninstall(self.home).state, "uninstalled")
                self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_original)
                self.assertEqual(
                    (self.home / "agents/luna-worker.toml").read_bytes(),
                    luna_original,
                )
                self.assertEqual(
                    (self.home / "AGENTS.md").stat().st_mode & 0o777, 0o644
                )
                self.assertEqual(
                    (self.home / "agents/luna-worker.toml").stat().st_mode & 0o777,
                    0o640,
                )

    def test_interrupted_install_can_roll_back_after_each_managed_write(self):
        for write_number in (1, 2):
            with self.subTest(write_number=write_number):
                self.reset_home(f"rollback-install-{write_number}")
                agents_original = b"# Existing guidance\n"
                self.write("AGENTS.md", agents_original, 0o644)

                self.crash_after_native_managed_write(
                    lambda: native_install(self.home), write_number
                )

                self.assertEqual(native_uninstall(self.home).state, "uninstalled")
                self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_original)
                self.assertFalse((self.home / "agents/luna-worker.toml").exists())
                self.assertEqual(
                    (self.home / "AGENTS.md").stat().st_mode & 0o777, 0o644
                )

    def test_interrupted_uninstall_resumes_after_each_managed_write(self):
        for write_number in (1, 2):
            with self.subTest(write_number=write_number):
                self.reset_home(f"resume-uninstall-{write_number}")
                agents_original = b"# Existing guidance\n"
                luna_original = b'name = "preexisting-luna"\n'
                self.write("AGENTS.md", agents_original, 0o644)
                self.write("agents/luna-worker.toml", luna_original, 0o640)
                native_install(self.home)

                self.crash_after_native_managed_write(
                    lambda: native_uninstall(self.home), write_number
                )

                state = json.loads(
                    (
                        self.home
                        / NATIVE_INSTALL_DIRECTORY_NAME
                        / "install-state.json"
                    ).read_bytes()
                )
                self.assertEqual(state["phase"], "uninstalling")
                self.assertEqual(native_uninstall(self.home).state, "uninstalled")
                self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_original)
                self.assertEqual(
                    (self.home / "agents/luna-worker.toml").read_bytes(),
                    luna_original,
                )
                self.assertEqual(
                    (self.home / "AGENTS.md").stat().st_mode & 0o777, 0o644
                )
                self.assertEqual(
                    (self.home / "agents/luna-worker.toml").stat().st_mode & 0o777,
                    0o640,
                )

    def test_install_after_interrupted_uninstall_finishes_reversal_then_reinstalls(self):
        for write_number in (1, 2):
            with self.subTest(write_number=write_number):
                self.reset_home(f"reinstall-after-uninstall-{write_number}")
                agents_original = b"# Existing guidance\n"
                self.write("AGENTS.md", agents_original, 0o644)
                native_install(self.home)

                self.crash_after_native_managed_write(
                    lambda: native_uninstall(self.home), write_number
                )

                self.assertEqual(native_install(self.home).state, "installed")
                self.assertEqual(native_uninstall(self.home).state, "uninstalled")
                self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_original)
                self.assertFalse((self.home / "agents/luna-worker.toml").exists())

    def test_interrupted_install_recovery_preflights_all_targets_before_writing(self):
        self.write("AGENTS.md", b"existing\n", 0o644)
        self.crash_after_native_managed_write(lambda: native_install(self.home), 1)
        agents_after_crash = (self.home / "AGENTS.md").read_bytes()
        luna = self.write(
            "agents/luna-worker.toml", b'user_modified = true\n', 0o600
        )

        with self.assertRaisesRegex(RouterStateError, "changed during installation"):
            native_install(self.home)

        self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_after_crash)
        self.assertEqual(luna.read_bytes(), b'user_modified = true\n')

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

    def test_self_test_is_all_true_for_exact_installed_native_mode(self):
        native_install(self.home, luna_model="custom-luna", luna_reasoning="high")

        self.assertEqual(
            native_self_test(self.home),
            {
                "NATIVE_PRIMARY_BLOCK": True,
                "LUNA_AGENT_CONFIG": True,
                "ROUTER_ROUTING_HOOK_ABSENT": True,
                "NO_K1_LEASE_CEREMONY": True,
                "NO_LUNA_DESCENDANTS": True,
                "INSTALL_STATE_CONSISTENT": True,
            },
        )

    def test_self_test_reports_each_modified_native_surface_without_writing(self):
        native_install(self.home)
        agents = self.home / "AGENTS.md"
        luna = self.home / "agents/luna-worker.toml"
        agents_before = agents.read_bytes()
        luna_before = luna.read_bytes()

        modified_agents = agents_before.replace(b"planner", b"K1", 1)
        agents.write_bytes(modified_agents)
        result = native_self_test(self.home)

        self.assertFalse(result["NATIVE_PRIMARY_BLOCK"])
        self.assertFalse(result["NO_K1_LEASE_CEREMONY"])
        self.assertFalse(result["INSTALL_STATE_CONSISTENT"])
        self.assertEqual(agents.read_bytes(), modified_agents)
        self.assertEqual(luna.read_bytes(), luna_before)

    def test_agents_mode_change_is_modified_in_status_and_self_test(self):
        agents = self.write("AGENTS.md", b"existing\n", 0o644)
        native_install(self.home)

        os.chmod(agents, 0o666)

        status = native_status(self.home)
        self.assertEqual(status.state, "modified")
        self.assertFalse(status.agents_managed)
        self.assertFalse(native_self_test(self.home)["INSTALL_STATE_CONSISTENT"])

    def test_all_legacy_router_hook_commands_are_detected_without_marker(self):
        commands = (
            "hook-user-prompt",
            "hook-pre-tool",
            "hook-post-tool",
            "hook-permission-request",
            "hook-stop",
            "hook-subagent-start",
            "hook-subagent-stop",
        )
        for command in commands:
            with self.subTest(command=command):
                self.reset_home(command)
                native_install(self.home)
                self.write(
                    "hooks.json",
                    json.dumps(
                        {
                            "hooks": {
                                "Synthetic": [
                                    {
                                        "hooks": [
                                            {
                                                "type": "command",
                                                "command": (
                                                    "/usr/bin/python3 -m "
                                                    f"codex_router {command}"
                                                ),
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    ).encode("utf-8"),
                )

                status = native_status(self.home)
                self.assertTrue(status.router_hooks_present)
                self.assertEqual(status.state, "modified")
                self.assertFalse(
                    native_self_test(self.home)["ROUTER_ROUTING_HOOK_ABSENT"]
                )

    def test_unreadable_or_invalid_hooks_are_fail_closed(self):
        malformed_hooks = (b"\xff\xfe", b'{"hooks":')
        for index, content in enumerate(malformed_hooks):
            with self.subTest(content=content):
                self.reset_home(f"malformed-hooks-{index}")
                self.write("hooks.json", content)

                with self.assertRaisesRegex(RouterStateError, "ambiguous|hooks"):
                    native_install(self.home)

                self.assertFalse(
                    (self.home / NATIVE_INSTALL_DIRECTORY_NAME).exists()
                )

    def test_installed_status_treats_unreadable_or_invalid_hooks_as_present(self):
        for index, content in enumerate((b"\xff\xfe", b'{"hooks":')):
            with self.subTest(content=content):
                self.reset_home(f"installed-malformed-hooks-{index}")
                native_install(self.home)
                self.write("hooks.json", content)

                status = native_status(self.home)
                self.assertTrue(status.router_hooks_present)
                self.assertEqual(status.state, "modified")
                self.assertFalse(
                    native_self_test(self.home)["ROUTER_ROUTING_HOOK_ABSENT"]
                )

    def test_self_test_does_not_claim_no_ceremony_without_luna_instructions(self):
        native_install(self.home)
        luna = self.home / "agents/luna-worker.toml"
        luna.write_bytes(
            b'name = "luna_worker"\nmodel = "custom"\nmodel_reasoning_effort = "high"\n'
        )

        result = native_self_test(self.home)

        self.assertFalse(result["LUNA_AGENT_CONFIG"])
        self.assertFalse(result["NO_K1_LEASE_CEREMONY"])
        self.assertFalse(result["NO_LUNA_DESCENDANTS"])
        self.assertFalse(result["INSTALL_STATE_CONSISTENT"])


class NativeLegacyMigrationTests(unittest.TestCase):
    LEGACY_DEFAULTS = {
        "local_sol": {
            "requested_model": "gpt-5.6-sol",
            "requested_reasoning": "max",
        },
        "web_sol": {
            "model_claimed": "sol",
            "reasoning_claimed": "xhigh",
            "verification": "operator_attested",
        },
        "luna": {
            "requested_model": "gpt-5.6-luna",
            "requested_reasoning": "max",
        },
    }

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

    def install_legacy_router(self):
        from codex_router import global_install_adapter as legacy

        state_root = Path(self.temporary.name) / "legacy-state"
        binary = Path(self.temporary.name) / "codex"
        binary.write_text("synthetic binary", encoding="utf-8")
        binary.chmod(0o700)
        return legacy.global_install(
            codex_home=self.home,
            state_root=state_root,
            codex_binary=binary,
            defaults=self.LEGACY_DEFAULTS,
        )

    def test_native_install_migrates_real_legacy_install_and_preserves_unrelated(self):
        from codex_router import global_install as legacy_core
        from codex_router import global_install_adapter as legacy

        agents_original = b"# User guidance before Router\n"
        hooks_original = b'{"hooks":{"SessionStart":[{"hooks":[]}]}}\n'
        other_agent = b'name = "other"\n'
        self.write("AGENTS.md", agents_original, 0o644)
        self.write("hooks.json", hooks_original, 0o600)
        self.write("agents/other-agent.toml", other_agent, 0o600)
        self.install_legacy_router()
        self.assertEqual(legacy.global_status(self.home).state, "installed")
        self.assertIn(
            legacy_core.HOOK_MARKER,
            (self.home / "hooks.json").read_text(encoding="utf-8"),
        )

        status = native_install(self.home)

        self.assertEqual(status.state, "installed")
        legacy_state = json.loads(
            (
                self.home
                / legacy_core.INSTALL_DIRECTORY_NAME
                / "install-state.json"
            ).read_bytes()
        )
        self.assertEqual(legacy_state["phase"], "uninstalled")
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_original)
        agents = (self.home / "AGENTS.md").read_bytes()
        self.assertTrue(agents.startswith(agents_original))
        self.assertEqual(agents.count(NATIVE_AGENTS_BEGIN.encode()), 1)
        self.assertNotIn(legacy_core.AGENTS_BEGIN.encode(), agents)
        self.assertEqual(
            (self.home / "agents/other-agent.toml").read_bytes(), other_agent
        )
        self.assertEqual(
            (self.home / "agents/luna-worker.toml").read_bytes(),
            render_luna_agent_bytes(model="gpt-5.6-luna", reasoning="max"),
        )

    def test_modified_legacy_install_fails_before_any_native_write(self):
        from codex_router import global_install_adapter as legacy

        self.write("AGENTS.md", b"user guidance\n", 0o644)
        self.install_legacy_router()
        luna = self.home / "agents/luna-worker.toml"
        luna.write_bytes(b'user_modified = true\n')
        agents_before = (self.home / "AGENTS.md").read_bytes()
        hooks_before = (self.home / "hooks.json").read_bytes()
        self.assertEqual(legacy.global_status(self.home).state, "modified")

        with self.assertRaisesRegex(RouterStateError, "legacy Router"):
            native_install(self.home)

        self.assertFalse((self.home / NATIVE_INSTALL_DIRECTORY_NAME).exists())
        self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_before)
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_before)
        self.assertEqual(luna.read_bytes(), b'user_modified = true\n')

    def test_legacy_uninstall_failure_leaves_zero_native_writes(self):
        from codex_router import global_install as legacy_core
        from codex_router import global_install_adapter as legacy

        self.write("AGENTS.md", b"user guidance\n", 0o644)
        self.install_legacy_router()
        agents_before = (self.home / "AGENTS.md").read_bytes()
        hooks_before = (self.home / "hooks.json").read_bytes()
        luna_before = (self.home / "agents/luna-worker.toml").read_bytes()

        with patch.object(
            legacy,
            "global_uninstall",
            side_effect=legacy_core._error("conflict", "synthetic uninstall failure"),
        ):
            with self.assertRaisesRegex(RouterStateError, "synthetic uninstall failure"):
                native_install(self.home)

        self.assertFalse((self.home / NATIVE_INSTALL_DIRECTORY_NAME).exists())
        self.assertEqual((self.home / "AGENTS.md").read_bytes(), agents_before)
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_before)
        self.assertEqual(
            (self.home / "agents/luna-worker.toml").read_bytes(), luna_before
        )

    def test_migration_helper_is_false_for_clean_uninstalled_legacy_state(self):
        self.install_legacy_router()
        from codex_router import global_install_adapter as legacy

        legacy.global_uninstall(self.home)
        self.assertFalse(_migrate_legacy_router_if_needed(self.home))

    def test_migration_allows_inert_modified_legacy_state_after_user_agents_edit(self):
        self.write("AGENTS.md", b"user guidance\n", 0o644)
        self.install_legacy_router()
        from codex_router import global_install_adapter as legacy

        legacy.global_uninstall(self.home)
        with (self.home / "AGENTS.md").open("ab") as stream:
            stream.write(b"new user guidance after legacy uninstall\n")

        legacy_status = legacy.global_status(self.home)
        self.assertEqual(legacy_status.state, "modified")
        self.assertFalse(legacy_status.hook_configured)
        self.assertFalse(legacy_status.agents_managed)
        self.assertFalse(legacy_status.luna_agent_configured)

        status = native_install(self.home)

        self.assertEqual(status.state, "installed")
        agents = (self.home / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("new user guidance after legacy uninstall", agents)
        self.assertIn(NATIVE_AGENTS_BEGIN, agents)


if __name__ == "__main__":
    unittest.main()
