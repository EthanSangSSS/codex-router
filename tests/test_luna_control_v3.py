import json
import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from codex_router import luna_control as control
from codex_router.state import RouterStateError


class LunaControlV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.secret = b"v3-control-secret-material-32bytes!"

    def new_task(self):
        return control.new_task(
            directory=self.directory,
            secret=self.secret,
            session_id="root-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )

    def test_new_task_persists_initial_dual_status_snapshot(self):
        snapshot = self.new_task()
        self.assertEqual(snapshot.logical_task_status, "ACTIVE")
        self.assertEqual(snapshot.execution_status, "IDLE")
        self.assertEqual(snapshot.packet_generation, 0)
        self.assertIsNone(snapshot.luna_agent_id)
        self.assertIsNone(snapshot.active_packet_id)
        self.assertEqual(
            control.read_snapshot(self.directory, self.secret, "root-session"), snapshot
        )

    def test_cancelled_task_may_remain_quiescing_until_settlement(self):
        snapshot = self.new_task()
        cancelled_in_flight = control.ControlSnapshot(
            task_epoch=snapshot.task_epoch,
            luna_epoch=snapshot.luna_epoch,
            root_session_tag=snapshot.root_session_tag,
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
            luna_agent_id="agent-1",
            luna_task_path="/root/luna_worker",
            packet_generation=1,
            active_packet_id="packet-1",
            active_child_turn_id="child-turn-1",
            logical_task_status="CANCELLED",
            execution_status="QUIESCING",
        )
        control.validate_snapshot(cancelled_in_flight)

    def test_invalid_state_combinations_fail_closed(self):
        snapshot = self.new_task()
        invalid = (
            replace(snapshot, execution_status="RETIRED"),
            replace(snapshot, packet_generation=-1),
            replace(snapshot, task_epoch="bad-task"),
            replace(snapshot, luna_epoch="bad-luna"),
            replace(snapshot, luna_agent_id="agent-1"),
            replace(snapshot, execution_status="RUNNING"),
            replace(snapshot, execution_status="QUIESCING"),
            replace(snapshot, active_child_turn_id="child-turn-1"),
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(RouterStateError):
                    control.validate_snapshot(value)

    def test_journal_is_owner_only_and_read_does_not_rewrite(self):
        snapshot = self.new_task()
        journal = self.directory / "luna-control-v3-1.json"
        self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
        before = journal.stat().st_mtime_ns
        self.assertEqual(
            control.read_snapshot(self.directory, self.secret, "root-session"), snapshot
        )
        after = journal.stat().st_mtime_ns
        self.assertEqual(after, before)

    def test_journal_symlink_is_rejected(self):
        self.new_task()
        journal = self.directory / "luna-control-v3-1.json"
        real = self.directory / "real-state.json"
        journal.rename(real)
        journal.symlink_to(real)
        with self.assertRaises(RouterStateError):
            control.read_snapshot(self.directory, self.secret, "root-session")

    def test_unknown_or_malformed_disk_schema_fails_closed(self):
        snapshot = self.new_task()
        journal = self.directory / "luna-control-v3-1.json"
        value = json.loads(journal.read_text(encoding="utf-8"))
        record = value["sessions"][snapshot.root_session_tag]
        record["unexpected"] = True
        journal.write_text(json.dumps(value), encoding="utf-8")
        journal.chmod(0o600)
        with self.assertRaises(RouterStateError):
            control.read_snapshot(self.directory, self.secret, "root-session")

    def test_mutation_fsyncs_file_and_containing_directory(self):
        real_fsync = os.fsync
        calls = []

        def observing_fsync(fd):
            calls.append(fd)
            return real_fsync(fd)

        with patch("codex_router.luna_control.os.fsync", side_effect=observing_fsync):
            self.new_task()
        self.assertGreaterEqual(len(calls), 2)

    def test_spawn_binds_when_result_arrives_before_subagent_start(self):
        original = self.new_task()
        reserved = control.reserve_spawn(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-1",
            task_name="luna_worker",
            fork_turns="none",
        )
        self.assertIsNotNone(reserved.pending_spawn)
        observed = control.observe_spawn_result(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )
        self.assertIsNone(observed.luna_agent_id)
        bound = control.observe_subagent_start(
            self.directory,
            self.secret,
            "root-session",
            agent_id="agent-1",
            agent_type="luna_worker",
        )
        self.assertEqual(bound.task_epoch, original.task_epoch)
        self.assertEqual(bound.luna_agent_id, "agent-1")
        self.assertEqual(bound.luna_task_path, "/root/luna_worker")
        self.assertIsNone(bound.pending_spawn)

    def test_spawn_binds_when_subagent_start_arrives_before_result(self):
        self.new_task()
        control.reserve_spawn(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-1",
            task_name="luna_worker",
            fork_turns="none",
        )
        observed = control.observe_subagent_start(
            self.directory,
            self.secret,
            "root-session",
            agent_id="agent-1",
            agent_type="luna_worker",
        )
        self.assertIsNone(observed.luna_agent_id)
        bound = control.observe_spawn_result(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )
        self.assertEqual(bound.luna_agent_id, "agent-1")
        self.assertEqual(bound.luna_task_path, "/root/luna_worker")
        self.assertIsNone(bound.pending_spawn)

    def test_spawn_reservation_fails_closed_on_ambiguity_or_mismatch(self):
        self.new_task()
        control.reserve_spawn(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-1",
            task_name="luna_worker",
            fork_turns="none",
        )
        failing_calls = (
            lambda: control.reserve_spawn(
                self.directory,
                self.secret,
                "root-session",
                tool_use_id="spawn-2",
                task_name="luna_worker",
                fork_turns="none",
            ),
            lambda: control.observe_spawn_result(
                self.directory,
                self.secret,
                "root-session",
                tool_use_id="other",
                task_path="/root/luna_worker",
            ),
            lambda: control.observe_spawn_result(
                self.directory,
                self.secret,
                "root-session",
                tool_use_id="spawn-1",
                task_path="/root/other",
            ),
            lambda: control.observe_subagent_start(
                self.directory,
                self.secret,
                "root-session",
                agent_id="agent-1",
                agent_type="reviewer",
            ),
        )
        for call in failing_calls:
            with self.subTest(call=call):
                with self.assertRaises(RouterStateError):
                    call()

    def test_spawn_requires_packet_only_context(self):
        self.new_task()
        for task_name, fork_turns in (
            ("other", "none"),
            ("luna_worker", "all"),
            ("luna_worker", ""),
        ):
            with self.subTest(task_name=task_name, fork_turns=fork_turns):
                with self.assertRaises(RouterStateError):
                    control.reserve_spawn(
                        self.directory,
                        self.secret,
                        "root-session",
                        tool_use_id="spawn-x",
                        task_name=task_name,
                        fork_turns=fork_turns,
                    )

    def test_bound_luna_is_persistent_and_prevents_replacement_spawn(self):
        original = self.new_task()
        control.reserve_spawn(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-1",
            task_name="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )
        bound = control.observe_subagent_start(
            self.directory,
            self.secret,
            "root-session",
            agent_id="agent-1",
            agent_type="luna_worker",
        )
        self.assertEqual(
            control.current_luna(self.directory, self.secret, "root-session"), bound
        )
        self.assertEqual(bound.task_epoch, original.task_epoch)
        with self.assertRaises(RouterStateError):
            control.reserve_spawn(
                self.directory,
                self.secret,
                "root-session",
                tool_use_id="spawn-2",
                task_name="luna_worker",
                fork_turns="none",
            )
        control.authorize_parent_target(
            self.directory,
            self.secret,
            "root-session",
            tool_name="followup_task",
            target="/root/luna_worker",
        )
        control.authorize_parent_target(
            self.directory,
            self.secret,
            "root-session",
            tool_name="send_message",
            target="agent-1",
        )

    def test_delayed_start_cannot_bind_after_new_task_epoch(self):
        first = self.new_task()
        control.reserve_spawn(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-old",
            task_name="luna_worker",
            fork_turns="none",
        )
        second = control.new_task(
            directory=self.directory,
            secret=self.secret,
            session_id="root-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        self.assertNotEqual(first.task_epoch, second.task_epoch)
        with self.assertRaises(RouterStateError):
            control.observe_subagent_start(
                self.directory,
                self.secret,
                "root-session",
                agent_id="late-agent",
                agent_type="luna_worker",
            )


if __name__ == "__main__":
    unittest.main()
