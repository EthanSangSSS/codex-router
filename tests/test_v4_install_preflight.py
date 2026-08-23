import json
import tempfile
import unittest
from pathlib import Path

from codex_router import global_install as global_install_core
from codex_router import global_install_adapter
from codex_router.state import RouterStateError


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


class V4InstallPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir(mode=0o700)
        self.state_root = self.root / "router-runs"
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)

    def _install(self, defaults):
        return global_install_adapter.global_install(
            codex_home=self.codex_home,
            state_root=self.state_root,
            codex_binary=self.binary,
            defaults=defaults,
        )

    def _protected_files(self):
        managed = self.codex_home / global_install_core.INSTALL_DIRECTORY_NAME
        return (
            self.codex_home / "hooks.json",
            self.codex_home / "AGENTS.md",
            self.codex_home / "agents" / "luna-worker.toml",
            managed / "config.json",
            managed / "install-state.json",
        )

    def test_corrupt_existing_v4_journal_blocks_refresh_before_any_managed_write(self):
        installed = self._install(ROLE_CONFIG)
        self.assertEqual(installed.state, "installed")
        managed = self.codex_home / global_install_core.INSTALL_DIRECTORY_NAME
        journal = managed / "lease-control-v4-0.json"
        corrupt = b'{"protocol":"wrong","sessions":{}}\n'
        journal.write_bytes(corrupt)
        journal.chmod(0o600)

        protected = self._protected_files()
        before = {path: path.read_bytes() for path in protected}
        changed = json.loads(json.dumps(ROLE_CONFIG))
        changed["luna"]["requested_reasoning"] = "high"

        with self.assertRaises(RouterStateError):
            self._install(changed)

        self.assertEqual(journal.read_bytes(), corrupt)
        self.assertEqual(
            {path: path.read_bytes() for path in protected},
            before,
        )

    def test_symlinked_existing_v4_journal_blocks_refresh_before_any_managed_write(self):
        installed = self._install(ROLE_CONFIG)
        self.assertEqual(installed.state, "installed")
        managed = self.codex_home / global_install_core.INSTALL_DIRECTORY_NAME
        journal = managed / "lease-control-v4-0.json"
        journal.unlink()
        outside = self.root / "outside-v4.json"
        outside.write_text(
            '{"protocol":"codex-router/lease-control/v4.0","sessions":{}}\n',
            encoding="utf-8",
        )
        outside.chmod(0o600)
        journal.symlink_to(outside)

        protected = self._protected_files()
        before = {path: path.read_bytes() for path in protected}
        changed = json.loads(json.dumps(ROLE_CONFIG))
        changed["luna"]["requested_reasoning"] = "high"

        with self.assertRaises(RouterStateError):
            self._install(changed)

        self.assertTrue(journal.is_symlink())
        self.assertEqual(
            {path: path.read_bytes() for path in protected},
            before,
        )


if __name__ == "__main__":
    unittest.main()
