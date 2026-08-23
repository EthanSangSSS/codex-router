import json
import tempfile
import unittest
from pathlib import Path

from codex_router import global_install_adapter, lease_control
from codex_router.hook import HOOK_CONTEXT_PREFIX, handle_hook_event


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


class V4V2MessageVisibilityContractTests(unittest.TestCase):
    def test_root_context_declares_v2_message_opaque_and_bootstrap_authoritative(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installation = root / "installation"
            installation.mkdir(mode=0o700)
            secret = bytes(range(32))
            (installation / "installation-secret").write_bytes(secret)
            (installation / "installation-secret").chmod(0o600)
            binary = root / "codex"
            binary.write_text("synthetic", encoding="utf-8")
            binary.chmod(0o700)
            (installation / "config.json").write_text(
                json.dumps(
                    {
                        "protocol": "codex-router/global-policy-config/v1",
                        "state_root": str(installation),
                        "codex_binary": str(binary),
                        "role_config": ROLE_CONFIG,
                    }
                ),
                encoding="utf-8",
            )
            (installation / "config.json").chmod(0o600)
            session_id = "session-v2-message-visibility"
            lease_control.initialize_session(installation, secret, session_id)

            output = handle_hook_event(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": session_id,
                    "turn_id": "root-turn-v2-message-visibility",
                    "prompt": "Implement one bounded repository change.",
                    "cwd": str(root),
                },
                installation,
            )
            raw = output["hookSpecificOutput"]["additionalContext"]
            self.assertTrue(raw.startswith(HOOK_CONTEXT_PREFIX))
            context = json.loads(raw[len(HOOK_CONTEXT_PREFIX) :])

            self.assertEqual(
                context["V2_PARENT_MESSAGE_PRETOOL_VISIBILITY"],
                "encrypted_opaque_not_plaintext_verifiable",
            )
            self.assertEqual(
                context["V2_AUTHORITY_GATE"],
                "first_child_capability_bootstrap",
            )
            self.assertIn("encrypted", context["spawn_contract"].lower())
            self.assertIn("first child", context["spawn_contract"].lower())

    def test_installed_primary_policy_declares_same_v2_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / "codex-home"
            codex_home.mkdir(mode=0o700)
            binary = root / "codex"
            binary.write_text("synthetic", encoding="utf-8")
            binary.chmod(0o700)

            global_install_adapter.global_install(
                codex_home=codex_home,
                state_root=root / "router-runs",
                codex_binary=binary,
                defaults=ROLE_CONFIG,
            )
            agents = (codex_home / "AGENTS.md").read_text(encoding="utf-8")

            self.assertIn("V2 parent PreToolUse", agents)
            self.assertIn("encrypted opaque", agents)
            self.assertIn("cannot mechanically compare its plaintext", agents)
            self.assertIn("does not grant worker authority", agents)
            self.assertIn("first child capability bootstrap", agents)


if __name__ == "__main__":
    unittest.main()
