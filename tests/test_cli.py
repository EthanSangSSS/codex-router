import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class RouterCliTests(unittest.TestCase):
    def cli(self, *args, env=None):
        merged = os.environ.copy()
        merged["PYTHONPATH"] = str(REPO / "src")
        if env:
            merged.update(env)
        return subprocess.run(
            [sys.executable, "-m", "codex_router", *args],
            cwd=REPO,
            env=merged,
            text=True,
            capture_output=True,
        )

    def test_fake_adapter_completes_offline_happy_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = self.cli(
                "run",
                "--task",
                "Return exactly ROUTER_MVP_OK",
                "--adapter-mode",
                "fake",
                "--state-dir",
                tmp,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "ROUTER_MVP_OK")
            runs = list(Path(tmp).iterdir())
            self.assertEqual(len(runs), 1)
            result = json.loads((runs[0] / "result.json").read_text())
            self.assertEqual(result["result"], "ROUTER_MVP_OK")

    def test_real_mode_fails_closed_when_provider_is_not_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = self.cli(
                "run",
                "--task",
                "do real work",
                "--adapter-mode",
                "real",
                "--state-dir",
                tmp,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("provider-not-configured", completed.stderr)


if __name__ == "__main__":
    unittest.main()
