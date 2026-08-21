import json
from pathlib import Path
import stat
import tempfile
import unittest

from codex_router import luna_control as control
from codex_router.cli import parser
from codex_router.global_install_adapter import BASELINE_HOOK_EVENTS, install_hook_v3
from codex_router.hook import handle_hook_event, handle_user_prompt
from codex_router.protocol import build_k1_stage_capability, build_luna_packet
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


class TurnBoundaryFixture(unittest.TestCase):
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
        config = {
            "protocol": "codex-router/global-policy-config/v1",
            "state_root": str(self.root / "runs"),
            "codex_binary": str(binary),
            "role_config": ROLE_CONFIG,
        }
        self._write_private(
            self.installation_dir / "config.json",
            json.dumps(config, ensure_ascii=False).encode("utf-8"),
        )

    def _write_private(self, path, content):
        path.write_bytes(content)
        path.chmod(0o600)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def new_task_and_bind(self, *, session="session-a", agent_id="agent-1"):
        control.new_task(
            self.installation_dir,
            self.secret,
            session,
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        control.set_current_root_turn(
            self.installation_dir, self.secret, session, turn_id="root-turn"
        )
        control.reserve_spawn(
            self.installation_dir,
            self.secret,
            session,
            tool_use_id="spawn-1",
            task_name="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.installation_dir,
            self.secret,
            session,
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )
        return control.observe_subagent_start(
            self.installation_dir,
            self.secret,
            session,
            agent_id=agent_id,
            agent_type="luna_worker",
        )

    def begin_packet(self, *, session="session-a", packet_id="packet-1"):
        snapshot = control.read_snapshot(self.installation_dir, self.secret, session)
        message = build_luna_packet(
            packet_id=packet_id,
            generation=snapshot.packet_generation + 1,
            objective="perform bounded work",
            working_directory=str(self.root),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("bounded work completes",),
            stop_conditions=("scope expansion required",),
        )
        control.stage_authority_packet(
            self.installation_dir,
            self.secret,
            session,
            root_turn_id="root-turn",
            capability=build_k1_stage_capability(
                self.secret,
                session_tag=control.session_tag(self.secret, session),
                root_turn_tag=snapshot.current_root_turn_tag,
                task_epoch=snapshot.task_epoch,
                generation=snapshot.packet_generation + 1,
            ),
            packet_wire=message,
        )
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": session,
            "turn_id": "root-turn",
            "tool_name": "followup_task",
            "tool_use_id": "send-1",
            "tool_input": {"target": "/root/luna_worker", "message": "enc_01J9opaque_native_payload"},
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }
        self.assertEqual(handle_hook_event(event, self.installation_dir), {})
        return control.read_snapshot(self.installation_dir, self.secret, session)

    def luna_pretool(self, *, turn="luna-turn-1", tool_name="Read"):
        return {
            "hook_event_name": "PreToolUse",
            "session_id": "session-a",
            "turn_id": turn,
            "tool_name": tool_name,
            "tool_use_id": f"tool-{turn}",
            "tool_input": {"path": str(self.root / "README.md")},
            "agent_id": "agent-1",
            "agent_type": "luna_worker",
        }

    def subagent_stop(self, *, turn="luna-turn-1", agent_id="agent-1"):
        return {
            "hook_event_name": "SubagentStop",
            "session_id": "session-a",
            "turn_id": turn,
            "agent_id": agent_id,
            "agent_type": "luna_worker",
        }


