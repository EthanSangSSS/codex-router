import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from codex_router.global_install_adapter import global_install
from codex_router.hook import handle_hook_event, handle_user_prompt


ROLE_CONFIG = {
    "local_sol": {"requested_model": "gpt-5.6-sol", "requested_reasoning": "max"},
    "web_sol": {
        "model_claimed": "sol",
        "reasoning_claimed": "xhigh",
        "verification": "operator_attested",
    },
    "luna": {"requested_model": "gpt-5.6-luna", "requested_reasoning": "max"},
}


class PolicySurfaceV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "codex-home"
        self.home.mkdir(mode=0o700)
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)
        global_install(
            codex_home=self.home,
            state_root=self.root / "runs",
            codex_binary=self.binary,
            defaults=ROLE_CONFIG,
        )
        self.installation = self.home / ".codex-router-policy-v1"

    def _bind_luna(self):
        self.assertEqual(
            handle_hook_event(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-a",
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
            ),
            {},
        )
        self.assertEqual(
            handle_hook_event(
                {
                    "hook_event_name": "SubagentStart",
                    "session_id": "session-a",
                    "turn_id": "child-turn",
                    "agent_id": "luna-native-id",
                    "agent_type": "luna_worker",
                },
                self.installation,
            ),
            {"hookSpecificOutput": {"hookEventName": "SubagentStart"}},
        )

    def test_managed_hook_set_omits_subagent_stop(self):
        document = json.loads((self.home / "hooks.json").read_text(encoding="utf-8"))
        router_events = set()
        for event, groups in document["hooks"].items():
            for group in groups:
                for hook in group.get("hooks", []):
                    if "codex-router-global-policy-v1" in hook.get("statusMessage", ""):
                        router_events.add(event)
        self.assertEqual(
            router_events,
            {
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "PermissionRequest",
                "Stop",
                "SubagentStart",
            },
        )

    def test_route_receipt_declares_revoke_only_terminal_policy(self):
        output = handle_user_prompt(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-a",
                "turn_id": "turn-a",
                "prompt": "修改 README",
                "cwd": str(self.root),
            },
            self.installation,
        )
        raw = output["hookSpecificOutput"]["additionalContext"]
        context = json.loads(raw.split(" ", 1)[1])
        self.assertEqual(
            context["parent_terminal_policy"], "revoke_only_security_boundary"
        )
        self.assertEqual(context["initial_context_mode"], "packet_only")

    def test_managed_agents_policy_says_hard_mode_and_no_stop_continuation(self):
        text = (self.home / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Sol plans", text)
        self.assertIn("fork_turns=none", text)
        self.assertIn("hard mode", text.lower())
        self.assertIn("Sol runs build/test/verification commands", text)
        self.assertIn("Stop only revokes", text)
        self.assertNotIn("Stop requests cleanup", text)
        self.assertNotIn("perform at most one native cleanup attempt", text)

    def test_luna_instructions_match_reduced_executor_contract(self):
        parsed = tomllib.loads(
            (self.home / "agents" / "luna-worker.toml").read_text(encoding="utf-8")
        )
        instructions = parsed["developer_instructions"]
        self.assertIn("hard mode", instructions.lower())
        self.assertIn("do not run shell", instructions.lower())
        self.assertIn("return process-dependent validation to Sol", instructions)
        self.assertNotIn("including focused tests", instructions)

    def test_permission_deny_prefers_bound_native_agent_id_even_without_role_text(self):
        self._bind_luna()
        output = handle_hook_event(
            {
                "hook_event_name": "PermissionRequest",
                "session_id": "session-a",
                "turn_id": "another-child-turn",
                "agent_id": "luna-native-id",
                "tool_name": "Bash",
                "tool_input": {"command": "echo forbidden"},
            },
            self.installation,
        )
        self.assertEqual(
            output["hookSpecificOutput"]["decision"]["behavior"], "deny"
        )

    def test_partial_child_identity_cannot_fall_through_to_primary_lifecycle_authority(self):
        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-b",
                "turn_id": "root-turn",
                "agent_type": "reviewer",
                "tool_name": "spawn_agent",
                "tool_use_id": "malformed-child-spawn",
                "tool_input": {
                    "task_name": "luna_worker",
                    "fork_turns": "none",
                    "message": "should not be admitted",
                },
            },
            self.installation,
        )
        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )


if __name__ == "__main__":
    unittest.main()
