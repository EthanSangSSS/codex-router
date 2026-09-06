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

    def initial_v2(self):
        with patch.object(
            n, "render_primary_block", n.render_initial_v2_primary_block
        ):
            n.native_install(self.home)
        return json.loads(
            (self.home / n.NATIVE_INSTALL_DIRECTORY_NAME / "install-state.json").read_text()
        )

    def test_cost_routing_has_no_mandatory_trigger_or_ceremony(self):
        block = n.render_primary_block()
        self.assertIn("quota savings exceed coordination cost", block)
        for phrase in (
            "selects one owner",
            "one fresh, verified `luna_worker`",
            "Luna exclusively owns implementation",
            "must not launch duplicate or overlapping",
            "terminal state or a confirmed interruption",
            "timeout or missing observation alone never authorizes takeover",
            "explicit current-task authorization and disjoint ownership",
            "Web capability-gap fallback and Company OS",
            "selectively verify only genuinely independent or unresolved/changed concerns",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, block)
        self.assertNotIn("LUNA_DECISION=", block)
        self.assertNotIn("MUST attempt", block)

    def test_native_spawn_binds_role_separately_from_task_label(self):
        block = n.render_primary_block()
        self.assertIn('agent_type="luna_worker"', block)
        self.assertIn("`task_name` is only a label", block)
        self.assertIn(
            '`task_name="luna_worker"` alone cannot select the Luna role or model',
            block,
        )
        self.assertIn(
            '`fork_turns="none"` for a fresh bounded context when that field exists',
            block,
        )
        self.assertIn("report capability failure", block)

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

    def test_migrate_initial_v2_updates_policy_with_separate_journal_and_preserves_worker(self):
        old = self.initial_v2()
        install = self.home / n.NATIVE_INSTALL_DIRECTORY_NAME
        existing_v2_journal = install / "migration-v2"
        existing_v2_journal.mkdir(mode=0o700)
        sentinel = existing_v2_journal / "legacy.before"
        sentinel.write_bytes(b"existing V2 recovery copy")

        worker = self.home / "agents/luna-worker.toml"
        worker_before = worker.read_bytes()
        worker_document_before = n.tomllib.loads(worker_before.decode("utf-8"))
        result = n.native_migrate_v2(self.home)

        self.assertEqual(result.state, "installed")
        self.assertEqual(worker.read_bytes(), worker_before)
        self.assertEqual(
            n.tomllib.loads(worker.read_bytes().decode("utf-8")),
            worker_document_before,
        )
        state = json.loads((install / "install-state.json").read_text())
        self.assertEqual(
            state["targets"]["AGENTS.md"]["original_sha256"],
            old["targets"]["AGENTS.md"]["original_sha256"],
        )
        self.assertEqual(
            state["targets"]["AGENTS.md"]["installed_block_sha256"],
            n._core._sha256((n.render_primary_block() + "\n").encode("utf-8")),
        )
        self.assertEqual(sentinel.read_bytes(), b"existing V2 recovery copy")
        policy_journal = install / n.NATIVE_POLICY_MIGRATION_DIRECTORY_NAME
        manifest = json.loads((policy_journal / "manifest.json").read_text())
        self.assertEqual(manifest["protocol"], n.NATIVE_POLICY_MIGRATION_PROTOCOL)
        self.assertEqual(manifest["source_policy"], "initial-v2")
        self.assertEqual(manifest["phase"], "installed")
        self.assertTrue(all(n.native_self_test(self.home).values()))
        self.assertEqual(n.native_migrate_v2(self.home).state, "installed")

    def test_initial_v2_unknown_worker_drift_refuses_without_changes(self):
        self.initial_v2()
        worker = self.home / "agents/luna-worker.toml"
        worker.write_bytes(worker.read_bytes() + b"\n# unknown drift\n")
        before = {
            str(p): p.read_bytes() for p in self.home.rglob("*") if p.is_file()
        }
        with self.assertRaises(RouterStateError):
            n.native_migrate_v2(self.home)
        self.assertEqual(
            before,
            {str(p): p.read_bytes() for p in self.home.rglob("*") if p.is_file()},
        )
        self.assertFalse(
            (self.home / n.NATIVE_INSTALL_DIRECTORY_NAME / n.NATIVE_POLICY_MIGRATION_DIRECTORY_NAME).exists()
        )

    def test_migrate_initial_v2_preserves_recorded_semantically_equal_worker_bytes(self):
        canonical = n.render_luna_agent_bytes(
            model="gpt-5.6-luna", reasoning="max"
        )
        formatted = canonical.replace(b"\ndescription =", b"\n\ndescription =", 1)
        with patch.object(n, "render_luna_agent_bytes", return_value=formatted):
            self.initial_v2()

        worker = self.home / "agents/luna-worker.toml"
        before = worker.read_bytes()
        self.assertNotEqual(before, canonical)
        result = n.native_migrate_v2(self.home)

        self.assertEqual(result.state, "installed")
        self.assertEqual(worker.read_bytes(), before)
        self.assertEqual(
            n.tomllib.loads(worker.read_text(encoding="utf-8")),
            n.tomllib.loads(canonical.decode("utf-8")),
        )

    def test_interrupted_initial_v2_migration_keeps_separate_hash_bound_journal(self):
        self.initial_v2()
        install = self.home / n.NATIVE_INSTALL_DIRECTORY_NAME
        existing_v2_journal = install / "migration-v2"
        existing_v2_journal.mkdir(mode=0o700)
        sentinel = existing_v2_journal / "legacy.before"
        sentinel.write_bytes(b"existing V2 recovery copy")

        original = n._core._replace_expected

        def interrupt(path, **kwargs):
            if path.name == "install-state.json":
                raise OSError("simulated interruption")
            return original(path, **kwargs)

        with patch.object(n._core, "_replace_expected", side_effect=interrupt):
            with self.assertRaises(OSError):
                n.native_migrate_v2(self.home)

        policy_journal = install / n.NATIVE_POLICY_MIGRATION_DIRECTORY_NAME
        manifest = json.loads((policy_journal / "manifest.json").read_text())
        self.assertEqual(manifest["phase"], "prepared")
        self.assertEqual(sentinel.read_bytes(), b"existing V2 recovery copy")
        for row in manifest["targets"]:
            target = self.home / row["path"]
            self.assertIn(
                n._core._sha256(target.read_bytes()),
                (row["before_sha256"], row["after_sha256"]),
            )

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
