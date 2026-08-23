import tempfile
import unittest
from pathlib import Path

from codex_router import lease_control as control
from codex_router.protocol import build_luna_packet
from codex_router.state import RouterStateError


class LeaseControlV4RootAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.secret = b"v4-root-authority-secret-material!!"
        self.session_id = "root-session"
        self.snapshot = control.initialize_session(
            self.directory, self.secret, self.session_id
        )

    def packet(self, *, generation=1, packet_id="packet-1"):
        return build_luna_packet(
            packet_id=packet_id,
            generation=generation,
            objective="root-authorized V4 work",
            working_directory="/workspace/repo",
            intended_write_scope=["src/example.py"],
            explicit_side_effect_authorizations=[],
            success_criteria=["stage succeeds"],
            stop_conditions=["root turn changes"],
        )

    def test_new_v4_session_has_no_current_root_turn(self):
        self.assertIsNone(self.snapshot.current_root_turn_tag)

    def test_setting_current_root_turn_persists_an_opaque_tag(self):
        updated = control.set_current_root_turn(
            self.directory,
            self.secret,
            self.session_id,
            turn_id="root-turn-1",
        )

        self.assertRegex(updated.current_root_turn_tag, r"^[0-9a-f]{64}$")
        self.assertEqual(
            control.read_snapshot(self.directory, self.secret, self.session_id),
            updated,
        )

    def test_stage_capability_is_bound_to_current_root_and_next_generation(self):
        current = control.set_current_root_turn(
            self.directory,
            self.secret,
            self.session_id,
            turn_id="root-turn-1",
        )
        capability = control.build_stage_capability(
            self.secret, current, root_turn_id="root-turn-1"
        )

        control.verify_stage_capability(
            self.secret,
            current,
            root_turn_id="root-turn-1",
            capability=capability,
        )
        self.assertRegex(capability, r"^v4s1\.[0-9a-f]{64}$")

    def test_new_root_turn_invalidates_old_stage_capability_before_generation_moves(self):
        first = control.set_current_root_turn(
            self.directory,
            self.secret,
            self.session_id,
            turn_id="root-turn-1",
        )
        old_capability = control.build_stage_capability(
            self.secret, first, root_turn_id="root-turn-1"
        )
        second = control.set_current_root_turn(
            self.directory,
            self.secret,
            self.session_id,
            turn_id="root-turn-2",
        )
        self.assertEqual(second.generation, first.generation)

        with self.assertRaises(RouterStateError):
            control.verify_stage_capability(
                self.secret,
                second,
                root_turn_id="root-turn-1",
                capability=old_capability,
            )

    def test_clearing_current_root_invalidates_old_stage_capability(self):
        current = control.set_current_root_turn(
            self.directory,
            self.secret,
            self.session_id,
            turn_id="root-turn-1",
        )
        capability = control.build_stage_capability(
            self.secret, current, root_turn_id="root-turn-1"
        )
        cleared = control.set_current_root_turn(
            self.directory,
            self.secret,
            self.session_id,
            turn_id=None,
        )

        self.assertIsNone(cleared.current_root_turn_tag)
        with self.assertRaises(RouterStateError):
            control.verify_stage_capability(
                self.secret,
                cleared,
                root_turn_id="root-turn-1",
                capability=capability,
            )

    def test_authorized_stage_is_atomic_to_current_root_and_capability(self):
        current = control.set_current_root_turn(
            self.directory,
            self.secret,
            self.session_id,
            turn_id="root-turn-1",
        )
        capability = control.build_stage_capability(
            self.secret, current, root_turn_id="root-turn-1"
        )

        staged = control.stage_authorized_lease(
            self.directory,
            self.secret,
            self.session_id,
            root_turn_id="root-turn-1",
            capability=capability,
            packet_wire=self.packet(generation=1),
        )

        self.assertEqual(staged.generation, 1)
        self.assertEqual(staged.active_lease.generation, 1)
        self.assertEqual(staged.current_root_turn_tag, current.current_root_turn_tag)

    def test_stale_root_cannot_stage_after_supersession(self):
        first = control.set_current_root_turn(
            self.directory,
            self.secret,
            self.session_id,
            turn_id="root-turn-1",
        )
        old_capability = control.build_stage_capability(
            self.secret, first, root_turn_id="root-turn-1"
        )
        control.set_current_root_turn(
            self.directory,
            self.secret,
            self.session_id,
            turn_id="root-turn-2",
        )
        before = control.read_snapshot(
            self.directory, self.secret, self.session_id
        )

        with self.assertRaises(RouterStateError):
            control.stage_authorized_lease(
                self.directory,
                self.secret,
                self.session_id,
                root_turn_id="root-turn-1",
                capability=old_capability,
                packet_wire=self.packet(generation=1),
            )

        self.assertEqual(
            control.read_snapshot(self.directory, self.secret, self.session_id),
            before,
        )


if __name__ == "__main__":
    unittest.main()
