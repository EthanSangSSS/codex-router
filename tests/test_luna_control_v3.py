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

    def begin_packet(self, *, packet_id, scope, authorizations=()):
        try:
            begin_packet = control.begin_packet
        except AttributeError:
            self.fail("V3.1 packet-generation API is not implemented")
        return begin_packet(
            self.directory,
            self.secret,
            "root-session",
            packet_id=packet_id,
            objective="bounded implementation",
            working_directory="/workspace/repo",
            intended_write_scope=scope,
            explicit_side_effect_authorizations=authorizations,
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )

    def start_packet(self, *, packet_id="packet-1", child_turn_id="turn-1"):
        self.begin_packet(packet_id=packet_id, scope=("src/math.py",))
        return control.start_execution(
            self.directory,
            self.secret,
            "root-session",
            child_turn_id=child_turn_id,
        )

    def freeze(self, *, reason, logical_cancel=False):
        try:
            freeze_authority = control.freeze_authority
        except AttributeError:
            self.fail("V3.1 authority-pause API is not implemented")
        return freeze_authority(
            self.directory,
            self.secret,
            "root-session",
            reason=reason,
            logical_cancel=logical_cancel,
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

    def test_packet_generation_replaces_scope_and_a1_authorizations(self):
        original = self.new_task()
        first = self.begin_packet(
            packet_id="packet-1",
            scope=("src/old.py",),
            authorizations=("git_push",),
        )
        second = self.begin_packet(
            packet_id="packet-2",
            scope=("src/new.py",),
        )

        self.assertEqual(first.packet_generation, 1)
        self.assertEqual(second.packet_generation, 2)
        self.assertEqual(second.luna_epoch, original.luna_epoch)
        self.assertEqual(second.intended_write_scope, ("src/new.py",))
        self.assertEqual(second.explicit_side_effect_authorizations, ())

    def _bind_luna(self, *, agent_id="agent-1"):
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
        return control.observe_subagent_start(
            self.directory,
            self.secret,
            "root-session",
            agent_id=agent_id,
            agent_type="luna_worker",
        )

    def test_same_native_profile_scope_change_keeps_luna_identity(self):
        original = self.new_task()
        bound = self._bind_luna()
        first = self.begin_packet(packet_id="packet-1", scope=("src/old.py",))
        second = self.begin_packet(packet_id="packet-2", scope=("src/new.py",))

        self.assertEqual(first.luna_epoch, original.luna_epoch)
        self.assertEqual(second.luna_epoch, bound.luna_epoch)
        self.assertEqual(second.luna_agent_id, "agent-1")

    def test_authority_profile_replacement_requires_verified_settlement(self):
        self.new_task()
        self.start_packet()

        retire_luna = getattr(control, "retire_luna", None)
        start_new_task_epoch = getattr(control, "start_new_task_epoch", None)
        self.assertIsNotNone(retire_luna)
        self.assertIsNotNone(start_new_task_epoch)
        with self.assertRaises(RouterStateError):
            retire_luna(
                self.directory,
                self.secret,
                "root-session",
                reason="native_authority_profile_change",
            )
        self.assertEqual(
            control.read_snapshot(
                self.directory, self.secret, "root-session"
            ).execution_status,
            "QUIESCING",
        )
        with self.assertRaises(RouterStateError):
            start_new_task_epoch(
                self.directory,
                self.secret,
                "root-session",
                native_parent_identity="root-parent",
                native_authority_profile="profile-B",
            )

        settled = control.observe_settlement(
            self.directory,
            self.secret,
            "root-session",
            source="verified_native_terminal",
            terminal_status="interrupted",
            child_turn_id="turn-1",
        )
        self.assertEqual(settled.execution_status, "PAUSED_SETTLED")
        retired = retire_luna(
            self.directory,
            self.secret,
            "root-session",
            reason="native_authority_profile_change",
        )
        self.assertEqual(retired.execution_status, "RETIRED")
        replacement = start_new_task_epoch(
            self.directory,
            self.secret,
            "root-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-B",
        )
        self.assertNotEqual(replacement.task_epoch, retired.task_epoch)
        self.assertNotEqual(replacement.luna_epoch, retired.luna_epoch)
        self.assertEqual(replacement.native_authority_profile, "profile-B")
        self.assertIsNone(replacement.pending_spawn)

    def test_recovery_rejects_ambiguous_or_untrusted_candidates(self):
        self.new_task()
        self._bind_luna()
        self.begin_packet(packet_id="packet-1", scope=("src/old.py",))
        self.freeze(reason="profile-reset")
        control.observe_settlement(
            self.directory,
            self.secret,
            "root-session",
            source="verified_native_terminal",
            terminal_status="interrupted",
            child_turn_id=None,
        )
        control.retire_luna(
            self.directory,
            self.secret,
            "root-session",
            reason="runtime_validated_context_reset",
        )
        replacement = control.start_new_task_epoch(
            self.directory,
            self.secret,
            "root-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        control.reserve_spawn(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-new",
            task_name="luna_worker",
            fork_turns="none",
            expected_agent_id="agent-new",
        )
        candidate = {
            "task_epoch": replacement.task_epoch,
            "luna_epoch": replacement.luna_epoch,
            "root_session_tag": replacement.root_session_tag,
            "native_parent_identity": "root-parent",
            "native_authority_profile": "profile-A",
            "agent_id": "agent-new",
            "agent_type": "luna_worker",
            "task_path": "/root/luna_worker",
        }
        reconcile = getattr(control, "reconcile_recovery", None)
        self.assertIsNotNone(reconcile)
        with self.assertRaises(RouterStateError):
            reconcile(
                self.directory,
                self.secret,
                "root-session",
                candidates=(candidate, dict(candidate)),
            )
        for field, value in (
            ("native_parent_identity", "other-parent"),
            ("native_authority_profile", "profile-other"),
            ("agent_id", "agent-other"),
            ("agent_type", "reviewer"),
            ("task_epoch", "task-stale"),
            ("luna_epoch", "luna-stale"),
        ):
            invalid = dict(candidate)
            invalid[field] = value
            with self.subTest(field=field):
                with self.assertRaises(RouterStateError):
                    reconcile(
                        self.directory,
                        self.secret,
                        "root-session",
                        candidate=invalid,
                    )
        with self.assertRaises(RouterStateError):
            reconcile(
                self.directory,
                self.secret,
                "root-session",
                candidate={"resumable": True},
            )
        bound = reconcile(
            self.directory,
            self.secret,
            "root-session",
            candidate=candidate,
        )
        self.assertEqual(bound.luna_agent_id, "agent-new")

    def test_delayed_old_epoch_start_cannot_bind_new_recovery(self):
        old = self.new_task()
        self.begin_packet(packet_id="packet-1", scope=("src/old.py",))
        self.freeze(reason="replace")
        control.observe_settlement(
            self.directory,
            self.secret,
            "root-session",
            source="verified_native_terminal",
            terminal_status="interrupted",
            child_turn_id=None,
        )
        control.retire_luna(
            self.directory,
            self.secret,
            "root-session",
            reason="new_task_epoch",
        )
        replacement = control.start_new_task_epoch(
            self.directory,
            self.secret,
            "root-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        control.reserve_spawn(
            self.directory,
            self.secret,
            "root-session",
            tool_use_id="spawn-new",
            task_name="luna_worker",
            fork_turns="none",
        )
        with self.assertRaises(RouterStateError):
            control.observe_subagent_start(
                self.directory,
                self.secret,
                "root-session",
                agent_id="late-old-agent",
                agent_type="luna_worker",
                task_epoch=old.task_epoch,
                luna_epoch=old.luna_epoch,
            )
        self.assertIsNone(
            control.read_snapshot(
                self.directory, self.secret, "root-session"
            ).luna_agent_id
        )

    def test_start_execution_records_native_child_turn(self):
        self.new_task()
        self.begin_packet(packet_id="packet-1", scope=("src/math.py",))

        try:
            start_execution = control.start_execution
        except AttributeError:
            self.fail("V3.1 execution API is not implemented")
        started = start_execution(
            self.directory,
            self.secret,
            "root-session",
            child_turn_id="child-turn-1",
        )

        self.assertEqual(started.execution_status, "RUNNING")
        self.assertEqual(started.active_child_turn_id, "child-turn-1")

    def test_delayed_prior_generation_result_is_stale_without_state_mutation(self):
        self.new_task()
        self.begin_packet(packet_id="packet-1", scope=("src/old.py",))
        self.begin_packet(packet_id="packet-2", scope=("src/new.py",))
        before = control.read_snapshot(self.directory, self.secret, "root-session")

        try:
            accept_result = control.accept_result
        except AttributeError:
            self.fail("V3.1 result API is not implemented")
        result = accept_result(
            self.directory,
            self.secret,
            "root-session",
            generation=1,
            child_turn_id=None,
        )

        after = control.read_snapshot(self.directory, self.secret, "root-session")
        self.assertEqual(result, "STALE")
        self.assertEqual(after, before)

    def test_pause_freezes_authority_and_interrupt_ack_cannot_settle(self):
        self.new_task()
        running = self.start_packet()

        paused = self.freeze(reason="user_pause")
        self.assertEqual(paused.execution_status, "QUIESCING")
        self.assertEqual(paused.logical_task_status, "ACTIVE")
        self.assertEqual(paused.packet_generation, running.packet_generation)
        self.assertEqual(paused.active_child_turn_id, "turn-1")

        try:
            record_interrupt_ack = control.record_interrupt_ack
        except AttributeError:
            self.fail("V3.1 interrupt-ack API is not implemented")
        acked = record_interrupt_ack(
            self.directory,
            self.secret,
            "root-session",
            previous_status="running",
        )
        self.assertEqual(acked.execution_status, "QUIESCING")
        self.assertNotEqual(acked.execution_status, "PAUSED_SETTLED")
        self.assertEqual(acked, paused)

        with self.assertRaises(RouterStateError):
            self.begin_packet(packet_id="packet-2", scope=("src/other.py",))

    def test_verified_native_terminal_settlement_allows_next_generation(self):
        self.new_task()
        self.start_packet()
        self.freeze(reason="user_pause")

        try:
            observe_settlement = control.observe_settlement
        except AttributeError:
            self.fail("V3.1 settlement API is not implemented")
        settled = observe_settlement(
            self.directory,
            self.secret,
            "root-session",
            source="verified_native_terminal",
            terminal_status="completed",
            child_turn_id="turn-1",
        )
        self.assertEqual(settled.execution_status, "PAUSED_SETTLED")
        self.assertEqual(settled.active_packet_id, "packet-1")
        self.assertEqual(settled.active_child_turn_id, "turn-1")

        self.assertEqual(
            control.accept_result(
                self.directory,
                self.secret,
                "root-session",
                generation=1,
                child_turn_id="turn-1",
            ),
            "STALE",
        )
        next_packet = self.begin_packet(
            packet_id="packet-2",
            scope=("src/other.py",),
        )
        self.assertEqual(next_packet.packet_generation, 2)
        self.assertEqual(next_packet.execution_status, "IDLE")

    def test_logical_cancellation_is_preserved_through_settlement(self):
        self.new_task()
        self.start_packet()
        cancelled = self.freeze(reason="user_cancel", logical_cancel=True)
        self.assertEqual(cancelled.logical_task_status, "CANCELLED")
        self.assertEqual(cancelled.execution_status, "QUIESCING")

        try:
            observe_settlement = control.observe_settlement
        except AttributeError:
            self.fail("V3.1 settlement API is not implemented")
        settled = observe_settlement(
            self.directory,
            self.secret,
            "root-session",
            source="verified_native_terminal",
            terminal_status="completed",
            child_turn_id="turn-1",
        )
        self.assertEqual(settled.logical_task_status, "CANCELLED")
        self.assertEqual(settled.execution_status, "PAUSED_SETTLED")

    def test_paused_settled_execution_cannot_restart_without_new_packet(self):
        self.new_task()
        self.start_packet()
        self.freeze(reason="user_pause")
        try:
            observe_settlement = control.observe_settlement
        except AttributeError:
            self.fail("V3.1 settlement API is not implemented")
        observe_settlement(
            self.directory,
            self.secret,
            "root-session",
            source="verified_native_terminal",
            terminal_status="interrupted",
            child_turn_id="turn-1",
        )

        with self.assertRaises(RouterStateError):
            control.start_execution(
                self.directory,
                self.secret,
                "root-session",
                child_turn_id="turn-1",
            )


if __name__ == "__main__":
    unittest.main()
