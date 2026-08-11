import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


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
REPO = Path(__file__).resolve().parents[1]


class GlobalSelfTestTests(unittest.TestCase):
    def setUp(self):
        from codex_router.global_install import global_install

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir(mode=0o700)
        self.state_root = self.root / "configured-runs"
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)
        global_install(
            codex_home=self.codex_home,
            state_root=self.state_root,
            codex_binary=self.binary,
            defaults=ROLE_CONFIG,
        )

    def snapshot(self):
        return {
            str(path.relative_to(self.codex_home)): path.read_bytes()
            for path in self.codex_home.rglob("*")
            if path.is_file()
        }

    def test_offline_self_test_is_ephemeral_private_and_has_no_external_actions(self):
        import codex_router.global_install as global_install_module

        before = self.snapshot()
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), patch(
            "webbrowser.open", side_effect=AssertionError("browser forbidden")
        ), patch.object(
            global_install_module,
            "handle_user_prompt",
            side_effect=AssertionError("self-test must use the configured subprocess"),
            create=True,
        ):
            result = global_install_module.global_self_test(self.codex_home)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["protocol"], "codex-router/global-self-test/v1")
        self.assertTrue(all(result["checks"].values()))
        self.assertFalse(result["network_used"])
        self.assertFalse(result["browser_used"])
        self.assertFalse(result["installation_activated"])
        self.assertEqual(result["hook_trust"], "unknown")
        self.assertTrue(result["checks"]["hook_command_subprocess"])
        self.assertTrue(result["checks"]["stateless_native_luna_route"])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.state_root.exists())
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        for raw_fragment in (
            "synthetic-self-test-session",
            "synthetic-self-test-turn",
            "synthetic-self-test-route",
            "ctx-",
            "run-hook-",
        ):
            self.assertNotIn(raw_fragment, serialized)
        persisted = b"\n".join(self.snapshot().values()).decode("utf-8", errors="ignore")
        self.assertNotIn("synthetic-self-test-session", persisted)
        self.assertNotIn("synthetic-self-test-route", persisted)

    def test_self_test_accepts_current_source_hook_contract(self):
        import codex_router.global_install as global_install_module
        import codex_router.hook as hook_module

        installation_dir = self.codex_home / ".codex-router-policy-v1"
        handle_user_prompt = getattr(hook_module, "handle_user_prompt", None)
        self.assertTrue(
            callable(handle_user_prompt),
            "current UserPromptSubmit handler is unavailable",
        )
        handle_agent_spawn = getattr(hook_module, "handle_agent_spawn", None)
        self.assertTrue(
            callable(handle_agent_spawn),
            "current PreToolUse agent-spawn handler is unavailable",
        )
        if not callable(handle_user_prompt) or not callable(handle_agent_spawn):
            return

        seen_events = []

        def invoke_current_source(_arguments, **kwargs):
            event = kwargs.get("event")
            self.assertIsInstance(event, dict)
            if not isinstance(event, dict):
                return {}
            seen_events.append(event.get("hook_event_name"))
            if event.get("hook_event_name") == "UserPromptSubmit":
                result = handle_user_prompt(event, installation_dir)
            elif event.get("hook_event_name") == "PreToolUse":
                result = handle_agent_spawn(event)
            else:
                self.fail("unexpected hook event type")
                return {}
            if result is None:
                return {}
            if isinstance(result, dict):
                nested = result.get("hookSpecificOutput")
                if result.get("permissionDecision") == "allow" or (
                    isinstance(nested, dict)
                    and nested.get("permissionDecision") == "allow"
                ):
                    return {}
            return result

        with patch.object(
            global_install_module,
            "_invoke_hook_argv",
            side_effect=invoke_current_source,
        ):
            try:
                result = global_install_module.global_self_test(self.codex_home)
            except Exception as error:
                self.fail(str(error))

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["checks"]["stateless_native_luna_route"])
        self.assertIn("UserPromptSubmit", seen_events)
        self.assertIn("PreToolUse", seen_events)

    def test_self_test_rejects_nonempty_json_for_allowed_luna(self):
        import codex_router.global_install as global_install_module
        from codex_router.state import RouterStateError

        before = self.snapshot()
        denial = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Only persistent luna_worker spawns are permitted"
                ),
            }
        }
        real_run = global_install_module.subprocess.run

        def fake_run(arguments, **kwargs):
            if "hook-user-prompt" in arguments:
                return real_run(arguments, **kwargs)
            self.assertEqual(arguments[-1], "hook-agent-spawn")
            event = json.loads(kwargs["input"])
            tool_input = event.get("tool_input") if isinstance(event, dict) else None
            if (
                isinstance(tool_input, dict)
                and tool_input.get("agent_type") == "luna_worker"
            ):
                return subprocess.CompletedProcess(
                    arguments, 0, b"{}\n", b""
                )
            return subprocess.CompletedProcess(
                arguments,
                0,
                json.dumps(denial, sort_keys=True).encode("utf-8") + b"\n",
                b"",
            )

        with patch.object(
            global_install_module.subprocess,
            "run",
            side_effect=fake_run,
        ):
            with self.assertRaises(RouterStateError) as raised:
                global_install_module.global_self_test(self.codex_home)

        self.assertEqual(raised.exception.code, "conflict")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.state_root.exists())

    def test_offline_self_test_exercises_luna_spawn_guard_without_activation(self):
        import codex_router.global_install as global_install_module

        before = self.snapshot()
        with patch.object(
            socket,
            "socket",
            side_effect=AssertionError("network forbidden"),
        ), patch(
            "webbrowser.open",
            side_effect=AssertionError("browser forbidden"),
        ):
            result = global_install_module.global_self_test(self.codex_home)

        self.assertEqual(result.get("status"), "pass")
        checks = result.get("checks", {})
        self.assertIsInstance(checks, dict)
        if not isinstance(checks, dict):
            return
        for check_name in (
            "agent_spawn_luna_allowed",
            "agent_spawn_non_luna_denied",
            "agent_spawn_malformed_denied",
            "agent_spawn_guard_subprocess",
        ):
            with self.subTest(self_test_check=check_name):
                self.assertTrue(checks.get(check_name), checks)
        self.assertFalse(result.get("network_used", True))
        self.assertFalse(result.get("browser_used", True))
        self.assertFalse(result.get("installation_activated", True))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.state_root.exists())

    def test_cli_self_test_outputs_one_safe_json_object(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPO / "src")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "codex_router",
                "global-self-test",
                "--codex-home",
                str(self.codex_home),
            ],
            cwd=REPO,
            env=environment,
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(len(completed.stdout.strip().splitlines()), 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertFalse(self.state_root.exists())

    def test_uninstalled_policy_cannot_claim_a_passing_self_test(self):
        from codex_router.global_install import global_self_test, global_uninstall
        from codex_router.state import RouterStateError

        global_uninstall(self.codex_home)

        with self.assertRaises(RouterStateError) as raised:
            global_self_test(self.codex_home)

        self.assertEqual(raised.exception.code, "conflict")


if __name__ == "__main__":
    unittest.main()
