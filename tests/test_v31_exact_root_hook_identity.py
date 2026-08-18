import json
from pathlib import Path
import stat
import tempfile
import unittest

from codex_router import luna_control as control
from codex_router.hook import handle_hook_event, handle_user_prompt
from codex_router.protocol import build_luna_packet


ROLE_CONFIG = {
    "local_sol": {"requested_model": "gpt-5.6-sol", "requested_reasoning": "max"},
    "web_sol": {
        "model_claimed": "sol",
        "reasoning_claimed": "xhigh",
        "verification": "operator_attested",
    },
    "luna": {"requested_model": "gpt-5.6-luna", "requested_reasoning": "max"},
}


class ExactRootHookIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installation_dir = self.root / "installation"
        self.installation_dir.mkdir(mode=0o700)
        self.secret = bytes(range(32))
        self._write_private(self.installation_dir / "installation-secret", self.secret)
        binary = self.root / "codex"
        binary.write_text("synthetic binary", encoding="utf-8")
        binary.chmod(0o700)
        self._write_private(
            self.installation_dir / "config.json",
            json.dumps(
                {
                    "protocol": "codex-router/global-policy-config/v1",
                    "state_root": str(self.root / "runs"),
                    "codex_binary": str(binary),
                    "role_config": ROLE_CONFIG,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )

    def _write_private(self, path, content):
        path.write_bytes(content)
        path.chmod(0o600)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def _submit_root_prompt(self, turn_id="root-turn-1"):
        output = handle_user_prompt(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-a",
                "turn_id": turn_id,
                "prompt": "修改 README 并运行测试",
                "cwd": str(self.root),
            },
            self.installation_dir,
        )
        self.assertIn("hookSpecificOutput", output)
        return output

    def _spawn_and_bind_luna(self):
        spawn = {
            "hook_event_name": "PreToolUse",
            "session_id": "session-a",
            "turn_id": "root-turn-1",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-1",
            "tool_input": {"task_name": "luna_worker", "fork_turns": "none"},
        }
        self.assertEqual(handle_hook_event(spawn, self.installation_dir), {})
        self.assertEqual(
            handle_hook_event(
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "session-a",
                    "turn_id": "root-turn-1",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "spawn-1",
                    "tool_input": spawn["tool_input"],
                    "tool_response": {"task_name": "/root/luna_worker"},
                },
                self.installation_dir,
            ),
            {"hookSpecificOutput": {"hookEventName": "PostToolUse"}},
        )
        self.assertEqual(
            handle_hook_event(
                {
                    "hook_event_name": "SubagentStart",
                    "session_id": "session-a",
                    "turn_id": "luna-turn-1",
                    "agent_id": "agent-1",
                    "agent_type": "luna_worker",
                },
                self.installation_dir,
            ),
            {"hookSpecificOutput": {"hookEventName": "SubagentStart"}},
        )

    def test_exact_root_wire_without_synthetic_actor_fields_can_spawn_and_send_k1(self):
        self._submit_root_prompt()
        self._spawn_and_bind_luna()

        snapshot = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        packet = build_luna_packet(
            packet_id="packet-1",
            generation=snapshot.packet_generation + 1,
            objective="modify README and test",
            working_directory=str(self.root),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("tests pass",),
            stop_conditions=("scope expansion required",),
        )
        send = {
            "hook_event_name": "PreToolUse",
            "session_id": "session-a",
            "turn_id": "root-turn-1",
            "tool_name": "send_message",
            "tool_use_id": "send-1",
            "tool_input": {"target": "/root/luna_worker", "message": packet},
        }
        self.assertEqual(handle_hook_event(send, self.installation_dir), {})
        admitted = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(admitted.active_packet_id, "packet-1")
        self.assertEqual(admitted.packet_generation, 1)

    def test_identity_free_lifecycle_event_from_noncurrent_turn_fails_closed(self):
        self._submit_root_prompt(turn_id="root-turn-1")
        before = control.read_snapshot(self.installation_dir, self.secret, "session-a")

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "internal-subagent-turn",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-internal",
                "tool_input": {"task_name": "luna_worker", "fork_turns": "none"},
            },
            self.installation_dir,
        )

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            control.read_snapshot(self.installation_dir, self.secret, "session-a"), before
        )

    def test_thread_spawn_user_prompt_does_not_replace_root_turn_authority(self):
        self._submit_root_prompt(turn_id="root-turn-1")
        self._spawn_and_bind_luna()
        before = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertIsNotNone(before.current_root_turn_tag)

        output = handle_user_prompt(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-a",
                "turn_id": "luna-turn-1",
                "agent_id": "agent-1",
                "agent_type": "luna_worker",
                "prompt": "[CODEX_ROUTER_PACKET_V3_1] {}",
                "cwd": str(self.root),
            },
            self.installation_dir,
        )

        self.assertEqual(output, {})
        after = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(after.current_root_turn_tag, before.current_root_turn_tag)
        self.assertEqual(after.luna_agent_id, "agent-1")


if __name__ == "__main__":
    unittest.main()
