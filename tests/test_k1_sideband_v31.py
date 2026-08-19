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

    def test_k1_larger_than_the_journal_is_rejected_before_a_write(self):
        packet = build_luna_packet(
            packet_id="packet-oversize",
            generation=1,
            objective="x" * (307 * 1024),
            working_directory=str(self.state),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )
        self.assertGreater(len(packet.encode("utf-8")), control._MAX_STATE_BYTES)
        journal = self.state / control._STATE
        before = journal.read_bytes()

        with patch.object(
            control, "_write_state_unlocked", wraps=control._write_state_unlocked
        ) as write:
            with self.assertRaisesRegex(RouterStateError, "journal capacity"):
                self.stage(packet)

        self.assertEqual(write.call_count, 0)
        self.assertEqual(journal.read_bytes(), before)

    def test_large_k1_that_fits_the_journal_persists(self):
        packet = build_luna_packet(
            packet_id="packet-journal-large",
            generation=1,
            objective="x" * (128 * 1024),
            working_directory=str(self.state),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )
        self.assertGreater(len(packet.encode("utf-8")), 512)

        staged = self.stage(packet)

        self.assertEqual(staged.authority_packet_wire, packet)
        self.assertLessEqual(
            len((self.state / control._STATE).read_bytes()), control._MAX_STATE_BYTES
        )

    def test_capacity_exhausting_k1_leaves_the_journal_unchanged(self):
        packet = build_luna_packet(
            packet_id="packet-capacity-edge",
            generation=1,
            objective="x" * (control._MAX_STATE_BYTES - 600),
            working_directory=str(self.state),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )
        self.assertLess(len(packet.encode("utf-8")), control._MAX_STATE_BYTES)
        journal = self.state / control._STATE
        before = journal.read_bytes()
        candidate = json.loads(before)
        candidate["sessions"][control.session_tag(self.secret, self.session_id)][
            "authority_packet_wire"
        ] = packet
        self.assertGreater(
            len(control._canonical_state_bytes(candidate)), control._MAX_STATE_BYTES
        )

        with self.assertRaisesRegex(RouterStateError, "journal capacity"):
            self.stage(packet)

        self.assertEqual(journal.read_bytes(), before)

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

    def test_root_supersession_after_commit_cancels_unstarted_authority_safely(self):
        self.stage()
        control.admit_staged_spawn(
            self.state,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            tool_use_id="spawn-1",
            task_name="luna_worker",
            agent_type="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.state,
            self.secret,
            self.session_id,
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )
        control.observe_subagent_start(
            self.state,
            self.secret,
            self.session_id,
            agent_id="agent-1",
            agent_type="luna_worker",
        )
        before = control.read_snapshot(self.state, self.secret, self.session_id)

        superseded = control.set_current_root_turn(
            self.state,
            self.secret,
            self.session_id,
            turn_id="root-turn-b",
        )

        self.assertNotEqual(superseded.current_root_turn_tag, before.current_root_turn_tag)
        self.assertEqual(superseded.packet_generation, before.packet_generation)
        self.assertIsNone(superseded.active_packet_id)
        self.assertIsNone(superseded.active_child_turn_id)
        self.assertIsNone(superseded.authority_packet_wire)
        self.assertEqual(superseded.execution_status, "IDLE")

    def test_root_supersession_preserves_unreconciled_spawn_reservation(self):
        self.stage()
        admitted = control.admit_staged_spawn(
            self.state,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            tool_use_id="spawn-1",
            task_name="luna_worker",
            agent_type="luna_worker",
            fork_turns="none",
        )

        superseded = control.set_current_root_turn(
            self.state,
            self.secret,
            self.session_id,
            turn_id="root-turn-b",
        )

        self.assertEqual(superseded.pending_spawn, admitted.pending_spawn)
        self.assertIsNone(superseded.active_packet_id)
        self.assertIsNone(superseded.active_child_turn_id)
        self.assertIsNone(superseded.authority_packet_wire)
        self.assertEqual(superseded.intended_write_scope, ())
        self.assertEqual(superseded.explicit_side_effect_authorizations, ())
        self.assertIsNone(superseded.recovery_baseline)

    def test_superseded_pending_spawn_still_accepts_matching_spawn_result(self):
        self.stage()
        control.admit_staged_spawn(
            self.state,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            tool_use_id="spawn-1",
            task_name="luna_worker",
            agent_type="luna_worker",
            fork_turns="none",
        )
        control.set_current_root_turn(
            self.state, self.secret, self.session_id, turn_id="root-turn-b"
        )

        observed = control.observe_spawn_result(
            self.state,
            self.secret,
            self.session_id,
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )

        self.assertIsNotNone(observed.pending_spawn)
        self.assertEqual(observed.pending_spawn.task_path, "/root/luna_worker")
        self.assertIsNone(observed.active_packet_id)
        self.assertIsNone(observed.authority_packet_wire)

    def test_superseded_pending_spawn_binds_but_cannot_use_old_k1(self):
        self.stage()
        control.admit_staged_spawn(
            self.state,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            tool_use_id="spawn-1",
            task_name="luna_worker",
            agent_type="luna_worker",
            fork_turns="none",
        )
        control.set_current_root_turn(
            self.state, self.secret, self.session_id, turn_id="root-turn-b"
        )
        control.observe_spawn_result(
            self.state,
            self.secret,
            self.session_id,
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )

        bound = control.observe_subagent_start(
            self.state,
            self.secret,
            self.session_id,
            agent_id="agent-1",
            agent_type="luna_worker",
        )

        self.assertEqual(bound.luna_agent_id, "agent-1")
        self.assertIsNone(bound.pending_spawn)
        self.assertIsNone(bound.active_packet_id)
        self.assertIsNone(bound.authority_packet_wire)
        with self.assertRaises(RouterStateError):
            control.authorize_executor_tool(
                self.state,
                self.secret,
                self.session_id,
                agent_id="agent-1",
                child_turn_id="luna-turn-1",
            )

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

    def test_retirement_clears_k1_in_the_same_locked_transaction(self):
        self.stage()

        with patch.object(control, "_locked_state", wraps=control._locked_state) as locked:
            retired = control.retire_luna(
                self.state, self.secret, self.session_id, "new_task_epoch"
            )

        mutate_calls = [
            call for call in locked.call_args_list if call.kwargs.get("mutate")
        ]
        self.assertEqual(len(mutate_calls), 1)
        self.assertIsNone(retired.authority_packet_wire)
        raw = json.loads((self.state / control._STATE).read_text(encoding="utf-8"))
        record = raw["sessions"][control.session_tag(self.secret, self.session_id)]
        self.assertIsNone(record["authority_packet_wire"])

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


