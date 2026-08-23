import argparse
import json
import tempfile
import unittest
from pathlib import Path

from codex_router import lease_control
from codex_router.cli import _stage_k1_fields
from codex_router.hook import HOOK_CONTEXT_PREFIX, handle_hook_event


class V4SpawnWiringTests(unittest.TestCase):
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
        self.session_id = "session-v4-spawn"
        lease_control.initialize_session(
            self.installation, self.secret, self.session_id
        )

    def context(self, output):
        raw = output["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(raw.startswith(HOOK_CONTEXT_PREFIX))
        return json.loads(raw[len(HOOK_CONTEXT_PREFIX) :])

    def route_and_stage(self, *, generation: int, turn_id: str, packet_id: str):
        route = handle_hook_event(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": self.session_id,
                "turn_id": turn_id,
                "prompt": f"Implement bounded generation {generation} work.",
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
                packet_id=packet_id,
                objective=f"generation {generation} work",
                working_directory=str(self.root),
                intended_write_scope=["src", "tests"],
                explicit_side_effect_authorization=[],
                success_criterion=["tests pass"],
                stop_condition=["scope expansion required"],
            )
        )
        return result

    def pre_spawn_event(self, result, *, turn_id: str, tool_use_id: str, **overrides):
        tool_input = {
            "task_name": result["task_name"],
            "agent_type": "luna_worker",
            "fork_turns": "none",
            "message": result["spawn_message"],
        }
        tool_input.update(overrides)
        return {
            "hook_event_name": "PreToolUse",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "tool_name": "spawn_agent",
            "tool_use_id": tool_use_id,
            "tool_input": tool_input,
        }

    def post_spawn_event(self, *, turn_id: str, tool_use_id: str, task_path: str):
        return {
            "hook_event_name": "PostToolUse",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "tool_name": "spawn_agent",
            "tool_use_id": tool_use_id,
            "tool_input": {},
            "tool_response": {"task_name": task_path},
        }

    def test_exact_current_v4_spawn_is_reserved_without_native_worker_binding(self):
        result = self.route_and_stage(
            generation=1, turn_id="root-turn-1", packet_id="packet-1"
        )

        output = handle_hook_event(
            self.pre_spawn_event(
                result, turn_id="root-turn-1", tool_use_id="spawn-v4-1"
            ),
            self.installation,
        )

        self.assertEqual(output, {})
        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(current.active_lease.spawn_tool_use_id, "spawn-v4-1")
        self.assertIsNone(current.active_lease.worker_agent_id)
        self.assertIsNone(current.active_lease.child_turn_id)

    def test_wrong_task_name_or_spawn_message_is_denied_without_reservation(self):
        result = self.route_and_stage(
            generation=1, turn_id="root-turn-1", packet_id="packet-1"
        )
        cases = (
            {"task_name": "luna_worker"},
            {"message": "stale or model-invented bootstrap message"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                before = lease_control.read_snapshot(
                    self.installation, self.secret, self.session_id
                )
                event = self.pre_spawn_event(
                    result,
                    turn_id="root-turn-1",
                    tool_use_id="bad-spawn",
                )
                event["tool_input"].update(overrides)
                output = handle_hook_event(event, self.installation)
                self.assertEqual(
                    output["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                self.assertEqual(
                    lease_control.read_snapshot(
                        self.installation, self.secret, self.session_id
                    ),
                    before,
                )

    def test_current_spawn_post_result_records_exact_generation_scoped_path(self):
        result = self.route_and_stage(
            generation=1, turn_id="root-turn-1", packet_id="packet-1"
        )
        handle_hook_event(
            self.pre_spawn_event(
                result, turn_id="root-turn-1", tool_use_id="spawn-v4-1"
            ),
            self.installation,
        )
        expected_path = f"/root/{result['task_name']}"

        output = handle_hook_event(
            self.post_spawn_event(
                turn_id="root-turn-1",
                tool_use_id="spawn-v4-1",
                task_path=expected_path,
            ),
            self.installation,
        )

        self.assertEqual(
            output,
            {"hookSpecificOutput": {"hookEventName": "PostToolUse"}},
        )
        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(current.active_lease.worker_task_path, expected_path)
        self.assertIsNone(current.active_lease.worker_agent_id)

    def test_late_old_spawn_post_result_does_not_mutate_new_generation(self):
        first = self.route_and_stage(
            generation=1, turn_id="root-turn-1", packet_id="packet-1"
        )
        handle_hook_event(
            self.pre_spawn_event(
                first, turn_id="root-turn-1", tool_use_id="spawn-old"
            ),
            self.installation,
        )
        second = self.route_and_stage(
            generation=2, turn_id="root-turn-2", packet_id="packet-2"
        )
        before = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )

        output = handle_hook_event(
            self.post_spawn_event(
                turn_id="root-turn-1",
                tool_use_id="spawn-old",
                task_path=f"/root/{first['task_name']}",
            ),
            self.installation,
        )

        self.assertEqual(
            output,
            {"hookSpecificOutput": {"hookEventName": "PostToolUse"}},
        )
        after = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(after, before)
        self.assertEqual(after.generation, 2)
        self.assertEqual(after.active_lease.expected_task_name, second["task_name"])
        self.assertIsNone(after.active_lease.spawn_tool_use_id)


if __name__ == "__main__":
    unittest.main()
