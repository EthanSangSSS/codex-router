import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch


ROLE_CONFIG = {
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
REPO = Path(__file__).resolve().parents[1]


class GlobalInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir(mode=0o700)
        self.state_root = self.root / "router-runs"
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)

    def install(self):
        from codex_router.global_install import global_install

        return global_install(
            codex_home=self.codex_home,
            state_root=self.state_root,
            codex_binary=self.binary,
            defaults=ROLE_CONFIG,
        )

    def uninstall(self):
        from codex_router.global_install import global_uninstall

        return global_uninstall(self.codex_home)

    def status(self):
        from codex_router.global_install import global_status

        return global_status(self.codex_home)

    def reset_case(self, name):
        case_root = self.root / name
        self.codex_home = case_root / "codex-home"
        self.codex_home.mkdir(parents=True, mode=0o700)
        self.state_root = case_root / "router-runs"
        self.binary = case_root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)

    def crash_install_after_managed_write(self, write_number):
        import codex_router.global_install as global_install_module

        original_replace = global_install_module._replace_expected
        writes = 0

        def replace_then_crash(*args, **kwargs):
            nonlocal writes
            original_replace(*args, **kwargs)
            writes += 1
            if writes == write_number:
                raise KeyboardInterrupt("synthetic install interruption")

        with patch.object(
            global_install_module,
            "_replace_expected",
            side_effect=replace_then_crash,
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.install()

    def install_legacy_policy_fixture(self):
        import codex_router.global_install as global_install_module

        old_agents_block = (
            f"{global_install_module.AGENTS_BEGIN}\n"
            "Legacy Router policy before refresh.\n"
            f"{global_install_module.AGENTS_END}\n"
        )
        old_luna_instructions = "Legacy Luna developer instructions before refresh.\n"
        with patch.object(
            global_install_module, "AGENTS_BLOCK", old_agents_block
        ), patch.object(
            global_install_module,
            "_LUNA_DEVELOPER_INSTRUCTIONS",
            old_luna_instructions,
        ):
            installed = self.install()
        self.assertEqual(installed.state, "installed")
        return old_agents_block, old_luna_instructions

    def test_install_preserves_semantics_modes_and_exact_uninstall_bytes(self):
        hooks_path = self.codex_home / "hooks.json"
        agents_path = self.codex_home / "AGENTS.md"
        hooks_original = (
            b'{\n  "description" : "keep formatting",\n  "custom": {"keep": true},\n'
            b'  "hooks": {"SessionStart": [{"hooks": []}]}\n}\n'
        )
        agents_original = b"# Existing guidance\n\nKeep this byte-for-byte.\n"
        hooks_path.write_bytes(hooks_original)
        agents_path.write_bytes(agents_original)
        hooks_path.chmod(0o640)
        agents_path.chmod(0o644)
        config_toml = self.codex_home / "config.toml"
        override = self.codex_home / "AGENTS.override.md"
        config_toml.write_bytes(b"[features]\nhooks = true\n")
        override.write_bytes(b"existing override\n")

        installed = self.install()

        self.assertEqual(installed.state, "installed")
        self.assertTrue(installed.hook_configured)
        self.assertTrue(installed.agents_managed)
        self.assertTrue(installed.luna_agent_configured)
        self.assertEqual(installed.hook_trust, "requires-user-check")
        self.assertTrue(installed.new_session_required)
        hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertEqual(hooks["description"], "keep formatting")
        self.assertEqual(hooks["custom"], {"keep": True})
        self.assertEqual(len(hooks["hooks"]["SessionStart"]), 1)
        prompt_groups = hooks["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(prompt_groups), 1)
        handlers = prompt_groups[0]["hooks"]
        self.assertEqual(len(handlers), 1)
        handler = handlers[0]
        self.assertEqual(handler["type"], "command")
        self.assertTrue(handler["command"].startswith("/"))
        self.assertIn("codex-router-global-policy-v1", handler["statusMessage"])
        managed_agents = agents_path.read_text(encoding="utf-8")
        self.assertIn("`luna_worker`", managed_agents)
        for required_policy in (
            "primary Sol coordinator, highest ordinary execution authority",
            "Sol plans and decomposes",
            "Sol reviews results",
            "exactly one current-root-turn `luna_worker`",
            "primary Sol must retain the native multi-agent capability",
            "capacity exhaustion or another ordinary execution blocker returns control to Sol",
            "take over ordinary execution",
            "revoked or turn-mismatched historical Luna",
            "Web Sol is manual operator work",
            "Hook route is stateless with respect to legacy Router runs",
            "revokes Luna authorization before any best-effort cleanup",
        ):
            with self.subTest(required_policy=required_policy):
                self.assertIn(required_policy, managed_agents)
        for stale_policy in (
            "Capacity exhaustion does not authorize Sol takeover",
            "capacity exhaustion is never a takeover reason",
            "BLOCKED_LUNA_CAPACITY",
            "takes over writable execution only",
        ):
            with self.subTest(stale_policy=stale_policy):
                self.assertNotIn(stale_policy, managed_agents)
        self.assertNotIn("drive Local Sol -> Web Sol -> Luna", managed_agents)
        self.assertIn("packet id", managed_agents)
        self.assertIn("latest bounded packet", managed_agents)
        luna_path = self.codex_home / "agents" / "luna-worker.toml"
        luna = tomllib.loads(luna_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "name": luna["name"],
                "model": luna["model"],
                "model_reasoning_effort": luna["model_reasoning_effort"],
            },
            {
                "name": "luna_worker",
                "model": "gpt-5.6-luna",
                "model_reasoning_effort": "max",
            },
        )
        self.assertIsInstance(luna["description"], str)
        self.assertIsInstance(luna["developer_instructions"], str)
        with self.subTest(luna_contract="recursive delegation disabled"):
            self.assertIs(luna.get("agents", {}).get("enabled"), False)
        self.assertIn("default execution worker", luna["description"])
        for required_luna_policy in (
            "default bounded execution worker for one authorized Router root turn",
            "Never act on a packet from another turn",
            "New packets do not inherit previous write permissions",
            "Never create, spawn, fork, relay, resume, or delegate any child or descendant agent",
            "BLOCKED_LUNA_RECURSIVE_DELEGATION",
            "BLOCKED_LUNA_CODEX_RUNTIME",
            "BLOCKED_USER_INTERACTION_REQUIRED",
            "ordinary blocker prevents completion, stop and report evidence to Sol",
        ):
            with self.subTest(required_luna_policy=required_luna_policy):
                self.assertIn(required_luna_policy, luna["developer_instructions"])
        self.assertNotIn("persistent execution worker for each parent task", luna["developer_instructions"])
        self.assertNotIn("ordinary packets", luna["developer_instructions"])
        self.assertNotIn("sandbox_mode", luna)
        self.assertNotIn("approval_policy", luna)
        self.assertIs(luna.get("features", {}).get("multi_agent"), False)
        self.assertIs(luna.get("features", {}).get("multi_agent_v2"), False)
        self.assertIs(luna.get("features", {}).get("unified_exec"), False)
        self.assertIs(luna.get("features", {}).get("code_mode"), False)
        self.assertIs(luna.get("features", {}).get("code_mode_only"), False)
        self.assertIs(luna.get("features", {}).get("request_permissions_tool"), False)
        self.assertEqual(config_toml.read_bytes(), b"[features]\nhooks = true\n")
        self.assertEqual(override.read_bytes(), b"existing override\n")

        install_dir = self.codex_home / ".codex-router-policy-v1"
        self.assertEqual(stat.S_IMODE(install_dir.stat().st_mode), 0o700)
        identity_name = "installation-" + "sec" + "ret"
        for path in (
            install_dir / "config.json",
            install_dir / identity_name,
            install_dir / "install-state.json",
            install_dir / "backups" / "hooks.json.original",
            install_dir / "backups" / "agents.md.original",
            luna_path,
        ):
            self.assertTrue(path.is_file(), path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)

        uninstalled = self.uninstall()

        self.assertEqual(uninstalled.state, "uninstalled")
        self.assertEqual(hooks_path.read_bytes(), hooks_original)
        self.assertEqual(agents_path.read_bytes(), agents_original)
        self.assertEqual(stat.S_IMODE(hooks_path.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(agents_path.stat().st_mode), 0o644)
        self.assertFalse(luna_path.exists())
        self.assertTrue(install_dir.is_dir())

    def test_existing_luna_agent_and_unrelated_agents_are_preserved_and_restored(self):
        agents_dir = self.codex_home / "agents"
        agents_dir.mkdir(mode=0o750)
        luna_path = agents_dir / "luna-worker.toml"
        other_path = agents_dir / "keep.toml"
        original_luna = b'name = "personal_luna"\n'
        original_other = b'name = "keep"\n'
        luna_path.write_bytes(original_luna)
        other_path.write_bytes(original_other)
        luna_path.chmod(0o640)
        other_path.chmod(0o644)

        installed = self.install()

        self.assertTrue(installed.luna_agent_configured)
        self.assertNotEqual(luna_path.read_bytes(), original_luna)
        self.assertEqual(other_path.read_bytes(), original_other)
        self.assertEqual(stat.S_IMODE(other_path.stat().st_mode), 0o644)

        self.uninstall()

        self.assertEqual(luna_path.read_bytes(), original_luna)
        self.assertEqual(stat.S_IMODE(luna_path.stat().st_mode), 0o640)
        self.assertEqual(other_path.read_bytes(), original_other)

    def test_hook_command_is_isolated_and_preflighted_before_managed_writes(self):
        from codex_router.state import RouterStateError

        hooks_path = self.codex_home / "hooks.json"
        agents_path = self.codex_home / "AGENTS.md"
        hooks_path.write_bytes(b'{"keep":true}\n')
        agents_path.write_bytes(b"keep agents\n")
        hooks_path.chmod(0o640)
        agents_path.chmod(0o644)
        hooks_before = hooks_path.read_bytes()
        agents_before = agents_path.read_bytes()
        broken_python = self.root / "broken-python"
        broken_python.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
        broken_python.chmod(0o700)

        with patch("codex_router.global_install.sys.executable", str(broken_python)):
            with self.assertRaises(RouterStateError) as raised:
                self.install()

        self.assertEqual(raised.exception.code, "conflict")
        self.assertNotIn(str(broken_python), str(raised.exception))
        self.assertEqual(hooks_path.read_bytes(), hooks_before)
        self.assertEqual(agents_path.read_bytes(), agents_before)
        self.assertEqual(stat.S_IMODE(hooks_path.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(agents_path.stat().st_mode), 0o644)
        self.assertEqual(self.status().state, "partial")

    def test_installed_hook_uses_exact_absolute_isolated_python_command(self):
        self.install()

        hooks = json.loads(
            (self.codex_home / "hooks.json").read_text(encoding="utf-8")
        )
        handler = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        arguments = shlex.split(handler["command"])
        self.assertEqual(arguments[0], str(Path(sys.executable)))
        self.assertEqual(arguments[1:3], ["-E", "-P"])
        self.assertEqual(arguments[3:6], ["-m", "codex_router", "hook-user-prompt"])
        self.assertEqual(arguments[6], "--installation-dir")
        self.assertEqual(
            arguments[7],
            str(self.codex_home / ".codex-router-policy-v1"),
        )
        expected = {
            "UserPromptSubmit": "hook-user-prompt",
            "PreToolUse": "hook-pre-tool",
            "PostToolUse": "hook-post-tool",
            "PermissionRequest": "hook-permission-request",
            "Stop": "hook-stop",
            "SubagentStart": "hook-subagent-start",
            "SubagentStop": "hook-subagent-stop",
        }
        self.assertEqual(set(hooks["hooks"]).intersection(expected), set(expected))
        for event, command in expected.items():
            installed = hooks["hooks"][event][0]["hooks"][0]
            self.assertEqual(shlex.split(installed["command"])[5], command)

    def test_interrupted_install_resumes_after_each_managed_write(self):
        for write_number in (1, 2, 3):
            with self.subTest(write_number=write_number):
                self.reset_case(f"resume-after-{write_number}")
                hooks_path = self.codex_home / "hooks.json"
                agents_path = self.codex_home / "AGENTS.md"
                hooks_original = b'{"keep":"hooks"}\n'
                agents_original = b"keep agents\n"
                hooks_path.write_bytes(hooks_original)
                agents_path.write_bytes(agents_original)
                hooks_path.chmod(0o640)
                agents_path.chmod(0o644)

                self.crash_install_after_managed_write(write_number)

                self.assertEqual(self.status().state, "partial")
                resumed = self.install()
                self.assertEqual(resumed.state, "installed")
                self.assertNotEqual(hooks_path.read_bytes(), hooks_original)
                self.assertNotEqual(agents_path.read_bytes(), agents_original)
                self.assertEqual(self.uninstall().state, "uninstalled")
                self.assertEqual(hooks_path.read_bytes(), hooks_original)
                self.assertEqual(agents_path.read_bytes(), agents_original)
                self.assertEqual(stat.S_IMODE(hooks_path.stat().st_mode), 0o640)
                self.assertEqual(stat.S_IMODE(agents_path.stat().st_mode), 0o644)

    def test_interrupted_install_can_roll_back_without_completing(self):
        for write_number in (1, 2, 3):
            with self.subTest(write_number=write_number):
                self.reset_case(f"rollback-after-{write_number}")
                hooks_path = self.codex_home / "hooks.json"
                agents_path = self.codex_home / "AGENTS.md"
                hooks_original = b'{"keep":"hooks"}\n'
                agents_original = b"keep agents\n"
                hooks_path.write_bytes(hooks_original)
                agents_path.write_bytes(agents_original)
                hooks_path.chmod(0o640)
                agents_path.chmod(0o644)

                self.crash_install_after_managed_write(write_number)

                self.assertEqual(self.status().state, "partial")
                self.assertEqual(self.uninstall().state, "uninstalled")
                self.assertEqual(hooks_path.read_bytes(), hooks_original)
                self.assertEqual(agents_path.read_bytes(), agents_original)
                self.assertEqual(stat.S_IMODE(hooks_path.stat().st_mode), 0o640)
                self.assertEqual(stat.S_IMODE(agents_path.stat().st_mode), 0o644)

    def test_interrupted_install_recovery_refuses_concurrent_user_edit(self):
        hooks_path = self.codex_home / "hooks.json"
        agents_path = self.codex_home / "AGENTS.md"
        hooks_path.write_bytes(b'{"keep":"hooks"}\n')
        agents_path.write_bytes(b"keep agents\n")
        self.crash_install_after_managed_write(1)
        hooks_after_crash = hooks_path.read_bytes()
        agents_path.write_bytes(b"user edit after interruption\n")

        from codex_router.state import RouterStateError

        with self.assertRaises(RouterStateError) as install_error:
            self.install()
        self.assertEqual(install_error.exception.code, "conflict")
        self.assertEqual(hooks_path.read_bytes(), hooks_after_crash)
        self.assertEqual(agents_path.read_bytes(), b"user edit after interruption\n")

        with self.assertRaises(RouterStateError) as uninstall_error:
            self.uninstall()
        self.assertEqual(uninstall_error.exception.code, "conflict")
        self.assertEqual(hooks_path.read_bytes(), hooks_after_crash)
        self.assertEqual(agents_path.read_bytes(), b"user edit after interruption\n")

    def test_absent_user_files_are_removed_on_uninstall_and_evidence_remains(self):
        self.install()
        hooks_path = self.codex_home / "hooks.json"
        agents_path = self.codex_home / "AGENTS.md"
        self.assertTrue(hooks_path.is_file())
        self.assertTrue(agents_path.is_file())
        luna_path = self.codex_home / "agents" / "luna-worker.toml"
        self.assertTrue(luna_path.is_file())

        self.uninstall()

        self.assertFalse(hooks_path.exists())
        self.assertFalse(agents_path.exists())
        self.assertFalse(luna_path.exists())
        self.assertTrue((self.codex_home / ".codex-router-policy-v1").is_dir())

    def test_repeated_install_and_uninstall_are_idempotent(self):
        first = self.install()
        hooks_once = (self.codex_home / "hooks.json").read_bytes()
        agents_once = (self.codex_home / "AGENTS.md").read_bytes()
        luna_once = (self.codex_home / "agents" / "luna-worker.toml").read_bytes()

        second = self.install()

        self.assertEqual(second.state, "installed")
        self.assertEqual((self.codex_home / "hooks.json").read_bytes(), hooks_once)
        self.assertEqual((self.codex_home / "AGENTS.md").read_bytes(), agents_once)
        self.assertEqual(
            (self.codex_home / "agents" / "luna-worker.toml").read_bytes(),
            luna_once,
        )
        hooks = json.loads(hooks_once)
        self.assertEqual(len(hooks["hooks"]["UserPromptSubmit"]), 1)
        self.assertEqual((first.hook_configured, second.hook_configured), (True, True))

        self.assertEqual(self.uninstall().state, "uninstalled")
        self.assertEqual(self.uninstall().state, "uninstalled")

    def test_installed_policy_refresh_preserves_user_agents_content_and_restores_it(self):
        import codex_router.global_install as global_install_module

        agents_path = self.codex_home / "AGENTS.md"
        agents_original = b"# User guidance before refresh\nKeep this line.\n"
        agents_path.write_bytes(agents_original)
        agents_path.chmod(0o644)
        self.install_legacy_policy_fixture()

        user_agents = b"# User guidance after refresh\nKeep this edited line.\n"
        installed_agents = agents_path.read_bytes()
        marker = installed_agents.index(
            global_install_module.AGENTS_BEGIN.encode("utf-8")
        )
        agents_path.write_bytes(
            user_agents
            + b"\n"
            + installed_agents[marker:]
        )
        user_mode = stat.S_IMODE(agents_path.stat().st_mode)

        refreshed = self.install()

        self.assertEqual(refreshed.state, "installed")
        self.assertEqual(
            agents_path.read_bytes(),
            user_agents
            + b"\n"
            + global_install_module.AGENTS_BLOCK.encode("utf-8"),
        )
        self.assertIn(
            global_install_module.AGENTS_BLOCK.strip(),
            agents_path.read_text(encoding="utf-8"),
        )
        self.assertTrue(
            agents_path.read_text(encoding="utf-8").startswith(
                user_agents.decode("utf-8")
            )
        )
        luna = tomllib.loads(
            (self.codex_home / "agents" / "luna-worker.toml").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(
            global_install_module._LUNA_DEVELOPER_INSTRUCTIONS,
            luna["developer_instructions"],
        )
        state = json.loads(
            (
                self.codex_home
                / ".codex-router-policy-v1"
                / "install-state.json"
            ).read_text(encoding="utf-8")
        )
        for record in state["targets"].values():
            self.assertFalse(any(key.startswith("upgrade_") for key in record))

        self.assertEqual(self.uninstall().state, "uninstalled")
        self.assertEqual(agents_path.read_bytes(), user_agents)
        self.assertEqual(stat.S_IMODE(agents_path.stat().st_mode), user_mode)

    def test_installed_policy_refreshes_unchanged_targets_when_strategy_changes(self):
        import codex_router.global_install as global_install_module

        agents_path = self.codex_home / "AGENTS.md"
        agents_original = b"# Unchanged target original\n"
        agents_path.write_bytes(agents_original)
        self.install_legacy_policy_fixture()
        old_agents = agents_path.read_bytes()
        old_luna = (self.codex_home / "agents" / "luna-worker.toml").read_bytes()

        refreshed = self.install()

        self.assertEqual(refreshed.state, "installed")
        self.assertNotEqual(agents_path.read_bytes(), old_agents)
        self.assertIn(
            global_install_module.AGENTS_BLOCK.strip(),
            agents_path.read_text(encoding="utf-8"),
        )
        self.assertNotIn(
            "Legacy Router policy before refresh.",
            agents_path.read_text(encoding="utf-8"),
        )
        luna_path = self.codex_home / "agents" / "luna-worker.toml"
        self.assertNotEqual(luna_path.read_bytes(), old_luna)
        luna = tomllib.loads(luna_path.read_text(encoding="utf-8"))
        self.assertIn(
            global_install_module._LUNA_DEVELOPER_INSTRUCTIONS,
            luna["developer_instructions"],
        )

        self.assertEqual(self.uninstall().state, "uninstalled")
        self.assertEqual(agents_path.read_bytes(), agents_original)
        self.assertFalse(luna_path.exists())

    def test_refresh_rejects_non_reversible_agents_separator_boundary(self):
        from codex_router.state import RouterStateError

        agents_path = self.codex_home / "AGENTS.md"
        agents_original = b"# Separator original\n"
        agents_path.write_bytes(agents_original)
        self.install_legacy_policy_fixture()
        installed_agents = agents_path.read_bytes()
        marker = installed_agents.index(b"# BEGIN CODEX ROUTER GLOBAL POLICY V1")
        # The old original ends in a newline, but this edited prefix provides
        # only that one newline before the old Router block. Re-appending the
        # block with the canonical installer rule would require two newlines.
        agents_path.write_bytes(b"# Edited prefix\n" + installed_agents[marker:])
        hooks_before = (self.codex_home / "hooks.json").read_bytes()
        agents_before = agents_path.read_bytes()
        luna_path = self.codex_home / "agents" / "luna-worker.toml"
        luna_before = luna_path.read_bytes()
        state_path = self.codex_home / ".codex-router-policy-v1" / "install-state.json"
        state_before = state_path.read_bytes()

        with self.assertRaises(RouterStateError) as raised:
            self.install()

        self.assertEqual(raised.exception.code, "conflict")
        self.assertEqual((self.codex_home / "hooks.json").read_bytes(), hooks_before)
        self.assertEqual(agents_path.read_bytes(), agents_before)
        self.assertEqual(luna_path.read_bytes(), luna_before)
        self.assertEqual(state_path.read_bytes(), state_before)

    def test_interrupted_installed_policy_refresh_resumes_and_uninstalls_exactly(self):
        agents_path = self.codex_home / "AGENTS.md"
        agents_path.write_bytes(b"# Refresh interruption user content\n")
        agents_path.chmod(0o640)
        self.install_legacy_policy_fixture()
        user_agents = b"# Refresh interruption edited content\n"
        installed_agents = agents_path.read_bytes()
        marker = installed_agents.index(b"# BEGIN CODEX ROUTER GLOBAL POLICY V1")
        agents_path.write_bytes(user_agents + b"\n" + installed_agents[marker:])
        user_mode = stat.S_IMODE(agents_path.stat().st_mode)

        self.crash_install_after_managed_write(1)

        self.assertEqual(self.status().state, "partial")
        resumed = self.install()
        self.assertEqual(resumed.state, "installed")
        self.assertEqual(self.uninstall().state, "uninstalled")
        self.assertEqual(agents_path.read_bytes(), user_agents)
        self.assertEqual(stat.S_IMODE(agents_path.stat().st_mode), user_mode)

    def test_interrupted_installed_policy_refresh_can_uninstall_without_resume(self):
        agents_path = self.codex_home / "AGENTS.md"
        agents_path.write_bytes(b"# Refresh rollback user content\n")
        agents_path.chmod(0o640)
        self.install_legacy_policy_fixture()
        user_agents = b"# Refresh rollback edited content\n"
        installed_agents = agents_path.read_bytes()
        marker = installed_agents.index(b"# BEGIN CODEX ROUTER GLOBAL POLICY V1")
        agents_path.write_bytes(user_agents + b"\n" + installed_agents[marker:])
        user_mode = stat.S_IMODE(agents_path.stat().st_mode)
        luna_path = self.codex_home / "agents" / "luna-worker.toml"

        self.crash_install_after_managed_write(1)

        self.assertEqual(self.status().state, "partial")
        uninstalled = self.uninstall()
        self.assertEqual(uninstalled.state, "uninstalled")
        self.assertEqual(agents_path.read_bytes(), user_agents)
        self.assertEqual(stat.S_IMODE(agents_path.stat().st_mode), user_mode)
        self.assertFalse(luna_path.exists())
        state = json.loads(
            (
                self.codex_home
                / ".codex-router-policy-v1"
                / "install-state.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(state["phase"], "uninstalled")
        for record in state["targets"].values():
            self.assertFalse(any(key.startswith("upgrade_") for key in record))

    def test_installed_user_edit_without_strategy_change_still_fails_closed(self):
        from codex_router.state import RouterStateError

        agents_path = self.codex_home / "AGENTS.md"
        agents_path.write_bytes(b"# Stable strategy user content\n")
        self.install()
        installed_agents = agents_path.read_bytes()
        marker = installed_agents.index(b"# BEGIN CODEX ROUTER GLOBAL POLICY V1")
        agents_path.write_bytes(
            b"# Stable strategy user edit\n\n" + installed_agents[marker:]
        )
        before_state = (
            self.codex_home
            / ".codex-router-policy-v1"
            / "install-state.json"
        ).read_bytes()

        with self.assertRaises(RouterStateError) as raised:
            self.install()

        self.assertEqual(raised.exception.code, "conflict")
        self.assertEqual(
            (
                self.codex_home
                / ".codex-router-policy-v1"
                / "install-state.json"
            ).read_bytes(),
            before_state,
        )

    def test_installed_policy_refresh_rejects_tampered_old_management_targets(self):
        import codex_router.global_install as global_install_module
        from codex_router.state import RouterStateError

        for target in ("agents", "luna"):
            with self.subTest(target=target):
                self.reset_case(f"refresh-tamper-{target}")
                agents_path = self.codex_home / "AGENTS.md"
                agents_path.write_bytes(b"# Tamper test user content\n")
                luna_path = self.codex_home / "agents" / "luna-worker.toml"
                self.install_legacy_policy_fixture()
                hooks_before = (self.codex_home / "hooks.json").read_bytes()
                agents_before = agents_path.read_bytes()
                luna_before = luna_path.read_bytes()
                state_before = (
                    self.codex_home
                    / ".codex-router-policy-v1"
                    / "install-state.json"
                ).read_bytes()

                if target == "agents":
                    agents_path.write_bytes(
                        agents_before.replace(
                            b"Legacy Router policy before refresh.",
                            b"Tampered Router policy before refresh.",
                        )
                    )
                else:
                    luna_path.write_bytes(
                        luna_before.replace(
                            b"Legacy Luna developer instructions before refresh.",
                            b"Tampered Luna developer instructions before refresh.",
                        )
                    )

                hooks_before_attempt = (self.codex_home / "hooks.json").read_bytes()
                agents_before_attempt = agents_path.read_bytes()
                luna_before_attempt = luna_path.read_bytes()
                with self.assertRaises(RouterStateError) as raised:
                    self.install()

                self.assertEqual(raised.exception.code, "conflict")
                self.assertEqual(
                    (self.codex_home / "hooks.json").read_bytes(),
                    hooks_before_attempt,
                )
                self.assertEqual(agents_path.read_bytes(), agents_before_attempt)
                self.assertEqual(luna_path.read_bytes(), luna_before_attempt)
                self.assertEqual(
                    (
                        self.codex_home
                        / ".codex-router-policy-v1"
                        / "install-state.json"
                    ).read_bytes(),
                    state_before,
                )

    def test_malformed_symlink_and_conflicting_markers_fail_without_overwrite(self):
        from codex_router.state import RouterStateError

        hooks_path = self.codex_home / "hooks.json"
        agents_path = self.codex_home / "AGENTS.md"
        cases = ("malformed", "symlink", "agent-marker", "hook-marker")

        for case in cases:
            with self.subTest(case=case):
                for path in (hooks_path, agents_path):
                    if path.is_symlink() or path.exists():
                        path.unlink()
                target = self.root / f"target-{case}"
                if target.exists():
                    target.unlink()
                if case == "malformed":
                    hooks_path.write_bytes(b"{not json")
                elif case == "symlink":
                    target.write_bytes(b"{}")
                    hooks_path.symlink_to(target)
                elif case == "agent-marker":
                    hooks_path.write_bytes(b"{}")
                    agents_path.write_text(
                        "# BEGIN CODEX ROUTER GLOBAL POLICY V1\nconflict\n",
                        encoding="utf-8",
                    )
                else:
                    hooks_path.write_text(
                        json.dumps(
                            {
                                "hooks": {
                                    "UserPromptSubmit": [
                                        {
                                            "hooks": [
                                                {
                                                    "type": "command",
                                                    "command": "conflict",
                                                    "statusMessage": "codex-router-global-policy-v1",
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        ),
                        encoding="utf-8",
                    )
                hooks_before = hooks_path.readlink() if hooks_path.is_symlink() else hooks_path.read_bytes()
                agents_before = agents_path.read_bytes() if agents_path.exists() else None

                with self.assertRaises(RouterStateError):
                    self.install()

                hooks_after = hooks_path.readlink() if hooks_path.is_symlink() else hooks_path.read_bytes()
                agents_after = agents_path.read_bytes() if agents_path.exists() else None
                self.assertEqual(hooks_after, hooks_before)
                self.assertEqual(agents_after, agents_before)
                self.assertFalse((self.codex_home / ".codex-router-policy-v1").exists())

    def cli(self, *arguments):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPO / "src")
        return subprocess.run(
            [sys.executable, "-m", "codex_router", *arguments],
            cwd=REPO,
            env=environment,
            text=True,
            capture_output=True,
        )

    def test_cli_install_status_and_uninstall_use_bounded_json(self):
        installed = self.cli(
            "global-install",
            "--codex-home",
            str(self.codex_home),
            "--state-dir",
            str(self.state_root),
            "--codex-bin",
            str(self.binary),
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        installed_payload = json.loads(installed.stdout)
        self.assertEqual(installed_payload["state"], "installed")
        self.assertEqual(installed_payload["hook_trust"], "requires-user-check")
        self.assertTrue(installed_payload["new_session_required"])
        self.assertTrue(installed_payload["luna_agent_configured"])
        self.assertNotIn("secret", installed.stdout.lower())

        status = self.cli("global-status", "--codex-home", str(self.codex_home))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["state"], "installed")
        self.assertTrue(json.loads(status.stdout)["luna_agent_configured"])

        uninstalled = self.cli(
            "global-uninstall", "--codex-home", str(self.codex_home)
        )
        self.assertEqual(uninstalled.returncode, 0, uninstalled.stderr)
        self.assertEqual(json.loads(uninstalled.stdout)["state"], "uninstalled")

        config = json.loads(
            (
                self.codex_home
                / ".codex-router-policy-v1"
                / "config.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(config["role_config"]["local_sol"]["requested_reasoning"], "max")
        self.assertEqual(config["role_config"]["web_sol"]["reasoning_claimed"], "xhigh")
        self.assertEqual(config["role_config"]["luna"]["requested_reasoning"], "max")

    def test_uninstalled_legacy_two_target_state_reinstalls_with_luna_agent(self):
        self.install()
        self.uninstall()
        state_path = (
            self.codex_home / ".codex-router-policy-v1" / "install-state.json"
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["targets"].pop("agents/luna-worker.toml")
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        state_path.chmod(0o600)

        reinstalled = self.install()

        self.assertEqual(reinstalled.state, "installed")
        self.assertTrue(reinstalled.luna_agent_configured)
        self.assertTrue((self.codex_home / "agents" / "luna-worker.toml").is_file())

    def test_modified_luna_agent_blocks_uninstall_before_any_restore(self):
        hooks_path = self.codex_home / "hooks.json"
        agents_path = self.codex_home / "AGENTS.md"
        hooks_path.write_bytes(b"{}\n")
        agents_path.write_bytes(b"original agents\n")
        self.install()
        installed_hooks = hooks_path.read_bytes()
        installed_agents = agents_path.read_bytes()
        luna_path = self.codex_home / "agents" / "luna-worker.toml"
        luna_path.write_text('name = "changed"\n', encoding="utf-8")

        from codex_router.state import RouterStateError

        with self.assertRaises(RouterStateError) as raised:
            self.uninstall()

        self.assertEqual(raised.exception.code, "conflict")
        self.assertEqual(hooks_path.read_bytes(), installed_hooks)
        self.assertEqual(agents_path.read_bytes(), installed_agents)
        self.assertEqual(luna_path.read_text(encoding="utf-8"), 'name = "changed"\n')

    def test_modified_installed_file_blocks_uninstall_before_any_restore(self):
        from codex_router.state import RouterStateError

        hooks_path = self.codex_home / "hooks.json"
        agents_path = self.codex_home / "AGENTS.md"
        hooks_path.write_bytes(b"{}\n")
        agents_original = b"original agents\n"
        agents_path.write_bytes(agents_original)
        self.install()
        installed_agents = agents_path.read_bytes()
        hooks_path.write_bytes(b'{"concurrent":true}\n')

        with self.assertRaises(RouterStateError) as raised:
            self.uninstall()

        self.assertEqual(raised.exception.code, "conflict")
        self.assertEqual(hooks_path.read_bytes(), b'{"concurrent":true}\n')
        self.assertEqual(agents_path.read_bytes(), installed_agents)
        self.assertNotEqual(agents_path.read_bytes(), agents_original)
        self.assertEqual(self.status().state, "modified")

    def test_tampered_backup_path_is_rejected_without_reading_or_restoring_targets(self):
        from codex_router.state import RouterStateError

        hooks_path = self.codex_home / "hooks.json"
        agents_path = self.codex_home / "AGENTS.md"
        hooks_path.write_bytes(b"{}\n")
        agents_path.write_bytes(b"original\n")
        self.install()
        hooks_installed = hooks_path.read_bytes()
        agents_installed = agents_path.read_bytes()
        state_path = (
            self.codex_home
            / ".codex-router-policy-v1"
            / "install-state.json"
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["targets"]["hooks.json"]["backup"] = "../AGENTS.md"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaises(RouterStateError) as raised:
            self.uninstall()

        self.assertEqual(raised.exception.code, "conflict")
        self.assertEqual(hooks_path.read_bytes(), hooks_installed)
        self.assertEqual(agents_path.read_bytes(), agents_installed)

    def test_invalid_inputs_and_symlinked_home_fail_before_writes(self):
        from codex_router.global_install import global_install
        from codex_router.state import RouterStateError

        home_link = self.root / "home-link"
        home_link.symlink_to(self.codex_home, target_is_directory=True)
        invalid_defaults = {"local_sol": {}}
        cases = (
            {"codex_home": home_link, "defaults": ROLE_CONFIG},
            {"codex_home": self.codex_home, "defaults": invalid_defaults},
            {"codex_home": self.codex_home, "defaults": ROLE_CONFIG, "state_root": Path("relative")},
        )

        for changes in cases:
            with self.subTest(changes=sorted(changes)):
                arguments = {
                    "codex_home": self.codex_home,
                    "state_root": self.state_root,
                    "codex_binary": self.binary,
                    "defaults": ROLE_CONFIG,
                }
                arguments.update(changes)
                with self.assertRaises(RouterStateError):
                    global_install(**arguments)
                self.assertFalse((self.codex_home / ".codex-router-policy-v1").exists())

    def test_symlinked_agents_directory_is_rejected_without_external_writes(self):
        from codex_router.state import RouterStateError

        external_agents = self.root / "external-agents"
        external_agents.mkdir()
        sentinel = external_agents / "keep.toml"
        sentinel.write_bytes(b'name = "keep"\n')
        (self.codex_home / "agents").symlink_to(
            external_agents, target_is_directory=True
        )

        with self.assertRaises(RouterStateError) as raised:
            self.install()

        self.assertEqual(raised.exception.code, "conflict")
        self.assertEqual(sentinel.read_bytes(), b'name = "keep"\n')
        self.assertFalse((external_agents / "luna-worker.toml").exists())
        self.assertFalse((self.codex_home / ".codex-router-policy-v1").exists())


if __name__ == "__main__":
    unittest.main()
