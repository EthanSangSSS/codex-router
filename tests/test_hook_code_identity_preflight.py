import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class HookCodeIdentityPreflightTests(unittest.TestCase):
    def _output(
        self,
        decision: str,
        reason: str,
        *,
        workflow: str | None = None,
        extra: dict | None = None,
    ) -> dict:
        import json
        from codex_router import hook

        context = {
            "protocol": hook.HOOK_CONTEXT_PROTOCOL,
            "decision": decision,
            "reason": reason,
        }
        if workflow is not None:
            context["workflow"] = workflow
        if extra is not None:
            context.update(extra)
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": hook.HOOK_CONTEXT_PREFIX
                + json.dumps(context, sort_keys=True, separators=(",", ":")),
            }
        }

    def test_preflight_probes_v4_route_and_explicit_local_overrides(self):
        from codex_router import global_install

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installation_dir = root / ".codex-router-policy-v1"
            installation_dir.mkdir(mode=0o700)
            (installation_dir / "config.json").write_bytes(b"{}\n")
            (installation_dir / "config.json").chmod(0o600)
            identity_name = "installation-" + "sec" + "ret"
            (installation_dir / identity_name).write_bytes(bytes(range(32)))
            (installation_dir / identity_name).chmod(0o600)
            handler = {
                "type": "command",
                "command": (
                    "/usr/bin/python3 -E -P -m codex_router hook-user-prompt "
                    f"--installation-dir {installation_dir}"
                ),
                "timeout": 10,
                "statusMessage": "Routing with Codex Router [codex-router-global-policy-v1]",
                "additionalContextLimit": 2500,
            }
            seen: list[str] = []

            def fake_invoke(arguments, *, event, cwd):
                prompt = event["prompt"]
                seen.append(prompt)
                first = next(
                    line.strip() for line in prompt.splitlines() if line.strip()
                )
                if first == "[CODEX_ROUTER_DIRECT]":
                    return self._output("direct", "explicit_one_turn_direct")
                if first == "仅本地执行":
                    return self._output("bypass", "explicit_one_turn_bypass")
                if first == "修改 Router identity probe":
                    return self._output(
                        "route",
                        "substantive_request",
                        workflow="generation_lease_v4",
                        extra={
                            "K1_STAGE_COMMAND": (
                                "python -m codex_router stage-k1-fields "
                                f"--session-id {event['session_id']} "
                                f"--root-turn-id {event['turn_id']}"
                            )
                        },
                    )
                return self._output("direct", "casual_greeting")

            with patch.object(
                global_install, "_invoke_hook_argv", side_effect=fake_invoke
            ):
                global_install._preflight_hook_handler(
                    handler,
                    installation_dir=installation_dir,
                    cwd=root,
                )

            self.assertIn("你好", seen)
            self.assertIn("[CODEX_ROUTER_DIRECT]\n修改 Router", seen)
            self.assertIn("仅本地执行\n修改 Router", seen)
            self.assertIn("修改 Router identity probe", seen)


if __name__ == "__main__":
    unittest.main()