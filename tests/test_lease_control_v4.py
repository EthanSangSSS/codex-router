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

    def stage(self, *, generation=1, packet_id="packet-1", root_turn_id=None):
        if control.read_snapshot(self.directory, self.secret, self.session_id) is None:
            self.initialize()
        return control.stage_lease(
            self.directory,
            self.secret,
            self.session_id,
            root_turn_id=root_turn_id or f"root-turn-{generation}",
            packet_wire=self.packet(generation=generation, packet_id=packet_id),
        )

    def reserve(self, *, tool_use_id="spawn-1"):
        snapshot = control.read_snapshot(self.directory, self.secret, self.session_id)
        lease = snapshot.active_lease
        return control.reserve_spawn(
            self.directory,
            self.secret,
            self.session_id,
            tool_use_id=tool_use_id,
            task_name=lease.expected_task_name,
            agent_type="luna_worker",
            fork_turns="none",
        )

    def force_persisted_lease_status_for_test(self, status):
        journal = self.directory / "lease-control-v4-0.json"
        value = json.loads(journal.read_text(encoding="utf-8"))
        session = next(iter(value["sessions"].values()))
        session["active_lease"]["status"] = status
        journal.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        journal.chmod(0o600)
        return control.read_snapshot(self.directory, self.secret, self.session_id)

    def test_new_v4_session_starts_generation_zero_without_active_lease(self):
        snapshot = self.initialize()
        self.assertEqual(snapshot.generation, 0)
        self.assertIsNone(snapshot.active_lease)
        self.assertTrue(snapshot.task_epoch.startswith("task-"))
        self.assertEqual(control.read_snapshot(self.directory, self.secret, self.session_id), snapshot)

    def test_first_staged_lease_is_generation_one_and_has_unique_lease_id(self):
        staged = self.stage()
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

    def test_staged_lease_revokes_without_terminal_evidence(self):
        staged = self.stage()
        revoked = control.revoke_current_lease(self.directory, self.secret, self.session_id)
        self.assertEqual(revoked.generation, staged.generation)
        self.assertIsNone(revoked.active_lease)

    def test_active_lease_revokes_without_terminal_evidence(self):
        self.stage()
        active = self.force_persisted_lease_status_for_test("ACTIVE")
        self.assertEqual(active.active_lease.status, "ACTIVE")
        revoked = control.revoke_current_lease(self.directory, self.secret, self.session_id)
        self.assertEqual(revoked.generation, active.generation)
        self.assertIsNone(revoked.active_lease)

    def test_revocation_clears_active_authority_immediately(self):
        staged = self.stage()
        old_lease_id = staged.active_lease.lease_id
        revoked = control.revoke_current_lease(self.directory, self.secret, self.session_id)
        reread = control.read_snapshot(self.directory, self.secret, self.session_id)
        self.assertIsNone(revoked.active_lease)
        self.assertEqual(reread, revoked)
        self.assertNotIn(old_lease_id, (repr(reread.active_lease),))

    def test_revoked_generation_does_not_block_next_generation(self):
        first = self.stage(generation=1, packet_id="packet-1")
        control.revoke_current_lease(self.directory, self.secret, self.session_id)
        second = self.stage(generation=2, packet_id="packet-2")
        self.assertEqual(second.generation, 2)
        self.assertEqual(second.active_lease.generation, 2)
        self.assertNotEqual(first.active_lease.lease_id, second.active_lease.lease_id)

    def test_next_generation_increments_and_changes_lease_id(self):
        first = self.stage(generation=1, packet_id="packet-1")
        first_id = first.active_lease.lease_id
        control.revoke_current_lease(self.directory, self.secret, self.session_id)
        second = self.stage(generation=2, packet_id="packet-2")
        self.assertEqual(second.generation, first.generation + 1)
        self.assertNotEqual(second.active_lease.lease_id, first_id)

    def test_repeated_revoke_with_no_active_lease_is_idempotent(self):
        initial = self.initialize()
        once = control.revoke_current_lease(self.directory, self.secret, self.session_id)
        twice = control.revoke_current_lease(self.directory, self.secret, self.session_id)
        self.assertEqual(once, initial)
        self.assertEqual(twice, once)

    def test_expected_task_name_is_generation_and_lease_scoped(self):
        first = self.stage(generation=1, packet_id="packet-1")
        first_name = first.active_lease.expected_task_name
        self.assertRegex(first_name, r"^luna_g1_[0-9a-f]{8}$")
        control.revoke_current_lease(self.directory, self.secret, self.session_id)
        second = self.stage(generation=2, packet_id="packet-2")
        second_name = second.active_lease.expected_task_name
        self.assertRegex(second_name, r"^luna_g2_[0-9a-f]{8}$")
        self.assertNotEqual(first_name, second_name)

    def test_spawn_reservation_rejects_wrong_task_name_agent_type_or_fork_mode(self):
        staged = self.stage()
        correct = staged.active_lease.expected_task_name
        cases = (
            {"task_name": "luna_worker", "agent_type": "luna_worker", "fork_turns": "none"},
            {"task_name": correct, "agent_type": "reviewer", "fork_turns": "none"},
            {"task_name": correct, "agent_type": "luna_worker", "fork_turns": "all"},
        )
        for index, values in enumerate(cases):
            with self.subTest(values=values):
                with self.assertRaises(RouterStateError):
                    control.reserve_spawn(self.directory, self.secret, self.session_id, tool_use_id=f"bad-spawn-{index}", **values)
                current = control.read_snapshot(self.directory, self.secret, self.session_id)
                self.assertIsNone(current.active_lease.spawn_tool_use_id)

    def test_spawn_reservation_belongs_only_to_current_lease(self):
        staged = self.stage()
        lease_id = staged.active_lease.lease_id
        reserved = self.reserve(tool_use_id="spawn-current")
        self.assertEqual(reserved.active_lease.lease_id, lease_id)
        self.assertEqual(reserved.active_lease.spawn_tool_use_id, "spawn-current")
        self.assertIsNone(reserved.active_lease.worker_agent_id)
        self.assertIsNone(reserved.active_lease.worker_task_path)

    def test_exact_spawn_result_records_only_current_task_path(self):
        staged = self.stage()
        expected_path = f"/root/{staged.active_lease.expected_task_name}"
        self.reserve(tool_use_id="spawn-current")
        updated, disposition = control.observe_spawn_result(
            self.directory, self.secret, self.session_id,
            tool_use_id="spawn-current", task_path=expected_path,
        )
        self.assertEqual(disposition, "CURRENT")
        self.assertEqual(updated.active_lease.worker_task_path, expected_path)
        self.assertIsNone(updated.active_lease.worker_agent_id)
        self.assertIsNone(updated.active_lease.child_turn_id)
        self.assertEqual(updated.active_lease.status, "STAGED")

    def test_wrong_path_for_current_spawn_result_fails_closed(self):
        self.stage()
        self.reserve(tool_use_id="spawn-current")
        before = control.read_snapshot(self.directory, self.secret, self.session_id)
        with self.assertRaises(RouterStateError):
            control.observe_spawn_result(
                self.directory, self.secret, self.session_id,
                tool_use_id="spawn-current", task_path="/root/wrong-task-path",
            )
        self.assertEqual(control.read_snapshot(self.directory, self.secret, self.session_id), before)

    def test_revoked_spawn_observation_is_stale_noop(self):
        first = self.stage(generation=1, packet_id="packet-1")
        first_path = f"/root/{first.active_lease.expected_task_name}"
        self.reserve(tool_use_id="spawn-old")
        control.revoke_current_lease(self.directory, self.secret, self.session_id)
        self.stage(generation=2, packet_id="packet-2")
        self.reserve(tool_use_id="spawn-new")
        before = control.read_snapshot(self.directory, self.secret, self.session_id)
        after, disposition = control.observe_spawn_result(
            self.directory, self.secret, self.session_id,
            tool_use_id="spawn-old", task_path=first_path,
        )
        self.assertEqual(disposition, "STALE")
        self.assertEqual(after, before)
        self.assertEqual(control.read_snapshot(self.directory, self.secret, self.session_id), before)

    def test_subagent_start_never_binds_uncorrelated_worker(self):
        self.stage()
        reserved = self.reserve(tool_use_id="spawn-current")
        after, disposition = control.observe_subagent_start(
            self.directory, self.secret, self.session_id,
            agent_id="agent-current", agent_type="luna_worker", turn_id="child-turn-current",
        )
        self.assertEqual(disposition, "NOOP")
        self.assertEqual(after, reserved)
        self.assertIsNone(after.active_lease.worker_agent_id)
        self.assertIsNone(after.active_lease.child_turn_id)

    def test_late_subagent_start_after_revoke_is_noop(self):
        self.stage(generation=1, packet_id="packet-1")
        self.reserve(tool_use_id="spawn-old")
        control.revoke_current_lease(self.directory, self.secret, self.session_id)
        self.stage(generation=2, packet_id="packet-2")
        before = control.read_snapshot(self.directory, self.secret, self.session_id)
        after, disposition = control.observe_subagent_start(
            self.directory, self.secret, self.session_id,
            agent_id="unknown-old-agent", agent_type="luna_worker", turn_id="unknown-old-turn",
        )
        self.assertEqual(disposition, "NOOP")
        self.assertEqual(after, before)
        self.assertIsNone(after.active_lease.worker_agent_id)

    def test_bootstrap_capability_is_lease_scoped(self):
        first = self.stage(generation=1, packet_id="packet-1")
        first_capability = control.build_bootstrap_capability(self.secret, first.active_lease)
        control.verify_bootstrap_capability(self.secret, first.active_lease, first_capability)
        control.revoke_current_lease(self.directory, self.secret, self.session_id)
        second = self.stage(generation=2, packet_id="packet-2")
        second_capability = control.build_bootstrap_capability(self.secret, second.active_lease)
        self.assertRegex(first_capability, r"^v4b1\.[0-9a-f]{64}$")
        self.assertRegex(second_capability, r"^v4b1\.[0-9a-f]{64}$")
        self.assertNotEqual(first_capability, second_capability)

    def test_old_bootstrap_capability_fails_against_new_lease(self):
        first = self.stage(generation=1, packet_id="packet-1")
        old_capability = control.build_bootstrap_capability(self.secret, first.active_lease)
        control.revoke_current_lease(self.directory, self.secret, self.session_id)
        second = self.stage(generation=2, packet_id="packet-2")
        with self.assertRaises(RouterStateError):
            control.verify_bootstrap_capability(self.secret, second.active_lease, old_capability)


if __name__ == "__main__":
    unittest.main()
