import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


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
        ):
            self.assertTrue(path.is_file(), path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)

        uninstalled = self.uninstall()

        self.assertEqual(uninstalled.state, "uninstalled")
        self.assertEqual(hooks_path.read_bytes(), hooks_original)
        self.assertEqual(agents_path.read_bytes(), agents_original)
        self.assertEqual(stat.S_IMODE(hooks_path.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(agents_path.stat().st_mode), 0o644)
        self.assertTrue(install_dir.is_dir())

    def test_absent_user_files_are_removed_on_uninstall_and_evidence_remains(self):
        self.install()
        hooks_path = self.codex_home / "hooks.json"
        agents_path = self.codex_home / "AGENTS.md"
        self.assertTrue(hooks_path.is_file())
        self.assertTrue(agents_path.is_file())

        self.uninstall()

        self.assertFalse(hooks_path.exists())
        self.assertFalse(agents_path.exists())
        self.assertTrue((self.codex_home / ".codex-router-policy-v1").is_dir())

    def test_repeated_install_and_uninstall_are_idempotent(self):
        first = self.install()
        hooks_once = (self.codex_home / "hooks.json").read_bytes()
        agents_once = (self.codex_home / "AGENTS.md").read_bytes()

        second = self.install()

        self.assertEqual(second.state, "installed")
        self.assertEqual((self.codex_home / "hooks.json").read_bytes(), hooks_once)
        self.assertEqual((self.codex_home / "AGENTS.md").read_bytes(), agents_once)
        hooks = json.loads(hooks_once)
        self.assertEqual(len(hooks["hooks"]["UserPromptSubmit"]), 1)
        self.assertEqual((first.hook_configured, second.hook_configured), (True, True))

        self.assertEqual(self.uninstall().state, "uninstalled")
        self.assertEqual(self.uninstall().state, "uninstalled")

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
        self.assertNotIn("secret", installed.stdout.lower())

        status = self.cli("global-status", "--codex-home", str(self.codex_home))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["state"], "installed")

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


if __name__ == "__main__":
    unittest.main()
