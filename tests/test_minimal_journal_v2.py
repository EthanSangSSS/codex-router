import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_router import native_lifecycle as lifecycle
from codex_router.hook import handle_hook_event
from codex_router.state import RouterStateError


ROLE_CONFIG = {
    "local_sol": {"requested_model": "gpt-5.6-sol", "requested_reasoning": "max"},
    "web_sol": {
        "model_claimed": "sol",
        "reasoning_claimed": "xhigh",
        "verification": "operator_attested",
    },
    "luna": {"requested_model": "gpt-5.6-luna", "requested_reasoning": "max"},
}


class MinimalJournalV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.secret = b"j" * 32
        secret_path = self.directory / "installation-secret"
        secret_path.write_bytes(self.secret)
        secret_path.chmod(0o600)
        self.assertEqual(stat.S_IMODE(secret_path.stat().st_mode), 0o600)
        binary = self.directory / "codex"
        binary.write_text("synthetic binary", encoding="utf-8")
        binary.chmod(0o700)
        config_path = self.directory / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "protocol": "codex-router/global-policy-config/v1",
                    "state_root": str(self.directory / "runs"),
                    "codex_binary": str(binary),
                    "role_config": ROLE_CONFIG,
                }
            ),
            encoding="utf-8",
        )
        config_path.chmod(0o600)

    def _spawn_and_bind(self, session="session-a", turn="turn-a", agent="luna-a"):
        lifecycle.pre_spawn(
            self.directory,
            self.secret,
            session,
            turn,
            "spawn-1",
            {"task_name": "luna_worker", "fork_turns": "none"},
        )
        lifecycle.bind_child(
            self.directory,
            self.secret,
            session,
            agent,
            "luna_worker",
        )

    def test_stop_is_revoke_only_and_never_requests_continuation(self):
        self._spawn_and_bind()
        output = handle_hook_event(
            {
                "hook_event_name": "Stop",
                "session_id": "session-a",
                "turn_id": "turn-a",
            },
            self.directory,
        )
        self.assertEqual(output, {})
        with self.assertRaises(RouterStateError):
            lifecycle.authorize_luna(
                self.directory, self.secret, "session-a", "luna-a"
            )

    def test_security_journal_does_not_persist_cleanup_stop_or_raw_scope_ids(self):
        self._spawn_and_bind()
        raw = (self.directory / "native-luna-safety-v2.json").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("session-a", raw)
        self.assertNotIn("turn-a", raw)
        state = json.loads(raw)
        serialized = json.dumps(state, sort_keys=True)
        self.assertNotIn("cleanup", serialized)
        self.assertNotIn("stop_blocked", serialized)

    def test_read_only_authorization_does_not_replace_or_rewrite_journal(self):
        self._spawn_and_bind()
        path = self.directory / "native-luna-safety-v2.json"
        before = path.stat()
        lifecycle.authorize_luna(
            self.directory, self.secret, "session-a", "luna-a"
        )
        after = path.stat()
        self.assertEqual(after.st_ino, before.st_ino)
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(after.st_size, before.st_size)

    def test_new_root_compacts_same_session_history(self):
        self._spawn_and_bind(turn="turn-old", agent="luna-old")
        lifecycle.revoke_stale(
            self.directory,
            self.secret,
            "session-a",
            "turn-new",
        )
        lifecycle.pre_spawn(
            self.directory,
            self.secret,
            "session-a",
            "turn-new",
            "spawn-new",
            {"task_name": "luna_worker", "fork_turns": "none"},
        )
        state = json.loads(
            (self.directory / "native-luna-safety-v2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(state["sessions"]), 1)
        with self.assertRaises(RouterStateError):
            lifecycle.authorize_luna(
                self.directory, self.secret, "session-a", "luna-old"
            )

    def test_distinct_sessions_can_each_hold_one_active_luna(self):
        self._spawn_and_bind(session="session-a", turn="turn-a", agent="luna-a")
        self._spawn_and_bind(session="session-b", turn="turn-b", agent="luna-b")
        lifecycle.authorize_luna(self.directory, self.secret, "session-a", "luna-a")
        lifecycle.authorize_luna(self.directory, self.secret, "session-b", "luna-b")

    def test_security_transition_fsyncs_containing_directory(self):
        with mock.patch.object(lifecycle, "_fsync_directory") as fsync_directory:
            lifecycle.pre_spawn(
                self.directory,
                self.secret,
                "session-a",
                "turn-a",
                "spawn-1",
                {"task_name": "luna_worker", "fork_turns": "none"},
            )
        fsync_directory.assert_called_with(self.directory)


if __name__ == "__main__":
    unittest.main()
