import json
import tempfile
import unittest
from pathlib import Path

from codex_router import lease_control as lease_control
from codex_router.hook import handle_hook_event
from codex_router.protocol import build_luna_packet


class HookV4LeaseTests(unittest.TestCase):
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
        self.session_id = "session-v4-hook"
        lease_control.initialize_session(
            self.installation, self.secret, self.session_id
        )

    def stage(self, *, generation=1, packet_id="packet-v4-1"):
        packet = build_luna_packet(
            packet_id=packet_id,
            generation=generation,
            objective="V4 hook bootstrap",
            working_directory=str(self.root),
            intended_write_scope=("src", "tests"),
            explicit_side_effect_authorizations=(),
            success_criteria=("bootstrap accepted",),
            stop_conditions=("identity mismatch",),
        )
        snapshot = lease_control.stage_lease(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=f"root-turn-v4-{generation}",
            packet_wire=packet,
        )
        lease = snapshot.active_lease
        lease_control.reserve_spawn(
            self.installation,
            self.secret,
            self.session_id,
            tool_use_id=f"spawn-v4-{generation}",
            task_name=lease.expected_task_name,
            agent_type="luna_worker",
            fork_turns="none",
        )
        snapshot = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        return snapshot, packet

    def bootstrap_event(
        self,
        *,
        capability: str | None,
        agent_id="agent-v4",
        turn_id="child-turn-v4",
    ):
        command = "pwd"
        if capability is not None:
            command += f" # CODEX_ROUTER_LEASE_BOOTSTRAP_V4={capability}"
        return {
            "hook_event_name": "PreToolUse",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "tool_name": "Bash",
            "tool_use_id": "bootstrap-tool-v4",
            "tool_input": {"command": command},
            "agent_id": agent_id,
            "agent_type": "luna_worker",
        }

    def test_current_capability_bootstrap_binds_worker_and_returns_context_only_k1(self):
        staged, packet = self.stage()
        capability = lease_control.build_bootstrap_capability(
            self.secret, staged.active_lease
        )

        output = handle_hook_event(
            self.bootstrap_event(capability=capability), self.installation
        )

        hook_output = output["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "PreToolUse")
        self.assertEqual(hook_output["additionalContext"], packet)
        self.assertNotIn("permissionDecision", hook_output)
        self.assertNotIn("permissionDecisionReason", hook_output)
        self.assertNotIn("updatedInput", hook_output)
        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(current.active_lease.status, "ACTIVE")
        self.assertEqual(current.active_lease.worker_agent_id, "agent-v4")
        self.assertEqual(current.active_lease.child_turn_id, "child-turn-v4")

    def test_missing_capability_cannot_bind_staged_v4_worker(self):
        self.stage()
        before = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )

        output = handle_hook_event(
            self.bootstrap_event(capability=None), self.installation
        )

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertEqual(
            lease_control.read_snapshot(
                self.installation, self.secret, self.session_id
            ),
            before,
        )

    def test_old_capability_cannot_bind_new_generation(self):
        first, _ = self.stage(generation=1, packet_id="packet-v4-1")
        old_capability = lease_control.build_bootstrap_capability(
            self.secret, first.active_lease
        )
        lease_control.revoke_current_lease(
            self.installation, self.secret, self.session_id
        )
        self.stage(generation=2, packet_id="packet-v4-2")
        before = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )

        output = handle_hook_event(
            self.bootstrap_event(
                capability=old_capability,
                agent_id="agent-old",
                turn_id="child-old",
            ),
            self.installation,
        )

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertEqual(
            lease_control.read_snapshot(
                self.installation, self.secret, self.session_id
            ),
            before,
        )
        self.assertIsNone(before.active_lease.worker_agent_id)

    def test_bound_worker_later_tool_is_allowed_only_for_exact_agent_and_turn(self):
        staged, _ = self.stage()
        capability = lease_control.build_bootstrap_capability(
            self.secret, staged.active_lease
        )
        handle_hook_event(
            self.bootstrap_event(capability=capability), self.installation
        )

        allowed = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": self.session_id,
                "turn_id": "child-turn-v4",
                "tool_name": "Bash",
                "tool_use_id": "later-v4",
                "tool_input": {"command": "git status --short"},
                "agent_id": "agent-v4",
                "agent_type": "luna_worker",
            },
            self.installation,
        )
        self.assertEqual(allowed, {})

        for agent_id, turn_id in (
            ("agent-wrong", "child-turn-v4"),
            ("agent-v4", "child-turn-wrong"),
        ):
            with self.subTest(agent_id=agent_id, turn_id=turn_id):
                denied = handle_hook_event(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": self.session_id,
                        "turn_id": turn_id,
                        "tool_name": "Bash",
                        "tool_use_id": f"wrong-{agent_id}-{turn_id}",
                        "tool_input": {"command": "git status --short"},
                        "agent_id": agent_id,
                        "agent_type": "luna_worker",
                    },
                    self.installation,
                )
                self.assertEqual(
                    denied["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def test_subagent_start_does_not_grant_v4_authority(self):
        staged, _ = self.stage()

        output = handle_hook_event(
            {
                "hook_event_name": "SubagentStart",
                "session_id": self.session_id,
                "turn_id": "child-turn-start",
                "agent_id": "agent-start-only",
                "agent_type": "luna_worker",
            },
            self.installation,
        )

        self.assertEqual(
            output,
            {"hookSpecificOutput": {"hookEventName": "SubagentStart"}},
        )
        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(current.active_lease.lease_id, staged.active_lease.lease_id)
        self.assertIsNone(current.active_lease.worker_agent_id)
        self.assertIsNone(current.active_lease.child_turn_id)


if __name__ == "__main__":
    unittest.main()
