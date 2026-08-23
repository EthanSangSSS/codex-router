import tempfile
import unittest
from pathlib import Path

from codex_router import global_install as global_install_core
from codex_router import global_install_adapter


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


class V4InstalledPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir(mode=0o700)
        self.state_root = self.root / "router-runs"
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)

    def _install(self):
        return global_install_adapter.global_install(
            codex_home=self.codex_home,
            state_root=self.state_root,
            codex_binary=self.binary,
            defaults=ROLE_CONFIG,
        )

    def test_installed_primary_policy_matches_generation_lease_wire(self):
        status = self._install()
        self.assertEqual(status.router_design, "v4.0_generation_lease")
        self.assertEqual(status.luna_execution_mode, "generation_lease_v4")
        self.assertEqual(status.live_activation, "PENDING_LIVE_ACCEPTANCE")

        agents = (self.codex_home / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("generation_lease_v4", agents)
        self.assertIn("complete injected `K1_STAGE_COMMAND` verbatim", agents)
        self.assertIn("seven-field UTF-8 JSON request", agents)
        self.assertIn("task_name returned by staging", agents)
        self.assertIn("spawn_message returned by staging", agents)
        self.assertIn("CODEX_ROUTER_LEASE_BOOTSTRAP_V4", agents)
        self.assertIn("logical lease revocation", agents)
        self.assertIn("does not wait for `SubagentStop`", agents)
        self.assertNotIn("V2 uses `task_name=luna_worker`", agents)
        self.assertNotIn('`Bash` tool with `{"command":"pwd"}`', agents)

    def test_installed_primary_policy_exposes_v1_and_v2_spawn_transports(self):
        self._install()
        agents = (self.codex_home / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("V1", agents)
        self.assertIn("V2", agents)
        self.assertIn("multi_agent_v1__spawn_agent", agents)
        self.assertIn("fork_context=false", agents)
        self.assertIn("task_name", agents)
        self.assertIn("fork_turns=none", agents)
        self.assertIn("spawn_message", agents)
        self.assertIn("does not carry `task_name` or `fork_turns`", agents)
        self.assertIn("Router lease identity", agents)

    def test_installed_luna_policy_uses_capability_bound_bootstrap(self):
        self._install()
        luna = (
            self.codex_home / "agents" / "luna-worker.toml"
        ).read_text(encoding="utf-8")
        self.assertIn("CODEX_ROUTER_LEASE_BOOTSTRAP_V4", luna)
        self.assertIn("current native spawn message", luna)
        self.assertIn("generation lease", luna.lower())
        self.assertNotIn('issue exactly the Codex `Bash` tool with `\\"command\\":\\"pwd\\"`', luna)

    def test_global_status_reports_v4_and_explicit_live_gates(self):
        self._install()
        status = global_install_adapter.global_status(self.codex_home)

        self.assertEqual(status.router_design, "v4.0_generation_lease")
        self.assertEqual(status.luna_execution_mode, "generation_lease_v4")
        self.assertEqual(status.live_activation, "PENDING_LIVE_ACCEPTANCE")
        self.assertIn(
            "V40_LIVE_PRETOOL_ACTOR_BINDING",
            status.live_activation_blockers,
        )
        self.assertIn(
            "V40_LIVE_MISSING_STOP_SUPERSESSION",
            status.live_activation_blockers,
        )
        self.assertNotIn(
            "G1_CURRENT_GENERATION_SPAWN_CORRELATION",
            status.live_activation_blockers,
        )

    def test_v4_install_still_uses_same_reversible_managed_targets(self):
        self._install()
        managed = self.codex_home / global_install_core.INSTALL_DIRECTORY_NAME
        self.assertTrue((managed / "lease-control-v4-0.json").is_file())
        self.assertTrue((self.codex_home / "hooks.json").is_file())
        self.assertTrue((self.codex_home / "AGENTS.md").is_file())
        self.assertTrue((self.codex_home / "agents" / "luna-worker.toml").is_file())


if __name__ == "__main__":
    unittest.main()
