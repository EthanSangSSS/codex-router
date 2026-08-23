import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_router import lease_control as control
from codex_router.protocol import build_luna_packet
from codex_router.state import RouterStateError


class V4SessionCapacityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.directory.chmod(0o700)
        self.secret = b"v4-session-capacity-secret-32bytes!"

    def test_capacity_reclaims_only_fully_idle_session_records(self):
        with patch.object(control, "_MAX_SESSIONS", 2):
            control.initialize_session(
                self.directory, self.secret, "session-idle-1"
            )
            control.initialize_session(
                self.directory, self.secret, "session-idle-2"
            )

            newest = control.initialize_session(
                self.directory, self.secret, "session-idle-3"
            )

            self.assertEqual(newest.generation, 0)
            self.assertIsNone(newest.active_lease)
            self.assertIsNone(newest.current_root_turn_tag)
            survivors = [
                control.read_snapshot(self.directory, self.secret, session_id)
                for session_id in (
                    "session-idle-1",
                    "session-idle-2",
                    "session-idle-3",
                )
            ]
            self.assertEqual(sum(snapshot is not None for snapshot in survivors), 2)
            self.assertIsNotNone(survivors[2])

    def test_capacity_never_reclaims_current_root_or_active_lease(self):
        with patch.object(control, "_MAX_SESSIONS", 2):
            first = "session-current-root"
            second = "session-active-lease"
            control.initialize_session(self.directory, self.secret, first)
            control.set_current_root_turn(
                self.directory,
                self.secret,
                first,
                turn_id="root-turn-current",
            )
            control.initialize_session(self.directory, self.secret, second)
            control.stage_lease(
                self.directory,
                self.secret,
                second,
                root_turn_id="root-turn-active",
                packet_wire=build_luna_packet(
                    packet_id="packet-active",
                    generation=1,
                    objective="hold active authority",
                    working_directory="/workspace/repo",
                    intended_write_scope=["src"],
                    explicit_side_effect_authorizations=[],
                    success_criteria=["authority remains"],
                    stop_conditions=["capacity pressure"],
                ),
            )

            with self.assertRaises(RouterStateError):
                control.initialize_session(
                    self.directory, self.secret, "session-must-not-evict"
                )

            self.assertIsNotNone(
                control.read_snapshot(self.directory, self.secret, first)
            )
            self.assertIsNotNone(
                control.read_snapshot(self.directory, self.secret, second)
            )

    def test_exact_terminal_makes_completed_session_reclaimable(self):
        session_id = "session-terminal-idle"
        control.initialize_session(self.directory, self.secret, session_id)
        control.set_current_root_turn(
            self.directory,
            self.secret,
            session_id,
            turn_id="root-turn-terminal",
        )
        staged = control.stage_lease(
            self.directory,
            self.secret,
            session_id,
            root_turn_id="root-turn-terminal",
            packet_wire=build_luna_packet(
                packet_id="packet-terminal",
                generation=1,
                objective="finish cleanly",
                working_directory="/workspace/repo",
                intended_write_scope=["src"],
                explicit_side_effect_authorizations=[],
                success_criteria=["terminal observed"],
                stop_conditions=["none"],
            ),
        )
        capability = control.build_bootstrap_capability(
            self.secret, staged.active_lease
        )
        control.authorize_executor_tool(
            self.directory,
            self.secret,
            session_id,
            agent_id="agent-terminal",
            agent_type="luna_worker",
            child_turn_id="child-terminal",
            bootstrap_capability=capability,
        )

        closed, disposition = control.observe_subagent_stop(
            self.directory,
            self.secret,
            session_id,
            agent_id="agent-terminal",
            agent_type="luna_worker",
            child_turn_id="child-terminal",
        )

        self.assertEqual(disposition, "CURRENT")
        self.assertIsNone(closed.active_lease)
        self.assertIsNone(closed.current_root_turn_tag)


if __name__ == "__main__":
    unittest.main()
