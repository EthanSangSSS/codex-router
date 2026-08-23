import tempfile
import unittest
from pathlib import Path

from codex_router import lease_control as control
from codex_router.protocol import build_luna_packet
from codex_router.state import RouterStateError


class LeaseControlV4BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.secret = b"v4-bootstrap-secret-material-32bytes"
        self.session_id = "root-session"
        control.initialize_session(self.directory, self.secret, self.session_id)

    def stage(self, *, generation=1, packet_id="packet-1"):
        return control.stage_lease(
            self.directory,
            self.secret,
            self.session_id,
            root_turn_id=f"root-turn-{generation}",
            packet_wire=build_luna_packet(
                packet_id=packet_id,
                generation=generation,
                objective="bootstrap current V4 worker",
                working_directory="/workspace/repo",
                intended_write_scope=["src/example.py"],
                explicit_side_effect_authorizations=[],
                success_criteria=["bootstrap accepted"],
                stop_conditions=["identity mismatch"],
            ),
        )

    def current_capability(self, snapshot):
        return control.build_bootstrap_capability(self.secret, snapshot.active_lease)

    def test_current_capability_bootstrap_binds_native_agent_and_child_turn(self):
        staged = self.stage()
        capability = self.current_capability(staged)

        updated, k1 = control.authorize_executor_tool(
            self.directory,
            self.secret,
            self.session_id,
            agent_id="agent-current",
            agent_type="luna_worker",
            child_turn_id="child-turn-current",
            bootstrap_capability=capability,
        )

        self.assertEqual(updated.active_lease.status, "ACTIVE")
        self.assertEqual(updated.active_lease.worker_agent_id, "agent-current")
        self.assertEqual(updated.active_lease.child_turn_id, "child-turn-current")
        self.assertEqual(k1, staged.active_lease.authority_packet_wire)

    def test_old_capability_cannot_bind_new_generation(self):
        first = self.stage(generation=1, packet_id="packet-1")
        old_capability = self.current_capability(first)
        control.revoke_current_lease(self.directory, self.secret, self.session_id)
        second = self.stage(generation=2, packet_id="packet-2")
        before = control.read_snapshot(self.directory, self.secret, self.session_id)

        with self.assertRaises(RouterStateError):
            control.authorize_executor_tool(
                self.directory,
                self.secret,
                self.session_id,
                agent_id="agent-old",
                agent_type="luna_worker",
                child_turn_id="child-old",
                bootstrap_capability=old_capability,
            )

        self.assertEqual(control.read_snapshot(self.directory, self.secret, self.session_id), before)
        self.assertIsNone(second.active_lease.worker_agent_id)

    def test_wrong_or_missing_capability_does_not_bind_worker(self):
        staged = self.stage()
        before = control.read_snapshot(self.directory, self.secret, self.session_id)
        invalid = (None, "v4b1." + "0" * 64)

        for capability in invalid:
            with self.subTest(capability=capability):
                with self.assertRaises(RouterStateError):
                    control.authorize_executor_tool(
                        self.directory,
                        self.secret,
                        self.session_id,
                        agent_id="agent-current",
                        agent_type="luna_worker",
                        child_turn_id="child-turn-current",
                        bootstrap_capability=capability,
                    )
                self.assertEqual(
                    control.read_snapshot(self.directory, self.secret, self.session_id),
                    before,
                )
        self.assertIsNone(staged.active_lease.worker_agent_id)

    def test_wrong_agent_type_does_not_bind_worker(self):
        staged = self.stage()
        capability = self.current_capability(staged)

        with self.assertRaises(RouterStateError):
            control.authorize_executor_tool(
                self.directory,
                self.secret,
                self.session_id,
                agent_id="agent-current",
                agent_type="reviewer",
                child_turn_id="child-turn-current",
                bootstrap_capability=capability,
            )

        current = control.read_snapshot(self.directory, self.secret, self.session_id)
        self.assertIsNone(current.active_lease.worker_agent_id)

    def test_bound_worker_later_tool_needs_exact_agent_and_child_turn(self):
        staged = self.stage()
        capability = self.current_capability(staged)
        bound, _ = control.authorize_executor_tool(
            self.directory,
            self.secret,
            self.session_id,
            agent_id="agent-current",
            agent_type="luna_worker",
            child_turn_id="child-turn-current",
            bootstrap_capability=capability,
        )

        same, k1 = control.authorize_executor_tool(
            self.directory,
            self.secret,
            self.session_id,
            agent_id="agent-current",
            agent_type="luna_worker",
            child_turn_id="child-turn-current",
            bootstrap_capability=None,
        )
        self.assertEqual(same, bound)
        self.assertIsNone(k1)

        for agent_id, child_turn_id in (
            ("agent-wrong", "child-turn-current"),
            ("agent-current", "child-turn-wrong"),
        ):
            with self.subTest(agent_id=agent_id, child_turn_id=child_turn_id):
                with self.assertRaises(RouterStateError):
                    control.authorize_executor_tool(
                        self.directory,
                        self.secret,
                        self.session_id,
                        agent_id=agent_id,
                        agent_type="luna_worker",
                        child_turn_id=child_turn_id,
                        bootstrap_capability=None,
                    )

    def test_revoked_or_absent_lease_denies_luna_tool(self):
        staged = self.stage()
        capability = self.current_capability(staged)
        control.revoke_current_lease(self.directory, self.secret, self.session_id)

        with self.assertRaises(RouterStateError):
            control.authorize_executor_tool(
                self.directory,
                self.secret,
                self.session_id,
                agent_id="agent-old",
                agent_type="luna_worker",
                child_turn_id="child-old",
                bootstrap_capability=capability,
            )


if __name__ == "__main__":
    unittest.main()