class K1ParentDispatchTests(unittest.TestCase):
    OPAQUE = "enc_01J9opaque_native_payload"

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
                        "local_sol": {"requested_model": "inherit", "requested_reasoning": "max"},
                        "web_sol": {"model_claimed": "sol", "reasoning_claimed": "xhigh", "verification": "operator_attested"},
                        "luna": {"requested_model": "executor", "requested_reasoning": "max"},
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

    def packet(self, *, packet_id="packet-1"):
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        return build_luna_packet(
            packet_id=packet_id,
            generation=snapshot.packet_generation + 1,
            objective="bounded work",
            working_directory=str(self.root),
            intended_write_scope=("README.md",),
            explicit_side_effect_authorizations=(),
            success_criteria=("pass",),
            stop_conditions=("blocked",),
        )

    def capability(self):
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        return build_k1_stage_capability(
            self.secret,
            session_tag=control.session_tag(self.secret, self.session_id),
            root_turn_tag=snapshot.current_root_turn_tag,
            task_epoch=snapshot.task_epoch,
            generation=snapshot.packet_generation + 1,
        )

    def stage(self, packet=None):
        return control.stage_authority_packet(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            capability=self.capability(),
            packet_wire=self.packet() if packet is None else packet,
        )

    def bind_luna(self):
        self.stage()
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
        control.start_execution(
            self.installation,
            self.secret,
            self.session_id,
            child_turn_id="luna-turn-1",
        )
        control.observe_turn_boundary(
            self.installation,
            self.secret,
            self.session_id,
            child_turn_id="luna-turn-1",
        )

    def spawn_event(self, *, turn_id=None, **overrides):
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": self.session_id,
            "turn_id": self.root_turn_id if turn_id is None else turn_id,
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-event-1",
            "tool_input": {
                "task_name": "luna_worker",
                "agent_type": "luna_worker",
                "fork_turns": "none",
                "message": self.OPAQUE,
            },
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }
        event["tool_input"].update(overrides)
        return event

    def followup_event(self, *, turn_id=None, target="/root/luna_worker"):
        return {
            "hook_event_name": "PreToolUse",
            "session_id": self.session_id,
            "turn_id": self.root_turn_id if turn_id is None else turn_id,
            "tool_name": "followup_task",
            "tool_use_id": "followup-event-1",
            "tool_input": {"target": target, "message": self.OPAQUE},
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }

    def test_shared_packet_transition_helper_is_available_for_all_commit_paths(self):
        self.assertTrue(callable(getattr(control, "_packet_commit_fields", None)))

    def test_spawn_accepts_opaque_message_with_valid_staged_gen1(self):
        self.stage()

        output = handle_hook_event(self.spawn_event(), self.installation)

        self.assertEqual(output, {})
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        self.assertEqual(snapshot.packet_generation, 1)
        self.assertIsNotNone(snapshot.pending_spawn)

    def test_spawn_without_stage_fails_closed(self):
        before = control.read_snapshot(self.installation, self.secret, self.session_id)

        output = handle_hook_event(self.spawn_event(), self.installation)

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(control.read_snapshot(self.installation, self.secret, self.session_id), before)

    def test_spawn_identity_fields_still_fail_closed(self):
        self.stage()

        output = handle_hook_event(
            self.spawn_event(task_name="not-luna"), self.installation
        )

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        self.assertEqual(snapshot.packet_generation, 0)
        self.assertIsNone(snapshot.pending_spawn)
        self.assertIsNotNone(snapshot.authority_packet_wire)

    def test_spawn_validation_failure_changes_neither_reservation_nor_generation(self):
        self.stage()
        before = control.read_snapshot(self.installation, self.secret, self.session_id)

        with self.assertRaises(control.RouterStateError):
            control.admit_staged_spawn(
                self.installation,
                self.secret,
                self.session_id,
                root_turn_id=self.root_turn_id,
                tool_use_id="spawn-1",
                task_name="not-luna",
                agent_type="luna_worker",
                fork_turns="none",
            )

        self.assertEqual(control.read_snapshot(self.installation, self.secret, self.session_id), before)

    def test_spawn_packet_commit_failure_leaves_no_pending_spawn(self):
        self.stage()
        before = control.read_snapshot(self.installation, self.secret, self.session_id)
        with patch.object(
            control,
            "_store_snapshot",
            side_effect=control.RouterStateError("conflict", "commit failed"),
        ):
            with self.assertRaises(control.RouterStateError):
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
        self.assertEqual(control.read_snapshot(self.installation, self.secret, self.session_id), before)

    def test_spawn_retry_after_denied_admission_is_not_poisoned(self):
        self.stage()
        with self.assertRaises(control.RouterStateError):
            control.admit_staged_spawn(
                self.installation,
                self.secret,
                self.session_id,
                root_turn_id="stale-root",
                tool_use_id="spawn-1",
                task_name="luna_worker",
                agent_type="luna_worker",
                fork_turns="none",
            )

        admitted = control.admit_staged_spawn(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            tool_use_id="spawn-2",
            task_name="luna_worker",
            agent_type="luna_worker",
            fork_turns="none",
        )

        self.assertEqual(admitted.packet_generation, 1)
        self.assertEqual(admitted.pending_spawn.tool_use_id, "spawn-2")

    def test_followup_accepts_opaque_message_for_exact_bound_executor(self):
        self.bind_luna()
        self.stage(packet=self.packet(packet_id="packet-2"))
        output = handle_hook_event(self.followup_event(), self.installation)

        self.assertEqual(output, {})
        snapshot = control.read_snapshot(self.installation, self.secret, self.session_id)
        self.assertEqual(snapshot.packet_generation, 2)
        self.assertEqual(snapshot.active_packet_id, "packet-2")

    def test_followup_wrong_target_changes_neither_stage_nor_generation(self):
        self.bind_luna()
        self.stage(packet=self.packet(packet_id="packet-2"))
        before = control.read_snapshot(self.installation, self.secret, self.session_id)

        with self.assertRaises(control.RouterStateError):
            control.admit_staged_followup(
                self.installation,
                self.secret,
                self.session_id,
                root_turn_id=self.root_turn_id,
                target="agent-other",
            )

        self.assertEqual(control.read_snapshot(self.installation, self.secret, self.session_id), before)

    def test_followup_commit_and_target_check_use_one_snapshot(self):
        self.bind_luna()
        self.stage(packet=self.packet(packet_id="packet-2"))
        with patch.object(control, "_record_for_session", wraps=control._record_for_session) as record:
            admitted = control.admit_staged_followup(
                self.installation,
                self.secret,
                self.session_id,
                root_turn_id=self.root_turn_id,
                target="/root/luna_worker",
            )

        self.assertEqual(record.call_count, 1)
        self.assertEqual(admitted.packet_generation, 2)

    def test_send_message_cannot_consume_stage_or_advance_generation(self):
        self.bind_luna()
        self.stage(packet=self.packet(packet_id="packet-2"))
        before = control.read_snapshot(self.installation, self.secret, self.session_id)
        event = {
            **self.followup_event(),
            "tool_name": "send_message",
            "tool_input": {"target": "/root/luna_worker", "message": self.OPAQUE},
        }

        output = handle_hook_event(event, self.installation)

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(control.read_snapshot(self.installation, self.secret, self.session_id), before)

    def test_stale_explicit_root_cannot_consume_current_staged_k1(self):
        self.bind_luna()
        stale_root = self.root_turn_id
        control.set_current_root_turn(
            self.installation, self.secret, self.session_id, turn_id="root-turn-b"
        )
        self.root_turn_id = "root-turn-b"
        self.stage(packet=self.packet(packet_id="packet-2"))
        before = control.read_snapshot(self.installation, self.secret, self.session_id)
        event = self.followup_event(turn_id=stale_root)

        output = handle_hook_event(event, self.installation)

        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(control.read_snapshot(self.installation, self.secret, self.session_id), before)

    def test_atomic_spawn_revalidates_root_turn_inside_transaction(self):
        self.stage()
        before = control.read_snapshot(self.installation, self.secret, self.session_id)

        with self.assertRaises(control.RouterStateError):
            control.admit_staged_spawn(
                self.installation,
                self.secret,
                self.session_id,
                root_turn_id="stale-root",
                tool_use_id="spawn-1",
                task_name="luna_worker",
                agent_type="luna_worker",
                fork_turns="none",
            )

        self.assertEqual(control.read_snapshot(self.installation, self.secret, self.session_id), before)

    def test_atomic_followup_revalidates_root_turn_inside_transaction(self):
        self.bind_luna()
        self.stage(packet=self.packet(packet_id="packet-2"))
        before = control.read_snapshot(self.installation, self.secret, self.session_id)

        with self.assertRaises(control.RouterStateError):
            control.admit_staged_followup(
                self.installation,
                self.secret,
                self.session_id,
                root_turn_id="stale-root",
                target="/root/luna_worker",
            )

        self.assertEqual(control.read_snapshot(self.installation, self.secret, self.session_id), before)
