import json
import stat
import tempfile
import unittest
from pathlib import Path

from codex_router.hook import handle_hook_event


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


class MinimalAgentIdV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installation = self.root / "installation"
        self.installation.mkdir(mode=0o700)
        self.secret = bytes(range(32))
        self._private(self.installation / "installation-secret", self.secret)
        binary = self.root / "codex"
        binary.write_text("synthetic binary", encoding="utf-8")
        binary.chmod(0o700)
        self._private(
            self.installation / "config.json",
            json.dumps(
                {
                    "protocol": "codex-router/global-policy-config/v1",
                    "state_root": str(self.root / "runs"),
                    "codex_binary": str(binary),
                    "role_config": ROLE_CONFIG,
                }
            ).encode("utf-8"),
        )

    def _private(self, path: Path, content: bytes) -> None:
        path.write_bytes(content)
        path.chmod(0o600)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def _spawn_pending(self) -> None:
        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "root-session",
                "turn_id": "root-turn",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-1",
                "tool_input": {
                    "task_name": "luna_worker",
                    "agent_type": "luna_worker",
                    "fork_turns": "none",
                    "message": "bounded packet",
                },
            },
            self.installation,
        )
        self.assertEqual(output, {})

    def test_subagent_start_binds_native_agent_id_without_transcript(self):
        self._spawn_pending()
        output = handle_hook_event(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "root-session",
                "turn_id": "child-active-turn",
                "agent_id": "native-luna-id",
                "agent_type": "luna_worker",
                "cwd": str(self.root),
            },
            self.installation,
        )
        self.assertEqual(
            output, {"hookSpecificOutput": {"hookEventName": "SubagentStart"}}
        )

    def test_bound_luna_authorizes_by_agent_id_not_child_turn_equality(self):
        self._spawn_pending()
        start = handle_hook_event(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "root-session",
                "turn_id": "child-start-turn",
                "agent_id": "native-luna-id",
                "agent_type": "luna_worker",
                "cwd": str(self.root),
            },
            self.installation,
        )
        self.assertEqual(
            start, {"hookSpecificOutput": {"hookEventName": "SubagentStart"}}
        )
        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "root-session",
                "turn_id": "different-child-active-turn",
                "agent_id": "native-luna-id",
                "agent_type": "luna_worker",
                "tool_name": "Read",
                "tool_use_id": "read-1",
                "tool_input": {"path": "README.md"},
            },
            self.installation,
        )
        self.assertEqual(output, {})

    def test_unknown_luna_agent_id_cannot_use_current_root_authority(self):
        self._spawn_pending()
        start = handle_hook_event(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "root-session",
                "turn_id": "child-start-turn",
                "agent_id": "native-luna-id",
                "agent_type": "luna_worker",
                "cwd": str(self.root),
            },
            self.installation,
        )
        self.assertEqual(
            start, {"hookSpecificOutput": {"hookEventName": "SubagentStart"}}
        )
        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "root-session",
                "turn_id": "child-active-turn",
                "agent_id": "historical-or-other-id",
                "agent_type": "luna_worker",
                "tool_name": "Read",
                "tool_use_id": "read-2",
                "tool_input": {"path": "README.md"},
            },
            self.installation,
        )
        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )


if __name__ == "__main__":
    unittest.main()
