import tempfile
import unittest
from pathlib import Path

from codex_router import luna_control as control
from codex_router.state import RouterStateError


class V31ReplacementReasonGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.secret = bytes(range(32))
        control.new_task(
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
        control.observe_subagent_start(
            self.directory,
            self.secret,
            "root-session",
            agent_id="agent-1",
            agent_type="luna_worker",
        )

    def _retire(self, reason):
        return control.retire_luna(
            self.directory,
            self.secret,
            "root-session",
            reason=reason,
        )

    def test_non_profile_replacement_reason_cannot_change_authority_profile(self):
        retired = self._retire("runtime_validated_context_reset")
        self.assertEqual(retired.native_authority_profile, "profile-A")

        with self.assertRaises(RouterStateError):
            control.replace_luna_epoch(
                self.directory,
                self.secret,
                "root-session",
                native_parent_identity="root-parent",
                native_authority_profile="profile-B",
                reason="runtime_validated_context_reset",
            )

        current = control.read_snapshot(
            self.directory,
            self.secret,
            "root-session",
        )
        self.assertEqual(current, retired)

    def test_profile_change_reason_may_change_authority_profile(self):
        retired = self._retire("native_authority_profile_change")
        replacement = control.replace_luna_epoch(
            self.directory,
            self.secret,
            "root-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-B",
            reason="native_authority_profile_change",
        )
        self.assertEqual(replacement.task_epoch, retired.task_epoch)
        self.assertEqual(replacement.native_authority_profile, "profile-B")


if __name__ == "__main__":
    unittest.main()
