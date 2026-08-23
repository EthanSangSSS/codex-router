import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class V4FreshProcessBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir(mode=0o700)
        self.state_root = self.root / "router-runs"
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic codex binary\n", encoding="utf-8")
        self.binary.chmod(0o700)
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(REPO / "src")

    def cli(self, *args, input_text=None):
        return subprocess.run(
            [sys.executable, "-m", "codex_router", *args],
            cwd=REPO,
            env=self.env,
            text=True,
            input=input_text,
            capture_output=True,
        )

    def test_install_status_and_self_test_survive_fresh_process_boundaries(self):
        installed = self.cli(
            "global-install",
            "--codex-home",
            str(self.codex_home),
            "--state-dir",
            str(self.state_root),
            "--codex-bin",
            str(self.binary),
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        install_payload = json.loads(installed.stdout)
        self.assertEqual(install_payload["state"], "installed")
        self.assertEqual(install_payload["router_design"], "v4.0_generation_lease")

        status = self.cli(
            "global-status",
            "--codex-home",
            str(self.codex_home),
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        status_payload = json.loads(status.stdout)
        self.assertEqual(status_payload["state"], "installed")
        self.assertEqual(status_payload["router_design"], "v4.0_generation_lease")
        self.assertEqual(status_payload["live_activation"], "PENDING_LIVE_ACCEPTANCE")

        self_test = self.cli(
            "global-self-test",
            "--codex-home",
            str(self.codex_home),
        )
        self.assertEqual(self_test.returncode, 0, self_test.stderr)
        self_test_payload = json.loads(self_test.stdout)
        self.assertEqual(self_test_payload["status"], "pass")
        self.assertEqual(
            self_test_payload["router_design"], "v4.0_generation_lease"
        )

    def test_hook_subprocess_uses_final_v4_request_staging_wrapper(self):
        installed = self.cli(
            "global-install",
            "--codex-home",
            str(self.codex_home),
            "--state-dir",
            str(self.state_root),
            "--codex-bin",
            str(self.binary),
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        installation_dir = Path(json.loads(installed.stdout)["installation_dir"])

        event = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "process-boundary-session",
            "turn_id": "process-boundary-turn",
            "prompt": "修改 Router process boundary probe",
            "cwd": str(self.root),
        }
        routed = self.cli(
            "hook-user-prompt",
            "--installation-dir",
            str(installation_dir),
            input_text=json.dumps(event, ensure_ascii=False) + "\n",
        )
        self.assertEqual(routed.returncode, 0, routed.stderr)
        payload = json.loads(routed.stdout)
        additional = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn('"workflow":"generation_lease_v4"', additional)
        self.assertIn('"K1_STAGE_INTERFACE":"private_request_file_v4"', additional)
        self.assertIn(" --request-file ", additional)


if __name__ == "__main__":
    unittest.main()
