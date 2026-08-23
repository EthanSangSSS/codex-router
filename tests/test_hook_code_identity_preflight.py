import unittest
from pathlib import Path
from unittest.mock import patch


class HookCodeIdentityPreflightTests(unittest.TestCase):
    def _output(self, decision: str, reason: str) -> dict:
        import json
        from codex_router import hook

        context = {
            "protocol": hook.HOOK_CONTEXT_PROTOCOL,
            "decision": decision,
            "reason": reason,
        }
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": hook.HOOK_CONTEXT_PREFIX
                + json.dumps(context, sort_keys=True, separators=(",", ":")),
            }
        }

    def test_preflight_probes_explicit_direct_and_bypass_markers(self):
        from codex_router import global_install

        installation_dir = Path("/tmp/router-installation")
        handler = {
            "type": "command",
            "command": "/usr/bin/python3 -E -P -m codex_router hook-user-prompt --installation-dir /tmp/router-installation",
            "timeout": 10,
            "statusMessage": "Routing with Codex Router [codex-router-global-policy-v1]",
            "additionalContextLimit": 2500,
        }
        seen: list[str] = []

        def fake_invoke(arguments, *, event, cwd):
            prompt = event["prompt"]
            seen.append(prompt)
            first = next(line.strip() for line in prompt.splitlines() if line.strip())
            if first == "[CODEX_ROUTER_DIRECT]":
                return self._output("direct", "explicit_one_turn_direct")
            if first == "仅本地执行":
                return self._output("bypass", "explicit_one_turn_bypass")
            return self._output("direct", "casual_greeting")

        with patch.object(global_install, "_invoke_hook_argv", side_effect=fake_invoke):
            global_install._preflight_hook_handler(
                handler,
                installation_dir=installation_dir,
                cwd=Path("/tmp"),
            )

        self.assertIn("你好", seen)
        self.assertIn("[CODEX_ROUTER_DIRECT]\n修改 Router", seen)
        self.assertIn("仅本地执行\n修改 Router", seen)


if __name__ == "__main__":
    unittest.main()
