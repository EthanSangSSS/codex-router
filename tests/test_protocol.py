import json
import unittest


def load_protocol_api(testcase):
    try:
        from codex_router.protocol import (
            ProtocolError,
            find_router_handoff,
            make_handoff,
            serialize_handoff_item,
        )
    except ModuleNotFoundError:
        testcase.fail("codex_router handoff protocol is not implemented")
    return ProtocolError, find_router_handoff, make_handoff, serialize_handoff_item


def load_stage_protocol_api(testcase):
    try:
        from codex_router.protocol import (
            ProtocolError,
            build_stage_packet,
            canonical_json_bytes,
            digest_json,
            failure_digest,
            normalize_content,
            submission_digest,
            validate_web_response,
            web_response_marker,
        )
    except ImportError:
        testcase.fail("codex_router canonical stage protocol is not implemented")
    return (
        ProtocolError,
        build_stage_packet,
        canonical_json_bytes,
        digest_json,
        failure_digest,
        normalize_content,
        submission_digest,
        validate_web_response,
        web_response_marker,
    )


def load_luna_packet_api(testcase):
    from codex_router import protocol

    try:
        return (
            protocol.LUNA_PACKET_PREFIX,
            protocol.build_luna_packet,
            protocol.parse_luna_packet,
        )
    except AttributeError:
        testcase.fail("V3.1 K1 packet API is not implemented")


def encode_luna_packet(prefix, packet, *, canonical=True):
    if canonical:
        payload = json.dumps(
            packet,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        payload = json.dumps(packet, ensure_ascii=False)
    return prefix + payload


class RouterProtocolTests(unittest.TestCase):
    def test_handoff_envelope_contains_protocol_run_id_and_stage(self):
        _, _, make_handoff, _ = load_protocol_api(self)
        envelope = make_handoff("run-123", "local_sol", "done")

        self.assertEqual(
            envelope,
            {
                "router_protocol": "codex-router/v1",
                "run_id": "run-123",
                "stage": "local_sol",
                "content": "done",
            },
        )

    def test_router_marker_is_found_amid_automatic_context(self):
        _, find_router_handoff, make_handoff, serialize_handoff_item = load_protocol_api(self)
        envelope = make_handoff("run-123", "local_sol", "local output")
        item = serialize_handoff_item(envelope)
        records = [
            {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "automatic developer context"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "automatic user-shaped context"}]}},
            {"type": "world_state", "payload": {"environment": "automatic"}},
            {"type": "response_item", "payload": item},
        ]

        self.assertEqual(find_router_handoff(records, "run-123", "local_sol"), envelope)

    def test_duplicate_router_marker_is_rejected(self):
        ProtocolError, find_router_handoff, make_handoff, serialize_handoff_item = load_protocol_api(self)
        item = serialize_handoff_item(make_handoff("run-123", "local_sol", "once"))

        with self.assertRaises(ProtocolError):
            find_router_handoff(
                [
                    {"type": "response_item", "payload": item},
                    {"type": "response_item", "payload": item},
                ],
                "run-123",
                "local_sol",
            )


class CanonicalProtocolTests(unittest.TestCase):
    def test_content_normalization_is_nfc_and_newlines_only(self):
        *_, normalize_content, _, _, _ = load_stage_protocol_api(self)

        self.assertEqual(
            normalize_content("  cafe\u0301\r\nline\r\n"),
            "  café\nline\n",
        )

    def test_content_normalization_rejects_invalid_utf8_scalar_values(self):
        ProtocolError, *_, normalize_content, _, _, _ = load_stage_protocol_api(self)

        with self.assertRaises(ProtocolError):
            normalize_content("\ud800")

    def test_canonical_json_is_stable_utf8_and_rejects_nan(self):
        _, _, canonical_json_bytes, *_ = load_stage_protocol_api(self)

        left = canonical_json_bytes({"z": "雪", "a": [2, 1]})
        right = canonical_json_bytes({"a": [2, 1], "z": "雪"})

        self.assertEqual(left, b'{"a":[2,1],"z":"\xe9\x9b\xaa"}')
        self.assertEqual(left, right)
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("nan")})


