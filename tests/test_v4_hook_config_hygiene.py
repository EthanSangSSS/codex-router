import json
import shlex
import tempfile
import unittest
from pathlib import Path

from codex_router import global_install_adapter as adapter


class V4HookConfigHygieneTests(unittest.TestCase):
    def test_subagent_stop_omits_unsupported_additional_context_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            installation = Path(temporary) / "installation"
            handler = {
                "type": "command",
                "command": shlex.join(
                    (
                        "/usr/bin/python3",
                        "-E",
                        "-P",
                        "-m",
                        "codex_router",
                        "hook-user-prompt",
                        "--installation-dir",
                        str(installation),
                    )
                ),
                "timeout": 10,
                "statusMessage": "Routing with Codex Router [codex-router-global-policy-v1]",
                "additionalContextLimit": 2500,
            }

            document = json.loads(adapter.install_hook_v2(None, handler))

        for event in (
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "SubagentStart",
        ):
            with self.subTest(event=event):
                installed = document["hooks"][event][0]["hooks"][0]
                self.assertEqual(installed["additionalContextLimit"], 2500)

        stop = document["hooks"]["SubagentStop"][0]["hooks"][0]
        self.assertNotIn("additionalContextLimit", stop)


if __name__ == "__main__":
    unittest.main()
