import json
import stat
import tempfile
import unittest
from pathlib import Path

from codex_router import a1
from codex_router import global_install_adapter as adapter
from codex_router import luna_control as control
from codex_router.hook import handle_hook_event
from codex_router.protocol import build_luna_packet
from codex_router.state import RouterStateError


class V31ControlPlaneCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installation_dir = self.root / "installation"
        self.installation_dir.mkdir(mode=0o700)
        self.secret = b"v3-control-plane-correction-secret!!"
        self._write_private(
            self.installation_dir / "installation-secret",
            self.secret,
        )
        binary = self.root / "codex"
        binary.write_text("synthetic binary", encoding="utf-8")
        binary.chmod(0o700)
        role_config = {
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
        self._write_private(
            self.installation_dir / "config.json",
            json.dumps(
                {
                    "protocol": "codex-router/global-policy-config/v1",
                    "state_root": str(self.root / "runs"),
                    "codex_binary": str(binary),
                    "role_config": role_config,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )

    def _write_private(self, path: Path, content: bytes) -> None:
        path.write_bytes(content)
        path.chmod(0o600)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def new_task(self, session: str = "root-session"):
        return control.new_task(
            self.installation_dir,
            self.secret,
            session,
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )

    def begin_packet(self, session: str, packet_id: str, scope=("src/math.py",)):
        return control.begin_packet(
            self.installation_dir,
            self.secret,
            session,
            packet_id=packet_id,
            objective="bounded work",
            working_directory=str(self.root),
            intended_write_scope=scope,
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )

    def bind_luna(self, session: str = "root-session", agent_id: str = "agent-1"):
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

    def test_running_generation_cannot_be_replaced_before_settlement(self):
        self.new_task()
        first = self.begin_packet("root-session", "packet-1")
        running = control.start_execution(
            self.installation_dir,
            self.secret,
            "root-session",
            child_turn_id="turn-1",
        )

        with self.assertRaises(RouterStateError):
            self.begin_packet("root-session", "packet-2", scope=("src/next.py",))

        current = control.read_snapshot(
            self.installation_dir, self.secret, "root-session"
        )
        self.assertEqual(current.packet_generation, first.packet_generation)
        self.assertEqual(current.active_packet_id, "packet-1")
        self.assertEqual(current.active_child_turn_id, "turn-1")
        self.assertEqual(current.execution_status, "RUNNING")
        self.assertEqual(current, running)

    def test_plaintext_parent_message_cannot_bypass_k1_generation_authority(self):
        self.new_task()
        self.bind_luna()
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": "root-session",
            "turn_id": "turn-root",
            "tool_name": "send_message",
            "tool_use_id": "message-1",
            "tool_input": {
                "target": "/root/luna_worker",
                "message": "continue with more work",
            },
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }

        output = handle_hook_event(event, self.installation_dir)

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "root-session"
        )
        self.assertEqual(snapshot.packet_generation, 0)
        self.assertIsNone(snapshot.active_packet_id)

    def test_valid_k1_parent_message_is_still_admitted(self):
        self.new_task()
        self.bind_luna()
        packet = build_luna_packet(
            packet_id="packet-1",
            generation=1,
            objective="bounded work",
            working_directory=str(self.root),
            intended_write_scope=("src/math.py",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": "root-session",
            "turn_id": "turn-root",
            "tool_name": "send_message",
            "tool_use_id": "message-1",
            "tool_input": {
                "target": "/root/luna_worker",
                "message": packet,
            },
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }

        self.assertEqual(handle_hook_event(event, self.installation_dir), {})
        snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "root-session"
        )
        self.assertEqual(snapshot.packet_generation, 1)
        self.assertEqual(snapshot.active_packet_id, "packet-1")

    def test_new_task_refuses_to_overwrite_existing_session_epoch(self):
        original = self.new_task()
        control.reserve_spawn(
            self.installation_dir,
            self.secret,
            "root-session",
            tool_use_id="spawn-old",
            task_name="luna_worker",
            fork_turns="none",
        )
        before = control.read_snapshot(
            self.installation_dir, self.secret, "root-session"
        )

        with self.assertRaises(RouterStateError):
            self.new_task()

        after = control.read_snapshot(
            self.installation_dir, self.secret, "root-session"
        )
        self.assertEqual(after, before)
        self.assertEqual(after.task_epoch, original.task_epoch)

    def test_profile_replacement_advances_luna_epoch_not_task_epoch(self):
        original = self.new_task()
        self.bind_luna()
        self.begin_packet("root-session", "packet-1")
        control.start_execution(
            self.installation_dir,
            self.secret,
            "root-session",
            child_turn_id="turn-1",
        )
        control.freeze_authority(
            self.installation_dir,
            self.secret,
            "root-session",
            reason="profile-change",
        )
        control.observe_settlement(
            self.installation_dir,
            self.secret,
            "root-session",
            source="verified_native_terminal",
            terminal_status="interrupted",
            child_turn_id="turn-1",
        )
        retired = control.retire_luna(
            self.installation_dir,
            self.secret,
            "root-session",
            reason="native_authority_profile_change",
        )

        self.assertEqual(retired.logical_task_status, "ACTIVE")
        self.assertEqual(retired.execution_status, "RETIRED")
        replace_luna_epoch = getattr(control, "replace_luna_epoch", None)
        self.assertIsNotNone(replace_luna_epoch)
        replacement = replace_luna_epoch(
            self.installation_dir,
            self.secret,
            "root-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-B",
            reason="native_authority_profile_change",
        )
        self.assertEqual(replacement.task_epoch, original.task_epoch)
        self.assertNotEqual(replacement.luna_epoch, original.luna_epoch)
        self.assertEqual(replacement.logical_task_status, "ACTIVE")
        self.assertEqual(replacement.execution_status, "IDLE")
        self.assertEqual(replacement.native_authority_profile, "profile-B")

    def test_start_new_task_epoch_requires_cancelled_retired_prior_task(self):
        self.new_task()
        retired = control.retire_luna(
            self.installation_dir,
            self.secret,
            "root-session",
            reason="new_task_epoch",
        )
        self.assertEqual(retired.logical_task_status, "CANCELLED")
        replacement = control.start_new_task_epoch(
            self.installation_dir,
            self.secret,
            "root-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
            reason="new_task_epoch",
        )
        self.assertNotEqual(replacement.task_epoch, retired.task_epoch)
        self.assertNotEqual(replacement.luna_epoch, retired.luna_epoch)
        self.assertEqual(replacement.logical_task_status, "ACTIVE")

    def test_a1_hard_readiness_requires_every_enabled_surface_to_be_proven(self):
        proven = a1.A1SurfaceCapability(
            category="git_push",
            surface="structured_tool",
            enforcement="PROVEN_PRE_ACTION",
            gate="PermissionRequest",
            actor_attribution="PROVEN",
        )
        unverified = a1.A1SurfaceCapability(
            category="git_push",
            surface="shell",
            enforcement="UNVERIFIED",
            gate=None,
            actor_attribution="UNVERIFIED",
        )
        self.assertFalse(a1.hard_claim_ready((proven, unverified), "git_push"))

        exact_runtime_record = {
            "record_type": "exact_runtime",
            "capabilities": (proven, unverified),
        }
        self.assertFalse(
            adapter.permission_request_registration_enabled(exact_runtime_record)
        )
        self.assertFalse(adapter.permission_request_registration_enabled((proven,)))

    def test_terminal_session_is_reclaimed_when_capacity_is_full(self):
        self.new_task("session-0")
        terminal = control.retire_luna(
            self.installation_dir,
            self.secret,
            "session-0",
            reason="new_task_epoch",
        )
        self.assertEqual(terminal.logical_task_status, "CANCELLED")
        self.assertEqual(terminal.execution_status, "RETIRED")
        for index in range(1, 64):
            self.new_task(f"session-{index}")

        created = self.new_task("session-64")

        self.assertEqual(created.logical_task_status, "ACTIVE")
        self.assertIsNone(
            control.read_snapshot(
                self.installation_dir,
                self.secret,
                "session-0",
            )
        )


if __name__ == "__main__":
    unittest.main()
