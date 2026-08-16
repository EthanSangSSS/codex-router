import json
import tempfile
import unittest
from pathlib import Path

from codex_router.cli import _global_status_payload
from codex_router.global_install_adapter import (
    global_install,
    global_status,
)


ROLE_CONFIG = {
    "local_sol": {"requested_model": "gpt-5.6-sol", "requested_reasoning": "max"},
    "web_sol": {
        "model_claimed": "sol",
        "reasoning_claimed": "xhigh",
        "verification": "operator_attested",
    },
    "luna": {"requested_model": "gpt-5.6-luna", "requested_reasoning": "max"},
}


class PrimaryCapabilityV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "codex-home"
        self.home.mkdir(mode=0o700)
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)

    def install(self):
        return global_install(
            codex_home=self.home,
            state_root=self.root / "runs",
            codex_binary=self.binary,
            defaults=ROLE_CONFIG,
        )

    def test_explicit_multi_agent_false_is_incompatible_without_rewrite(self):
        config = self.home / "config.toml"
        original = b"[features]\nmulti_agent = false\n"
        config.write_bytes(original)
        self.install()
        status = global_status(self.home)
        self.assertEqual(status.compatibility, "INCOMPATIBLE")
        self.assertIn("multi_agent", status.compatibility_reason)
        self.assertEqual(config.read_bytes(), original)

    def test_explicit_agents_disabled_is_incompatible_without_rewrite(self):
        config = self.home / "config.toml"
        original = b"[agents]\nenabled = false\n"
        config.write_bytes(original)
        self.install()
        status = global_status(self.home)
        self.assertEqual(status.compatibility, "INCOMPATIBLE")
        self.assertIn("agents.enabled", status.compatibility_reason)
        self.assertEqual(config.read_bytes(), original)

    def test_explicit_required_primary_capabilities_can_be_statically_compatible(self):
        config = self.home / "config.toml"
        config.write_text(
            "[agents]\nenabled = true\n\n[features]\nmulti_agent = true\nhooks = true\n",
            encoding="utf-8",
        )
        self.install()
        status = global_status(self.home)
        self.assertEqual(status.compatibility, "COMPATIBLE")
        self.assertEqual(status.luna_execution_mode, "hard_mode_no_process")

    def test_absent_primary_config_is_unknown_not_claimed_compatible(self):
        self.install()
        status = global_status(self.home)
        self.assertEqual(
            status.compatibility,
            "UNKNOWN_REQUIRES_CAPABILITY_CHECK",
        )
        self.assertEqual(status.luna_execution_mode, "hard_mode_no_process")

    def test_hooks_explicitly_disabled_is_incompatible(self):
        (self.home / "config.toml").write_text(
            "[agents]\nenabled = true\n\n[features]\nmulti_agent = true\nhooks = false\n",
            encoding="utf-8",
        )
        self.install()
        status = global_status(self.home)
        self.assertEqual(status.compatibility, "INCOMPATIBLE")
        self.assertIn("hooks", status.compatibility_reason)

    def test_cli_status_payload_exposes_preflight_and_execution_mode(self):
        self.install()
        status = global_status(self.home)
        payload = _global_status_payload(status)
        self.assertEqual(payload["compatibility"], status.compatibility)
        self.assertEqual(payload["compatibility_reason"], status.compatibility_reason)
        self.assertEqual(payload["luna_execution_mode"], "hard_mode_no_process")


if __name__ == "__main__":
    unittest.main()
