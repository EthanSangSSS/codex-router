import base64
import hashlib
import hmac
import json
import unittest

from codex_router.protocol import (
    ProtocolError,
    build_k1_stage_capability,
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

