import json
import tempfile
import unittest
from pathlib import Path

from codex_router import lease_control as control
from codex_router.protocol import build_luna_packet
from codex_router.state import RouterStateError


class LeaseControlV4TerminalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.directory.chmod(0o700)
        self.secret = b"v4-terminal-secret-material-32bytes!"
        self.session_id = "session-v4-terminal"
        control.initialize_session(self.directory, self.secret, self.session_id)

    def stage_and_bind(
        self,
        *,
        generation=1,
        packet_id="packet-1",
        agent_id="agent-1",
        child_turn_id="child-turn-1",
    ):
        staged = control.stage_lease(
            self.directory,
            self.secret,
            self.session_id,
            root_turn_id=f"root-turn-{generation}",
            packet_wire=build_luna_packet(
                packet_id=packet_id,
                generation=generation,
                objective="bounded terminal reconciliation",
                working_directory="/workspace/repo",
                intended_write_scope=["src/example.py"],
                explicit_side_effect_authorizations=[],
                success_criteria=["terminal is reconciled"],
                stop_conditions=["identity mismatch"],
            ),
        )
        capability = control.build_bootstrap_capability(
            self.secret, staged.active_lease
        )
        bound, _ = control.authorize_executor_tool(
            self.directory,
            self.secret,
            self.session_id,
            agent_id=agent_id,
            agent_type="luna_worker",
            child_turn_id=child_turn_id,
            bootstrap_capability=capability,
        )
        return bound

    def test_current_exact_subagent_stop_closes_current_lease(self):
        bound = self.stage_and_bind()

        closed, disposition = control.observe_subagent_stop(
            self.directory,
            self.secret,
            self.session_id,
            agent_id="agent-1",
            agent_type="luna_worker",
            child_turn_id="child-turn-1",
        )

        self.assertEqual(disposition, "CURRENT")
        self.assertEqual(closed.generation, bound.generation)
        self.assertIsNone(closed.active_lease)
        self.assertEqual(
            control.read_snapshot(self.directory, self.secret, self.session_id),
            closed,
        )

    def test_stale_previous_generation_stop_does_not_clear_new_lease(self):
        self.stage_and_bind(
            generation=1,
            packet_id="packet-1",
            agent_id="agent-old",
            child_turn_id="child-old",
        )
        control.revoke_current_lease(self.directory, self.secret, self.session_id)
        second = control.stage_lease(
            self.directory,
            self.secret,
            self.session_id,
            root_turn_id="root-turn-2",
            packet_wire=build_luna_packet(
                packet_id="packet-2",
                generation=2,
                objective="new generation",
                working_directory="/workspace/repo",
                intended_write_scope=["src/new.py"],
                explicit_side_effect_authorizations=[],
                success_criteria=["new lease remains"],
                stop_conditions=["stale terminal"],
            ),
        )

        after, disposition = control.observe_subagent_stop(
            self.directory,
            self.secret,
            self.session_id,
            agent_id="agent-old",
            agent_type="luna_worker",
            child_turn_id="child-old",
        )

        self.assertEqual(disposition, "STALE")
        self.assertEqual(after, second)
        self.assertEqual(
            control.read_snapshot(self.directory, self.secret, self.session_id),
            second,
        )

    def test_duplicate_old_stop_is_noop(self):
        self.stage_and_bind()
        first, first_disposition = control.observe_subagent_stop(
            self.directory,
            self.secret,
            self.session_id,
            agent_id="agent-1",
            agent_type="luna_worker",
            child_turn_id="child-turn-1",
        )

        second, second_disposition = control.observe_subagent_stop(
            self.directory,
            self.secret,
            self.session_id,
            agent_id="agent-1",
            agent_type="luna_worker",
            child_turn_id="child-turn-1",
        )

        self.assertEqual(first_disposition, "CURRENT")
        self.assertEqual(second_disposition, "NOOP")
        self.assertEqual(second, first)

    def test_wrong_agent_or_child_turn_stop_does_not_clear_current_lease(self):
        bound = self.stage_and_bind()
        cases = (
            ("agent-wrong", "child-turn-1"),
            ("agent-1", "child-wrong"),
        )
        for agent_id, child_turn_id in cases:
            with self.subTest(agent_id=agent_id, child_turn_id=child_turn_id):
                after, disposition = control.observe_subagent_stop(
                    self.directory,
                    self.secret,
                    self.session_id,
                    agent_id=agent_id,
                    agent_type="luna_worker",
                    child_turn_id=child_turn_id,
                )
                self.assertEqual(disposition, "STALE")
                self.assertEqual(after, bound)
                self.assertEqual(
                    control.read_snapshot(
                        self.directory, self.secret, self.session_id
                    ),
                    bound,
                )

    def test_missing_subagent_stop_does_not_block_next_generation(self):
        first = self.stage_and_bind()
        control.revoke_current_lease(self.directory, self.secret, self.session_id)

        second = control.stage_lease(
            self.directory,
            self.secret,
            self.session_id,
            root_turn_id="root-turn-2",
            packet_wire=build_luna_packet(
                packet_id="packet-2",
                generation=2,
                objective="continue without old terminal event",
                working_directory="/workspace/repo",
                intended_write_scope=["src/new.py"],
                explicit_side_effect_authorizations=[],
                success_criteria=["generation two stages"],
                stop_conditions=["none"],
            ),
        )

        self.assertEqual(first.generation, 1)
        self.assertEqual(second.generation, 2)
        self.assertIsNotNone(second.active_lease)

    def test_corrupt_current_active_identity_fails_closed_instead_of_fake_cleanup(self):
        staged = control.stage_lease(
            self.directory,
            self.secret,
            self.session_id,
            root_turn_id="root-turn-1",
            packet_wire=build_luna_packet(
                packet_id="packet-1",
                generation=1,
                objective="corrupt test fixture",
                working_directory="/workspace/repo",
                intended_write_scope=["src/example.py"],
                explicit_side_effect_authorizations=[],
                success_criteria=["must fail closed"],
                stop_conditions=["corrupt identity"],
            ),
        )
        journal = self.directory / "lease-control-v4-0.json"
        value = json.loads(journal.read_text(encoding="utf-8"))
        record = value["sessions"][staged.root_session_tag]
        record["active_lease"]["status"] = "ACTIVE"
        record["active_lease"]["worker_agent_id"] = None
        record["active_lease"]["child_turn_id"] = None
        journal.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        journal.chmod(0o600)

        with self.assertRaises(RouterStateError):
            control.observe_subagent_stop(
                self.directory,
                self.secret,
                self.session_id,
                agent_id="agent-1",
                agent_type="luna_worker",
                child_turn_id="child-turn-1",
            )


if __name__ == "__main__":
    unittest.main()
