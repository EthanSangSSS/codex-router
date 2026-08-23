import json
import tempfile
import unittest
from pathlib import Path

from codex_router import lease_control
from codex_router.hook import handle_hook_event
from codex_router.protocol import build_luna_packet


class HookV4TerminalTests(unittest.TestCase):
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
        self.session_id = "session-v4-terminal-hook"
        lease_control.initialize_session(
            self.installation, self.secret, self.session_id
        )

    def stage_and_bind(
        self,
        *,
        generation=1,
        packet_id="packet-1",
        agent_id="agent-1",
        child_turn_id="child-turn-1",
    ):
        staged = lease_control.stage_lease(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=f"root-turn-{generation}",
            packet_wire=build_luna_packet(
                packet_id=packet_id,
                generation=generation,
                objective="terminal Hook test",
                working_directory=str(self.root),
                intended_write_scope=("src",),
                explicit_side_effect_authorizations=(),
                success_criteria=("terminal reconciled",),
                stop_conditions=("identity mismatch",),
            ),
        )
        capability = lease_control.build_bootstrap_capability(
            self.secret, staged.active_lease
        )
        bound, _ = lease_control.authorize_executor_tool(
            self.installation,
            self.secret,
            self.session_id,
            agent_id=agent_id,
            agent_type="luna_worker",
            child_turn_id=child_turn_id,
            bootstrap_capability=capability,
        )
        return bound

    def stop_event(self, *, agent_id, turn_id):
        return {
            "hook_event_name": "SubagentStop",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "agent_id": agent_id,
            "agent_type": "luna_worker",
            "stop_hook_active": False,
            "last_assistant_message": "done",
            "cwd": str(self.root),
        }

    def expected_output(self):
        return {"hookSpecificOutput": {"hookEventName": "SubagentStop"}}

    def test_exact_current_subagent_stop_closes_v4_lease(self):
        self.stage_and_bind()

        output = handle_hook_event(
            self.stop_event(agent_id="agent-1", turn_id="child-turn-1"),
            self.installation,
        )

        self.assertEqual(output, self.expected_output())
        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertIsNone(current.active_lease)

    def test_late_old_subagent_stop_does_not_clear_new_generation(self):
        self.stage_and_bind(
            generation=1,
            packet_id="packet-1",
            agent_id="agent-old",
            child_turn_id="child-old",
        )
        lease_control.revoke_current_lease(
            self.installation, self.secret, self.session_id
        )
        second = lease_control.stage_lease(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id="root-turn-2",
            packet_wire=build_luna_packet(
                packet_id="packet-2",
                generation=2,
                objective="new generation",
                working_directory=str(self.root),
                intended_write_scope=("src/new.py",),
                explicit_side_effect_authorizations=(),
                success_criteria=("new lease survives",),
                stop_conditions=("stale stop",),
            ),
        )

        output = handle_hook_event(
            self.stop_event(agent_id="agent-old", turn_id="child-old"),
            self.installation,
        )

        self.assertEqual(output, self.expected_output())
        self.assertEqual(
            lease_control.read_snapshot(
                self.installation, self.secret, self.session_id
            ),
            second,
        )

    def test_duplicate_old_subagent_stop_is_noop(self):
        self.stage_and_bind()
        event = self.stop_event(agent_id="agent-1", turn_id="child-turn-1")
        first = handle_hook_event(event, self.installation)
        after_first = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )

        second = handle_hook_event(event, self.installation)

        self.assertEqual(first, self.expected_output())
        self.assertEqual(second, self.expected_output())
        self.assertEqual(
            lease_control.read_snapshot(
                self.installation, self.secret, self.session_id
            ),
            after_first,
        )

    def test_wrong_agent_or_child_turn_stop_is_stale_noop(self):
        bound = self.stage_and_bind()
        for agent_id, turn_id in (
            ("agent-wrong", "child-turn-1"),
            ("agent-1", "child-wrong"),
        ):
            with self.subTest(agent_id=agent_id, turn_id=turn_id):
                output = handle_hook_event(
                    self.stop_event(agent_id=agent_id, turn_id=turn_id),
                    self.installation,
                )
                self.assertEqual(output, self.expected_output())
                self.assertEqual(
                    lease_control.read_snapshot(
                        self.installation, self.secret, self.session_id
                    ),
                    bound,
                )


if __name__ == "__main__":
    unittest.main()
