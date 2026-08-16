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

    def tearDown(self): self.temp.cleanup()

    def bind(self):
        lifecycle.pre_spawn(self.directory, self.secret, "root-session", "root-turn", "tool-1", {"task_name": "luna_worker"})
        lifecycle.post_spawn(self.directory, self.secret, "root-session", "root-turn", "tool-1", {"task_name": "/root/luna_worker"})
        lifecycle.bind_child(self.directory, self.secret, {"agent_id": "child-session", "agent_type": "luna_worker"}, {"parent_thread_id": "root-session", "agent_path": "/root/luna_worker"})

    def test_bind_then_interrupt_revokes_before_single_native_attempt(self):
        self.bind()
        lifecycle.begin_interrupt(self.directory, self.secret, "root-session", "root-turn", {"task_name": "/root/luna_worker"})
        with self.assertRaises(RouterStateError): lifecycle.authorize_luna(self.directory, self.secret, "child-session")
        with self.assertRaises(RouterStateError): lifecycle.begin_interrupt(self.directory, self.secret, "root-session", "root-turn", {"task_name": "/root/luna_worker"})
        lifecycle.finish_interrupt(self.directory, self.secret, "root-session", "root-turn", {"previous_status": "running"})

    def test_spawn_response_mismatch_revokes(self):
        lifecycle.pre_spawn(self.directory, self.secret, "root-session", "root-turn", "tool-1", {"task_name": "luna_worker"})
        with self.assertRaises(RouterStateError): lifecycle.post_spawn(self.directory, self.secret, "root-session", "root-turn", "tool-1", {"task_name": "/root/other"})

    def test_stop_blocks_only_once(self):
        self.bind()
        self.assertTrue(lifecycle.stop_once(self.directory, self.secret, "root-session", "root-turn"))
        self.assertFalse(lifecycle.stop_once(self.directory, self.secret, "root-session", "root-turn"))

    def test_parent_message_is_limited_to_bound_luna(self):
        self.bind()
        lifecycle.authorize_parent_operation(self.directory, self.secret, "root-session", "root-turn", {"task_name": "/root/luna_worker"})
        with self.assertRaises(RouterStateError): lifecycle.authorize_parent_operation(self.directory, self.secret, "root-session", "root-turn", {"task_name": "/root/other"})

    def test_hmac_tamper_fails_closed(self):
        self.bind()
        journal = self.directory / "native-luna-safety-v2.json"
        journal.write_text('{"protocol":"codex-router/native-luna-safety-v2","bindings":{}}')
        journal.chmod(0o600)
        with self.assertRaises(RouterStateError): lifecycle.authorize_luna(self.directory, self.secret, "child-session")