class StagePacketTests(unittest.TestCase):
    def setUp(self):
        (
            self.ProtocolError,
            self.build_stage_packet,
            _,
            self.digest_json,
            self.failure_digest,
            _,
            self.submission_digest,
            self.validate_web_response,
            self.web_response_marker,
        ) = load_stage_protocol_api(self)
        self.packet = self.build_stage_packet(
            driver_context_id="ctx-550e8400-e29b-41d4-a716-446655440000",
            run_id="run-123",
            packet_id="packet-123",
            target_stage="web_sol",
            source_revision=1,
            payload={"task": "review", "local_sol_output": "done"},
        )

    def test_packet_digest_binds_every_identity_field(self):
        changed = dict(self.packet)
        changed["driver_context_id"] = "ctx-123e4567-e89b-12d3-a456-426614174000"
        changed.pop("packet_digest")

        self.assertNotEqual(
            self.packet["packet_digest"],
            self.digest_json(changed),
        )

    def test_submission_digest_normalizes_content_and_binds_stable_metadata(self):
        stable = {
            "verification": "operator_attested",
            "model_claimed": "sol",
        }
        first = self.submission_digest(
            self.packet["driver_context_id"],
            "run-123",
            "web_sol",
            self.packet["packet_digest"],
            "answer\r\n",
            stable,
        )
        second = self.submission_digest(
            self.packet["driver_context_id"],
            "run-123",
            "web_sol",
            self.packet["packet_digest"],
            "answer\n",
            stable,
        )
        changed = self.submission_digest(
            self.packet["driver_context_id"],
            "run-123",
            "web_sol",
            self.packet["packet_digest"],
            "answer\n",
            {**stable, "model_claimed": "other"},
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_failure_digest_is_stable_for_equivalent_mapping_order(self):
        first = self.failure_digest(
            self.packet["driver_context_id"],
            "run-123",
            "web_sol",
            self.packet["packet_digest"],
            {"code": "web-failed", "summary": "offline"},
            {"verification": "operator_attested"},
        )
        second = self.failure_digest(
            self.packet["driver_context_id"],
            "run-123",
            "web_sol",
            self.packet["packet_digest"],
            {"summary": "offline", "code": "web-failed"},
            {"verification": "operator_attested"},
        )

        self.assertEqual(first, second)

    def test_web_marker_must_be_the_unique_first_nonempty_line(self):
        marker = self.web_response_marker(self.packet)

        self.validate_web_response("\n" + marker + "\nanalysis", self.packet)
        invalid_values = (
            "analysis\n" + marker,
            marker + "\n" + marker,
            marker.replace("run-123", "run-other"),
        )
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                with self.assertRaises(self.ProtocolError):
                    self.validate_web_response(invalid, self.packet)


class LunaPacketTests(unittest.TestCase):
    def setUp(self):
        self.prefix, self.build_luna_packet, self.parse_luna_packet = (
            load_luna_packet_api(self)
        )
        self.packet = {
            "packet_id": "packet-1",
            "generation": 1,
            "objective": "Add multiply() and tests",
            "working_directory": "/workspace/repo",
            "intended_write_scope": ["src/math.py", "tests/test_math.py"],
            "explicit_side_effect_authorizations": [],
            "success_criteria": ["focused tests pass"],
            "stop_conditions": ["scope expansion required", "A1 authorization required"],
        }

    def test_build_and_parse_use_the_exact_canonical_k1_wire_object(self):
        message = self.build_luna_packet(**self.packet)

        self.assertEqual(
            message,
            self.prefix
            + '{"explicit_side_effect_authorizations":[],"generation":1,'
            '"intended_write_scope":["src/math.py","tests/test_math.py"],'
            '"objective":"Add multiply() and tests","packet_id":"packet-1",'
            '"stop_conditions":["scope expansion required","A1 authorization required"],'
            '"success_criteria":["focused tests pass"],'
            '"working_directory":"/workspace/repo"}',
        )
        self.assertEqual(self.parse_luna_packet(message), self.packet)

    def test_parse_rejects_invalid_k1_schema_and_noncanonical_json(self):
        invalid_packets = {
            "missing_key": {key: value for key, value in self.packet.items() if key != "objective"},
            "extra_key": {**self.packet, "unexpected": True},
            "relative_working_directory": {
                **self.packet,
                "working_directory": "workspace/repo",
            },
            "empty_objective": {**self.packet, "objective": ""},
            "duplicate_scope": {
                **self.packet,
                "intended_write_scope": ["src/math.py", "src/math.py"],
            },
            "non_text_scope": {
                **self.packet,
                "intended_write_scope": ["src/math.py", 7],
            },
            "malformed_generation": {**self.packet, "generation": True},
        }
        for name, packet in invalid_packets.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.parse_luna_packet(encode_luna_packet(self.prefix, packet))

        with self.assertRaises(ValueError):
            self.parse_luna_packet(
                encode_luna_packet(self.prefix, self.packet, canonical=False)
            )


if __name__ == "__main__":
    unittest.main()
