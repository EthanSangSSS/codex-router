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


if __name__ == "__main__":
    unittest.main()
