import json
import os
from pathlib import Path
import shlex
import stat
import tempfile
import unittest
from unittest.mock import patch

from codex_router import cli
from codex_router import luna_control as control
from codex_router.hook import HOOK_CONTEXT_PREFIX, handle_hook_event, handle_user_prompt
from codex_router.protocol import build_k1_stage_capability, build_luna_packet


class RouterUsabilityV32SecurityTests(unittest.TestCase):
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
        self.session = "session-v32-security"
        self.root_turn = "root-turn-v32-security"
        control.new_task(
            self.installation,
            self.secret,
            self.session,
            "root-parent",
            "profile-A",
        )
        control.set_current_root_turn(
            self.installation,
            self.secret,
            self.session,
            turn_id=self.root_turn,
        )

    def snapshot(self):
        return control.read_snapshot(self.installation, self.secret, self.session)

    def route(self) -> tuple[list[str], Path]:
        output = handle_user_prompt(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": self.session,
                "turn_id": self.root_turn,
                "prompt": "fix the failing tests",
                "cwd": str(self.root),
            },
            self.installation,
        )
        additional = output["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(additional.startswith(HOOK_CONTEXT_PREFIX))
        context = json.loads(additional[len(HOOK_CONTEXT_PREFIX) :])
        arguments = shlex.split(context["K1_STAGE_COMMAND"], posix=True)
        request_index = arguments.index("--request-file")
        return arguments[arguments.index("stage-k1-fields") :], Path(
            arguments[request_index + 1]
        )

    def request(self, path: Path, **overrides: object) -> None:
        value: dict[str, object] = {
            "packet_id": "packet-security",
            "objective": "bounded security regression",
            "working_directory": str(self.root),
            "intended_write_scope": ["src", "tests"],
            "explicit_side_effect_authorizations": [],
            "success_criteria": ["tests pass"],
            "stop_conditions": ["scope expansion required"],
        }
        value.update(overrides)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)

    def invoke(self, arguments: list[str]) -> tuple[int, list[dict[str, object]]]:
        outputs: list[dict[str, object]] = []

        def capture(value: dict[str, object], **_kwargs: object) -> None:
            outputs.append(value)

        with patch.object(cli, "_print_json", side_effect=capture):
            result = cli.main(arguments)
        return result, outputs

    def bind_packet_and_luna(self) -> str:
        snapshot = self.snapshot()
        assert snapshot is not None
        packet = build_luna_packet(
            packet_id="packet-bootstrap-security",
            generation=1,
            objective="bounded bootstrap",
            working_directory=str(self.root),
            intended_write_scope=(),
            explicit_side_effect_authorizations=(),
            success_criteria=("pass",),
            stop_conditions=("stop",),
        )
        capability = build_k1_stage_capability(
            self.secret,
            session_tag=control.session_tag(self.secret, self.session),
            root_turn_tag=snapshot.current_root_turn_tag,
            task_epoch=snapshot.task_epoch,
            generation=1,
        )
        control.stage_authority_packet(
            self.installation,
            self.secret,
            self.session,
            root_turn_id=self.root_turn,
            capability=capability,
            packet_wire=packet,
        )
        control.admit_staged_spawn(
            self.installation,
            self.secret,
            self.session,
            root_turn_id=self.root_turn,
            tool_use_id="spawn-security",
            task_name="luna_worker",
            agent_type="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.installation,
            self.secret,
            self.session,
            tool_use_id="spawn-security",
            task_path="/root/luna_worker",
        )
        control.observe_subagent_start(
            self.installation,
            self.secret,
            self.session,
            agent_id="luna-security",
            agent_type="luna_worker",
        )
        return packet

    def test_request_path_outside_router_namespace_fails_without_state_change(self) -> None:
        arguments, expected = self.route()
        outside = self.root / "outside-request.json"
        self.request(outside)
        before = self.snapshot()
        request_index = arguments.index("--request-file")
        arguments[request_index + 1] = str(outside)

        result, outputs = self.invoke(arguments)

        self.assertNotEqual(result, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(outside.exists())
        self.assertEqual(outputs[-1]["primary_fallback_state"], "SAFE_LOCAL_FALLBACK")
        self.assertNotEqual(outside, expected)

    def test_symlink_request_fails_without_following_target(self) -> None:
        arguments, expected = self.route()
        target = self.root / "target.json"
        self.request(target)
        expected.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.symlink(target, expected)
        before = self.snapshot()

        result, _outputs = self.invoke(arguments)

        self.assertNotEqual(result, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(target.exists())
        self.assertTrue(expected.is_symlink())

    def test_group_writable_request_is_rejected(self) -> None:
        arguments, expected = self.route()
        self.request(expected)
        expected.chmod(0o620)
        before = self.snapshot()

        result, _outputs = self.invoke(arguments)

        self.assertNotEqual(result, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(stat.S_IMODE(expected.stat().st_mode), 0o620)

    def test_safe_readable_request_is_normalized_to_private_mode(self) -> None:
        arguments, expected = self.route()
        self.request(expected)
        expected.chmod(0o644)

        result, outputs = self.invoke(arguments)

        self.assertEqual(result, 0, outputs)
        self.assertEqual(outputs[-1]["status"], "staged")
        self.assertFalse(expected.exists())

    def test_invalid_list_type_and_relative_working_directory_do_not_stage(self) -> None:
        for override in (
            {"intended_write_scope": "src"},
            {"working_directory": "relative/path"},
        ):
            with self.subTest(override=override):
                # Each case needs a fresh root turn because a failed request is
                # intentionally retained for diagnostics at the exact path.
                arguments, expected = self.route()
                if expected.exists() or expected.is_symlink():
                    expected.unlink()
                self.request(expected, **override)
                before = self.snapshot()

                result, _outputs = self.invoke(arguments)

                self.assertNotEqual(result, 0)
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(expected.exists())

    def test_stale_request_command_cannot_replay_generation(self) -> None:
        arguments, expected = self.route()
        self.request(expected)
        result, outputs = self.invoke(arguments)
        self.assertEqual(result, 0, outputs)

        # Recreate a valid request at the same path, but reuse the old one-time
        # capability embedded in the old complete command.
        self.request(expected, packet_id="packet-replay")
        before = self.snapshot()

        replay_result, _outputs = self.invoke(arguments)

        self.assertNotEqual(replay_result, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(expected.exists())

    def test_pwd_probe_with_extra_payload_is_not_allowlisted(self) -> None:
        self.bind_packet_and_luna()

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": self.session,
                "turn_id": "luna-turn-security",
                "tool_name": "Bash",
                "tool_use_id": "pwd-extra",
                "tool_input": {"command": "pwd", "timeout": 1},
                "agent_id": "luna-security",
                "agent_type": "luna_worker",
            },
            self.installation,
        )

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        snapshot = self.snapshot()
        assert snapshot is not None
        self.assertEqual(snapshot.execution_status, "IDLE")
        self.assertIsNone(snapshot.active_child_turn_id)


if __name__ == "__main__":
    unittest.main()
