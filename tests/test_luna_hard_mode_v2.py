import json
import stat
import tempfile
import tomllib
import unittest
from pathlib import Path

from codex_router import global_install_adapter as global_install
from codex_router import native_lifecycle as lifecycle
from codex_router.hook import handle_hook_event


ROLE_CONFIG = {
    "local_sol": {"requested_model": "gpt-5.6-sol", "requested_reasoning": "max"},
    "web_sol": {
        "model_claimed": "sol",
        "reasoning_claimed": "xhigh",
        "verification": "operator_attested",
    },
    "luna": {"requested_model": "gpt-5.6-luna", "requested_reasoning": "max"},
}


class LunaHardModeV2Tests(unittest.TestCase):
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
        lifecycle.pre_spawn(
            self.installation,
            self.secret,
            "session-a",
            "root-turn",
            "spawn-1",
            {"task_name": "luna_worker", "fork_turns": "none"},
        )
        lifecycle.bind_child(
            self.installation,
            self.secret,
            "session-a",
            "luna-a",
            "luna_worker",
        )

    def _private(self, path: Path, content: bytes) -> None:
        path.write_bytes(content)
        path.chmod(0o600)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def _luna_tool(self, tool_name: str, tool_input: dict) -> dict:
        return handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "child-active-turn",
                "agent_id": "luna-a",
                "agent_type": "luna_worker",
                "tool_name": tool_name,
                "tool_use_id": f"{tool_name}-1",
                "tool_input": tool_input,
            },
            self.installation,
        )

    def test_bound_luna_cannot_use_even_benign_shell_in_hard_mode(self):
        for tool_name in ("Bash", "shell_command"):
            with self.subTest(tool_name=tool_name):
                output = self._luna_tool(tool_name, {"command": "echo ok"})
                self.assertEqual(
                    output["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                self.assertIn(
                    "hard mode",
                    output["hookSpecificOutput"]["permissionDecisionReason"].lower(),
                )

    def test_bound_luna_still_allows_non_process_work(self):
        self.assertEqual(self._luna_tool("Read", {"path": "README.md"}), {})
        self.assertEqual(self._luna_tool("apply_patch", {"patch": "synthetic"}), {})

    def test_bound_luna_denies_every_non_allowlisted_tool_surface(self):
        denied_tools = (
            "unknown_future_tool",
            "mcp__calendar__create_event",
            "list_mcp_resources",
            "list_mcp_resource_templates",
            "read_mcp_resource",
            "spawn_agent",
            "send_message",
            "followup_task",
            "wait_agent",
            "list_agents",
            "Bash",
            "shell_command",
            "exec_command",
            "write_stdin",
            "exec",
            "wait",
            "request_permissions",
            "request_plugin_install",
            "list_available_plugins_to_install",
            "tool_search",
            "web_search",
        )
        for tool_name in denied_tools:
            with self.subTest(tool_name=tool_name):
                output = self._luna_tool(tool_name, {"args": {}})
                self.assertEqual(
                    output["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def test_primary_sol_shell_is_not_restricted_by_luna_hard_mode(self):
        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "root-turn",
                "tool_name": "Bash",
                "tool_use_id": "root-shell",
                "tool_input": {"command": "python -m unittest"},
            },
            self.installation,
        )
        self.assertEqual(output, {})

    def test_generated_luna_profile_uses_documented_hard_mode_keys(self):
        parsed = tomllib.loads(
            global_install._luna_agent_bytes(ROLE_CONFIG["luna"]).decode("utf-8")
        )
        self.assertFalse(parsed["agents"]["enabled"])
        self.assertFalse(parsed["features"]["multi_agent"])
        self.assertFalse(parsed["features"]["shell_tool"])
        self.assertFalse(parsed["features"]["unified_exec"])
        self.assertFalse(parsed["features"]["code_mode"]["enabled"])
        self.assertFalse(parsed["features"]["multi_agent_v2"])
        self.assertFalse(parsed["features"]["code_mode_only"])
        self.assertFalse(parsed["features"]["request_permissions_tool"])
        self.assertFalse(parsed["features"]["apps"])
        self.assertFalse(parsed["features"]["enable_mcp_apps"])
        self.assertFalse(parsed["features"]["plugins"])
        self.assertFalse(parsed["features"]["tool_suggest"])
        self.assertEqual(parsed["web_search"], "disabled")


if __name__ == "__main__":
    unittest.main()
