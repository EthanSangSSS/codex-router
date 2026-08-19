import base64
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import unittest

from codex_router import luna_control as control
from codex_router.protocol import (
    ProtocolError,
    build_k1_stage_capability,
    build_luna_packet,
    canonical_json_bytes,
    verify_k1_stage_capability,
)


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
        self.stage()

        cancelled = control.freeze_authority(
            self.state,
            self.secret,
            self.session_id,
            reason="cancel",
            logical_cancel=True,
        )

        self.assertIsNone(cancelled.authority_packet_wire)

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
