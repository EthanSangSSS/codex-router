import io
import json
import shlex
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from codex_router import lease_control
from codex_router import cli as cli_module
from codex_router.hook import HOOK_CONTEXT_PREFIX, handle_hook_event


class V4RequestFileStagingTests(unittest.TestCase):
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
        self.session_id = "session-v4-request"
        lease_control.initialize_session(
            self.installation, self.secret, self.session_id
        )

    def _root_event(self, *, turn_id: str):
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "prompt": "Implement a bounded V4 task.",
            "cwd": str(self.root),
        }

    def _context(self, output):
        raw = output["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(raw.startswith(HOOK_CONTEXT_PREFIX))
        return json.loads(raw[len(HOOK_CONTEXT_PREFIX) :])

    def _route(self, *, turn_id: str):
        return self._context(
            handle_hook_event(
                self._root_event(turn_id=turn_id),
                self.installation,
            )
        )

    def test_v4_route_uses_private_request_file_not_semantic_argv(self):
        context = self._route(turn_id="root-turn-request-1")
        argv = shlex.split(context["K1_STAGE_COMMAND"])

        self.assertIn("stage-k1-fields", argv)
        self.assertIn("--request-file", argv)
        request_path = Path(argv[argv.index("--request-file") + 1])
        self.assertTrue(request_path.is_absolute())
        self.assertEqual(request_path.parent, self.installation / "stage-requests")
        self.assertNotIn("--packet-id", argv)
        self.assertNotIn("--objective", argv)
        self.assertNotIn("--working-directory", argv)

    def test_v4_request_file_stages_exact_packet_and_is_removed(self):
        context = self._route(turn_id="root-turn-request-2")
        argv = shlex.split(context["K1_STAGE_COMMAND"])
        request_path = Path(argv[argv.index("--request-file") + 1])
        request_path.write_text(
            json.dumps(
                {
                    "packet_id": "packet-v4-request-2",
                    "objective": "bounded request-file staging",
                    "working_directory": str(self.root),
                    "intended_write_scope": ["src", "tests"],
                    "explicit_side_effect_authorizations": [],
                    "success_criteria": ["tests pass"],
                    "stop_conditions": ["scope expansion required"],
                }
            ),
            encoding="utf-8",
        )
        request_path.chmod(0o600)

        command_argv = argv[argv.index("stage-k1-fields") :]
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cli_module.main(command_argv)

        self.assertEqual(exit_code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "staged")
        self.assertEqual(result["packet_id"], "packet-v4-request-2")
        self.assertEqual(result["generation"], 1)
        self.assertRegex(result["task_name"], r"^luna_g1_[0-9a-f]{8}$")
        self.assertRegex(
            result["bootstrap_capability"], r"^v4b1\.[0-9a-f]{64}$"
        )
        self.assertIn(result["bootstrap_capability"], result["spawn_message"])
        self.assertEqual(result["request_cleanup"], "removed")
        self.assertFalse(request_path.exists())

        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(current.generation, 1)
        self.assertEqual(
            current.active_lease.expected_task_name,
            result["task_name"],
        )


if __name__ == "__main__":
    unittest.main()
