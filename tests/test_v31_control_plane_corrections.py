import json
from pathlib import Path
import tempfile
import unittest

from codex_router import luna_control as control
from codex_router.hook import handle_hook_event
from codex_router.protocol import build_k1_stage_capability, build_luna_packet


class V31ControlPlaneCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installation_dir = self.root / "installation"
        self.installation_dir.mkdir(mode=0o700)
        self.secret = bytes(range(32))
        (self.installation_dir / "installation-secret").write_bytes(self.secret)
        (self.installation_dir / "installation-secret").chmod(0o600)
        binary = self.root / "codex"
        binary.write_text("synthetic binary", encoding="utf-8")
        binary.chmod(0o700)
        config = {
            "protocol": "codex-router/global-policy-config/v1",
            "state_root": str(self.root / "runs"),
            "codex_binary": str(binary),
            "role_config": {
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
            },
        }
        (self.installation_dir / "config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        (self.installation_dir / "config.json").chmod(0o600)

    def bind_luna(self):
        control.new_task(
            self.installation_dir,
            self.secret,
            "session-a",
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        control.reserve_spawn(
            self.installation_dir,
            self.secret,
            "session-a",
            tool_use_id="spawn-1",
            task_name="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.installation_dir,
            self.secret,
            "session-a",
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )
        control.observe_subagent_start(
            self.installation_dir,
            self.secret,
            "session-a",
            agent_id="agent-1",
            agent_type="luna_worker",
        )

    def test_plaintext_parent_message_cannot_bypass_k1_generation_authority(self):
        self.bind_luna()
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": "session-a",
            "turn_id": "root-turn",
            "tool_name": "send_message",
            "tool_use_id": "send-1",
            "tool_input": {
                "target": "/root/luna_worker",
                "message": "continue without a K1 packet",
            },
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }

        output = handle_hook_event(event, self.installation_dir)

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertEqual(snapshot.packet_generation, 0)
        self.assertIsNone(snapshot.active_packet_id)

    def test_valid_k1_followup_task_is_still_admitted_for_bound_luna(self):
        self.bind_luna()
        control.set_current_root_turn(
            self.installation_dir, self.secret, "session-a", turn_id="root-turn"
        )
        packet = build_luna_packet(
            packet_id="packet-1",
            generation=1,
            objective="continue bounded work",
            working_directory=str(self.root),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": "session-a",
            "turn_id": "root-turn",
            "tool_name": "followup_task",
            "tool_use_id": "followup-1",
            "tool_input": {
                "target": "/root/luna_worker",
                "message": "enc_01J9opaque_native_payload",
            },
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }

        snapshot = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        control.stage_authority_packet(
            self.installation_dir,
            self.secret,
            "session-a",
            root_turn_id="root-turn",
            capability=build_k1_stage_capability(
                self.secret,
                session_tag=control.session_tag(self.secret, "session-a"),
                root_turn_tag=snapshot.current_root_turn_tag,
                task_epoch=snapshot.task_epoch,
                generation=1,
            ),
            packet_wire=packet,
        )

        self.assertEqual(handle_hook_event(event, self.installation_dir), {})
        snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertEqual(snapshot.packet_generation, 1)
        self.assertEqual(snapshot.active_packet_id, "packet-1")
        self.assertEqual(snapshot.execution_status, "IDLE")


if __name__ == "__main__":
    unittest.main()
