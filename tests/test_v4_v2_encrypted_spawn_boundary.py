import argparse
import json
import tempfile
import unittest
from pathlib import Path

from codex_router import lease_control
from codex_router.cli import _stage_k1_fields
from codex_router.hook import HOOK_CONTEXT_PREFIX, handle_hook_event


class V4V2EncryptedSpawnBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installation = self.root / "installation"
        self.installation.mkdir(mode=0o700)
        self.secret = bytes(range(32))
        (self.installation / "installation-secret").write_bytes(self.secret)
        (self.installation / "installation-secret").chmod(0o600)
        binary = self.root / "codex"
        binary.write_text("synthetic", encoding="utf-8")
        binary.chmod(0o700)
        (self.installation / "config.json").write_text(
            json.dumps(
                {
                    "protocol": "codex-router/global-policy-config/v1",
                    "state_root": str(self.installation),
                    "codex_binary": str(binary),
                    "role_config": {
                        "local_sol": {
                            "requested_model": "inherit",
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
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.installation / "config.json").chmod(0o600)
        self.session_id = "session-v4-v2-encrypted"
        lease_control.initialize_session(
            self.installation, self.secret, self.session_id
        )

    def context(self, output):
        raw = output["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(raw.startswith(HOOK_CONTEXT_PREFIX))
        return json.loads(raw[len(HOOK_CONTEXT_PREFIX) :])

    def route_and_stage(self):
        turn_id = "root-turn-v2-encrypted"
        route = handle_hook_event(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": self.session_id,
                "turn_id": turn_id,
                "prompt": "Implement bounded generation one work.",
                "cwd": str(self.root),
            },
            self.installation,
        )
        context = self.context(route)
        result = _stage_k1_fields(
            argparse.Namespace(
                installation_dir=self.installation,
                session_id=self.session_id,
                root_turn_id=turn_id,
                capability=context["K1_STAGE_CAPABILITY"],
                packet_id="packet-v2-encrypted",
                objective="bounded V2 encrypted-message work",
                working_directory=str(self.root),
                intended_write_scope=[],
                explicit_side_effect_authorization=[],
                success_criterion=["read-only result returned"],
                stop_condition=["scope expansion required"],
            )
        )
        return turn_id, result

    def test_v2_encrypted_message_reserves_spawn_but_does_not_bind_authority(self):
        turn_id, result = self.route_and_stage()
        opaque_v2_message = "gAAAAAB" + ("A" * 197)

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": self.session_id,
                "turn_id": turn_id,
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-v2-encrypted",
                "tool_input": {
                    "task_name": result["task_name"],
                    "agent_type": "luna_worker",
                    "fork_turns": "none",
                    "message": opaque_v2_message,
                },
            },
            self.installation,
        )

        self.assertEqual(output, {})
        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(
            current.active_lease.spawn_tool_use_id,
            "spawn-v2-encrypted",
        )
        self.assertEqual(current.active_lease.status, "STAGED")
        self.assertIsNone(current.active_lease.worker_agent_id)
        self.assertIsNone(current.active_lease.child_turn_id)


if __name__ == "__main__":
    unittest.main()