class TurnBoundaryControlTests(TurnBoundaryFixture):
    def test_no_tool_turn_boundary_clears_admitted_packet(self):
        self.new_task_and_bind()
        before = self.begin_packet()
        self.assertEqual(before.execution_status, "IDLE")
        self.assertIsNotNone(before.active_packet_id)

        result = control.observe_turn_boundary(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="luna-turn-1",
        )

        self.assertEqual(result, "CURRENT")
        after = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(after.execution_status, "IDLE")
        self.assertIsNone(after.active_packet_id)
        self.assertIsNone(after.active_child_turn_id)

    def test_running_turn_boundary_returns_to_idle(self):
        self.new_task_and_bind()
        self.begin_packet()
        control.start_execution(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="luna-turn-1",
        )

        result = control.observe_turn_boundary(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="luna-turn-1",
        )

        self.assertEqual(result, "CURRENT")
        after = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(after.execution_status, "IDLE")
        self.assertIsNone(after.active_packet_id)
        self.assertIsNone(after.active_child_turn_id)

    def test_quiescing_turn_boundary_settles_router_scheduling_authority(self):
        self.new_task_and_bind()
        self.begin_packet()
        control.start_execution(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="luna-turn-1",
        )
        control.freeze_authority(
            self.installation_dir,
            self.secret,
            "session-a",
            reason="superseded",
        )

        result = control.observe_turn_boundary(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="luna-turn-1",
        )

        self.assertEqual(result, "CURRENT")
        after = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(after.execution_status, "PAUSED_SETTLED")
        self.assertIsNotNone(after.active_packet_id)
        self.assertEqual(after.active_child_turn_id, "luna-turn-1")

    def test_stale_or_conflicting_turn_boundary_cannot_mutate_authority(self):
        self.new_task_and_bind()
        stale_before = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertEqual(
            control.observe_turn_boundary(
                self.installation_dir,
                self.secret,
                "session-a",
                child_turn_id="late-turn",
            ),
            "STALE",
        )
        self.assertEqual(
            control.read_snapshot(self.installation_dir, self.secret, "session-a"),
            stale_before,
        )

        self.begin_packet()
        control.start_execution(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="current-turn",
        )
        before = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        with self.assertRaises(RouterStateError):
            control.observe_turn_boundary(
                self.installation_dir,
                self.secret,
                "session-a",
                child_turn_id="wrong-turn",
            )
        self.assertEqual(
            control.read_snapshot(self.installation_dir, self.secret, "session-a"), before
        )


