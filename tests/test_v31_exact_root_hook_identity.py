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

    def _packet(self, *, packet_id, generation):
        return build_luna_packet(
            packet_id=packet_id,
            generation=generation,
            objective="modify README and test",
            working_directory=str(self.root),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("tests pass",),
            stop_conditions=("scope expansion required",),
        )

    def _spawn_luna_with_initial_packet(self, packet):
        spawn = {
            "hook_event_name": "PreToolUse",
            "session_id": "session-a",
            "turn_id": "root-turn-1",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-1",
            "tool_input": {
                "message": packet,
                "task_name": "luna_worker",
                "agent_type": "luna_worker",
                "fork_turns": "none",
            },
        }
        self.assertEqual(handle_hook_event(spawn, self.installation_dir), {})
        reserved = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(reserved.active_packet_id, "packet-1")
        self.assertEqual(reserved.packet_generation, 1)

        # Exact runtime may surface SubagentStart before the parent spawn result.
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
        self.assertEqual(
            handle_user_prompt(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-a",
                    "turn_id": "luna-turn-1",
                    "agent_id": "agent-1",
                    "agent_type": "luna_worker",
                    "prompt": packet,
                    "cwd": str(self.root),
                },
                self.installation_dir,
            ),
            {},
        )
        started = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(started.execution_status, "RUNNING")
        self.assertEqual(started.active_child_turn_id, "luna-turn-1")

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

    def _stop_luna(self, turn_id):
        return handle_hook_event(
            {
                "hook_event_name": "SubagentStop",
                "session_id": "session-a",
                "turn_id": turn_id,
                "agent_id": "agent-1",
                "agent_type": "luna_worker",
            },
            self.installation_dir,
        )

    def _dispatch_followup(self, packet, *, tool_use_id="followup-2"):
        return handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "root-turn-1",
                "tool_name": "followup_task",
                "tool_use_id": tool_use_id,
                "tool_input": {"target": "/root/luna_worker", "message": packet},
            },
            self.installation_dir,
        )

    def test_exact_root_wire_spawns_with_initial_k1_then_triggers_followup_k1(self):
        self._submit_root_prompt()
        packet1 = self._packet(packet_id="packet-1", generation=1)
        self._spawn_luna_with_initial_packet(packet1)
        self._stop_luna("luna-turn-1")

        packet2 = self._packet(packet_id="packet-2", generation=2)
        self.assertEqual(self._dispatch_followup(packet2), {})
        admitted = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(admitted.active_packet_id, "packet-2")
        self.assertEqual(admitted.packet_generation, 2)

        self.assertEqual(
            handle_user_prompt(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-a",
                    "turn_id": "luna-turn-2",
                    "agent_id": "agent-1",
                    "agent_type": "luna_worker",
                    "prompt": packet2,
                    "cwd": str(self.root),
                },
                self.installation_dir,
            ),
            {},
        )
        running = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(running.execution_status, "RUNNING")
        self.assertEqual(running.active_child_turn_id, "luna-turn-2")

    def test_queue_only_send_message_cannot_admit_new_k1_generation(self):
        self._submit_root_prompt()
        packet1 = self._packet(packet_id="packet-1", generation=1)
        self._spawn_luna_with_initial_packet(packet1)
        self._stop_luna("luna-turn-1")
        before = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        packet2 = self._packet(packet_id="packet-2", generation=2)

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "root-turn-1",
                "tool_name": "send_message",
                "tool_use_id": "queue-only-2",
                "tool_input": {"target": "/root/luna_worker", "message": packet2},
            },
            self.installation_dir,
        )

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("followup_task", output["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(
            control.read_snapshot(self.installation_dir, self.secret, "session-a"), before
        )

    def test_current_app_collaboration_spawn_alias_is_admitted_at_root_pretool(self):
        self._submit_root_prompt()
        packet = self._packet(packet_id="packet-1", generation=1)
        spawn = {
            "hook_event_name": "PreToolUse",
            "session_id": "session-a",
            "turn_id": "root-turn-1",
            "tool_name": "collaborationspawn_agent",
            "tool_use_id": "spawn-alias-1",
            "tool_input": {
                "message": packet,
                "task_name": "luna_worker",
                "agent_type": "luna_worker",
                "fork_turns": "none",
            },
        }

        self.assertEqual(handle_hook_event(spawn, self.installation_dir), {})
        snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertEqual(snapshot.active_packet_id, "packet-1")
        self.assertEqual(snapshot.packet_generation, 1)
        self.assertIsNotNone(snapshot.pending_spawn)

    def test_current_app_collaboration_spawn_alias_is_corroborated_at_posttool(self):
        self._submit_root_prompt()
        packet = self._packet(packet_id="packet-1", generation=1)
        spawn_input = {
            "message": packet,
            "task_name": "luna_worker",
            "agent_type": "luna_worker",
            "fork_turns": "none",
        }
        self.assertEqual(
            handle_hook_event(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-a",
                    "turn_id": "root-turn-1",
                    "tool_name": "collaborationspawn_agent",
                    "tool_use_id": "spawn-alias-2",
                    "tool_input": spawn_input,
                },
                self.installation_dir,
            ),
            {},
        )
        self.assertEqual(
            handle_hook_event(
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "session-a",
                    "turn_id": "root-turn-1",
                    "tool_name": "collaborationspawn_agent",
                    "tool_use_id": "spawn-alias-2",
                    "tool_input": spawn_input,
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
                    "agent_id": "agent-alias-2",
                    "agent_type": "luna_worker",
                },
                self.installation_dir,
            ),
            {"hookSpecificOutput": {"hookEventName": "SubagentStart"}},
        )
        snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertEqual(snapshot.luna_agent_id, "agent-alias-2")
        self.assertIsNone(snapshot.pending_spawn)

    def test_current_app_collaboration_followup_alias_admits_generation_two(self):
        self._submit_root_prompt()
        packet1 = self._packet(packet_id="packet-1", generation=1)
        self._spawn_luna_with_initial_packet(packet1)
        self._stop_luna("luna-turn-1")
        packet2 = self._packet(packet_id="packet-2", generation=2)

        self.assertEqual(
            handle_hook_event(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-a",
                    "turn_id": "root-turn-1",
                    "tool_name": "collaborationfollowup_task",
                    "tool_use_id": "followup-alias-2",
                    "tool_input": {
                        "target": "/root/luna_worker",
                        "message": packet2,
                    },
                },
                self.installation_dir,
            ),
            {},
        )
        snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertEqual(snapshot.active_packet_id, "packet-2")
        self.assertEqual(snapshot.packet_generation, 2)

    def test_current_app_collaboration_send_alias_remains_queue_only(self):
        self._submit_root_prompt()
        packet1 = self._packet(packet_id="packet-1", generation=1)
        self._spawn_luna_with_initial_packet(packet1)
        self._stop_luna("luna-turn-1")
        before = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        packet2 = self._packet(packet_id="packet-2", generation=2)

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "root-turn-1",
                "tool_name": "collaborationsend_message",
                "tool_use_id": "send-alias-2",
                "tool_input": {
                    "target": "/root/luna_worker",
                    "message": packet2,
                },
            },
            self.installation_dir,
        )

        self.assertEqual(
            output.get("hookSpecificOutput", {}).get("permissionDecision"),
            "deny",
        )
        self.assertIn(
            "followup_task",
            output.get("hookSpecificOutput", {}).get(
                "permissionDecisionReason", ""
            ),
        )
        self.assertEqual(
            control.read_snapshot(self.installation_dir, self.secret, "session-a"),
            before,
        )

    def test_current_app_collaboration_lifecycle_alias_remains_denied_for_luna(self):
        self._submit_root_prompt()
        packet = self._packet(packet_id="packet-1", generation=1)
        self._spawn_luna_with_initial_packet(packet)

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "luna-turn-1",
                "tool_name": "collaborationfollowup_task",
                "tool_use_id": "child-followup-alias",
                "tool_input": {"target": "/root/luna_worker"},
                "agent_id": "agent-1",
                "agent_type": "luna_worker",
            },
            self.installation_dir,
        )

        self.assertEqual(
            output.get("hookSpecificOutput", {}).get("permissionDecision"),
            "deny",
        )
        self.assertIn(
            "lifecycle continuation",
            output.get("hookSpecificOutput", {}).get(
                "permissionDecisionReason", ""
            ),
        )

    def test_unknown_collaboration_agent_name_remains_fail_closed(self):
        self._submit_root_prompt()
        before = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "root-turn-1",
                "tool_name": "collaborationevil_agent",
                "tool_use_id": "unknown-alias",
                "tool_input": {},
            },
            self.installation_dir,
        )

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "unknown agent lifecycle operation",
            output["hookSpecificOutput"]["permissionDecisionReason"],
        )
        self.assertEqual(
            control.read_snapshot(self.installation_dir, self.secret, "session-a"),
            before,
        )

    def test_identity_free_lifecycle_event_from_noncurrent_turn_fails_closed(self):
        self._submit_root_prompt(turn_id="root-turn-1")
        before = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        packet = self._packet(packet_id="packet-1", generation=1)

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "internal-subagent-turn",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-internal",
                "tool_input": {
                    "message": packet,
                    "task_name": "luna_worker",
                    "agent_type": "luna_worker",
                    "fork_turns": "none",
                },
            },
            self.installation_dir,
        )

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            control.read_snapshot(self.installation_dir, self.secret, "session-a"), before
        )

    def test_child_user_prompt_binds_turn_without_replacing_root_authority(self):
        self._submit_root_prompt(turn_id="root-turn-1")
        packet = self._packet(packet_id="packet-1", generation=1)
        before_spawn = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertIsNotNone(before_spawn.current_root_turn_tag)

        self._spawn_luna_with_initial_packet(packet)

        after = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(after.current_root_turn_tag, before_spawn.current_root_turn_tag)
        self.assertEqual(after.luna_agent_id, "agent-1")
        self.assertEqual(after.active_child_turn_id, "luna-turn-1")
        self.assertEqual(after.execution_status, "RUNNING")

    def test_late_old_subagent_stop_cannot_clear_new_generation(self):
        self._submit_root_prompt()
        packet1 = self._packet(packet_id="packet-1", generation=1)
        self._spawn_luna_with_initial_packet(packet1)
        self._stop_luna("luna-turn-1")

        packet2 = self._packet(packet_id="packet-2", generation=2)
        self.assertEqual(self._dispatch_followup(packet2), {})
        self.assertEqual(
            handle_user_prompt(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-a",
                    "turn_id": "luna-turn-2",
                    "agent_id": "agent-1",
                    "agent_type": "luna_worker",
                    "prompt": packet2,
                    "cwd": str(self.root),
                },
                self.installation_dir,
            ),
            {},
        )
        before = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(before.active_child_turn_id, "luna-turn-2")

        self._stop_luna("luna-turn-1")

        after = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(after, before)
        self.assertEqual(after.active_packet_id, "packet-2")
        self.assertEqual(after.execution_status, "RUNNING")


if __name__ == "__main__":
    unittest.main()
