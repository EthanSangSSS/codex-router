import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from codex_router import lease_control
from codex_router import global_install as global_install_core
from codex_router import global_install_adapter
from codex_router.hook import HOOK_CONTEXT_PREFIX, handle_hook_event
from codex_router.state import RouterStateError


ROLE_CONFIG = {
    "local_sol": {
        "requested_model": "gpt-5.6-sol",
        "requested_reasoning": "max",
    },
    "web_sol": {
        "model_claimed": "sol",
        "reasoning_claimed": "xhigh",
        "verification": "operator_attested",
    },
    "luna": {
        "requested_model": "gpt-5.6-luna",
        "requested_reasoning": "max",
    },
}


class LeaseControlV4ActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installation = self.root / "installation"
        self.installation.mkdir(mode=0o700)

    def test_activate_installation_creates_empty_v4_journal_mode_0600(self):
        path = lease_control.activate_installation(self.installation)

        self.assertEqual(path, self.installation / "lease-control-v4-0.json")
        self.assertTrue(path.is_file())
        self.assertFalse(path.is_symlink())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")),
            {"protocol": "codex-router/lease-control/v4.0", "sessions": {}},
        )

    def test_activate_installation_preserves_v3_journal_and_is_idempotent(self):
        legacy = self.installation / "luna-control-v3-1.json"
        legacy_bytes = b'{"legacy":"must remain byte exact"}\n'
        legacy.write_bytes(legacy_bytes)
        legacy.chmod(0o600)

        first = lease_control.activate_installation(self.installation)
        before = first.stat().st_mtime_ns
        second = lease_control.activate_installation(self.installation)
        after = second.stat().st_mtime_ns

        self.assertEqual(first, second)
        self.assertEqual(before, after)
        self.assertEqual(legacy.read_bytes(), legacy_bytes)

    def test_activate_installation_rejects_existing_v4_symlink(self):
        real = self.installation / "real-v4.json"
        real.write_text(
            '{"protocol":"codex-router/lease-control/v4.0","sessions":{}}\n',
            encoding="utf-8",
        )
        real.chmod(0o600)
        journal = self.installation / "lease-control-v4-0.json"
        journal.symlink_to(real)

        with self.assertRaises(RouterStateError):
            lease_control.activate_installation(self.installation)

        self.assertTrue(journal.is_symlink())

    def test_activate_installation_rejects_corrupt_existing_v4_without_overwrite(self):
        journal = self.installation / "lease-control-v4-0.json"
        corrupt = b'{"protocol":"wrong","sessions":{}}\n'
        journal.write_bytes(corrupt)
        journal.chmod(0o600)

        with self.assertRaises(RouterStateError):
            lease_control.activate_installation(self.installation)

        self.assertEqual(journal.read_bytes(), corrupt)

    def test_adapter_global_install_activates_empty_v4_journal(self):
        codex_home = self.root / "codex-home"
        codex_home.mkdir(mode=0o700)
        state_root = self.root / "router-runs"
        binary = self.root / "codex"
        binary.write_text("synthetic binary", encoding="utf-8")
        binary.chmod(0o700)

        status = global_install_adapter.global_install(
            codex_home=codex_home,
            state_root=state_root,
            codex_binary=binary,
            defaults=ROLE_CONFIG,
        )

        self.assertEqual(status.state, "installed")
        managed = codex_home / global_install_core.INSTALL_DIRECTORY_NAME
        journal = managed / "lease-control-v4-0.json"
        self.assertTrue(journal.is_file())
        self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
        self.assertEqual(
            json.loads(journal.read_text(encoding="utf-8")),
            {"protocol": "codex-router/lease-control/v4.0", "sessions": {}},
        )

    def test_first_root_prompt_after_adapter_install_uses_v4_without_new_session_preseed(self):
        codex_home = self.root / "codex-home"
        codex_home.mkdir(mode=0o700)
        state_root = self.root / "router-runs"
        binary = self.root / "codex"
        binary.write_text("synthetic binary", encoding="utf-8")
        binary.chmod(0o700)
        global_install_adapter.global_install(
            codex_home=codex_home,
            state_root=state_root,
            codex_binary=binary,
            defaults=ROLE_CONFIG,
        )
        managed = codex_home / global_install_core.INSTALL_DIRECTORY_NAME

        output = handle_hook_event(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "fresh-v4-session",
                "turn_id": "root-turn-1",
                "prompt": "Implement one bounded repository change.",
                "cwd": str(self.root),
            },
            managed,
        )

        raw = output["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(raw.startswith(HOOK_CONTEXT_PREFIX))
        context = json.loads(raw[len(HOOK_CONTEXT_PREFIX) :])
        self.assertEqual(context["workflow"], "generation_lease_v4")
        snapshot = lease_control.read_snapshot(
            managed,
            (managed / "installation-secret").read_bytes(),
            "fresh-v4-session",
        )
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.generation, 0)
        self.assertIsNone(snapshot.active_lease)
        self.assertIsNotNone(snapshot.current_root_turn_tag)


if __name__ == "__main__":
    unittest.main()