class TurnBoundaryHookTests(TurnBoundaryFixture):
    def test_bound_luna_pretool_handshakes_before_same_turn_tool_admission(self):
        self.new_task_and_bind()
        self.begin_packet()

        first_output = handle_hook_event(self.luna_pretool(), self.installation_dir)
        self.assertEqual(
            first_output["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertIn("additionalContext", first_output["hookSpecificOutput"])
        first = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(first.execution_status, "RUNNING")
        self.assertEqual(first.active_child_turn_id, "luna-turn-1")
        self.assertIsNotNone(first.authority_packet_wire)

        self.assertEqual(handle_hook_event(self.luna_pretool(), self.installation_dir), {})
        established = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertIsNone(established.authority_packet_wire)

        self.assertEqual(handle_hook_event(self.luna_pretool(), self.installation_dir), {})
        self.assertEqual(
            control.read_snapshot(self.installation_dir, self.secret, "session-a"),
            established,
        )

    def test_bound_luna_ordinary_tool_without_packet_is_denied(self):
        self.new_task_and_bind()

        output = handle_hook_event(self.luna_pretool(), self.installation_dir)

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        snapshot = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(snapshot.execution_status, "IDLE")
        self.assertIsNone(snapshot.active_packet_id)

    def test_new_user_prompt_freezes_running_authority(self):
        self.new_task_and_bind()
        self.begin_packet()
        control.start_execution(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="luna-turn-1",
        )

        output = handle_user_prompt(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-a",
                "turn_id": "root-turn-2",
                "prompt": "继续修改另一个文件",
                "cwd": str(self.root),
            },
            self.installation_dir,
        )

        self.assertIn("hookSpecificOutput", output)
        after = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(after.execution_status, "QUIESCING")

    def test_interrupt_agent_freezes_before_native_cleanup_dispatch(self):
        self.new_task_and_bind()
        self.begin_packet()
        control.start_execution(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="luna-turn-1",
        )
        interrupt = {
            "hook_event_name": "PreToolUse",
            "session_id": "session-a",
            "turn_id": "root-turn",
            "tool_name": "interrupt_agent",
            "tool_use_id": "interrupt-1",
            "tool_input": {"target": "/root/luna_worker"},
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }

        self.assertEqual(handle_hook_event(interrupt, self.installation_dir), {})
        after = control.read_snapshot(self.installation_dir, self.secret, "session-a")
        self.assertEqual(after.execution_status, "QUIESCING")

    def test_subagent_stop_closes_running_and_no_tool_turns(self):
        self.new_task_and_bind()
        self.begin_packet()
        control.start_execution(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="luna-turn-1",
        )
        expected = {"hookSpecificOutput": {"hookEventName": "SubagentStop"}}
        self.assertEqual(
            handle_hook_event(self.subagent_stop(), self.installation_dir), expected
        )
        completed = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertEqual(completed.execution_status, "IDLE")
        self.assertIsNone(completed.active_packet_id)
        self.assertIsNone(completed.luna_agent_id)
        self.assertIsNone(completed.luna_task_path)

        control.reserve_spawn(
            self.installation_dir,
            self.secret,
            "session-a",
            tool_use_id="spawn-2",
            task_name="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.installation_dir,
            self.secret,
            "session-a",
            tool_use_id="spawn-2",
            task_path="/root/luna_worker",
        )
        control.observe_subagent_start(
            self.installation_dir,
            self.secret,
            "session-a",
            agent_id="agent-2",
            agent_type="luna_worker",
        )
        self.begin_packet(packet_id="packet-2")
        self.assertEqual(
            handle_hook_event(
                self.subagent_stop(turn="luna-turn-2", agent_id="agent-2"),
                self.installation_dir,
            ),
            expected,
        )
        no_tool = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        self.assertEqual(no_tool.execution_status, "IDLE")
        self.assertIsNone(no_tool.active_packet_id)
        self.assertIsNone(no_tool.luna_agent_id)
        self.assertIsNone(no_tool.luna_task_path)

    def test_mismatched_subagent_stop_does_not_mutate_current_authority(self):
        self.new_task_and_bind()
        self.begin_packet()
        control.start_execution(
            self.installation_dir,
            self.secret,
            "session-a",
            child_turn_id="luna-turn-1",
        )
        before = control.read_snapshot(self.installation_dir, self.secret, "session-a")

        handle_hook_event(
            self.subagent_stop(turn="wrong-turn", agent_id="historical-agent"),
            self.installation_dir,
        )

        self.assertEqual(
            control.read_snapshot(self.installation_dir, self.secret, "session-a"), before
        )


class TurnBoundaryInstallTests(unittest.TestCase):
    def test_baseline_hook_set_is_exactly_five_and_includes_subagent_stop(self):
        self.assertEqual(
            BASELINE_HOOK_EVENTS,
            (
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "SubagentStart",
                "SubagentStop",
            ),
        )

        handler = {
            "type": "command",
            "command": (
                "/usr/bin/python3 -E -P -m codex_router hook-user-prompt "
                "--installation-dir /tmp/router-install"
            ),
            "timeout": 5,
            "statusMessage": "Routing with Codex Router [codex-router-global-policy-v1]",
        }
        document = json.loads(install_hook_v3(None, handler=handler))
        self.assertEqual(set(document["hooks"]), set(BASELINE_HOOK_EVENTS))
        command = document["hooks"]["SubagentStop"][-1]["hooks"][0]["command"]
        self.assertIn("hook-subagent-stop", command)

    def test_packaged_cli_exposes_subagent_stop_entrypoint(self):
        args = parser().parse_args(
            ["hook-subagent-stop", "--installation-dir", "/tmp/router-install"]
        )
        self.assertEqual(args.command, "hook-subagent-stop")
        self.assertEqual(args.installation_dir, Path("/tmp/router-install"))


if __name__ == "__main__":
    unittest.main()
