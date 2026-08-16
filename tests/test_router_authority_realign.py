import json
import stat
import tempfile
import unittest
from pathlib import Path

from codex_router import native_lifecycle as lifecycle
from codex_router.hook import handle_hook_event, handle_user_prompt


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


class RouterAuthorityRealignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installation_dir = self.root / "installation"
        self.installation_dir.mkdir(mode=0o700)
        self.secret = bytes(range(32))
        self._write_private(self.installation_dir / "installation-secret", self.secret)
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)
        self._write_private(
            self.installation_dir / "config.json",
            json.dumps(
                {
                    "protocol": "codex-router/global-policy-config/v1",
                    "state_root": str(self.root / "runs"),
                    "codex_binary": str(self.binary),
                    "role_config": ROLE_CONFIG,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )

    def _write_private(self, path: Path, content: bytes) -> None:
        path.write_bytes(content)
        path.chmod(0o600)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def _bind_luna(self, *, session: str = "session-a", turn: str = "turn-a") -> None:
        lifecycle.pre_spawn(
            self.installation_dir,
            self.secret,
            session,
            turn,
            "spawn-1",
            {"task_name": "luna_worker", "fork_turns": "none"},
        )
        lifecycle.post_spawn(
            self.installation_dir,
            self.secret,
            session,
            turn,
            "spawn-1",
            {"task_name": "/root/luna_worker"},
        )
        lifecycle.bind_child(
            self.installation_dir,
            self.secret,
            session,
            "luna-child",
            "luna_worker",
        )

    def _journal_record(self, session: str, turn: str):
        path = self.installation_dir / "native-luna-safety-v2.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        key = lifecycle._key(session, turn)
        return state["bindings"][key]

    def _prompt(self, prompt: str, *, session: str = "session-a", turn: str = "turn-a"):
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session,
            "turn_id": turn,
            "prompt": prompt,
            "cwd": str(self.root),
        }

    def _route_context(self, prompt: str = "修改 README"):
        output = handle_user_prompt(self._prompt(prompt), self.installation_dir)
        raw = output["hookSpecificOutput"]["additionalContext"]
        prefix = "[CODEX_ROUTER_POLICY_V1] "
        self.assertTrue(raw.startswith(prefix))
        return json.loads(raw[len(prefix) :])

    def test_route_context_preserves_sol_final_authority_and_returns_blockers_to_sol(self):
        context = self._route_context()
        self.assertEqual(context["decision"], "route")
        self.assertEqual(context["sol_role"], "plan_review_final_authority")
        self.assertEqual(context["luna_lifecycle"], "persistent_while_root_turn_active")
        self.assertEqual(context["parent_terminal_policy"], "revoke_then_cleanup")
        self.assertEqual(context["capacity_failure_policy"], "return_to_sol")
        self.assertEqual(context["luna_codex_runtime_policy"], "forbidden")
        self.assertEqual(context["interactive_blocker_policy"], "return_to_sol_or_user")

    def test_direct_override_revokes_prior_turn_before_returning_direct(self):
        self._bind_luna(turn="turn-old")
        output = handle_user_prompt(
            self._prompt("[CODEX_ROUTER_DIRECT]\n修复 Router", turn="turn-new"),
            self.installation_dir,
        )
        raw = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn('"decision":"direct"', raw)
        self.assertEqual(
            self._journal_record("session-a", "turn-old")["authorization"],
            "REVOKED",
        )

    def test_new_routed_root_turn_revokes_prior_turn_binding(self):
        self._bind_luna(turn="turn-old")
        context = self._route_context("修改 README")
        self.assertEqual(context["decision"], "route")
        self.assertEqual(
            self._journal_record("session-a", "turn-old")["authorization"],
            "REVOKED",
        )

    def test_stop_revokes_active_binding_before_requesting_one_cleanup_continuation(self):
        self._bind_luna()
        output = handle_hook_event(
            {
                "hook_event_name": "Stop",
                "session_id": "session-a",
                "turn_id": "turn-a",
            },
            self.installation_dir,
        )
        self.assertEqual(output["decision"], "block")
        record = self._journal_record("session-a", "turn-a")
        self.assertEqual(record["authorization"], "REVOKED")
        self.assertTrue(record["stop_blocked"])
        second = handle_hook_event(
            {
                "hook_event_name": "Stop",
                "session_id": "session-a",
                "turn_id": "turn-a",
            },
            self.installation_dir,
        )
        self.assertEqual(second, {})

    def test_non_luna_permission_request_defers_to_native_approval_flow(self):
        output = handle_hook_event(
            {
                "hook_event_name": "PermissionRequest",
                "session_id": "session-a",
                "turn_id": "turn-a",
                "tool_name": "Bash",
                "tool_input": {"command": "echo ok"},
                "agent_type": "primary",
            },
            self.installation_dir,
        )
        self.assertEqual(output, {})

    def test_non_primary_child_cannot_create_or_control_router_agents(self):
        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "turn-a",
                "tool_name": "spawn_agent",
                "tool_use_id": "child-spawn",
                "agent_id": "other-child",
                "agent_type": "reviewer",
                "tool_input": {"task_name": "luna_worker", "fork_turns": "none"},
            },
            self.installation_dir,
        )
        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_v2_parent_message_followup_and_interrupt_use_target_field(self):
        self._bind_luna()
        for tool_name, tool_input in (
            ("send_message", {"target": "/root/luna_worker", "message": "fix"}),
            ("followup_task", {"target": "/root/luna_worker", "message": "fix"}),
            ("interrupt_agent", {"target": "/root/luna_worker"}),
        ):
            with self.subTest(tool_name=tool_name):
                output = handle_hook_event(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "session-a",
                        "turn_id": "turn-a",
                        "tool_name": tool_name,
                        "tool_use_id": f"{tool_name}-1",
                        "tool_input": tool_input,
                    },
                    self.installation_dir,
                )
                self.assertEqual(output, {})

    def test_parent_rejects_wrong_v2_target(self):
        self._bind_luna()
        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "turn-a",
                "tool_name": "send_message",
                "tool_use_id": "send-1",
                "tool_input": {"target": "/root/other", "message": "x"},
            },
            self.installation_dir,
        )
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_spawn_requires_fork_turns_none(self):
        for tool_input in (
            {"task_name": "luna_worker"},
            {"task_name": "luna_worker", "fork_turns": "all"},
        ):
            with self.subTest(tool_input=tool_input):
                with self.subTest():
                    temp = tempfile.TemporaryDirectory()
                    self.addCleanup(temp.cleanup)
                    root = Path(temp.name)
                    install = root / "installation"
                    install.mkdir(mode=0o700)
                    self._write_private(install / "installation-secret", self.secret)
                    binary = root / "codex"
                    binary.write_text("synthetic binary", encoding="utf-8")
                    binary.chmod(0o700)
                    self._write_private(
                        install / "config.json",
                        json.dumps(
                            {
                                "protocol": "codex-router/global-policy-config/v1",
                                "state_root": str(root / "runs"),
                                "codex_binary": str(binary),
                                "role_config": ROLE_CONFIG,
                            }
                        ).encode("utf-8"),
                    )
                    output = handle_hook_event(
                        {
                            "hook_event_name": "PreToolUse",
                            "session_id": "session-packet",
                            "turn_id": "turn-packet",
                            "tool_name": "spawn_agent",
                            "tool_use_id": "spawn-packet",
                            "tool_input": tool_input,
                        },
                        install,
                    )
                    self.assertEqual(
                        output["hookSpecificOutput"]["permissionDecision"], "deny"
                    )

    def test_spawn_with_packet_only_context_is_admitted(self):
        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-a",
                "turn_id": "turn-a",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-packet",
                "tool_input": {"task_name": "luna_worker", "fork_turns": "none"},
            },
            self.installation_dir,
        )
        self.assertEqual(output, {})


if __name__ == "__main__":
    unittest.main()
