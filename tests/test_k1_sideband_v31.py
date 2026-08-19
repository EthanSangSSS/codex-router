import base64
from dataclasses import replace
import hashlib
import hmac
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_router import luna_control as control
from codex_router.hook import handle_hook_event, handle_user_prompt
from codex_router.protocol import (
    ProtocolError,
    build_k1_stage_capability,
    build_luna_packet,
    canonical_json_bytes,
    verify_k1_stage_capability,
)
from codex_router.state import RouterStateError


def _decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class K1StageCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.secret = bytes(range(32))
        self.authority = {
            "session_tag": "session-tag",
            "root_turn_tag": "root-turn-tag",
            "task_epoch": "task-epoch",
            "generation": 2,
        }

    def build(self) -> str:
        return build_k1_stage_capability(self.secret, **self.authority)

    def verify(self, token: str, **overrides: object) -> None:
        verify_k1_stage_capability(token, self.secret, **(self.authority | overrides))

    def test_stage_capability_accepts_exact_current_authority(self):
        self.verify(self.build())

    def test_stage_capability_rejects_changed_session_tag(self):
        with self.assertRaises(ProtocolError):
            self.verify(self.build(), session_tag="other-session")

    def test_stage_capability_rejects_changed_root_turn_tag(self):
        with self.assertRaises(ProtocolError):
            self.verify(self.build(), root_turn_tag="other-root-turn")

    def test_stage_capability_rejects_changed_task_epoch(self):
        with self.assertRaises(ProtocolError):
            self.verify(self.build(), task_epoch="other-task-epoch")

    def test_stage_capability_rejects_generation_replay(self):
        with self.assertRaises(ProtocolError):
            self.verify(self.build(), generation=3)

    def test_stage_capability_rejects_malformed_token(self):
        for token in ("", "not-a-token", "a.b.c", "$.AA", "AA.$"):
            with self.subTest(token=token):
                with self.assertRaises(ProtocolError):
                    self.verify(token)

    def test_stage_capability_rejects_tampered_mac(self):
        payload, mac = self.build().split(".")
        tampered = payload + "." + ("A" if mac[-1] != "A" else "B") + mac[1:]
        with self.assertRaises(ProtocolError):
            self.verify(tampered)

    def test_stage_capability_mac_is_domain_separated(self):
        payload, mac = self.build().split(".")
        claims = json.loads(_decode_base64url(payload))
        bare_mac = base64.urlsafe_b64encode(
            hmac.new(self.secret, canonical_json_bytes(claims), hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")

        self.assertNotEqual(mac, bare_mac)

    def test_stage_capability_rejects_boolean_version_claim(self):
        claims = self.authority | {"v": True}
        payload = base64.urlsafe_b64encode(canonical_json_bytes(claims)).rstrip(b"=").decode("ascii")
        mac = hmac.new(
            self.secret,
            b"codex-router/k1-stage-capability/v1\0" + canonical_json_bytes(claims),
            hashlib.sha256,
        ).digest()
        token = payload + "." + base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")

        with self.assertRaises(ProtocolError):
            self.verify(token)


class K1RenderedContractTests(unittest.TestCase):
    def test_renderer_declares_sideband_authority_and_first_tool_handshake(self):
        from codex_router import global_install_adapter as adapter

        combined = (
            f"{adapter.AGENTS_BLOCK_V3}\n"
            f"{adapter.LUNA_DEVELOPER_INSTRUCTIONS_V3}"
        )

        for required in (
            "stage canonical K1 through `router stage-k1` first",
            "Native `spawn_agent`/`followup_task` message is a transport trigger, not authority",
            "`send_message` is QueueOnly and cannot advance K1",
            "Native collaboration messages are transport triggers, not work authority.",
            "The authoritative work packet is `[CODEX_ROUTER_PACKET_V3_1]` injected by Router as developer context.",
            "Do not perform tool work for a new generation until Router performs the first-tool authority handshake.",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)
        self.assertNotIn("generation-1 K1 packet as `message`", combined)


class K1SidebandStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name) / "state"
        self.state.mkdir(mode=0o700)
        self.secret = bytes(range(32))
        self.session_id = "session-a"
        self.root_turn_id = "root-turn-a"
        control.new_task(
            self.state,
            self.secret,
            self.session_id,
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        control.set_current_root_turn(
            self.state,
            self.secret,
            self.session_id,
            turn_id=self.root_turn_id,
        )

    def packet(self, *, packet_id="packet-1"):
        snapshot = control.read_snapshot(self.state, self.secret, self.session_id)
        return build_luna_packet(
            packet_id=packet_id,
            generation=snapshot.packet_generation + 1,
            objective="perform bounded work",
            working_directory=str(self.state),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )

    def capability(self):
        snapshot = control.read_snapshot(self.state, self.secret, self.session_id)
        return build_k1_stage_capability(
            self.secret,
            session_tag=control.session_tag(self.secret, self.session_id),
            root_turn_tag=snapshot.current_root_turn_tag,
            task_epoch=snapshot.task_epoch,
            generation=snapshot.packet_generation + 1,
        )

    def stage(self, packet=None):
        return control.stage_authority_packet(
            self.state,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            capability=self.capability(),
            packet_wire=self.packet() if packet is None else packet,
        )

    def test_stage_packet_accepts_exact_next_generation(self):
        packet = self.packet()
        before = control.read_snapshot(self.state, self.secret, self.session_id)

        staged = self.stage(packet)

        self.assertEqual(staged.authority_packet_wire, packet)
        self.assertEqual(staged.packet_generation, before.packet_generation)
        self.assertEqual(staged.active_packet_id, before.active_packet_id)
        self.assertEqual(staged.execution_status, before.execution_status)
        self.assertIsNone(staged.pending_spawn)

    def test_valid_canonical_k1_over_identity_limit_can_stage_and_persist(self):
        snapshot = control.read_snapshot(self.state, self.secret, self.session_id)
        packet = build_luna_packet(
            packet_id="packet-large",
            generation=snapshot.packet_generation + 1,
            objective="x" * 600,
            working_directory=str(self.state),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )
        self.assertGreater(len(packet.encode("utf-8")), 512)

        staged = self.stage(packet)

        self.assertEqual(staged.authority_packet_wire, packet)

    def test_identical_stage_retry_is_idempotent(self):
        packet = self.packet()
        first = self.stage(packet)
        second = self.stage(packet)

        self.assertEqual(second, first)

    def test_different_duplicate_stage_is_denied(self):
        first = self.packet(packet_id="packet-1")
        second = self.packet(packet_id="packet-2")
        self.stage(first)

        with self.assertRaises(control.RouterStateError):
            self.stage(second)

        snapshot = control.read_snapshot(self.state, self.secret, self.session_id)
        self.assertEqual(snapshot.authority_packet_wire, first)

    def test_legacy_base_snapshot_loads_authority_wire_as_none(self):
        self._remove_snapshot_fields(
            "authority_packet_wire", "recovery_baseline", "current_root_turn_tag"
        )

        snapshot = control.read_snapshot(self.state, self.secret, self.session_id)

        self.assertIsNone(snapshot.authority_packet_wire)

    def test_legacy_overlay_snapshot_loads_authority_wire_as_none(self):
        self._remove_snapshot_fields("authority_packet_wire")

        snapshot = control.read_snapshot(self.state, self.secret, self.session_id)

        self.assertIsNone(snapshot.authority_packet_wire)

    def test_new_root_turn_clears_unused_staged_authority(self):
        self.stage()

        snapshot = control.set_current_root_turn(
            self.state,
            self.secret,
            self.session_id,
            turn_id="root-turn-b",
        )

        self.assertIsNone(snapshot.authority_packet_wire)

    def test_same_root_turn_rebind_does_not_destroy_current_stage(self):
        staged = self.stage()

        rebound = control.set_current_root_turn(
            self.state,
            self.secret,
            self.session_id,
            turn_id=self.root_turn_id,
        )

        self.assertEqual(rebound.authority_packet_wire, staged.authority_packet_wire)

    def test_retire_clears_staged_authority(self):
        self.stage()

        retired = control.retire_luna(
            self.state, self.secret, self.session_id, "new_task_epoch"
        )

        self.assertIsNone(retired.authority_packet_wire)

    def test_logical_cancel_clears_staged_authority(self):
        control.begin_packet(
            self.state,
            self.secret,
            self.session_id,
            packet_id="active-packet",
            objective="active packet",
            working_directory=str(self.state),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("blocked",),
        )

        cancelled = control.freeze_authority(
            self.state,
            self.secret,
            self.session_id,
            reason="cancel",
            logical_cancel=True,
        )

        self.assertIsNone(cancelled.authority_packet_wire)
        self.assertIsNone(cancelled.active_packet_id)
        self.assertEqual(cancelled.execution_status, "IDLE")

    def test_replacement_snapshot_starts_without_staged_authority(self):
        self.stage()
        control.retire_luna(
            self.state, self.secret, self.session_id, "new_task_epoch"
        )

        replacement = control.start_new_task_epoch(
            self.state,
            self.secret,
            self.session_id,
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )

        self.assertIsNone(replacement.authority_packet_wire)

    def test_staging_does_not_change_packet_generation(self):
        before = control.read_snapshot(self.state, self.secret, self.session_id)

        after = self.stage()

        self.assertEqual(after.packet_generation, before.packet_generation)

    def test_recovery_baseline_unchanged_by_staging_only(self):
        before = control.read_snapshot(self.state, self.secret, self.session_id)

        after = self.stage()

        self.assertEqual(after.recovery_baseline, before.recovery_baseline)

    def _remove_snapshot_fields(self, *fields):
        state_path = self.state / control._STATE
        state = json.loads(state_path.read_text(encoding="utf-8"))
        tag = control.session_tag(self.secret, self.session_id)
        for field in fields:
            state["sessions"][tag].pop(field, None)
        state_path.write_text(
            json.dumps(state, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )


class K1ExecutorHandshakeTests(unittest.TestCase):
    def setUp(self):
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
        self.session_id = "session-a"
        self.root_turn_id = "root-turn-a"
        control.new_task(
            self.installation,
            self.secret,
            self.session_id,
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        control.set_current_root_turn(
            self.installation,
            self.secret,
            self.session_id,
            turn_id=self.root_turn_id,
        )

    def _packet(self):
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        return build_luna_packet(
            packet_id="packet-1",
            generation=snapshot.packet_generation + 1,
            objective="bounded work",
            working_directory=str(self.root),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("pass",),
            stop_conditions=("blocked",),
        )

    def _bind_luna_with_staged_packet(self):
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        packet = self._packet()
        capability = build_k1_stage_capability(
            self.secret,
            session_tag=control.session_tag(self.secret, self.session_id),
            root_turn_tag=snapshot.current_root_turn_tag,
            task_epoch=snapshot.task_epoch,
            generation=snapshot.packet_generation + 1,
        )
        control.stage_authority_packet(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            capability=capability,
            packet_wire=packet,
        )
        control.admit_staged_spawn(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            tool_use_id="spawn-1",
            task_name="luna_worker",
            agent_type="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.installation,
            self.secret,
            self.session_id,
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )
        control.observe_subagent_start(
            self.installation,
            self.secret,
            self.session_id,
            agent_id="agent-1",
            agent_type="luna_worker",
        )
        return packet

    def _pretool(self, *, turn_id="luna-turn-1", tool_name="Read"):
        return {
            "hook_event_name": "PreToolUse",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "tool_name": tool_name,
            "tool_use_id": f"tool-{turn_id}",
            "tool_input": {"path": str(self.root / "README.md")},
            "agent_id": "agent-1",
            "agent_type": "luna_worker",
        }

    def test_first_executor_tool_is_blocked_and_receives_exact_k1_context(self):
        packet = self._bind_luna_with_staged_packet()

        output = handle_hook_event(self._pretool(), self.installation)

        self.assertNotEqual(output, {})
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(output["hookSpecificOutput"]["additionalContext"], packet)
        self.assertIn("authority handshake", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_first_executor_tool_has_no_fake_side_effect(self):
        self._bind_luna_with_staged_packet()

        output = handle_hook_event(self._pretool(tool_name="Write"), self.installation)

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse((self.root / "README.md").exists())

    def test_first_tool_does_not_clear_staged_wire(self):
        packet = self._bind_luna_with_staged_packet()

        handle_hook_event(self._pretool(), self.installation)

        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        self.assertEqual(snapshot.authority_packet_wire, packet)
        self.assertEqual(snapshot.active_child_turn_id, "luna-turn-1")

    def test_second_same_turn_tool_clears_staged_wire_then_runs_normal_policy(self):
        self._bind_luna_with_staged_packet()
        handle_hook_event(self._pretool(), self.installation)

        output = handle_hook_event(self._pretool(), self.installation)

        self.assertEqual(output, {})
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        self.assertIsNone(snapshot.authority_packet_wire)
        self.assertEqual(snapshot.active_child_turn_id, "luna-turn-1")

    def test_second_different_turn_fails_closed(self):
        self._bind_luna_with_staged_packet()
        handle_hook_event(self._pretool(), self.installation)

        output = handle_hook_event(self._pretool(turn_id="luna-turn-2"), self.installation)

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNotNone(
            control.read_snapshot(self.installation, self.secret, self.session_id).authority_packet_wire
        )

    def test_quiescing_same_turn_executor_tool_is_denied_without_side_effect(self):
        self._bind_luna_with_staged_packet()
        handle_hook_event(self._pretool(), self.installation)
        control.freeze_authority(
            self.installation,
            self.secret,
            self.session_id,
            reason="review-hard-pause",
        )

        output = handle_hook_event(
            self._pretool(tool_name="Write"), self.installation
        )

        self.assertNotEqual(output, {})
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        snapshot = control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(snapshot.execution_status, "QUIESCING")
        self.assertIsNotNone(snapshot.authority_packet_wire)

    def test_matching_wire_clear_is_atomic_after_authority_check(self):
        self._bind_luna_with_staged_packet()
        handle_hook_event(self._pretool(), self.installation)

        with patch.object(
            control,
            "clear_staged_authority",
            side_effect=AssertionError("separate wire clear is forbidden"),
        ):
            output = handle_hook_event(self._pretool(), self.installation)

        self.assertEqual(output, {})
        snapshot = control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertIsNone(snapshot.authority_packet_wire)

    def test_forbidden_lifecycle_tool_remains_forbidden_after_handshake(self):
        packet = self._bind_luna_with_staged_packet()
        first = handle_hook_event(self._pretool(tool_name="spawn_agent"), self.installation)
        second = handle_hook_event(self._pretool(tool_name="spawn_agent"), self.installation)

        self.assertEqual(first["hookSpecificOutput"]["additionalContext"], packet)
        self.assertEqual(second["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("forbids agent lifecycle", second["hookSpecificOutput"]["permissionDecisionReason"])

    def test_send_input_denied_with_state_unchanged(self):
        self._bind_luna_with_staged_packet()
        before = control.read_snapshot(self.installation, self.secret, self.session_id)
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": self.session_id,
            "turn_id": self.root_turn_id,
            "tool_name": "send_input",
            "tool_use_id": "send-input-1",
            "tool_input": {
                "target": "/root/luna_worker",
                "message": "legacy work surface",
            },
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }

        output = handle_hook_event(event, self.installation)

        self.assertNotEqual(output, {})
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            control.read_snapshot(self.installation, self.secret, self.session_id),
            before,
        )

    def test_resume_agent_denied_with_state_unchanged(self):
        self._bind_luna_with_staged_packet()
        before = control.read_snapshot(self.installation, self.secret, self.session_id)
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": self.session_id,
            "turn_id": self.root_turn_id,
            "tool_name": "resume_agent",
            "tool_use_id": "resume-1",
            "tool_input": {"id": "agent-1"},
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }

        output = handle_hook_event(event, self.installation)

        self.assertNotEqual(output, {})
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            control.read_snapshot(self.installation, self.secret, self.session_id),
            before,
        )

    def test_unbound_executor_cannot_trigger_handshake(self):
        packet = self._packet()
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        capability = build_k1_stage_capability(
            self.secret,
            session_tag=control.session_tag(self.secret, self.session_id),
            root_turn_tag=snapshot.current_root_turn_tag,
            task_epoch=snapshot.task_epoch,
            generation=snapshot.packet_generation + 1,
        )
        control.stage_authority_packet(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            capability=capability,
            packet_wire=packet,
        )

        output = handle_hook_event(self._pretool(), self.installation)

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("additionalContext", output["hookSpecificOutput"])

    def test_active_packet_without_child_turn_or_authority_wire_is_invalid(self):
        self._bind_luna_with_staged_packet()
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)

        with self.assertRaises(RouterStateError):
            control.validate_snapshot(replace(snapshot, authority_packet_wire=None))

    def test_overlay_loader_rejects_impossible_active_packet_state(self):
        self._bind_luna_with_staged_packet()
        state_path = self.installation / control._STATE
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["sessions"][control.session_tag(self.secret, self.session_id)]["authority_packet_wire"] = None
        state_path.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaises(RouterStateError):
            control.read_snapshot(self.installation, self.secret, self.session_id)

    def test_child_user_prompt_plaintext_k1_is_not_required(self):
        self._bind_luna_with_staged_packet()

        output = handle_user_prompt(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": self.session_id,
                "turn_id": "luna-turn-1",
                "agent_id": "agent-1",
                "agent_type": "luna_worker",
                "prompt": "opaque native trigger",
                "cwd": str(self.root),
            },
            self.installation,
        )

        self.assertEqual(output, {})
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        self.assertIsNone(snapshot.active_child_turn_id)


class K1StageCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.installation = Path(self.temporary.name) / "installation"
        self.installation.mkdir(mode=0o700)
        self.secret = bytes(range(32))
        (self.installation / "installation-secret").write_bytes(self.secret)
        (self.installation / "installation-secret").chmod(0o600)
        binary = Path(self.temporary.name) / "codex"
        binary.write_text("synthetic", encoding="utf-8")
        binary.chmod(0o700)
        (self.installation / "config.json").write_text(
            json.dumps(
                {
                    "protocol": "codex-router/global-policy-config/v1",
                    "state_root": str(self.installation),
                    "codex_binary": str(binary),
                    "role_config": {
                        "local_sol": {"requested_model": "inherit", "requested_reasoning": "max"},
                        "web_sol": {"model_claimed": "sol", "reasoning_claimed": "xhigh", "verification": "operator_attested"},
                        "luna": {"requested_model": "gpt-5.6-luna", "requested_reasoning": "max"},
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.installation / "config.json").chmod(0o600)
        self.session_id = "session-a"
        self.root_turn_id = "root-turn-a"
        control.new_task(self.installation, self.secret, self.session_id, "root-parent", "profile-A")
        control.set_current_root_turn(self.installation, self.secret, self.session_id, turn_id=self.root_turn_id)

    def _packet_and_capability(self):
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        packet = build_luna_packet(
            packet_id="packet-1", generation=1, objective="bounded work",
            working_directory=str(self.installation), intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(), success_criteria=("pass",), stop_conditions=("blocked",),
        )
        capability = build_k1_stage_capability(
            self.secret, session_tag=control.session_tag(self.secret, self.session_id),
            root_turn_tag=snapshot.current_root_turn_tag, task_epoch=snapshot.task_epoch,
            generation=1,
        )
        return packet, capability

    def test_stage_k1_cli_is_exposed(self):
        from codex_router.cli import parser

        parsed = parser().parse_args(
            [
                "stage-k1",
                "--installation-dir",
                "/tmp/installation",
                "--session-id",
                "session-a",
                "--root-turn-id",
                "turn-a",
                "--capability",
                "token",
            ]
        )

        self.assertEqual(parsed.command, "stage-k1")

    def test_stage_k1_cli_reads_one_packet_from_stdin_and_stages_it(self):
        from codex_router import cli
        packet, capability = self._packet_and_capability()
        stream = type("Input", (), {"buffer": io.BytesIO(packet.encode("utf-8"))})()
        with patch.object(cli.sys, "stdin", stream):
            result = cli.main(["stage-k1", "--installation-dir", str(self.installation), "--session-id", self.session_id, "--root-turn-id", self.root_turn_id, "--capability", capability])

        self.assertEqual(result, 0)
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        self.assertEqual(snapshot.authority_packet_wire, packet)

    def test_stage_k1_cli_rejects_stale_capability(self):
        from codex_router import cli
        packet, capability = self._packet_and_capability()
        stream = type("Input", (), {"buffer": io.BytesIO(packet.encode("utf-8"))})()

        with patch.object(cli.sys, "stdin", stream):
            result = cli.main(["stage-k1", "--installation-dir", str(self.installation), "--session-id", self.session_id, "--root-turn-id", "stale-turn", "--capability", capability])

        self.assertNotEqual(result, 0)
