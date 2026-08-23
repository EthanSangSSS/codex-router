import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_router import lease_control as control
from codex_router.protocol import build_luna_packet
from codex_router.state import RouterStateError


class LeaseControlV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.secret = b"v4-lease-secret-material-32bytes!!"
        self.session_id = "root-session"

    def initialize(self):
        return control.initialize_session(
            self.directory,
            self.secret,
            self.session_id,
        )

    def packet(self, *, generation=1, packet_id="packet-1"):
        return build_luna_packet(
            packet_id=packet_id,
            generation=generation,
            objective="bounded V4 lease work",
            working_directory="/workspace/repo",
            intended_write_scope=["src/example.py"],
            explicit_side_effect_authorizations=[],
            success_criteria=["focused tests pass"],
            stop_conditions=["scope expansion required"],
        )

    def test_new_v4_session_starts_generation_zero_without_active_lease(self):
        snapshot = self.initialize()

        self.assertEqual(snapshot.generation, 0)
        self.assertIsNone(snapshot.active_lease)
        self.assertTrue(snapshot.task_epoch.startswith("task-"))
        self.assertEqual(
            control.read_snapshot(self.directory, self.secret, self.session_id),
            snapshot,
        )

    def test_first_staged_lease_is_generation_one_and_has_unique_lease_id(self):
        self.initialize()

        staged = control.stage_lease(
            self.directory,
            self.secret,
            self.session_id,
            root_turn_id="root-turn-1",
            packet_wire=self.packet(generation=1),
        )

        self.assertEqual(staged.generation, 1)
        self.assertIsNotNone(staged.active_lease)
        self.assertEqual(staged.active_lease.generation, 1)
        self.assertTrue(staged.active_lease.lease_id)
        self.assertEqual(staged.active_lease.packet_id, "packet-1")
        self.assertEqual(staged.active_lease.status, "STAGED")

    def test_corrupt_v4_schema_fails_closed(self):
        self.initialize()
        journal = self.directory / "lease-control-v4-0.json"
        value = json.loads(journal.read_text(encoding="utf-8"))
        value["unexpected"] = True
        journal.write_text(json.dumps(value), encoding="utf-8")
        journal.chmod(0o600)

        with self.assertRaises(RouterStateError):
            control.read_snapshot(self.directory, self.secret, self.session_id)

    def test_v4_journal_symlink_is_rejected(self):
        self.initialize()
        journal = self.directory / "lease-control-v4-0.json"
        real = self.directory / "real-v4-state.json"
        journal.rename(real)
        journal.symlink_to(real)

        with self.assertRaises(RouterStateError):
            control.read_snapshot(self.directory, self.secret, self.session_id)

    def test_v4_journal_is_owner_only(self):
        self.initialize()
        journal = self.directory / "lease-control-v4-0.json"
        lock = self.directory / "lease-control-v4-0.lock"

        self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

    def test_v4_mutation_fsyncs_file_and_directory(self):
        real_fsync = os.fsync
        calls = []

        def observing_fsync(fd):
            calls.append(fd)
            return real_fsync(fd)

        with patch("codex_router.lease_control.os.fsync", side_effect=observing_fsync):
            self.initialize()

        self.assertGreaterEqual(len(calls), 2)

    def test_v3_journal_is_not_imported_as_v4_authority(self):
        legacy = self.directory / "luna-control-v3-1.json"
        legacy_bytes = b'{"legacy":"stale-authority-must-not-import"}\n'
        legacy.write_bytes(legacy_bytes)
        legacy.chmod(0o600)

        snapshot = self.initialize()

        self.assertEqual(snapshot.generation, 0)
        self.assertIsNone(snapshot.active_lease)
        self.assertEqual(legacy.read_bytes(), legacy_bytes)


if __name__ == "__main__":
    unittest.main()
