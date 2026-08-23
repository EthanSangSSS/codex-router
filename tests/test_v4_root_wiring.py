import argparse
import json
import tempfile
import unittest
from pathlib import Path

from codex_router import lease_control
from codex_router.cli import _stage_k1_fields
from codex_router.hook import HOOK_CONTEXT_PREFIX, handle_hook_event
from codex_router.protocol import build_luna_packet
from codex_router.state import RouterStateError


class V4RootWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installation = self.root / "installation"
        self.installation.mkdir(mode=0o700)
        self.secret = bytes(range(32))
        (self.installation / "installation-secret").write_bytes(self.secret)
        (self.installation / "installation-secret").chmod(0o600)
        binary = self.root / "codex"
        binary.write_text("synthetic", encoding="utf-8")
        binary.chmod(0o700)
        (self.installation / "config.json").write_text(
            json.dumps(
                {
                    "protocol": "codex-router/global-policy-config/v1",
                    "state_root": str(self.installation),
                    "codex_binary": str(binary),
                    "role_config": {
                        "local_sol": {
                            "requested_model": "inherit",
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
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.installation / "config.json").chmod(0o600)
        self.session_id = "session-v4-root"
        lease_control.initialize_session(
            self.installation, self.secret, self.session_id
        )

    def root_event(self, prompt: str, *, turn_id: str):
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "prompt": prompt,
            "cwd": str(self.root),
        }

    def context(self, output):
        raw = output["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(raw.startswith(HOOK_CONTEXT_PREFIX))
        return json.loads(raw[len(HOOK_CONTEXT_PREFIX) :])

    def seed_old_active_lease(self):
        lease_control.set_current_root_turn(
            self.installation,
            self.secret,
            self.session_id,
            turn_id="old-root-turn",
        )
        snapshot = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        capability = lease_control.build_stage_capability(
            self.secret, snapshot, root_turn_id="old-root-turn"
        )
        staged = lease_control.stage_authorized_lease(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id="old-root-turn",
            capability=capability,
            packet_wire=build_luna_packet(
                packet_id="old-packet",
                generation=1,
                objective="old routed work",
                working_directory=str(self.root),
                intended_write_scope=("src",),
                explicit_side_effect_authorizations=(),
                success_criteria=("old",),
                stop_conditions=("superseded",),
            ),
        )
        bootstrap = lease_control.build_bootstrap_capability(
            self.secret, staged.active_lease
        )
        active, _ = lease_control.authorize_executor_tool(
            self.installation,
            self.secret,
            self.session_id,
            agent_id="old-agent",
            agent_type="luna_worker",
            child_turn_id="old-child-turn",
            bootstrap_capability=bootstrap,
        )
        return active

    def test_direct_v4_turn_revokes_old_lease_and_never_requires_routed_fallback(self):
        old = self.seed_old_active_lease()
        self.assertEqual(old.active_lease.status, "ACTIVE")

        output = handle_hook_event(
            self.root_event(
                "[CODEX_ROUTER_DIRECT]\nContinue locally without Luna.",
                turn_id="direct-root-turn",
            ),
            self.installation,
        )

        context = self.context(output)
        self.assertEqual(context["decision"], "direct")
        self.assertNotIn("K1_STAGE_COMMAND", context)
        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(current.generation, 1)
        self.assertIsNone(current.active_lease)
        self.assertIsNone(current.current_root_turn_tag)

    def test_new_routed_v4_root_revokes_old_lease_and_issues_current_stage_capability(self):
        self.seed_old_active_lease()

        output = handle_hook_event(
            self.root_event(
                "Implement the next bounded repository change.",
                turn_id="new-root-turn",
            ),
            self.installation,
        )

        context = self.context(output)
        self.assertEqual(context["decision"], "route")
        self.assertEqual(context["workflow"], "generation_lease_v4")
        self.assertRegex(context["K1_STAGE_CAPABILITY"], r"^v4s1\.[0-9a-f]{64}$")
        self.assertIn("stage-k1-fields", context["K1_STAGE_COMMAND"])
        self.assertIn(context["K1_STAGE_CAPABILITY"], context["K1_STAGE_COMMAND"])
        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(current.generation, 1)
        self.assertIsNone(current.active_lease)
        self.assertIsNotNone(current.current_root_turn_tag)
        lease_control.verify_stage_capability(
            self.secret,
            current,
            root_turn_id="new-root-turn",
            capability=context["K1_STAGE_CAPABILITY"],
        )

    def test_routed_root_exposes_v1_and_v2_spawn_transport_contracts(self):
        output = handle_hook_event(
            self.root_event(
                "Implement a bounded repository change.",
                turn_id="transport-root-turn",
            ),
            self.installation,
        )

        contract = self.context(output)["spawn_contract"]
        self.assertIn("multi_agent_v1__spawn_agent", contract)
        self.assertIn("fork_context", contract)
        self.assertIn("task_name", contract)
        self.assertIn("fork_turns=none", contract)
        self.assertIn("spawn_message", contract)
        self.assertIn("V1", contract)
        self.assertIn("V2", contract)

    def test_routed_root_exposes_exact_typed_k1_request_schema(self):
        output = handle_hook_event(
            self.root_event(
                "Inspect a bounded repository file.",
                turn_id="schema-root-turn",
            ),
            self.installation,
        )

        schema = self.context(output)["K1_REQUEST_SCHEMA"]
        self.assertEqual(
            schema,
            {
                "packet_id": "non-empty UTF-8 string",
                "objective": "non-empty UTF-8 string",
                "working_directory": "absolute path string",
                "intended_write_scope": "array[string]",
                "explicit_side_effect_authorizations": "array[string]",
                "success_criteria": "array[string]",
                "stop_conditions": "array[string]",
            },
        )

    def test_v4_stage_fields_returns_generation_scoped_spawn_contract(self):
        route_output = handle_hook_event(
            self.root_event(
                "Implement a bounded V4 task.",
                turn_id="root-turn-1",
            ),
            self.installation,
        )
        route_context = self.context(route_output)
        args = argparse.Namespace(
            installation_dir=self.installation,
            session_id=self.session_id,
            root_turn_id="root-turn-1",
            capability=route_context["K1_STAGE_CAPABILITY"],
            packet_id="packet-v4-root-1",
            objective="implement bounded V4 task",
            working_directory=str(self.root),
            intended_write_scope=["src", "tests"],
            explicit_side_effect_authorization=[],
            success_criterion=["tests pass"],
            stop_condition=["scope expansion required"],
        )

        result = _stage_k1_fields(args)

        self.assertEqual(result["status"], "staged")
        self.assertEqual(result["packet_id"], "packet-v4-root-1")
        self.assertEqual(result["generation"], 1)
        self.assertRegex(result["task_name"], r"^luna_g1_[0-9a-f]{8}$")
        self.assertRegex(
            result["bootstrap_capability"], r"^v4b1\.[0-9a-f]{64}$"
        )
        self.assertIn(result["bootstrap_capability"], result["spawn_message"])
        self.assertIn("pwd # CODEX_ROUTER_LEASE_BOOTSTRAP_V4=", result["spawn_message"])
        current = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        self.assertEqual(current.generation, 1)
        self.assertEqual(current.active_lease.expected_task_name, result["task_name"])

    def test_stale_stage_capability_from_superseded_root_is_rejected_without_mutation(self):
        first_output = handle_hook_event(
            self.root_event("First routed task.", turn_id="root-turn-1"),
            self.installation,
        )
        first_context = self.context(first_output)
        handle_hook_event(
            self.root_event("Second routed task.", turn_id="root-turn-2"),
            self.installation,
        )
        before = lease_control.read_snapshot(
            self.installation, self.secret, self.session_id
        )
        args = argparse.Namespace(
            installation_dir=self.installation,
            session_id=self.session_id,
            root_turn_id="root-turn-1",
            capability=first_context["K1_STAGE_CAPABILITY"],
            packet_id="stale-packet",
            objective="stale work",
            working_directory=str(self.root),
            intended_write_scope=["src"],
            explicit_side_effect_authorization=[],
            success_criterion=["must not run"],
            stop_condition=["stale"],
        )

        with self.assertRaises(RouterStateError):
            _stage_k1_fields(args)

        self.assertEqual(
            lease_control.read_snapshot(
                self.installation, self.secret, self.session_id
            ),
            before,
        )


if __name__ == "__main__":
    unittest.main()
