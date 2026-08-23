import json
import tempfile
import unittest
from pathlib import Path

from codex_router import global_install_adapter
from codex_router.hook import HOOK_CONTEXT_PREFIX, handle_hook_event


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

EXPECTED_SCHEMA = {
    "packet_id": "non-empty string",
    "objective": "non-empty string",
    "working_directory": "absolute path string",
    "intended_write_scope": "array[string]",
    "explicit_side_effect_authorizations": "array[string]",
    "success_criteria": "array[string]",
    "stop_conditions": "array[string]",
}


class V4RequestSchemaContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir(mode=0o700)
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)
        global_install_adapter.global_install(
            codex_home=self.codex_home,
            state_root=self.root / "router-runs",
            codex_binary=self.binary,
            defaults=ROLE_CONFIG,
        )
        self.installation = self.codex_home / ".codex-router-policy-v1"

    def test_routed_root_exposes_exact_request_file_json_types(self):
        output = handle_hook_event(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "schema-session",
                "turn_id": "schema-turn",
                "prompt": "Read project metadata and report the bounded result.",
                "cwd": str(self.root),
            },
            self.installation,
        )

        raw = output["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(raw.startswith(HOOK_CONTEXT_PREFIX))
        context = json.loads(raw[len(HOOK_CONTEXT_PREFIX) :])
        self.assertEqual(context["workflow"], "generation_lease_v4")
        self.assertEqual(context["K1_REQUEST_SCHEMA"], EXPECTED_SCHEMA)

    def test_installed_primary_policy_declares_same_request_file_json_types(self):
        agents = (self.codex_home / "AGENTS.md").read_text(encoding="utf-8")

        for field, type_name in EXPECTED_SCHEMA.items():
            self.assertIn(f"`{field}`: `{type_name}`", agents)
        self.assertIn("Do not serialize any array field as a scalar string or object", agents)


if __name__ == "__main__":
    unittest.main()
