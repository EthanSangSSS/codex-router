import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from codex_router import native_primary_luna as n
from codex_router.state import RouterStateError

class NativeV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir(mode=0o700)

    def legacy(self):
        with patch.object(n, "render_primary_block", n.render_legacy_primary_block), patch.object(n, "render_luna_agent_bytes", n.render_legacy_luna_agent_bytes):
            n.native_install(self.home)
        return json.loads((self.home / n.NATIVE_INSTALL_DIRECTORY_NAME / "install-state.json").read_text())

    def test_cost_routing_has_no_mandatory_trigger_or_ceremony(self):
        block = n.render_primary_block()
        self.assertIn("quota savings exceed coordination cost", block)
        self.assertNotIn("LUNA_DECISION=", block)
        self.assertNotIn("MUST attempt", block)
        self.assertIn("Web", block)
        self.assertIn("Company OS", block)

    def test_migrate_preserves_original_backups_and_adopts_reviewed_compatible_worker(self):
        old = self.legacy()
        worker = self.home / "agents/luna-worker.toml"
        worker.write_bytes(worker.read_bytes().replace(b"[agents]\nenabled = false\n", b""))
        digest = n._core._sha256(worker.read_bytes())
        before = worker.read_bytes()
        result = n.native_migrate_v2(self.home, reviewed_worker_sha256=digest)
        self.assertEqual(result.state, "installed")
        self.assertEqual(worker.read_bytes(), before)
        state = json.loads((self.home / n.NATIVE_INSTALL_DIRECTORY_NAME / "install-state.json").read_text())
        self.assertEqual(state["targets"]["AGENTS.md"]["original_sha256"], old["targets"]["AGENTS.md"]["original_sha256"])
        self.assertTrue(all(n.native_self_test(self.home).values()))
        self.assertEqual(n.native_migrate_v2(self.home).state, "installed")

    def test_unknown_worker_or_block_drift_refuses_without_changes(self):
        self.legacy()
        worker = self.home / "agents/luna-worker.toml"
        worker.write_bytes(worker.read_bytes() + b'\nunknown = "user value"\n')
        before = {str(p):p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        with self.assertRaises(RouterStateError):
            n.native_migrate_v2(self.home, reviewed_worker_sha256=n._core._sha256(worker.read_bytes()))
        self.assertEqual(before, {str(p):p.read_bytes() for p in self.home.rglob("*") if p.is_file()})

    def test_missing_review_digest_refuses_drift(self):
        self.legacy()
        worker = self.home / "agents/luna-worker.toml"
        worker.write_bytes(worker.read_bytes().replace(b"[agents]\nenabled = false\n", b""))
        with self.assertRaises(RouterStateError): n.native_migrate_v2(self.home)

    def test_managed_block_drift_refuses(self):
        self.legacy()
        target = self.home / "AGENTS.md"
        target.write_bytes(target.read_bytes().replace(b"planner", b"changed", 1))
        before = target.read_bytes()
        with self.assertRaises(RouterStateError): n.native_migrate_v2(self.home)
        self.assertEqual(before, target.read_bytes())

    def test_interrupted_migration_retains_hash_bound_recovery_copies(self):
        self.legacy()
        original = n._core._replace_expected
        def interrupt(path, **kwargs):
            if path.name == "install-state.json": raise OSError("simulated interruption")
            return original(path, **kwargs)
        with patch.object(n._core, "_replace_expected", side_effect=interrupt):
            with self.assertRaises(OSError): n.native_migrate_v2(self.home)
        journal = self.home / n.NATIVE_INSTALL_DIRECTORY_NAME / "migration-v2"
        manifest = json.loads((journal / "manifest.json").read_text())
        self.assertEqual(manifest["phase"], "prepared")
        for row in manifest["targets"]:
            target = self.home / row["path"]
            before = (journal / row["backup"]).read_bytes()
            self.assertEqual(n._core._sha256(before), row["before_sha256"])
            self.assertIn(n._core._sha256(target.read_bytes()), (row["before_sha256"], row["after_sha256"]))
            target.write_bytes(before)
        self.assertEqual(n.native_status(self.home).state, "installed")
