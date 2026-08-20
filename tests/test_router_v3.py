import tempfile
import unittest
from pathlib import Path

from codex_router import luna_control as control
from codex_router.state import RouterStateError


class RouterV3SettlementGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.secret = b"v3-router-settlement-secret-32bytes!"
        control.new_task(
            directory=self.directory,
            secret=self.secret,
            session_id="root-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        control.begin_packet(
            self.directory,
            self.secret,
            "root-session",
            packet_id="packet-1",
            objective="bounded execution",
            working_directory="/workspace/repo",
            intended_write_scope=("src/math.py",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )
        control.start_execution(
            self.directory,
            self.secret,
            "root-session",
            child_turn_id="turn-1",
        )
        try:
            freeze_authority = control.freeze_authority
        except AttributeError:
            self.fail("V3.1 authority-pause API is not implemented")
        freeze_authority(
            self.directory,
            self.secret,
            "root-session",
            reason="user_pause",
        )

    def test_interrupt_ack_or_unverified_source_cannot_settle(self):
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

        try:
            observe_settlement = control.observe_settlement
        except AttributeError:
            self.fail("V3.1 settlement API is not implemented")
        with self.assertRaises(RouterStateError):
            observe_settlement(
                self.directory,
                self.secret,
                "root-session",
                source="interrupt_ack",
                terminal_status="interrupted",
                child_turn_id="turn-1",
            )

        current = control.read_snapshot(self.directory, self.secret, "root-session")
        self.assertEqual(current.execution_status, "QUIESCING")


class RouterV3HookBridgeTests(unittest.TestCase):
    def test_hook_bridge_uses_v31_luna_control(self):
        hook_source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "codex_router"
            / "hook.py"
        ).read_text(encoding="utf-8")
        self.assertIn("luna_control", hook_source)

    def test_cli_keeps_legacy_stop_and_permission_entry_points_callable(self):
        from codex_router.cli import parser

        subcommands = parser()._subparsers._group_actions[0].choices
        self.assertIn("hook-stop", subcommands)
        self.assertIn("hook-permission-request", subcommands)


if __name__ == "__main__":
    unittest.main()
