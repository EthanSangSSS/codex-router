import json
import tempfile
import unittest
from pathlib import Path

from codex_router import native_lifecycle as lifecycle
from codex_router.state import RouterStateError


class NativeLunaLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.secret = b"s" * 32

    def tearDown(self):
        self.temp.cleanup()

    def bind(self, *, turn="root-turn", agent_id="child-session"):
        lifecycle.pre_spawn(
            self.directory,
            self.secret,
            "root-session",
            turn,
            "tool-1",
            {"task_name": "luna_worker", "fork_turns": "none"},
        )
        lifecycle.post_spawn(
            self.directory,
            self.secret,
            "root-session",
            turn,
            "tool-1",
            {"task_name": "/root/luna_worker"},
        )
        lifecycle.bind_child(
            self.directory,
            self.secret,
            "root-session",
            agent_id,
            "luna_worker",
        )

    def record(self):
        state = json.loads(
            (self.directory / "native-luna-safety-v2.json").read_text(
                encoding="utf-8"
            )
        )
        return state["sessions"][lifecycle.session_tag(self.secret, "root-session")]

    def test_parent_interrupt_revokes_before_native_attempt_and_cannot_repeat(self):
        self.bind()
        lifecycle.begin_interrupt(
            self.directory,
            self.secret,
            "root-session",
            "root-turn",
            "interrupt_agent",
            {"target": "/root/luna_worker"},
        )
        with self.assertRaises(RouterStateError):
            lifecycle.authorize_luna(
                self.directory,
                self.secret,
                "root-session",
                "child-session",
            )
        with self.assertRaises(RouterStateError):
            lifecycle.begin_interrupt(
                self.directory,
                self.secret,
                "root-session",
                "root-turn",
                "interrupt_agent",
                {"target": "/root/luna_worker"},
            )
        self.assertEqual(self.record()["authorization"], "REVOKED")
        self.assertNotIn("cleanup", self.record())

    def test_spawn_response_mismatch_durably_revokes(self):
        lifecycle.pre_spawn(
            self.directory,
            self.secret,
            "root-session",
            "root-turn",
            "tool-1",
            {"task_name": "luna_worker", "fork_turns": "none"},
        )
        with self.assertRaises(RouterStateError):
            lifecycle.post_spawn(
                self.directory,
                self.secret,
                "root-session",
                "root-turn",
                "tool-1",
                {"task_name": "/root/other"},
            )
        self.assertEqual(self.record()["authorization"], "REVOKED")

    def test_duplicate_child_binding_durably_revokes(self):
        self.bind()
        with self.assertRaises(RouterStateError):
            lifecycle.bind_child(
                self.directory,
                self.secret,
                "root-session",
                "other-child",
                "luna_worker",
            )
        self.assertEqual(self.record()["authorization"], "REVOKED")

    def test_stop_revokes_idempotently_without_stop_state(self):
        self.bind()
        self.assertTrue(
            lifecycle.stop_once(
                self.directory, self.secret, "root-session", "root-turn"
            )
        )
        self.assertEqual(self.record()["authorization"], "REVOKED")
        self.assertNotIn("stop_blocked", self.record())
        self.assertFalse(
            lifecycle.stop_once(
                self.directory, self.secret, "root-session", "root-turn"
            )
        )

    def test_stop_revocation_does_not_authorize_cleanup_after_terminal_boundary(self):
        self.bind()
        lifecycle.stop_once(
            self.directory, self.secret, "root-session", "root-turn"
        )
        with self.assertRaises(RouterStateError):
            lifecycle.begin_interrupt(
                self.directory,
                self.secret,
                "root-session",
                "root-turn",
                "interrupt_agent",
                {"target": "child-session"},
            )

    def test_unknown_agent_id_is_denied_without_authorizing_by_role_text(self):
        self.bind()
        with self.assertRaises(RouterStateError):
            lifecycle.authorize_luna(
                self.directory,
                self.secret,
                "root-session",
                "historical-or-other-child",
            )
        self.assertEqual(self.record()["authorization"], "ACTIVE")

    def test_parent_message_is_limited_to_bound_luna(self):
        self.bind()
        lifecycle.authorize_parent_operation(
            self.directory,
            self.secret,
            "root-session",
            "root-turn",
            "send_message",
            {"target": "/root/luna_worker"},
        )
        with self.assertRaises(RouterStateError):
            lifecycle.authorize_parent_operation(
                self.directory,
                self.secret,
                "root-session",
                "root-turn",
                "send_message",
                {"target": "/root/other"},
            )

    def test_malformed_journal_fails_closed(self):
        self.bind()
        journal = self.directory / "native-luna-safety-v2.json"
        journal.write_text(
            '{"protocol":"codex-router/native-luna-safety-v2","sessions":{"bad":{}}}',
            encoding="utf-8",
        )
        journal.chmod(0o600)
        with self.assertRaises(RouterStateError):
            lifecycle.authorize_luna(
                self.directory,
                self.secret,
                "root-session",
                "child-session",
            )


if __name__ == "__main__":
    unittest.main()
