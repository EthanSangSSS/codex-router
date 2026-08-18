import subprocess
import tempfile
import unittest
from pathlib import Path

from codex_router import luna_control as control
from codex_router.state import RouterStateError


class QuarantinedRecoveryEdgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.state.chmod(0o700)
        self.secret = b"v3-control-secret-material-32bytes!"
        self.session = "root-session"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init")
        self.git("config", "user.email", "router-tests@example.invalid")
        self.git("config", "user.name", "Router Tests")
        (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-m", "baseline")
        control.new_task(
            self.state,
            self.secret,
            self.session,
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        control.reserve_spawn(
            self.state,
            self.secret,
            self.session,
            tool_use_id="spawn-1",
            task_name="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.state,
            self.secret,
            self.session,
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )
        control.observe_subagent_start(
            self.state,
            self.secret,
            self.session,
            agent_id="agent-1",
            agent_type="luna_worker",
        )

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def begin(self):
        return control.begin_packet(
            self.state,
            self.secret,
            self.session,
            packet_id="packet-1",
            objective="edge proof",
            working_directory=str(self.repo),
            intended_write_scope=("tracked.txt",),
            explicit_side_effect_authorizations=(),
            success_criteria=("done",),
            stop_conditions=("blocked",),
        )

    def quarantine(self):
        control.freeze_authority(
            self.state,
            self.secret,
            self.session,
            reason="replacement",
        )
        return control.quarantine_execution(
            self.state,
            self.secret,
            self.session,
            reason="settlement_unobservable",
        )

    def test_start_execution_drops_recovery_baseline_if_workspace_changed_after_capture(self):
        packet = self.begin()
        self.assertIsNotNone(packet.recovery_baseline)
        (self.repo / "tracked.txt").write_text("user changed before start\n", encoding="utf-8")

        started = control.start_execution(
            self.state,
            self.secret,
            self.session,
            child_turn_id="turn-1",
        )

        self.assertEqual(started.execution_status, "RUNNING")
        self.assertIsNone(started.recovery_baseline)

    def test_quarantined_luna_allows_cleanup_target_but_never_parent_work(self):
        self.begin()
        control.start_execution(
            self.state,
            self.secret,
            self.session,
            child_turn_id="turn-1",
        )
        quarantined = self.quarantine()
        self.assertEqual(quarantined.execution_status, "QUARANTINED")

        control.authorize_parent_target(
            self.state,
            self.secret,
            self.session,
            tool_name="interrupt_agent",
            target="agent-1",
        )
        control.authorize_parent_target(
            self.state,
            self.secret,
            self.session,
            tool_name="close_agent",
            target="/root/luna_worker",
        )
        with self.assertRaises(RouterStateError):
            control.authorize_parent_target(
                self.state,
                self.secret,
                self.session,
                tool_name="send_message",
                target="agent-1",
            )


if __name__ == "__main__":
    unittest.main()
